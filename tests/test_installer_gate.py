"""Regression guards for the install.sh build gate.

That the matrix job runs the installer, that it is allowed to fail a build, and
that the two lists which have to agree (the matrix's containers and the gate's
bootstrap arms) actually do.

These match the constructs themselves rather than bare substrings: every path
and flag worth guarding also appears in a comment or in a `fail` message in the
same file, so `"…" in text` passes on a script that no longer does the thing.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "install.sh"
GATE_SH = REPO_ROOT / "scripts" / "install-test.sh"
MATRIX = REPO_ROOT / ".github" / "workflows" / "distro-test-matrix.yml"
JUSTFILE = REPO_ROOT / "justfile"

#: Container image -> the ID its /etc/os-release reports, which is what the
#: gate's bootstrap `case "$ID"` switches on. A new container needs an entry
#: here and an arm there.
CONTAINER_OS_IDS = {
    "ubuntu:24.04": "ubuntu",
    "ubuntu:26.04": "ubuntu",
    "debian:12": "debian",
    "fedora:42": "fedora",
    "archlinux:latest": "arch",
    "opensuse/tumbleweed": "opensuse-tumbleweed",
}


def _matrix_text() -> str:
    return MATRIX.read_text(encoding="utf-8")


def _gate_text() -> str:
    return GATE_SH.read_text(encoding="utf-8")


def _without_comments(text: str) -> str:
    """Drop whole-line comments, so a guard cannot be satisfied by prose."""
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def _job_block(workflow_text: str, job: str) -> str:
    """The job's lines, from its key to the next key at the same indent."""
    lines = workflow_text.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if line.rstrip("\n") == f"  {job}:"),
        None,
    )
    assert start is not None, f"no {job} job in the workflow"
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if re.match(r"^  \S", line):
            break
        block.append(line)
    return "".join(block)


def _bootstrap_case() -> str:
    """The gate's bootstrap `case "$ID"`, which is not the only case on $ID."""
    blocks = re.findall(r'^case "\$ID" in\n(.*?)^esac', _gate_text(), re.M | re.S)
    bootstrap = [block for block in blocks if "apt-get" in block]
    assert len(bootstrap) == 1, 'no single `case "$ID"` installs the bootstrap packages'
    return bootstrap[0]


def _matrix_containers() -> list:
    """The container images the matrix runs, one per line by convention."""
    block = _job_block(_matrix_text(), "install")
    listing = re.search(r"^        container:\n((?:\s+- \S+\n)+)", block, re.M)
    assert listing, "the install job has no container list"
    return [line.strip()[2:] for line in listing.group(1).splitlines()]


def _paths_filters() -> list:
    """Every quoted entry under a `paths:` filter, push and pull_request alike."""
    return re.findall(r"^\s+- '([^']+)'$", _matrix_text(), re.M)


def test_the_matrix_runs_the_installer():
    """Checking for a function name or creating a venv by hand tests the
    container, not the installer."""
    block = _job_block(_matrix_text(), "install")
    assert re.search(r"^\s*docker run", block, re.M), "the matrix job must run a container"
    assert re.search(
        r'^\s*bash "\$PWD/scripts/install-test\.sh"$', block, re.M
    ), "the matrix job no longer runs the gate script"
    assert re.search(r"&& bash install\.sh --auto", _gate_text()), (
        "the gate no longer invokes install.sh; it would be testing the"
        " container rather than the installer again"
    )


def test_the_matrix_can_fail_a_build():
    """`continue-on-error: true` makes the whole matrix advisory."""
    block = _job_block(_matrix_text(), "install")
    assert not re.search(r"^\s*continue-on-error:\s*true", block, re.M), (
        "the install matrix is advisory again; a gate that cannot fail a build"
        " is documentation, not a gate"
    )


def test_every_matrix_container_has_a_bootstrap_arm():
    """install.sh needs sudo and a non-root user before it will start, and the
    gate provides them per package manager. A container with no arm fails at the
    `case "$ID"` fallthrough, 40 minutes into a CI run rather than here."""
    bootstrap = _bootstrap_case()
    for container in _matrix_containers():
        assert container in CONTAINER_OS_IDS, (
            f"{container} is in the matrix but not in CONTAINER_OS_IDS; add its"
            " /etc/os-release ID so this guard can check the gate handles it"
        )
        os_id = CONTAINER_OS_IDS[container]
        assert re.search(rf"^  [\w |-]*\b{re.escape(os_id)}\b[\w |-]*\)", bootstrap, re.M), (
            f"{container} reports ID={os_id}, which scripts/install-test.sh has"
            " no bootstrap arm for"
        )


