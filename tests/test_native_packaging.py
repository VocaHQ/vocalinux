"""Regression guards for the native .deb/.rpm packaging (#600).

Offline consistency checks in the shape of test_appimage_packaging.py: the
nfpm config, the pinned build inputs, the smoke gate, and the CI wiring must
agree with pyproject.toml, requirements/runtime.txt, and each other.
"""

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
NATIVE = REPO_ROOT / "packaging" / "native"
NFPM_YAML = NATIVE / "nfpm.yaml"
BUILD_SH = NATIVE / "build.sh"
DOCKER_BUILD_SH = NATIVE / "docker-build.sh"
CONTAINER_BUILD_SH = NATIVE / "container-build.sh"
SMOKE_SH = NATIVE / "smoke-test.sh"
PINS = NATIVE / "tool_checksums.txt"
PYPROJECT = REPO_ROOT / "pyproject.toml"
RUNTIME = REPO_ROOT / "requirements" / "runtime.txt"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
RELEASE_YML = WORKFLOWS / "release.yml"
PIPELINE_YML = WORKFLOWS / "unified-pipeline.yml"

#: Runtime dependencies no distro packages; build.sh vendors their wheels
#: under /usr/lib/vocalinux/vendor instead of declaring distro deps.
VENDORED = ("pywhispercpp", "pynput")

#: pip name -> the Debian/Ubuntu package that Provides it. pywhispercpp's own
#: runtime deps (tqdm, platformdirs) are the package's deps too.
DEB_PROVIDES = {
    "numpy": "python3-numpy",
    "requests": "python3-requests",
    "tqdm": "python3-tqdm",
    "platformdirs": "python3-platformdirs",
    "psutil": "python3-psutil",
    "evdev": "python3-evdev",
    "pyaudio": "python3-pyaudio",
    "pysocks": "python3-socks",
    "xlib": "python3-xlib",
    "pygobject": "python3-gi",
}

#: pip name -> the Fedora package that Provides it. Note python3-pynput is
#: absent on purpose: Fedora has no pynput package, which is half of why
#: VENDORED exists.
RPM_PROVIDES = {
    "numpy": "python3-numpy",
    "requests": "python3-requests",
    "tqdm": "python3-tqdm",
    "platformdirs": "python3-platformdirs",
    "psutil": "python3-psutil",
    "evdev": "python3-evdev",
    "pyaudio": "python3-pyaudio",
    "pysocks": "python3-pysocks",
    "xlib": "python3-xlib",
    "pygobject": "python3-gobject",
}

#: Host binaries the injectors and helpers shell out to. Both formats
#: recommend them; install.d documents the same set for install.sh.
HOST_TOOLS = ("xdotool", "wtype", "ydotool", "wl-clipboard", "xclip", "xsel")

#: pywhispercpp's own Requires-Dist (extras excluded): the vendored wheel's
#: dependencies are the package's dependencies too.
PYWHISPERCPP_DEPS = ("numpy", "requests", "tqdm", "platformdirs")


def _nfpm() -> dict:
    """nfpm.yaml as parsed YAML (VOCA_* placeholders parse as strings)."""
    return yaml.safe_load(NFPM_YAML.read_text(encoding="utf-8"))


def _deb_dep_names() -> set:
    names = set()
    for dep in _nfpm()["overrides"]["deb"]["depends"]:
        names.add(dep.split(" ", 1)[0])
    return names


def _rpm_dep_names() -> set:
    names = set()
    for dep in _nfpm()["overrides"]["rpm"]["depends"]:
        names.add(dep.split(" ", 1)[0])
    return names


def _pins() -> dict:
    """name -> (kind, value, source) from tool_checksums.txt."""
    pins = {}
    for line in PINS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, kind, value, source = line.split(None, 3)
        pins[name] = (kind, value, source.strip())
    return pins


