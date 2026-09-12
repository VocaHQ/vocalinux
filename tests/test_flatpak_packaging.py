"""Tie the Flatpak's dependency set back to the lock that everything else uses.

`packaging/flatpak/python3-dependencies.yaml` was generated once from a package
list typed on a command line, then hand-edited, then never compared to anything.
By 2026-09-10 ten of its fifteen shared packages were behind
`requirements/runtime.txt` and two more (pydub, lxml) were still built after
#705 deleted them for having no imports in `src/`.

The one that mattered was pywhispercpp 1.4.1, under the project's own
`>=1.5.0`. Nothing could catch it: the Flatpak installs the project with
`pip3 install --no-deps`, so the constraint in `pyproject.toml` is never
evaluated, and `recognition_manager.py` degrades GPU `context_params` below
1.5.0, so Flatpak users lost that quietly rather than loudly.

`packaging/appimage/build.sh` has done this check for the AppImage since #743.
These are the Flatpak's, and they run offline: `scripts/sync_flatpak_deps.py`
needs PyPI to look a URL up, but everything asserted here is already in the
repo.
"""

import re
import tomllib
from pathlib import Path

import pytest
from packaging.markers import Marker
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
EXPORT = REPO_ROOT / "requirements" / "runtime.txt"
FLATPAK_DIR = REPO_ROOT / "packaging" / "flatpak"
DEPS_YAML = FLATPAK_DIR / "python3-dependencies.yaml"
MANIFEST = FLATPAK_DIR / "com.vocalinux.Vocalinux.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "flatpak.yml"

#: Kept in step with scripts/sync_flatpak_deps.py, which resolves the same
#: markers when it picks a version. GNOME 50 is a freedesktop 25.08 base.
TARGET_ENV = {
    "sys_platform": "linux",
    "platform_system": "Linux",
    "platform_machine": "x86_64",
    "os_name": "posix",
    "python_version": "3.13",
    "python_full_version": "3.13.0",
    "implementation_name": "cpython",
    "platform_python_implementation": "CPython",
    "extra": "",
}

#: org.gnome.Platform//50 ships these. PyGObject is already absent from the
#: export, which `just lock` builds with --no-emit-package pygobject.
RUNTIME_PROVIDED = {"pycairo"}

#: Build backends for the sdists the sandbox compiles under
#: --no-build-isolation. Never imported at runtime, so never in the export.
BUILD_BACKENDS = {"meson-python", "pyproject-metadata"}


def _locked() -> dict:
    """Every package the export selects for the Flatpak target: version, digests."""
    selected = {}
    current = None
    for raw in EXPORT.read_text(encoding="utf-8").splitlines():
        line = raw.strip().rstrip("\\").strip()
        if not line or line.startswith("#"):
            continue
        head = re.match(r"^([A-Za-z0-9._-]+)==([^ ;]+)\s*(?:;\s*(.*))?$", line)
        if head:
            name, version, marker = head.groups()
            current = None
            if marker and not Marker(marker).evaluate(TARGET_ENV):
                continue
            current = canonicalize_name(name)
            selected[current] = {"version": version, "hashes": set()}
            continue
        digest = re.match(r"^--hash=sha256:([0-9a-f]{64})$", line)
        if digest and current:
            selected[current]["hashes"].add(digest.group(1))
    return selected


def _flatpak_sources() -> list:
    """Every PyPI artifact the Flatpak downloads: name, version, digest, filename."""
    lines = DEPS_YAML.read_text(encoding="utf-8").splitlines()
    sources = []
    for index, line in enumerate(lines):
        url = re.match(r"^\s*url: https://files\.pythonhosted\.org/\S+/([^/\s]+)$", line)
        if not url:
            continue
        filename = url.group(1)
        digest = re.match(r"^\s*sha256: ([0-9a-f]{64})\s*$", lines[index + 1])
        assert digest, f"{DEPS_YAML.name}:{index + 2}: PyPI source with no sha256 under it"
        if filename.endswith(".whl"):
            name, version = filename.split("-")[0], filename.split("-")[1]
        else:
            base = re.sub(r"\.(tar\.gz|zip|tar\.bz2)$", "", filename)
            name, _, version = base.rpartition("-")
        sources.append(
            {
                "name": canonicalize_name(name),
                "version": version,
                "sha256": digest.group(1),
                "filename": filename,
            }
        )
    assert sources, "no PyPI sources found; the parser and the file disagree"
    return sources


def _flatpak_versions() -> dict:
    return {source["name"]: source["version"] for source in _flatpak_sources()}


def test_the_project_is_installed_without_deps() -> None:
    """The reason every other test here has to exist.

    `--no-deps` is correct (the runtime provides PyGObject and the modules
    below provide the rest), but it means pip never reads `pyproject.toml`'s
    constraints. Nothing inside a Flatpak build can notice a dependency that
    violates them, so the check has to live out here.
    """
    assert "pip3 install --no-deps" in MANIFEST.read_text(encoding="utf-8")


@pytest.mark.parametrize("source", _flatpak_sources(), ids=lambda s: s["name"])
def test_every_source_is_the_version_the_lock_resolved(source) -> None:
    """A version here that uv did not resolve is a package nothing tested."""
    if source["name"] in BUILD_BACKENDS:
        pytest.skip("build backend; absent from the runtime export by design")
    locked = _locked().get(source["name"])
    assert locked, (
        f"{source['name']} is built by the Flatpak but the lock does not"
        " resolve it for Linux. Drop its module, or add it to pyproject.toml."
    )
    assert source["version"] == locked["version"], (
        f"{source['name']}: Flatpak builds {source['version']},"
        f" requirements/runtime.txt pins {locked['version']}."
        " Run `just flatpak-deps`."
    )


