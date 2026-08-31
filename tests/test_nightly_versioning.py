"""A nightly artifact's filename and its own metadata have to agree.

`nightly.yml` used to build the wheel and then rename the file to carry the
nightly version, leaving `.dist-info` still saying 0.16.1 while the filename
claimed 0.16.1.dev<date>+<sha>. pip installed that without complaint for as long
as the AppImage build used pip. #743 moved that install to uv, which rejects the
mismatch outright:

    Wheel version does not match filename (0.16.1 != 0.16.1.dev20260831+71929b7),
    which indicates a malformed wheel.

Nightly went red the first night it ran the new build.sh and stayed red. The fix
is to stamp `vocalinux.version.__version__` — where `tool.setuptools.dynamic`
reads the version from — before building, so the two cannot disagree.

Parsed as text rather than YAML: the only YAML parser in the venv arrives
transitively through pre-commit.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
NIGHTLY = REPO_ROOT / ".github" / "workflows" / "nightly.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"

STAMP = '__version__ = \\"${'

#: The jobs that build a distribution, and so must stamp before they do.
BUILDING_JOBS = {"nightly", "nightly-appimage-arm64"}


def _text() -> str:
    return NIGHTLY.read_text(encoding="utf-8")


def _jobs() -> dict:
    """job name -> its block of the workflow, split on the 2-space indent."""
    text = _text()
    start = text.index("\njobs:\n")
    body = text[start:]
    headers = list(re.finditer(r"^  ([a-z0-9][a-z0-9-]*):$", body, re.M))
    assert headers, "no jobs found; nightly.yml's layout moved"

    jobs = {}
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(body)
        jobs[header.group(1)] = body[header.start() : end]
    return jobs


def _building_jobs() -> dict:
    return {name: block for name, block in _jobs().items() if "python -m build" in block}


def test_the_version_still_comes_from_the_file_the_workflow_stamps():
    """If setuptools stopped reading version.py, stamping it would silently do
    nothing and the mismatch would come back."""
    pyproject = PYPROJECT.read_text(encoding="utf-8")
    assert 'version = {attr = "vocalinux.version.__version__"}' in pyproject


def test_nightly_never_renames_a_built_artifact():
    """Renaming a wheel does not change what is recorded inside it."""
    text = _text()
    assert "Rename artifacts" not in text, "the rename step is back"
    offenders = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"\bmv\b.*dist/", line) or re.search(r"newname=", line)
    ]
    assert not offenders, "nightly renames build output:\n" + "\n".join(offenders)


def test_every_job_that_builds_stamps_the_version_first():
    jobs = _building_jobs()
    # A floor, not a fixed count. The guard is worthless if the parser quietly
    # stops finding a job, but a third build job should not fail CI merely for
    # existing: the loop below covers whatever is actually there.
    missing = BUILDING_JOBS - set(jobs)
    assert not missing, f"{sorted(missing)} no longer builds, or the parser stopped seeing it"
    for name, block in jobs.items():
        assert STAMP in block, f"{name} builds without stamping the version"
        assert block.index(STAMP) < block.index(
            "python -m build"
        ), f"{name} stamps the version after building, which changes nothing"


def test_the_stamp_is_verified_rather_than_assumed():
    """A `sed` that matches nothing exits 0 and hands the build a stale version."""
    for name, block in _building_jobs().items():
        assert re.search(
            r'grep -q "\^__version__ = ', block
        ), f"{name} does not check that the stamp landed"


def test_both_jobs_stamp_the_same_version():
    """The aarch64 job builds its own wheel; if it stamps something else, the two
    AppImages on one nightly release carry different versions.

    Anchored on the assignment that feeds `sed`, not on the value appearing
    anywhere in the job: it also appears in the AppImage step, which made an
    earlier version of this test pass while aarch64 stamped a date.
    """
    arm = _jobs()["nightly-appimage-arm64"]
    assert (
        'VERSION="${{ needs.nightly.outputs.version }}"' in arm
    ), "aarch64 stamps something other than the version the nightly job published"