def _project_dependencies() -> set:
    """pip names of every runtime dependency in pyproject.toml."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    names = set()
    for dep in data["project"]["dependencies"]:
        match = re.match(r"^([A-Za-z0-9._-]+)", dep)
        assert match, f"unparseable dependency {dep!r}"
        names.add(match.group(1).lower().replace("_", "-"))
    return names


def _exported_versions() -> dict:
    """package -> version out of the hash-pinned runtime export."""
    return {
        match.group(1).lower(): match.group(2)
        for match in (
            re.match(r"^([A-Za-z0-9._-]+)==([^\s;\\]+)", line)
            for line in RUNTIME.read_text(encoding="utf-8").splitlines()
        )
        if match
    }


def test_vendored_set_matches_build_sh_and_runtime_pins() -> None:
    """The vendored wheels are exactly the pinned ones: anything else vendored
    drifts from the lock, anything not vendored goes undeclared."""
    build = BUILD_SH.read_text(encoding="utf-8")
    exported = _exported_versions()
    for name in VENDORED:
        assert name in exported, f"{name} is not pinned in requirements/runtime.txt"
        assert "pip3 download" in build and name in build, f"{name} is not vendored by build.sh"
    # Only these two may be downloaded: the awk that writes the vendor
    # requirements file must name exactly this set.
    match = re.search(r"\(([^)]+)\)==", build)
    vendor_names = set(match.group(1).split("|")) if match else set()
    assert vendor_names == set(
        VENDORED
    ), f"build.sh vendors {vendor_names}, expected {set(VENDORED)}"


def test_vendored_packages_are_not_declared_as_distro_deps() -> None:
    """A vendored name declared as a dep either fails dependency resolution
    (pynput does not exist on Fedora) or shadows the vendored copy."""
    deb, rpm = _deb_dep_names(), _rpm_dep_names()
    for name in VENDORED:
        python_name = f"python3-{name}"
        assert python_name not in deb, f"{python_name} declared in deb but {name} is vendored"
        assert python_name not in rpm, f"{python_name} declared in rpm but {name} is vendored"
        assert name not in deb and name not in rpm


def test_every_project_dependency_is_covered_in_both_formats() -> None:
    """pyproject.toml dependencies must be either vendored or satisfied by a
    declared distro package in each format — a miss is an uninstallable
    package or an import failure at first run."""
    project = _project_dependencies() | set(PYWHISPERCPP_DEPS)
    deb, rpm = _deb_dep_names(), _rpm_dep_names()
    missing_deb, missing_rpm = [], []
    for name in sorted(project):
        if name in VENDORED:
            continue
        if DEB_PROVIDES.get(name) not in deb:
            missing_deb.append(name)
        if RPM_PROVIDES.get(name) not in rpm:
            missing_rpm.append(name)
    assert not missing_deb, f"deps with no deb coverage: {missing_deb}"
    assert not missing_rpm, f"deps with no rpm coverage: {missing_rpm}"


def test_distro_substrate_is_a_hard_dependency() -> None:
    """Interpreter, PyGObject, GTK and the AppIndicator typelib are what the
    app cannot start without; the smoke proves only what the package pulls."""
    deb, rpm = _deb_dep_names(), _rpm_dep_names()
    for name in (
        "python3",
        "python3-gi",
        "python3-gi-cairo",
        "gir1.2-gtk-3.0",
        "gir1.2-ayatanaappindicator3-0.1",
    ):
        assert name in deb, f"{name} missing from deb depends"
    for name in (
        "python3",
        "python3-gobject",
        "python3-cairo",
        "gtk3",
        "libayatana-appindicator-gtk3",
    ):
        assert name in rpm, f"{name} missing from rpm depends"


def test_python_floor_matches_requires_python() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    floor = re.search(r">=\s*(\d+\.\d+)", data["project"]["requires-python"]).group(1)
    deps = _nfpm()["overrides"]
    assert f"python3 (>= {floor})" in deps["deb"]["depends"]
    assert f"python3 >= {floor}" in deps["rpm"]["depends"]
    # VENDOR_PYS in build.sh must start at the same floor and cover the CI
    # matrix (3.11..3.14): a missing version means a distro Python with no
    # wheel to load.
    build = BUILD_SH.read_text(encoding="utf-8")
    match = re.search(r'VENDOR_PYS="([^"]+)"', build)
    assert match, "VENDOR_PYS not set in build.sh"
    versions = match.group(1).split()
    assert versions[0] == floor, f"VENDOR_PYS floor {versions[0]} != requires-python {floor}"
    assert versions == sorted(versions, key=lambda v: tuple(map(int, v.split("."))))


def test_host_tools_are_recommended_in_both_formats() -> None:
    deps = _nfpm()["overrides"]
    for tool in HOST_TOOLS:
        assert tool in deps["deb"]["recommends"], f"{tool} missing from deb recommends"
        assert tool in deps["rpm"]["recommends"], f"{tool} missing from rpm recommends"


def test_the_pins_are_digests_rather_than_names() -> None:
    for name, (kind, value, source) in _pins().items():
        if kind == "sha256":
            assert re.fullmatch(r"[0-9a-f]{64}", value), f"{name}: not a sha256"
            assert source.startswith("https://"), f"{name}: {source}"
            assert (
                "/continuous/" not in source and "/master/" not in source
            ), f"{name} points at a moving ref, so its digest is a coincidence"
        elif kind == "docker":
            assert "@sha256:" in value, f"{name}: a tag is not a pin"
        elif kind == "version":
            assert re.fullmatch(r"\d+(\.\d+)+", value), f"{name}: {value}"
        else:
            raise AssertionError(f"{name}: unknown pin kind {kind!r}")


def test_every_download_goes_through_the_verifying_helper() -> None:
    """Same contract as the AppImage gate: an unpinned download is a build
    nobody can reproduce."""
    build = BUILD_SH.read_text(encoding="utf-8")
    assert "fetch_pinned" in build
    assert build.count("curl -fSL") == 1, "downloads must go through fetch_pinned"
    pinned = set(_pins())
    fetched = set(re.findall(r'fetch_pinned\s+"?([^"\s]+)"?', build))
    fetched.discard("$NFPM_PIN")  # resolves to the per-arch nfpm-* pin
    for arch in ("nfpm-x86_64", "nfpm-aarch64"):
        assert arch in pinned, f"{arch} missing from {PINS.name}"
    for name in fetched:
        assert name in pinned, f"build.sh fetches '{name}', which {PINS.name} does not pin"


def test_docker_build_uses_the_pinned_base_image() -> None:
    text = DOCKER_BUILD_SH.read_text(encoding="utf-8")
    assert 'awk \'$1=="base-image"' in text
    pins = _pins()
    assert "base-image" in pins and pins["base-image"][0] == "docker"
    assert pins["base-image"][1].startswith("docker.io/library/debian@sha256:")


def test_nfpm_contents_and_launcher_env_agree() -> None:
    """The launcher and the import smoke must point at where the payload tree
    actually lands."""
    text = BUILD_SH.read_text(encoding="utf-8")
    smoke = SMOKE_SH.read_text(encoding="utf-8")
    for where in (text, smoke):
        assert "/usr/lib/vocalinux/app" in where
        assert "/usr/lib/vocalinux/vendor" in where
    assert "/usr/bin/vocalinux" in text and "/usr/bin/vocalinux-gui" in text
    assert "pywhispercpp.libs" in text and "pywhispercpp.libs" in smoke
    # Arguments keep their boundaries: $* into an unquoted exec re-splits a
    # path like "Meeting notes.wav" before argparse sees it (PR #913).
    assert '"$@"' in text and "QUOTED_ARGS" in text
    assert "EXEC_CMD" not in text
    contents = _nfpm()["contents"]
    tree = [c for c in contents if c.get("type") == "tree"]
    assert len(tree) == 1 and tree[0]["dst"] == "/"
    packagers = {c.get("packager") for c in contents}
    assert "deb" in packagers and "rpm" in packagers, "license placement must differ per format"


def test_smoke_gate_covers_both_formats() -> None:
    smoke = SMOKE_SH.read_text(encoding="utf-8")
    assert "debian|ubuntu)" in smoke, "smoke must install the .deb on Debian-family images"
    assert "fedora)" in smoke, "smoke must install the .rpm on Fedora"
    assert "vocalinux --version" in smoke
    assert "vocalinux-gui --version" in smoke
    assert "pywhispercpp.model" in smoke, "the smoke must prove the vendored extension loads"
    assert (
        'find_spec("pynput")' in smoke
    ), "pynput raises ImportError without a display; check presence, not import"


def test_release_workflow_builds_and_attaches_both_arches() -> None:
    text = RELEASE_YML.read_text(encoding="utf-8")
    assert "build-native:" in text and "build-native-arm64:" in text
    assert "ubuntu-24.04-arm" in text
    assert text.count("packaging/native/docker-build.sh") == 2
    assert "name: native-x86_64" in text and "name: native-aarch64" in text
    assert "dist/*.deb dist/*.rpm" in text


def test_checksums_cover_the_packages() -> None:
    text = RELEASE_YML.read_text(encoding="utf-8")
    publish = re.search(r"publish-checksums:.*?(?=\n  [a-z])", text, re.S)
    assert publish, "publish-checksums job not found"
    block = publish.group(0)
    assert "build-native" in block and "build-native-arm64" in block, (
        "publish-checksums must wait for the package jobs or SHA256SUMS is "
        "published before the files exist"
    )
    assert re.search(
        r"sha256sum -- .*\*\.deb.*\*\.rpm", block
    ), "SHA256SUMS must cover .deb and .rpm"


def test_wayland_input_group_is_documented() -> None:
    """The packages cannot run usermod, and `sg input` only helps users
    already listed in /etc/group: a fresh Wayland install leaves the default
    hotkey dead unless the docs name the step."""
    install_md = (REPO_ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
    section = install_md.split("## Distro packages", 1)[1].split("\n## ", 1)[0]
    assert (
        "usermod -aG input" in section
    ), "INSTALL.md's .deb/.rpm section must document the Wayland input-group step"
    release = RELEASE_YML.read_text(encoding="utf-8")
    assert (
        "usermod -aG input" in release
    ), "the release notes' .deb/.rpm block must document the same step"


def test_pipeline_gates_the_packages() -> None:
    text = PIPELINE_YML.read_text(encoding="utf-8")
    assert "- 'packaging/native/**'" in text, "changes filter must watch packaging/native"
    assert "native-build:" in text and "native-smoke:" in text
    assert "native-x86_64" in text
    for distro in ("debian:12", "fedora:42"):
        assert distro in text, f"{distro} missing from the smoke matrix"
    # Each distro in the smoke matrix needs a recipe in smoke-test.sh.
    smoke = SMOKE_SH.read_text(encoding="utf-8")
    matrix = re.search(r"native-smoke:.*?distro:\n((?:\s+- [^\n]+\n)+)", text, re.S)
    assert matrix
    for distro in re.findall(r"- (\S+)", matrix.group(1)):
        family = distro.split(":")[0].split("/")[-1]
        assert family in smoke, f"smoke-test.sh has no recipe for {distro}"
