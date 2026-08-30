"""Guard the hash-pinned requirements/* exports against drift.

`just lock` regenerates these by hand-written `uv export` lines, so a dependency
that moves between an extra and a group silently falls out of the export. That
happened: the linters moved into the `lint` dependency group and
`requirements/dev.txt` kept exporting only `--extra dev`, so the file no longer
reproduced either `just deps` or what CI lints with.
"""

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
JUSTFILE = REPO_ROOT / "justfile"
DEV_EXPORT = REPO_ROOT / "requirements" / "dev.txt"


def _pyproject() -> dict:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def _requirement_names(specs: list) -> list:
    """Distribution names out of PEP 508 specifiers, lowercased."""
    return [re.split(r"[<>=!~\[; ]", spec, maxsplit=1)[0].strip().lower() for spec in specs]


def _exported_names(path: Path) -> set:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==", line)
        if match:
            names.add(match.group(1).lower())
    return names


def test_build_system_setuptools_accepts_arch_extra():
    """AUR PKGBUILD uses python -m build --no-isolation against Arch extra setuptools 84."""
    requires = _pyproject()["build-system"]["requires"]
    setuptools_req = next(r for r in requires if r.lower().startswith("setuptools"))
    assert "<82" not in setuptools_req
    assert ">=77" in setuptools_req.replace(" ", "")


def test_the_dev_export_requests_every_group_it_needs():
    """The export line has to name the lint group, not just the dev extra."""
    line = next(
        l
        for l in JUSTFILE.read_text(encoding="utf-8").splitlines()
        if "-o requirements/dev.txt" in l
    )
    assert "--extra dev" in line
    assert "--group lint" in line, "the linters live in a group; the extra alone misses them"


def test_every_linter_reaches_the_dev_export():
    """What CI lints with must be reproducible from the committed export."""
    linters = _requirement_names(_pyproject()["dependency-groups"]["lint"])
    assert linters, "no lint group in pyproject.toml"
    missing = sorted(set(linters) - _exported_names(DEV_EXPORT))
    assert not missing, f"missing from requirements/dev.txt; re-run `just lock`: {missing}"


def test_documented_uv_run_examples_do_not_prune_the_linters():
    """`uv sync`/`uv run` install exactly what the flags name and remove the rest.

    That is why every justfile recipe passes the same DEV_EXTRAS. A documented
    example that stops at `--extra dev` silently uninstalls black, isort and
    flake8 from .venv, so the next `just lint` fails for a reason the reader has
    no way to connect to the command they were told to run.
    """
    offenders = []
    for path in sorted(REPO_ROOT.glob("*.md")) + sorted((REPO_ROOT / "docs").glob("**/*.md")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "uv run --extra dev" in line or "uv sync --extra dev" in line:
                if "--group lint" not in line:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")
    assert not offenders, "these examples uninstall the linters:\n" + "\n".join(offenders)


def test_justfile_uv_run_recipes_do_not_sync():
    """`uv run` without --no-sync prunes whisper/vosk after `just deps-all`."""
    offenders = []
    for number, line in enumerate(JUSTFILE.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("#") or not stripped.startswith("uv run"):
            continue
        if "--no-sync" not in stripped:
            offenders.append(f"{number}: {stripped}")
    assert not offenders, "uv run without --no-sync undoes just deps-all:\n" + "\n".join(offenders)


def test_the_dev_extra_reaches_the_dev_export():
    dev = _requirement_names(_pyproject()["project"]["optional-dependencies"]["dev"])
    missing = sorted(set(dev) - _exported_names(DEV_EXPORT))
    assert not missing, f"missing from requirements/dev.txt; re-run `just lock`: {missing}"


#: Recipes that may call `uv run --no-sync` without depending on `_tooling`.
#: `version` reads one string out of version.py with a bare interpreter, so
#: syncing the whole dev environment ahead of it would buy nothing.
NO_TOOLING_NEEDED = {"version"}


def _justfile_recipes() -> dict:
    """Map every recipe name to its dependency list and its body lines."""
    recipes = {}
    current = None
    for line in JUSTFILE.read_text(encoding="utf-8").splitlines():
        header = re.match(r"^([a-z_][A-Za-z0-9_-]*):(.*)$", line)
        if header:
            current = header.group(1)
            recipes[current] = (header.group(2).split(), [])
        elif current and line.startswith((" ", "\t")):
            recipes[current][1].append(line.strip())
        elif line.strip():
            current = None
    return recipes


def test_no_sync_recipes_bootstrap_the_venv():
    """Something has to create .venv before `uv run --no-sync` can use it.

    Nothing does, once every recipe stops syncing: a fresh clone gets an empty
    .venv and `error: Failed to spawn: pytest`. No CI job would catch it either,
    because the pipeline drives uv directly and never runs `just`.
    """
    offenders = []
    for name, (dependencies, body) in _justfile_recipes().items():
        if name in NO_TOOLING_NEEDED:
            continue
        if not any("uv run --no-sync" in body_line for body_line in body):
            continue
        if "_tooling" not in dependencies:
            offenders.append(name)
    assert not offenders, "these run tooling out of .venv but never create it:\n" + "\n".join(
        offenders
    )


def test_default_is_the_first_recipe():
    """`just` with no arguments runs the first recipe, whatever it is named.

    A recipe added above `default` silently becomes what bare `just` does, and
    `[private]` does not exempt it — which is how `_tooling` first landed here,
    turning `just` into a sync instead of the recipe listing.
    """
    first = next(iter(_justfile_recipes()))
    assert first == "default", f"bare `just` would run `{first}` instead of listing recipes"