def test_the_gate_installs_unattended_without_skipping_system_deps():
    """--auto because there is no TTY, --skip-models because a model is 40-75 MB
    per container per run and the download path is checksum-verified elsewhere.
    Never --skip-system-deps: the per-distro package installation is the point."""
    gate = _without_comments(_gate_text())
    assert re.search(r"bash install\.sh --auto --skip-models", gate)
    assert "--skip-system-deps" not in gate, (
        "the gate skips system dependency installation, which is the one part"
        " of install.sh the old matrix already failed to exercise"
    )


def test_the_gate_checks_the_model_manifest_ships():
    """--skip-models means install.sh never reads model_checksums.txt here, so
    the manifest leaving the tree would pass every other check in the gate. That
    is the shape of #736, minus the release-tag skew a local-mode gate cannot
    reach."""
    assert re.search(
        r'\[ -f "\$TREE/src/vocalinux/utils/model_checksums\.txt" \]', _gate_text()
    ), "the gate no longer checks the model manifest ships"
    assert (REPO_ROOT / "src" / "vocalinux" / "utils" / "model_checksums.txt").is_file()


def test_the_gate_runs_as_an_unprivileged_user():
    """install.sh refuses to run as root and calls sudo directly. Running the
    gate as root would test a path no user takes; without sudo it would not get
    past the first package install."""
    gate = _without_comments(_gate_text())
    assert "useradd" in gate
    assert re.search(r'su - "\$INSTALL_USER"', gate)
    assert "NOPASSWD" in gate


def test_the_installer_still_refuses_root():
    """The assumption the gate's user setup exists for. If install.sh starts
    allowing root, that setup is dead weight and should go deliberately."""
    assert re.search(r"\$EUID.{0,12}-eq 0", INSTALLER.read_text(encoding="utf-8")), (
        "install.sh no longer refuses to run as root; scripts/install-test.sh"
        " creates an unprivileged user only because of that check"
    )


def test_the_gate_takes_this_commit_from_git_not_the_working_directory():
    """git archive rather than cp: a stray venv, build artefact or uncommitted
    fix must not be able to make the gate pass, and it is why the checkout can be
    mounted read-only while local mode writes a venv. Running from the extracted
    tree is what puts install.sh in local mode, and so what makes the gate answer
    for this commit rather than for the last tag."""
    assert re.search(
        r'git -C "\$REPO" archive HEAD \| tar -x', _gate_text()
    ), "the gate no longer extracts the tree from git"
    installer = INSTALLER.read_text(encoding="utf-8").splitlines()
    assert any(
        "grep" in line and "pyproject.toml" in line and "vocalinux" in line for line in installer
    ), (
        "local mode is no longer detected from pyproject.toml in the working"
        " directory; the gate may now be testing a downloaded tag instead of"
        " this commit"
    )


def test_installer_changes_reach_the_gate():
    """A path that matches no filter starts no job at all, and the push and
    pull_request filters have to carry it independently."""
    filters = _paths_filters()
    for needed in ("install.sh", "scripts/**", "pyproject.toml"):
        assert (
            filters.count(needed) == 2
        ), f"{needed} is missing from a paths filter; a change there starts no gate"


def test_the_gate_is_runnable_locally():
    """CI and the local entry point must run the same script; a gate only CI
    can run is one nobody iterates on."""
    justfile = JUSTFILE.read_text(encoding="utf-8")
    assert re.search(r"^install-gate distro=", justfile, re.M)
    assert "scripts/install-test.sh" in justfile


def test_the_smoke_checks_what_the_installer_claims_to_have_created():
    """Asserting exit 0 alone would pass on an installer that silently
    installed nothing. These are the artefacts install.sh reports creating."""
    gate = _gate_text()
    for construct in (
        r'\[ -x "\$VENV/bin/python" \]',
        r'\[ -x "\$INSTALL_HOME/\.local/bin/vocalinux" \]',
        r'\[ -f "\$INSTALL_HOME/\.local/share/applications/vocalinux\.desktop" \]',
        r"'\$INSTALL_HOME/\.local/bin/vocalinux' --version",
    ):
        assert re.search(construct, gate), f"the smoke no longer asserts {construct}"


