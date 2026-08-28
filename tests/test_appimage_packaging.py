"""Regression guards for AppImage packaging."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APPIMAGE = REPO_ROOT / "packaging" / "appimage"
BUILD_SH = APPIMAGE / "build.sh"
PINS = APPIMAGE / "tool_checksums.txt"
REQUIREMENTS = REPO_ROOT / "requirements"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
#: Workflows that build an AppImage, and so decide which distros it runs on.
APPIMAGE_WORKFLOWS = ("unified-pipeline.yml", "release.yml", "nightly.yml")


def _pins() -> dict:
    """name -> (kind, value, source) from tool_checksums.txt."""
    pins = {}
    for line in PINS.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, kind, value, source = line.split(None, 3)
        pins[name] = (kind, value, source.strip())
    return pins


def _exported_versions(path: Path) -> dict:
    """package -> version out of a hash-pinned requirements export."""
    return {
        match.group(1).lower(): match.group(2)
        for match in (
            re.match(r"^([A-Za-z0-9._-]+)==([^\s;\\]+)", line)
            for line in path.read_text(encoding="utf-8").splitlines()
        )
        if match
    }


# Typelibs that must ship in the AppImage. xlib/Dbusmenu/GModule/fontconfig are
# transitive GIR deps — pruning them broke Gtk on openSUSE (#585).
REQUIRED_TYPELIBS = (
    "Gtk-3.0",
    "Gdk-3.0",
    "xlib-2.0",
    "GModule-2.0",
    "Dbusmenu-0.4",
    "fontconfig-2.0",
    "Notify-0.7",
)

# Tray stacks are alternates (same order as tray_indicator.py).
INDICATOR_TYPELIBS = (
    "AyatanaAppIndicator3-0.1",
    "AyatanaAppindicator3-0.1",
    "AppIndicator3-0.1",
)


def test_appimage_build_ships_transitive_typelibs():
    text = BUILD_SH.read_text()
    assert "TYPELIBS=(" in text
    # Must not wipe linuxdeploy's typelib set down to a partial allowlist.
    assert 'rm -rf "$APPDIR/usr/lib/girepository-1.0"' not in text
    assert "keeping linuxdeploy extras" in text or "Ensuring required typelibs" in text
    for typelib in REQUIRED_TYPELIBS:
        assert typelib in text, f"missing typelib seed {typelib} in {BUILD_SH}"
    for typelib in INDICATOR_TYPELIBS:
        assert typelib in text, f"missing indicator typelib seed {typelib}"
    assert "INDICATOR_TYPELIBS=" in text
    assert "indicator_found" in text
    assert "Need at least one of:" in text


def test_every_typelib_the_app_requires_is_seeded():
    """A required typelib the bundle does not seed sends GI to the host's search
    path — the openSUSE/Fedora breakage from #585."""
    seeded = BUILD_SH.read_text(encoding="utf-8")
    required = set()
    for path in (REPO_ROOT / "src" / "vocalinux").rglob("*.py"):
        for namespace, version in re.findall(
            r"require_version\(\s*[\"']([\w]+)[\"']\s*,\s*[\"']([\d.]+)[\"']", path.read_text()
        ):
            required.add(f"{namespace}-{version}")
    assert required, "no gi.require_version calls found; has the app stopped using GI?"
    missing = sorted(name for name in required if name not in seeded)
    assert not missing, f"the app requires these typelibs; TYPELIBS does not seed them: {missing}"


def test_bundled_typelibs_come_with_the_library_they_load():
    """Ship a typelib without the library it dlopens and GI loads the host's
    copy against the bundle's older GLib. IBus did: on any host with GLib 2.76+
    the app died on `undefined symbol: g_task_set_static_name`. The build host
    cannot see it — its libraries match what it bundled."""
    text = BUILD_SH.read_text(encoding="utf-8")
    assert "libibus-1.0.so.5" in text, "the IBus typelib is seeded but its library is not bundled"
    assert "verify_typelib_libraries" in text
    assert "HOST_PROVIDED_LIBS" in text, (
        "the check needs its list of libraries the excludelist keeps on the host, "
        "or harfbuzz fails the build"
    )


def test_appimage_build_bundles_gi_runtime_libs():
    text = BUILD_SH.read_text()
    for lib in (
        "libappindicator3.so.1",
        "libayatana-appindicator3.so.1",
        "libdbusmenu-glib.so.4",
        "libdbusmenu-gtk3.so.4",
        "libnotify.so.4",
    ):
        assert lib in text, f"missing GI runtime lib {lib} in {BUILD_SH}"


def test_appimage_build_smokes_gi_without_host_typelibs():
    text = BUILD_SH.read_text()
    assert "smoke_gi_imports" in text
    assert "unshare --user --mount" in text


def test_appimage_build_rebuilds_pywhispercpp_with_vulkan():
    text = BUILD_SH.read_text()
    assert "GGML_VULKAN=1" in text
    assert "libggml-vulkan" in text
    assert "VOCALINUX_APPIMAGE_REQUIRE_VULKAN" in text
    assert "VOCALINUX_APPIMAGE_SKIP_VULKAN" in text
    assert "rebuild_pywhispercpp_vulkan" in text
    assert 'CC="${CC:-gcc}"' in text
    assert 'CXX="${CXX:-g++}"' in text


