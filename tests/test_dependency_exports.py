"""Guard the hash-pinned requirements/* exports against drift.

`just lock` regenerates these by hand-written `uv export` lines, so a dependency
that moves between an extra and a group silently falls out of the export. That
happened: the linters moved into the `lint` dependency group and
`requirements/dev.txt` kept exporting only `--extra dev`, so the file no longer
reproduced either `just deps` or what CI lints with.
"""

import importlib.util
import re
import tomllib
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
JUSTFILE = REPO_ROOT / "justfile"
INSTALLER = REPO_ROOT / "install.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "unified-pipeline.yml"
REQUIREMENTS = REPO_ROOT / "requirements"
DEV_EXPORT = REQUIREMENTS / "dev.txt"

#: Extras with no hash-pinned export, and the reason each is allowed none.
#: Anything not listed here must have one: an extra without an export is an
#: install path with nothing pinned, which is how parakeet, faster-whisper and
#: vosk shipped to users. Enumerated against pyproject.toml below, so a renamed
#: extra cannot hide behind a stale entry.
EXPORT_EXEMPT = {
    "docs": "nothing builds or installs docs: sphinx appears nowhere but this extra",
}


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


def _extras() -> dict:
    return _pyproject()["project"]["optional-dependencies"]


def _export_for(extra: str) -> Path:
    """`uv export --extra` normalises underscores, and so do the filenames."""
    return REQUIREMENTS / f"{extra.replace('_', '-')}.txt"


def _pinned_hash_counts(path: Path) -> list:
    """Every pin in an export, as `(distribution, hashes it carries)`.

    One entry per pin rather than per name. numpy is pinned twice in every
    engine export under exclusive `python_full_version` markers, and a dict
    keyed by name merges the two: stripping every hash off either block left it
    unflagged, because the other block's count answered for both.

    `--hash=` appearing anywhere in the file says nothing about the package on
    any given line either: uv writes `name==version \\` and then one indented
    `--hash=` line per artifact, so the hashes have to be counted per pin.
    """
    pins = []
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        pin = re.match(r"^([A-Za-z0-9._-]+)==", line)
        if pin:
            current = [pin.group(1).lower(), 0]
            pins.append(current)
        elif current and "--hash=" in line:
            current[1] += 1
        elif line and not line.startswith((" ", "\t", "#")):
            current = None
    return pins


def _installer_extra_call_sites() -> list:
    """Every `pip_install_extras_skip_pygobject` call, as `(line number, names)`.

    The call takes a log path and then one or more extra names, so the names are
    the words that follow it, up to whatever shell operator ends the command.
    Two of the six call sites end in `;` rather than whitespace, so cutting on
    the operator has to come before splitting on spaces. Read rather than
    listed: the point of this file is that a hand-kept list is what stales.

    One entry per call site, and every word is kept. Returning only the union
    and dropping words that did not look like an extra name hid a whole call
    site whenever the name was quoted, held in a variable, or spelled with a
    dash, and the union stayed non-empty from the other five. Keeping the word
    turns each of those into a name pyproject.toml does not declare, which is
    what the caller already fails on. That is not pedantry: the installer
    matches `^<extra> = [` against pyproject.toml verbatim, writes an empty file
    when it misses, and `pip_install_reqs_file` returns 0 on an empty file. A
    name this cannot read is an engine that installs nothing and reports
    success.
    """
    sites = []
    pattern = re.compile(r'pip_install_extras_skip_pygobject\s+"\$PIP_LOG_FILE"(.*)')
    for number, line in enumerate(INSTALLER.read_text(encoding="utf-8").splitlines(), 1):
        match = pattern.search(line)
        if not match:
            continue
        command = re.split(r"[;|&(){}#]", match.group(1))[0]
        names = {word.strip("\"'") for word in command.split() if word != "\\"}
        sites.append((number, names))
    return sites


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


def test_the_export_exemption_list_names_real_extras():
    """An exemption for an extra that no longer exists exempts nothing.

    Renaming `docs` while this entry stays would leave the new name silently
    unexported, which is the failure this whole file exists to prevent.
    """
    extras = set(_extras())
    assert extras, "no extras in pyproject.toml; the enumeration below would check nothing"
    unknown = sorted(EXPORT_EXEMPT.keys() - extras)
    assert not unknown, f"EXPORT_EXEMPT names extras that are gone: {unknown}"
    assert extras - EXPORT_EXEMPT.keys(), "every extra is exempt; nothing is being checked"


def test_every_extra_has_a_hash_pinned_export():
    """Enumerated from pyproject.toml, not from a list of what we remember.

    `[parakeet]`, `[faster_whisper]` and `[vosk]` each reached users with no
    export, because `just lock` names its exports by hand and nothing compared
    that list to the extras it is supposed to cover.
    """
    checked, missing = [], []
    for extra in _extras():
        if extra in EXPORT_EXEMPT:
            continue
        export = _export_for(extra)
        if not export.is_file():
            missing.append(f"[{extra}] has no {export.relative_to(REPO_ROOT)}")
            continue
        checked.append(extra)
        pinned = _pinned_hash_counts(export)
        if not pinned:
            missing.append(f"{export.relative_to(REPO_ROOT)} pins nothing")
            continue
        unhashed = sorted({name for name, hashes in pinned if not hashes})
        if unhashed:
            missing.append(f"{export.relative_to(REPO_ROOT)} carries no hash for {unhashed}")
    assert checked, "no extra was checked; the enumeration is empty or wholly exempt"
    assert not missing, "add the export to `just lock`, then re-run it:\n" + "\n".join(missing)