def test_the_smoke_checks_what_an_import_walk_cannot_see():
    """Two blind spots of a Python-only smoke: the injection backends are
    reached through subprocess, and keyboard_backends imports evdev and pynput
    under `except ImportError`, so both stay green when the binaries are absent
    or neither backend built."""
    gate = _gate_text()
    assert re.search(
        r"^for tool in xclip xsel wl-copy; do", gate, re.M
    ), "the smoke no longer checks the injection binaries install.sh promises"
    assert re.search(r"^\s*command -v ibus-daemon\b", gate, re.M), (
        "the smoke no longer checks the IBus runtime, so trading the openSUSE"
        " or arch package for a typelib-only one would pass again"
    )
    assert re.search(r"^assert EVDEV_AVAILABLE or PYNPUT_AVAILABLE", gate, re.M), (
        "the smoke imports keyboard_backends without asserting a backend is"
        " available, which is the failure the suse compiler packages fix"
    )


REMOTE_GATE_SH = REPO_ROOT / "scripts" / "install-remote-test.sh"


def _remote_gate_text() -> str:
    return REMOTE_GATE_SH.read_text(encoding="utf-8")


def _remote_bootstrap_case() -> str:
    """The remote gate's bootstrap `case "$ID"`, which is not the only case."""
    blocks = re.findall(r'^case "\$ID" in\n(.*?)^esac', _remote_gate_text(), re.M | re.S)
    bootstrap = [block for block in blocks if "apt-get" in block]
    assert len(bootstrap) == 1, 'no single `case "$ID"` installs the bootstrap packages'
    return bootstrap[0]


def _remote_job_image() -> str:
    """The container image the install-remote job runs the gate in."""
    block = _job_block(_matrix_text(), "install-remote")
    run = re.search(r'^\s*(\S+)\s*\\\n\s*bash "\$PWD/scripts/install-remote-test\.sh"', block, re.M)
    assert run, "the install-remote job has no docker image line above the gate call"
    return run.group(1)


def test_the_workflow_runs_the_remote_gate():
    """The remote path (bootstrap outside a checkout -> tag -> clone/fetch ->
    handoff) is the one a curl|bash user takes; a gate that only runs the local
    mode leaves it unguarded."""
    block = _job_block(_matrix_text(), "install-remote")
    assert re.search(r"^\s*docker run", block, re.M), "the remote job must run a container"
    assert re.search(
        r'^\s*bash "\$PWD/scripts/install-remote-test\.sh"$', block, re.M
    ), "the remote job no longer runs the remote gate script"


def test_the_remote_gate_can_fail_a_build():
    """Same rule as the local matrix: advisory jobs are documentation."""
    block = _job_block(_matrix_text(), "install-remote")
    assert not re.search(r"^\s*continue-on-error:\s*true", block, re.M), (
        "the remote install gate is advisory; a gate that cannot fail a build"
        " is documentation, not a gate"
    )


def test_the_remote_gate_selects_a_tag():
    """Tag selection is half the remote contract; a run without --tag resolves
    whatever the latest release API returns instead of a chosen ref."""
    gate = _without_comments(_remote_gate_text())
    assert re.search(r"--tag=", gate), (
        "the remote gate no longer passes --tag; it tests the latest-release"
        " fallback rather than the selectable-tag path"
    )


def test_the_remote_gate_fails_closed_on_the_selected_tag():
    """Guardrail: installer, sourced modules and requirement exports must all
    come from the selected tag. The only evidence is the clone's HEAD equalling
    the tag commit the gate published."""
    gate = _without_comments(_remote_gate_text())
    assert re.search(r"rev-parse HEAD", gate)
    assert re.search(r'"\$cloned_sha" = "\$EXPECTED_SHA"', gate), (
        "the remote gate no longer compares the clone's HEAD to the tag commit;"
        " installing a different revision would pass"
    )
    assert re.search(
        r'rev-parse "\$GATE_TAG\^\{commit\}"', gate
    ), "the remote gate no longer checks the selected tag ref reached the clone"


