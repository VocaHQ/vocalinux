"""Pin what a third-party action actually resolves to when CI runs it.

Every `uses:` in this repository floated on a moving tag — `@v4`, `@v5`,
`@release/v1`. A tag is writable by whoever owns the action, so
`KSXGitHub/github-actions-deploy-aur@v4.2.0`, which is handed the SSH key that
can push to our AUR package, was whatever that tag happened to point at on the
morning of a release. Same for the action that uploads our release assets and
the one that publishes to PyPI.

Parsed as text rather than YAML for the same reason as the sibling guards: the
only YAML parser in the venv arrives transitively through pre-commit.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

#: Owner whose refs may float: our own org is inside this repository's trust
#: boundary, and a shared workflow exists to propagate without 30 version bumps.
OWN_ORG = "vocahq"

SHA = re.compile(r"^[0-9a-f]{40}$")


def _uses() -> list:
    """(workflow, line number, ref, trailing comment) for every `uses:`."""
    found = []
    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for number, line in enumerate(workflow.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"\s*uses:\s*(\S+)\s*(?:#\s*(.*))?$", line)
            if match:
                found.append((workflow.name, number, match.group(1), match.group(2)))
    return found


def test_the_workflows_are_still_where_this_test_thinks_they_are():
    """A guard that silently scans nothing passes forever."""
    entries = _uses()
    assert len(entries) > 40, f"only found {len(entries)} `uses:` entries"


def test_every_third_party_action_is_pinned_to_a_commit():
    floating = [
        f"{workflow}:{number} {ref}"
        for workflow, number, ref, _ in _uses()
        if not SHA.match(ref.rpartition("@")[2]) and not ref.lower().startswith(f"{OWN_ORG}/")
    ]
    assert not floating, "these run with our secrets off a moving tag:\n" + "\n".join(floating)


def test_only_our_own_org_may_float():
    """The exemption is a rule about trust boundaries, not a list to append to."""
    for workflow, number, ref, _ in _uses():
        if SHA.match(ref.rpartition("@")[2]):
            continue
        owner = ref.split("/")[0].lower()
        assert owner == OWN_ORG, f"{workflow}:{number} exempts {owner}, which we do not own"


def test_every_pin_records_the_version_it_came_from():
    """A bare 40-hex SHA tells a reader nothing and gives Dependabot nothing to
    bump against."""
    unlabelled = [
        f"{workflow}:{number} {ref}"
        for workflow, number, ref, comment in _uses()
        if SHA.match(ref.rpartition("@")[2]) and not comment
    ]
    assert not unlabelled, "pinned with no version comment:\n" + "\n".join(unlabelled)


def test_something_moves_the_pins():
    """A pin nobody bumps is an action that stops getting its own security
    fixes, with the pin hiding that it has gone stale."""
    assert DEPENDABOT.exists(), "actions are pinned but nothing updates them"
    config = DEPENDABOT.read_text(encoding="utf-8")
    # Anchored on the ecosystem declaration, not the bare word: "github-actions"
    # is also the group name and appears in the comment, so a looser check passed
    # while the ecosystem had been switched to pip.
    assert re.search(
        r"^\s*-\s*package-ecosystem:\s*[\"']?github-actions[\"']?\s*$", config, re.M
    ), "dependabot.yml does not update the action pins"
