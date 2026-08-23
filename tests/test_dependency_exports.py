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


def test_the_dev_extra_reaches_the_dev_export():
    dev = _requirement_names(_pyproject()["project"]["optional-dependencies"]["dev"])
    missing = sorted(set(dev) - _exported_names(DEV_EXPORT))
    assert not missing, f"missing from requirements/dev.txt; re-run `just lock`: {missing}"