def test_the_remote_gate_bootstraps_outside_a_checkout():
    """install.sh chooses local mode from a pyproject.toml in the working
    directory; the remote path only runs when the bootstrap starts where no
    checkout exists. Overriding the clone source is what keeps the run on this
    commit instead of the public repo's last release."""
    gate = _without_comments(_remote_gate_text())
    assert "VOCALINUX_REPO_URL" in gate, (
        "the remote gate no longer redirects the clone source; it would"
        " install the public repo's tag rather than this commit"
    )
    installer = _without_comments(INSTALLER.read_text(encoding="utf-8"))
    assert re.search(r"VOCALINUX_REPO_URL:-https://github\.com/VocaHQ/vocalinux\.git", installer), (
        "install.sh no longer honors VOCALINUX_REPO_URL; the gate's mirror"
        " cannot reach it and the clone falls back to the public repo"
    )


def test_the_remote_gate_runs_as_an_unprivileged_user():
    """install.sh refuses to run as root and calls sudo directly. The remote
    handoff re-execs as the same user, so a root run would test a path no
    user takes twice over."""
    gate = _without_comments(_remote_gate_text())
    assert "useradd" in gate
    assert re.search(r'su - "\$INSTALL_USER"', gate)
    assert "NOPASSWD" in gate


def test_the_remote_gate_covers_the_fetch_arm():
    """The remote path has two ways in: `git clone` on a fresh machine and
    `git fetch origin tag` + `git reset --hard` over an existing clone, which
    is what every re-run hits. Asserting the update message in an install log
    proves the second arm ran."""
    gate = _without_comments(_remote_gate_text())
    assert re.search(
        r'grep -l "Updating existing clone"', gate
    ), "the remote gate no longer checks the fetch+reset arm ran"
    assert gate.count("run_remote_install") >= 3, "the remote gate no longer runs the install twice"


def test_the_remote_gate_checks_handoff_artifacts():
    """handoff_to_tagged_installer appends --venv-dir and re-execs with the
    remote marker; the remote venv and the relocated activation helper are the
    only observable proof both arrived."""
    gate = _without_comments(_remote_gate_text())
    for construct in (
        r'\[ -x "\$REMOTE_VENV/bin/python" \]',
        r'\[ -f "\$INSTALL_HOME/\.local/bin/activate-vocalinux\.sh" \]',
    ):
        assert re.search(construct, gate), f"the remote gate no longer asserts {construct}"


def test_the_remote_gate_smoke_tests_the_installed_app():
    """Same standard as the local gate: the app binary answers --version
    through the wrapper the user's PATH carries."""
    gate = _without_comments(_remote_gate_text())
    assert re.search(r"'\$INSTALL_HOME/\.local/bin/vocalinux' --version", gate)
    assert re.search(
        r'\[ -x "\$INSTALL_HOME/\.local/bin/vocalinux" \]', gate
    ), "the remote gate no longer asserts the user-facing wrapper exists"


def test_the_remote_gate_has_a_bootstrap_arm_for_its_distro():
    """The job is pinned to one container; the gate's bootstrap arms are per
    /etc/os-release ID. A pinned distro with no arm fails at the case
    fallthrough 40 minutes into CI rather than here."""
    image = _remote_job_image()
    assert image in CONTAINER_OS_IDS, (
        f"{image} is the remote gate's container but not in CONTAINER_OS_IDS;"
        " add its /etc/os-release ID so this guard can check the gate handles it"
    )
    os_id = CONTAINER_OS_IDS[image]
    bootstrap = _remote_bootstrap_case()
    assert re.search(rf"^  [\w |-]*\b{re.escape(os_id)}\b[\w |-]*\)", bootstrap, re.M), (
        f"{image} reports ID={os_id}, which scripts/install-remote-test.sh has"
        " no bootstrap arm for"
    )


def test_the_remote_gate_is_runnable_locally():
    """CI and the local entry point must run the same script."""
    justfile = JUSTFILE.read_text(encoding="utf-8")
    assert re.search(r"^remote-install-gate distro=", justfile, re.M)
    assert "scripts/install-remote-test.sh" in justfile