def test_just_lock_regenerates_every_extra_export():
    """A committed export nothing regenerates is a snapshot, not a pin."""
    lock_body = _justfile_recipes()["lock"][1]
    assert lock_body, "the lock recipe has no body"
    checked, missing = [], []
    for extra in _extras():
        if extra in EXPORT_EXEMPT:
            continue
        checked.append(extra)
        target = f"-o {_export_for(extra).relative_to(REPO_ROOT)}"
        if not any(target in line for line in lock_body):
            missing.append(target)
    assert checked, "no extra was checked; the enumeration is empty or wholly exempt"
    assert not missing, f"`just lock` writes no such file: {missing}"


def test_every_extra_reaches_its_own_export():
    """The export must actually carry what the extra declares."""
    checked, missing = [], []
    for extra, specs in _extras().items():
        if extra in EXPORT_EXEMPT:
            continue
        if not specs:
            missing.append(f"[{extra}] declares nothing, so its export proves nothing")
            continue
        export = _export_for(extra)
        if not export.is_file():
            continue  # reported by test_every_extra_has_a_hash_pinned_export
        checked.append(extra)
        absent = sorted(set(_requirement_names(specs)) - _exported_names(export))
        if absent:
            missing.append(f"{export.relative_to(REPO_ROOT)} is missing {absent}")
    assert checked, "no extra was compared against its export"
    assert not missing, "re-run `just lock`:\n" + "\n".join(missing)


def test_every_extra_the_installer_installs_is_pinnable():
    """install.sh is the path that hands users unpinned ranges today (2.3).

    Whatever it installs as an extra has to have an export before that swap can
    happen, so this reads the call sites rather than trusting the list above.
    Each site has to yield a name: one the reader cannot parse vanishes into the
    union otherwise, and the union stays non-empty from the sites it did parse.
    """
    sites = _installer_extra_call_sites()
    assert sites, "no pip_install_extras_skip_pygobject call sites found in install.sh"
    silent = [number for number, names in sites if not names]
    assert not silent, f"install.sh lines {silent} install extras this test cannot read"
    installed = {name for _, names in sites for name in names}
    declared = set(_extras())
    # Compared verbatim, not normalised: write_pip_reqs_skip_pygobject matches
    # `^<extra> = [` against pyproject.toml, so `faster-whisper` finds nothing
    # where `faster_whisper` is declared and installs the engine not at all.
    unknown = sorted(installed - declared)
    assert not unknown, f"install.sh installs extras pyproject.toml does not declare: {unknown}"
    unpinnable = sorted(e for e in installed if not _export_for(e).is_file())
    assert not unpinnable, f"install.sh installs these with no hash-pinned export: {unpinnable}"


def _export_checker() -> ModuleType:
    """Load scripts/check_exports.py without running it.

    Importing rather than shelling out keeps this offline: `export_commands`
    parses the recipe and starts no subprocess.
    """
    path = REPO_ROOT / "scripts" / "check_exports.py"
    spec = importlib.util.spec_from_file_location("check_exports", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_drift_check_covers_every_export_just_lock_writes():
    """A drift check that skips a file is a file that can drift.

    `uv pip compile` targets stay out: requirements/whisper.txt and the AppImage
    files resolve against live indexes on purpose, so they are neither offline
    reproducible nor derived from the lock. The recipe is parsed here a second
    way, by hand, so the checker's own parser is what is under test.
    """
    body = " ".join(line.removesuffix("\\") for line in _justfile_recipes()["lock"][1])
    written = set(re.findall(r"uv export .*?-o (\S+)", body))
    assert written, "the lock recipe has no `uv export` lines to check"
    covered = {
        target.relative_to(REPO_ROOT).as_posix()
        for _, target in _export_checker().export_commands()
    }
    assert covered == written, f"the drift check misses {sorted(written - covered)}"


def _changes_filter(name: str) -> list:
    """The path patterns under one `dorny/paths-filter` key, and only those.

    Searching the whole workflow would accept the pattern anywhere in it: moved
    into the `web` or `aur` filter it would still be found, while a scripts-only
    change quietly stopped waking the job that runs the checker.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    header = re.search(rf"^(?P<indent> +){name}:\n", text, re.M)
    assert header, f"no `{name}` filter in {WORKFLOW.name}"
    patterns = []
    for line in text[header.end() :].splitlines():
        if line.strip() and not line.startswith(header.group("indent") + " "):
            break
        if line.strip().startswith("- "):
            patterns.append(line.strip()[2:].strip().strip("\"'"))
    return patterns


def test_ci_runs_the_drift_check():
    """A guard no workflow runs is a guard that is not running.

    `just lock-check` and `just flatpak-deps-check` both sit in the justfile
    unwired to any workflow, which is how three engine exports could be added
    with nothing comparing them to the lock they came from.
    """
    assert "scripts/check_exports.py" in WORKFLOW.read_text(
        encoding="utf-8"
    ), "no job runs the export drift check, so a stale export reaches main unnoticed"
    # The job has to wake up for the files it checks, and for the checker
    # itself: a scripts-only change that missed the filter would skip both this
    # step and the tests that validate it.
    watched = _changes_filter("python")
    assert watched, "the python changes filter matches nothing"
    missing = [
        pattern
        for pattern in ("requirements/**", "uv.lock", "pyproject.toml", "justfile", "scripts/**")
        if pattern not in watched
    ]
    assert not missing, f"the python changes filter does not watch {missing}"
