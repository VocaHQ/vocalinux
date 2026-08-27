"""Guard against Python-version drift between the places that declare it.

`requires-python`, the classifiers, the CI matrix and install.sh's MIN_VERSION
used to disagree (3.9 floor, 3.9-3.13 matrix, classifiers promising 3.14), which
is how an unsupported interpreter can quietly become the one users install with.
"""

import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
INSTALL_SH = REPO_ROOT / "install.sh"
PIPELINE = REPO_ROOT / ".github" / "workflows" / "unified-pipeline.yml"
PKGBUILD = REPO_ROOT / "packaging" / "aur" / "vocalinux" / "PKGBUILD"

# Everything user-facing that could state the floor. Scanned as trees rather than
# a fixed list: docs and the website drifted to "3.9+" for a full release cycle
# after the floor moved, and a new page must not be able to reintroduce it.
DOC_AND_SITE_GLOBS = [
    (REPO_ROOT / "docs", "**/*.md"),
    (REPO_ROOT / "web" / "src", "**/*.tsx"),
    (REPO_ROOT / "web" / "src", "**/*.ts"),
    (REPO_ROOT, "README.md"),
    (REPO_ROOT, "CONTRIBUTING.md"),
]


def _doc_and_site_files() -> list:
    files = []
    for base, pattern in DOC_AND_SITE_GLOBS:
        files.extend(p for p in base.glob(pattern) if "node_modules" not in p.parts)
    return sorted(set(files))


def _version_tuple(version: str) -> tuple:
    return tuple(int(part) for part in version.split("."))


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def _requires_python_floor() -> str:
    requires = _pyproject()["project"]["requires-python"]
    match = re.fullmatch(r">=\s*(\d+\.\d+)", requires.strip())
    assert match, f"unexpected requires-python format: {requires!r}"
    return match.group(1)


def _classifier_versions() -> list:
    versions = []
    for classifier in _pyproject()["project"]["classifiers"]:
        match = re.fullmatch(r"Programming Language :: Python :: (\d+\.\d+)", classifier)
        if match:
            versions.append(match.group(1))
    return versions


def _ci_matrix_versions() -> list:
    match = re.search(r"python-version: \[([^\]]+)\]", PIPELINE.read_text(encoding="utf-8"))
    assert match, "python-version matrix not found in unified-pipeline.yml"
    return re.findall(r"'(\d+\.\d+)'", match.group(1))


def _install_sh_min_version() -> str:
    # Anchored on the function: install.sh also carries an Ubuntu MIN_VERSION.
    match = re.search(
        r'check_python_version\(\) \{.*?local MIN_VERSION="(\d+\.\d+)"',
        INSTALL_SH.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert match, "check_python_version's MIN_VERSION not found in install.sh"
    return match.group(1)


def test_installer_floor_matches_requires_python():
    assert _install_sh_min_version() == _requires_python_floor()


def test_classifiers_match_supported_range():
    floor = _requires_python_floor()
    classifiers = _classifier_versions()

    assert classifiers, "no Programming Language :: Python :: X.Y classifiers"
    assert min(map(_version_tuple, classifiers)) == _version_tuple(floor)


def test_ci_matrix_covers_every_supported_version():
    # The matrix is the only thing that proves a promised version works.
    assert sorted(_ci_matrix_versions()) == sorted(_classifier_versions())


def test_running_interpreter_is_supported():
    assert sys.version_info[:2] >= _version_tuple(_requires_python_floor())


def _pkgbuild_python_floor() -> str:
    match = re.search(r"'python>=(\d+\.\d+)'", PKGBUILD.read_text(encoding="utf-8"))
    assert match, "python>= dependency not found in the AUR PKGBUILD"
    return match.group(1)


def test_aur_package_matches_requires_python():
    assert _pkgbuild_python_floor() == _requires_python_floor()


def test_docs_and_site_do_not_advertise_an_older_floor():
    """No user-facing file may promise a Python older than the real floor."""
    floor = _version_tuple(_requires_python_floor())
    files = _doc_and_site_files()
    assert files, "found nothing to scan; the docs/website layout moved"

    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for number, line in enumerate(text.splitlines(), 1):
            for claimed in re.findall(r"Python (\d+\.\d+)\+", line):
                if _version_tuple(claimed) < floor:
                    rel = path.relative_to(REPO_ROOT)
                    offenders.append(f"{rel}:{number} claims Python {claimed}+")

    assert not offenders, "user-facing files promise an unsupported Python:\n" + "\n".join(
        offenders
    )