def test_pywhispercpp_is_pinned_once_and_the_pins_agree():
    """1.5.1 landed mid-review and broke both AppImage jobs with nothing in the
    repo changed. The bundle and the Vulkan rebuild install the same sdist, so
    install.sh and the lock export have to agree on which one."""
    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    declared = re.search(r'^PYWHISPERCPP_VERSION="([^"]+)"', installer, re.M)
    assert declared, "install.sh no longer declares the version build.sh reads"

    exported = _exported_versions(REQUIREMENTS / "vad.txt").get("pywhispercpp")
    assert exported == declared.group(1), (
        "install.sh and requirements/vad.txt pin different pywhispercpp releases; "
        "change pyproject.toml and run `just lock`"
    )

    build = BUILD_SH.read_text(encoding="utf-8")
    assert 'PYWHISPERCPP_VERSION="$(sed' in build, "the pin must come from install.sh"
    assert "--no-binary pywhispercpp" in build, "the Vulkan rebuild must build from source"


def test_every_download_goes_through_the_verifying_helper():
    """`continuous` and `master` move under us, and nothing noticed."""
    text = BUILD_SH.read_text(encoding="utf-8")
    assert (
        text.count("curl_retry -o") == 1
    ), "downloads must go through fetch_pinned, which checks the digest first"
    assert "/continuous/" not in text
    assert "linuxdeploy-plugin-gtk/master/" not in text

    pinned = set(_pins())
    for name in set(re.findall(r'fetch_pinned "([^"]+)"', text)):
        wanted = (
            [name.replace("$ARCH", arch) for arch in ("x86_64", "aarch64")]
            if "$ARCH" in name
            else [name]
        )
        for entry in wanted:
            assert entry in pinned, f"build.sh fetches '{entry}', which {PINS.name} does not pin"


def test_the_pins_are_digests_rather_than_names():
    for name, (kind, value, source) in _pins().items():
        if kind == "sha256":
            assert re.fullmatch(r"[0-9a-f]{64}", value), f"{name}: not a sha256"
            assert source.startswith("https://"), f"{name}: {source}"
            assert (
                "/continuous/" not in source and "/master/" not in source
            ), f"{name} points at a moving ref, so its digest is a coincidence"
        elif kind == "git":
            assert re.fullmatch(r"[0-9a-f]{40}", value), f"{name}: not a commit"
        elif kind == "docker":
            assert "@sha256:" in value, f"{name}: a tag is not a pin"
        elif kind == "version":
            assert re.fullmatch(r"\d+(\.\d+)+", value), f"{name}: {value}"
        else:
            raise AssertionError(f"{name}: unknown pin kind {kind!r}")


def test_the_appimage_is_built_in_the_pinned_base_image():
    """An AppImage cannot run on a glibc older than the one that built it, and
    ubuntu-latest (2.39) rules out Debian 12, Ubuntu 22.04 and RHEL 9 — which is
    what we shipped as the universal option."""
    for workflow in APPIMAGE_WORKFLOWS:
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        assert (
            "packaging/appimage/build.sh" not in text
        ), f"{workflow} runs build.sh on the runner; go through docker-build.sh"
        assert "packaging/appimage/docker-build.sh" in text, workflow

    image = _pins()["base-image"][1]
    assert "22.04" in _pins()["base-image"][2], (
        "raising the base image raises the glibc floor and silently drops distros; "
        "if that is intended, update docs/INSTALL.md in the same change"
    )
    assert image.startswith("docker.io/library/ubuntu@sha256:")


def test_the_bundle_is_installed_from_the_lock():
    text = BUILD_SH.read_text(encoding="utf-8")
    assert "-m pip install" not in text, "pip resolves at build time; install from the exports"
    assert "--require-hashes" in text
    for export in ("requirements/vad.txt", "requirements/appimage.txt"):
        assert export in text, f"{export} is not what the bundle is built from"


def test_the_vad_export_still_covers_the_runtime_export():
    """build.sh installs vad.txt alone, on the assumption it carries everything
    runtime.txt does. Two resolutions that drift would ship a third one."""
    runtime = _exported_versions(REQUIREMENTS / "runtime.txt")
    vad = _exported_versions(REQUIREMENTS / "vad.txt")
    missing = {name: ver for name, ver in runtime.items() if vad.get(name) != ver}
    assert not missing, f"requirements/vad.txt no longer covers runtime.txt: {missing}"


def test_pygobject_stays_on_the_line_the_base_image_can_build():
    """3.52 moved to girepository-2.0 (glib 2.80+) and the base image has 2.72,
    so bumping this to the lock's version fails the build."""
    version = _exported_versions(REQUIREMENTS / "appimage.txt").get("pygobject")
    assert version, "requirements/appimage.txt no longer pins PyGObject"
    assert tuple(int(part) for part in version.split(".")[:2]) <= (3, 50), version


def test_vulkan_builds_against_pinned_headers_not_the_base_image_ones():
    """ggml-vulkan.cpp does not compile against the base image's headers
    (1.3.204): PipelineRobustnessCreateInfoEXT and friends are younger. Only the
    compile sees them — the bundle carries no loader."""
    assert "vulkan-headers" in _pins(), "the Vulkan headers are not pinned"
    assert "-DVulkan_INCLUDE_DIR=" in BUILD_SH.read_text(
        encoding="utf-8"
    ), "the rebuild does not point ggml at the pinned headers"


def test_vulkan_shaders_get_the_compiler_the_base_image_lacks():
    """ggml demands glslc specifically, and Ubuntu 22.04 packages none."""
    text = BUILD_SH.read_text(encoding="utf-8")
    assert "ensure_glslc" in text
    assert "shaderc" in _pins()
    for workflow in APPIMAGE_WORKFLOWS:
        content = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        assert (
            "vocalinux-appimage" in content
        ), f"{workflow} does not cache the built glslc; every run rebuilds it"