@pytest.mark.parametrize("source", _flatpak_sources(), ids=lambda s: s["name"])
def test_every_digest_is_one_uv_recorded(source) -> None:
    """The bytes the Flatpak fetches are the bytes in uv.lock, not merely the
    same version number. A digest uv never saw is an artifact nothing pinned."""
    if source["name"] in BUILD_BACKENDS:
        pytest.skip("build backend; absent from the runtime export by design")
    hashes = _locked()[source["name"]]["hashes"]
    assert source["sha256"] in hashes, (
        f"{source['filename']} carries a digest absent from"
        " requirements/runtime.txt. Run `just flatpak-deps`."
    )


def test_the_flatpak_carries_every_runtime_dependency() -> None:
    """A missing one fails at first launch, not at build time, because the
    project is installed with --no-deps and nothing resolves the gap."""
    missing = sorted(set(_locked()) - set(_flatpak_versions()) - RUNTIME_PROVIDED)
    assert not missing, (
        "the lock resolves these for Linux and the Flatpak does not build them:"
        f" {', '.join(missing)}"
    )


def test_the_flatpak_builds_nothing_the_lock_does_not_resolve() -> None:
    """#705 deleted pydub, lxml, tqdm and python-xlib from `pyproject.toml`.

    Two of those four came back through the dependency chain: pywhispercpp
    needs tqdm and pynput needs python-xlib, so the lock still resolves them
    and the Flatpak must still build them. pydub and lxml are the ones with no
    path back, and they stayed here for four months. Compare against the
    resolved set rather than the direct one, or this test deletes two packages
    the Flatpak needs.
    """
    extra = sorted(set(_flatpak_versions()) - set(_locked()) - BUILD_BACKENDS)
    assert not extra, (
        f"the Flatpak builds packages nothing depends on: {', '.join(extra)}."
        " Delete their modules from python3-dependencies.yaml."
    )


def test_pywhispercpp_satisfies_the_projects_own_floor() -> None:
    """The finding this file was written for. Stated as the constraint rather
    than a literal, so bumping the floor cannot leave the check behind it."""
    with PYPROJECT.open("rb") as handle:
        dependencies = tomllib.load(handle)["project"]["dependencies"]
    spec = next(d for d in dependencies if canonicalize_name(d.split(">")[0]) == "pywhispercpp")
    constraint = SpecifierSet(spec[len("pywhispercpp") :])
    shipped = _flatpak_versions()["pywhispercpp"]
    assert Version(shipped) in constraint, (
        f"the Flatpak ships pywhispercpp {shipped}, outside the project's own"
        f" {constraint}. recognition_manager.py degrades GPU context_params"
        " below 1.5.0, so this is silent for the user."
    )


def test_the_version_injection_names_the_version_being_built() -> None:
    """pywhispercpp's sdist carries no version.txt and its setup() takes no
    version= argument, so the module rewrites setup.py before building and
    spells the version out four times. All four have to agree with the tarball
    actually downloaded, or the build renames a directory tar just wrote.
    """
    module = re.search(
        r"^  - name: python3-pywhispercpp$(.*?)(?=^  - name: |\Z)",
        DEPS_YAML.read_text(encoding="utf-8"),
        re.M | re.S,
    )
    assert module, "the pywhispercpp module is gone; this test needs rewriting"
    spelled = set(re.findall(r"pywhispercpp-(\d+(?:\.\d+)+)(?![\d.]\d)", module.group(1)))
    spelled |= set(re.findall(r"PYWHISPERCPP_VERSION=(\d+(?:\.\d+)+)", module.group(1)))
    spelled |= set(re.findall(r'version=\\"(\d+(?:\.\d+)+)\\"', module.group(1)))
    assert spelled == {_flatpak_versions()["pywhispercpp"]}, (
        f"the pywhispercpp module spells out {sorted(spelled)}; the tarball it"
        f" downloads is {_flatpak_versions()['pywhispercpp']}"
    )


def test_the_manifest_env_agrees_with_the_module() -> None:
    """build-options.env sets PYWHISPERCPP_VERSION for the whole build. Left
    behind, it tells the build one version while the module builds another."""
    declared = re.search(r'PYWHISPERCPP_VERSION: "([^"]+)"', MANIFEST.read_text(encoding="utf-8"))
    assert declared, "the manifest no longer sets PYWHISPERCPP_VERSION"
    assert declared.group(1) == _flatpak_versions()["pywhispercpp"]


@pytest.mark.parametrize("source", _flatpak_sources(), ids=lambda s: s["name"])
def test_no_source_is_pinned_to_one_python_abi(source) -> None:
    """Universal wheel or sdist, never a cp-tagged wheel.

    The SDK's Python minor version is not ours to choose and moves with the
    GNOME runtime. An abi3 or cp313 wheel builds today and stops resolving the
    day the runtime bumps, with nothing in this repo changed.
    """
    if not source["filename"].endswith(".whl"):
        return
    assert source["filename"].endswith("-none-any.whl"), (
        f"{source['filename']} is pinned to one interpreter ABI; take the sdist"
        " and let the sandbox build it against the SDK's own Python"
    )


def test_a_lock_refresh_reaches_the_flatpak_build() -> None:
    """The manifest is generated from requirements/, so a change there changes
    what the Flatpak ships. Without the path filter, `just lock` could move
    every version in it and start no Flatpak job."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("'requirements/**'") >= 2, (
        "flatpak.yml does not watch requirements/**, so a lock refresh changes"
        " what the Flatpak builds and runs no build"
    )
