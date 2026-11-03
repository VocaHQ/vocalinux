#!/usr/bin/env bash
# Run install.sh's remote path end to end in a distro container and check what
# it installed.
#
# Usage (a read-only mount is enough; the tag is published from git, not the
# tree):
#   docker run --rm -v "$PWD:/repo:ro" debian:12 bash /repo/scripts/install-remote-test.sh
#   or: just remote-install-gate debian:12
#
# The mirror carries controlled releases based on HEAD, with behavioral
# witnesses in the installer, every sourced module, and both mandatory exports.
# The bootstrap deliberately cannot install: continuing past the tagged handoff
# is an error. Real pip installs tiny hashed wheel witnesses *alongside* the
# unchanged locked dependencies, proving which exports it consumed.
#
# Only curl's exact latest-release endpoint is substituted. Git, other network
# calls, system/Python dependencies, and the installed-app smoke are real.
# Cover explicit-tag clone/fetch (including a terminal-backed streaming pipe),
# controlled latest selection, cross-release --upgrade, API outage, and incomplete
# releases. Each case gets a fresh HOME except the reinstall/upgrade sequence.
# --skip-models avoids repeated model downloads, whose checksums are exercised elsewhere;
# never skip system dependency installation here.
set -euo pipefail

REPO="${REPO:-/repo}"
INSTALL_USER="${INSTALL_USER:-installer}"
USER_HOME="/home/$INSTALL_USER"
INSTALL_HOME="$USER_HOME"
# Opaque on purpose: a name the public repository cannot already carry, so a
# silent fallback to GitHub fails loudly instead of installing the wrong ref.
GATE_TAG="${GATE_TAG:-v0.0.0-remote-gate}"
MIRROR="/srv/vocalinux-remote.git"
WORK="/srv/remote-gate"
FIXTURE_SOURCE="/tmp/gate-source"
BOOTSTRAP="$WORK/bootstrap.sh"
LATEST_TAG="$GATE_TAG-latest"
LATEST_RESPONSE="unavailable"
MISSING_MODULE_TAG="$GATE_TAG-missing-module"
MISSING_RUNTIME_TAG="$GATE_TAG-missing-runtime"
MISSING_BUILD_TAG="$GATE_TAG-missing-build"

fail() {
  echo "FAIL: $*" >&2
  dump_install_log
  exit 1
}

# install.sh writes a full transcript under ~/.local/state/vocalinux/. It is the
# only place the per-distro package manager output survives.
dump_install_log() {
  local log
  log="$(ls -1t "$INSTALL_HOME"/.local/state/vocalinux/install-*.log 2>/dev/null | head -n1 || true)"
  if [ -n "$log" ]; then
    echo "== last 200 lines of $log ==" >&2
    tail -n 200 "$log" >&2
  else
    echo "== no install log was written ==" >&2
  fi
}

# A mirror going slow mid-transaction leaves a half-populated cache, so
# re-running the same transaction resumes rather than restarts.
retry() {
  local attempt
  for attempt in 1 2 3; do
    "$@" && return 0
    echo "   '$1' failed (attempt $attempt); retrying" >&2
    sleep 5
  done
  return 1
}

[ -f "$REPO/install.sh" ] || fail "$REPO/install.sh not found; mount the checkout at \$REPO"

. /etc/os-release
echo "== ${NAME:-unknown} ${VERSION_ID:-} =="

echo "== Bootstrap: sudo, git and an unprivileged user =="
# git and Python build the fixtures; curl is needed for the exact-endpoint shim.
# All remaining system dependencies must be installed by install.sh itself.
# Same arms as scripts/install-test.sh so `just remote-install-gate <distro>`
# works everywhere the local gate does.
case "$ID" in
  ubuntu | debian)
    export DEBIAN_FRONTEND=noninteractive
    retry apt-get update -qq
    retry apt-get install -y -qq sudo git curl python3 ca-certificates >/dev/null
    ;;
  fedora | rhel | centos)
    retry dnf install -y -q sudo git curl python3 shadow-utils >/dev/null
    ;;
  arch)
    # -Syu, never -Sy: archlinux:latest lags the mirrors, and a partial upgrade
    # would be this script's breakage rather than the installer's.
    retry pacman -Syu --noconfirm --needed sudo git curl python >/dev/null
    ;;
  opensuse-tumbleweed | opensuse-leap | sles)
    retry zypper --non-interactive --gpg-auto-import-keys refresh >/dev/null
    retry zypper --non-interactive install -y sudo git curl python3 >/dev/null
    ;;
  *)
    fail "no bootstrap arm for ID='$ID'; add one when adding the container"
    ;;
esac

id -u "$INSTALL_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$INSTALL_USER"
echo "$INSTALL_USER ALL=(ALL) NOPASSWD: ALL" >"/etc/sudoers.d/$INSTALL_USER"
chmod 0440 "/etc/sudoers.d/$INSTALL_USER"

echo "== Publish controlled releases based on HEAD in a local mirror =="
# safe.directory: the mounted checkout and, for a linked worktree, its mounted
# common gitdir are owned by another uid.
git config --global --add safe.directory '*'
# CI checks out with fetch-depth 1, and a shallow boundary commit can neither
# be pushed nor fetched into a ref ("shallow update not allowed"). The tag
# therefore carries an orphan commit: a root commit is not a shallow root.
# Only the fixture helper's explicit witnesses differ from HEAD's tree.
SOURCE_TREE="$(git -C "$REPO" rev-parse 'HEAD^{tree}')" \
  || fail "$REPO is not a git checkout; the gate publishes the tag from git"
git clone --quiet --depth 1 "file://$REPO" "$FIXTURE_SOURCE"
# commit-tree needs an identity the bare container does not carry.
export GIT_AUTHOR_NAME=gate GIT_AUTHOR_EMAIL=gate@local
export GIT_COMMITTER_NAME=gate GIT_COMMITTER_EMAIL=gate@local
mkdir -p "$WORK"
git init --bare "$MIRROR" >/dev/null
publish_tree() {
  local tree=$1 ref=$2 sha
  sha="$(git -C "$FIXTURE_SOURCE" commit-tree "$tree" -m "remote-install gate: $ref")"
  git -C "$FIXTURE_SOURCE" push "$MIRROR" "$sha:$ref" >/dev/null
}

publish_fixture() {
  local role=$1 tag=$2 tree
  git -C "$FIXTURE_SOURCE" reset --hard HEAD >/dev/null
  python3 "$REPO/scripts/remote_installer_fixture.py" "$FIXTURE_SOURCE" "$WORK" "$role"
  git -C "$FIXTURE_SOURCE" add install.sh install.d requirements/runtime.txt requirements/installer-build.txt src/vocalinux/version.py
  tree="$(git -C "$FIXTURE_SOURCE" write-tree)"
  [ "$tree" != "$SOURCE_TREE" ] || fail "the $role fixture is indistinguishable from HEAD"
  publish_tree "$tree" "refs/tags/$tag"
}

publish_fixture explicit "$GATE_TAG"
publish_fixture latest "$LATEST_TAG"
# A valid default branch makes a wrong-ref fallback observable rather than
# relying on git having no other revision available.
publish_tree "$SOURCE_TREE" refs/heads/main
git -C "$MIRROR" symbolic-ref HEAD refs/heads/main

publish_incomplete() {
  local missing=$1 tag=$2
  git -C "$FIXTURE_SOURCE" read-tree "$(git -C "$MIRROR" rev-parse "$GATE_TAG^{tree}")"
  git -C "$FIXTURE_SOURCE" update-index --force-remove "$missing"
  publish_tree "$(git -C "$FIXTURE_SOURCE" write-tree)" "refs/tags/$tag"
}
publish_incomplete install.d/system_dependencies.sh "$MISSING_MODULE_TAG"
publish_incomplete requirements/runtime.txt "$MISSING_RUNTIME_TAG"
publish_incomplete requirements/installer-build.txt "$MISSING_BUILD_TAG"
# The installer clones as $INSTALL_USER, and git refuses a root-owned remote
# for anyone else as "dubious ownership".
chown -R "$INSTALL_USER:$INSTALL_USER" "$MIRROR"

printf '{"tag_name":"%s"}\n' "$LATEST_TAG" > "$WORK/latest.json"
# Mutation control: deliberately bypass handoff. A SHA-only fixture used to
# accept this behavior; this bootstrap must reject it even after a real clone.
sed '/^    handoff_to_tagged_installer$/,+1d' "$BOOTSTRAP" > "$WORK/no-handoff.sh"

select_scenario() {
  local name=$1
  INSTALL_HOME="$USER_HOME/remote-gate/$name"
  [ ! -e "$INSTALL_HOME" ] || fail "scenario $name is not isolated: $INSTALL_HOME already exists"
  mkdir -p "$INSTALL_HOME"
  chown "$INSTALL_USER:$INSTALL_USER" "$INSTALL_HOME"
  CLONE_DIR="$INSTALL_HOME/.local/share/vocalinux-install"
  REMOTE_VENV="$INSTALL_HOME/.local/share/vocalinux/venv"
  CASE_OUTPUT="$WORK/$name.log"
}

run_remote_install() {
  # cd to $INSTALL_HOME so the bootstrap sees no checkout: local mode is chosen
  # by a pyproject.toml naming vocalinux in the working directory, and the
  # remote path is the one under test.
  local args=""
  if [ "$#" -gt 0 ]; then
    printf -v args ' %q' "$@"
  fi
  run_remote_command "bash '$BOOTSTRAP' --auto --skip-models $args"
}

run_remote_command() {
  local command=$1
  su - "$INSTALL_USER" -c "export HOME='$INSTALL_HOME'; cd '$INSTALL_HOME' && \
    PATH='$WORK/bin':\"\$PATH\" VOCALINUX_REPO_URL='file://$MIRROR' \
    REMOTE_GATE_LATEST='$LATEST_RESPONSE' $command" \
    2>&1 | tee "$CASE_OUTPUT"
}

# The user's literal `curl | bash`: installer code reaches bash on a pipe while
# a controlling terminal exists. `script` allocates that pty — a saved file on
# stdin or a headless pipe takes the headless --auto branch instead, which is
# exactly how the fd-0 redirect regression in #933 slipped through. bsdutils /
# util-linux `script` is in the base package set of every gated distro.
command -v script >/dev/null 2>&1 || fail "script(1) not found; needed to give the piped run a terminal"
#
# The producer half matters too: a `cat` of the whole file finishes inside the
# pipe buffer long before bash reaches the tagged-installer handoff, so it can
# never be killed by a consumer that abandons the pipe the way a still-
# streaming curl can (the error 23 the #933 fix still had to drain for). The
# helper below trickles the bootstrap so it is mid-write at the handoff, and
# pipefail makes its exit status count — a consumer that closes the pipe early
# kills it with SIGPIPE and fails the run instead of hiding behind bash's own
# exit status.
PIPED_FEED=/tmp/vl-piped-feed.sh
cat >"$PIPED_FEED" <<'EOF'
#!/usr/bin/env bash
# Usage: vl-piped-feed.sh BOOTSTRAP [installer args...]
set -o pipefail
bootstrap=$1; shift
# ~16 KiB/s: still writing (and soon blocked on the full pipe buffer) when the
# bootstrap reaches the tagged-installer handoff, the way curl is mid-download.
drip() {
  local file=$1 chunk rc=0
  split -b 8192 "$file" /tmp/vl-feed-
  for chunk in /tmp/vl-feed-*; do
    # A cat killed by SIGPIPE means the consumer closed the pipe early — the
    # download failure this arm exists to catch. Keep the status through the
    # cleanup so pipefail above sees it.
    cat "$chunk" || { rc=$?; break; }
    sleep 0.5
  done
  rm -f /tmp/vl-feed-*
  return "$rc"
}
drip "$bootstrap" | bash -s -- "$@"
EOF
chmod 0755 "$PIPED_FEED"
run_remote_install_piped() {
  run_remote_command "script -qec \"'$PIPED_FEED' '$BOOTSTRAP' --auto --skip-models '--tag=$GATE_TAG'\" /dev/null"
}

assert_trace() {
  local role=$1 module
  {
    echo bootstrap
    echo "installer:$role"
    for module in package_map.sh interactive.sh system_dependencies.sh models.sh desktop.sh; do
      echo "module:$role:$module"
    done
  } > "$WORK/expected.trace"
  diff -u "$WORK/expected.trace" "$INSTALL_HOME/remote-gate.trace" \
    || fail "the tagged installer and modules did not execute exactly once ($role)"
}

assert_selected_revision() {
  local tag=$1
  EXPECTED_SHA="$(git -C "$MIRROR" rev-parse "$tag^{commit}")"
  local expected_tree cloned_sha cloned_tree
  expected_tree="$(git -C "$MIRROR" rev-parse "$tag^{tree}")"
  [ -d "$CLONE_DIR/.git" ] || fail "remote install left no clone at $CLONE_DIR"
  cloned_sha="$(git -C "$CLONE_DIR" rev-parse HEAD)"
  [ "$cloned_sha" = "$EXPECTED_SHA" ] || fail \
    "installed from the wrong revision: clone HEAD is $cloned_sha, $tag is $EXPECTED_SHA"
  [ "$(git -C "$CLONE_DIR" rev-parse "$tag^{commit}" 2>/dev/null || true)" = "$EXPECTED_SHA" ] \
    || fail "the clone does not carry the selected tag ref $tag"
  cloned_tree="$(git -C "$CLONE_DIR" rev-parse 'HEAD^{tree}')"
  [ "$cloned_tree" = "$expected_tree" ] || fail "the clone's tree is not the selected fixture's tree"
  git -C "$CLONE_DIR" diff --exit-code HEAD -- install.sh install.d requirements src/vocalinux/version.py >/dev/null \
    || fail "the installer, modules, exports or app version were modified after checkout"
}

assert_remote_install() {
  local tag=$1 role=$2 version=$3
  echo "== Assert: the clone is exactly the selected tag =="
  assert_selected_revision "$tag"
  assert_trace "$role"

  echo "== Assert: real pip consumed both tagged exports =="
  su - "$INSTALL_USER" -c "export HOME='$INSTALL_HOME'; '$REMOTE_VENV/bin/python' - '$version'" <<'PY' \
    || fail "pip did not install the selected release's export witnesses"
import sys
from importlib.metadata import version

for kind in ("build", "runtime"):
    name = f"vocalinux-remote-{kind}-fixture"
    assert version(name) == sys.argv[1], (name, version(name), sys.argv[1])
PY

  # The artifacts the #701 guardrail names: the tagged installer, its sourced
  # modules, and the exports pip installs with --require-hashes.
  [ -f "$CLONE_DIR/install.d/system_dependencies.sh" ] \
    || fail "the clone ships no install.d/system_dependencies.sh for the tagged installer to source"
  [ -f "$CLONE_DIR/requirements/runtime.txt" ] \
    || fail "the clone ships no requirements/runtime.txt for the tagged installer to install"
  # Same shape as the local gate's #736 check, now reachable through the remote
  # path: --skip-models means the run itself never reads the manifest.
  [ -f "$CLONE_DIR/src/vocalinux/utils/model_checksums.txt" ] \
    || fail "the tag ships no src/vocalinux/utils/model_checksums.txt; install.sh pins model downloads against it"

  echo "== Assert: the handoff carried the original arguments =="
  # handoff_to_tagged_installer appends --venv-dir; a venv anywhere else means
  # the appended argument was dropped.
  [ -x "$REMOTE_VENV/bin/python" ] \
    || fail "no remote venv at $REMOTE_VENV; the handoff's --venv-dir did not reach the tagged installer"
  # The remote marker relocates the activation helper to ~/.local/bin only when
  # VOCALINUX_REMOTE_INSTALL survives the exec.
  [ -f "$INSTALL_HOME/.local/bin/activate-vocalinux.sh" ] \
    || fail "no ~/.local/bin/activate-vocalinux.sh; the remote marker did not survive the handoff"
  # --skip-models forwarded: a model in the data dir means the tagged installer
  # re-parsed arguments the handoff did not deliver.
  if [ -d "$INSTALL_HOME/.local/share/vocalinux/models" ]; then
    [ -z "$(find "$INSTALL_HOME/.local/share/vocalinux/models" -type f -print -quit)" ] \
      || fail "models were downloaded; --skip-models did not survive the handoff"
  fi

  echo "== Assert: the installed app is there and answers =="
  [ -x "$INSTALL_HOME/.local/bin/vocalinux" ] || fail "no wrapper at ~/.local/bin/vocalinux"
  [ -x "$INSTALL_HOME/.local/bin/vocalinux-gui" ] || fail "no wrapper at ~/.local/bin/vocalinux-gui"
  [ -f "$INSTALL_HOME/.local/share/applications/vocalinux.desktop" ] \
    || fail "no desktop entry; install_desktop_entry did not run"

  # The version the wrapper reports must be the tag's own, not an assertion
  # about a version string composed locally.
  local expected_version version_output
  expected_version="$(grep -oP '__version__\s*=\s*"\K[^"]+' "$CLONE_DIR/src/vocalinux/version.py")" \
    || fail "cannot read __version__ from the clone's version.py"
  version_output="$(su - "$INSTALL_USER" -c "export HOME='$INSTALL_HOME'; '$INSTALL_HOME/.local/bin/vocalinux' --version")" \
    || fail "the installed wrapper cannot report a version"
  case "$version_output" in
    *"$expected_version"*) ;;
    *) fail "wrapper reports '$version_output', expected the tag's $expected_version" ;;
  esac
  echo "   vocalinux --version: $version_output"

  # Same blind spots as the local gate: the injection binaries are reached
  # through subprocess, and the IBus runtime only where the package list
  # promises it.
  for tool in xclip xsel wl-copy; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is not on PATH; install.sh lists it for every distro"
  done
  case "$ID" in
    arch | opensuse-tumbleweed | opensuse-leap | sles)
      command -v ibus-daemon >/dev/null 2>&1 \
        || fail "no ibus-daemon: the package list ships the IBus typelib without the runtime ibus_engine.py spawns"
      ;;
  esac

  su - "$INSTALL_USER" -c "export HOME='$INSTALL_HOME'; '$REMOTE_VENV/bin/python' - '$expected_version'" <<'PY' || fail "the installation does not import"
import sys
from importlib.metadata import version

import vocalinux.main
import vocalinux.ui.tray_indicator
import vocalinux.speech_recognition.recognition_manager
import vocalinux.text_injection.text_injector
from vocalinux.ui.keyboard_backends import EVDEV_AVAILABLE, PYNPUT_AVAILABLE
import gi

assert version("vocalinux") == sys.argv[1], "installed package metadata is not the selected release"

# keyboard_backends imports each backend under `except ImportError`, so the
# import above stays clean when evdev and pynput both failed to build. Assert
# the flags rather than the import.
assert EVDEV_AVAILABLE or PYNPUT_AVAILABLE, (
    "no keyboard backend is importable: evdev and pynput both failed to install"
)

# The typelibs the installer is responsible for putting on the system. Both are
# loaded lazily at runtime, so importing the modules above proves nothing about
# them: a missing one would surface on a user's first dictation instead.
gi.require_version("Gtk", "3.0")
gi.require_version("IBus", "1.0")
from gi.repository import Gtk, IBus  # noqa: F401

print(
    "   main, tray, recognition, injection, Gtk and IBus import;"
    f" keyboard backends: evdev={EVDEV_AVAILABLE} pynput={PYNPUT_AVAILABLE}"
)
PY
}

assert_api_unused() {
  [ ! -e "$INSTALL_HOME/remote-gate.api" ] || fail "an explicit --tag consulted the latest API"
}

assert_no_success() {
  local artifact
  for artifact in .local/bin/vocalinux .local/bin/vocalinux-gui .local/share/applications/vocalinux.desktop; do
    [ ! -e "$INSTALL_HOME/$artifact" ] || fail "failed install created $artifact"
  done
  if grep -Fq 'Installation Complete!' "$CASE_OUTPUT"; then
    fail "failed install printed the success banner"
  fi
  if [ -x "$REMOTE_VENV/bin/python" ]; then
    su - "$INSTALL_USER" -c "'$REMOTE_VENV/bin/python' -" <<'PY' \
      || fail "failed install continued with a project installation"
from importlib.metadata import PackageNotFoundError, distribution

try:
    distribution("vocalinux")
except PackageNotFoundError:
    pass
else:
    raise AssertionError("vocalinux was installed despite missing release inputs")
PY
  fi
}

expect_failure() {
  local expected_rc=$1 reason=$2 rc=0
  shift 2
  run_remote_install "$@" || rc=$?
  [ "$rc" -eq "$expected_rc" ] || fail "expected exit $expected_rc ($reason), got $rc"
  grep -Fq -- "$reason" "$CASE_OUTPUT" || fail "failure did not explain: $reason"
  assert_no_success
}

echo "== Run 1: explicit tag with unavailable API (fresh clone) as $INSTALL_USER =="
select_scenario explicit
START=$(date +%s)
run_remote_install "--tag=$GATE_TAG" || fail "the remote install exited non-zero on a fresh clone"
echo "   install took $(( $(date +%s) - START ))s"
assert_remote_install "$GATE_TAG" explicit 1.0
assert_api_unused

echo "== Run 2: re-run over the existing clone (fetch + reset), piped under a terminal =="
# The second bootstrap sees $CLONE_DIR/.git and updates it instead of cloning:
# the arm a user re-running curl|bash takes on every release after the first —
# served here literally through `cat | bash` on a pty so the terminal-backed
# pipe keeps regression coverage (#933).
# Move the clone off the tag and drop its local tag ref first: a run that only
# had to notice the right commit was already checked out would pass even if
# the fetch and reset were both no-ops.
# Remove export witnesses too: a rerun that stops consuming either export must
# not pass on packages left by run 1.
su - "$INSTALL_USER" -c "'$REMOTE_VENV/bin/python' -m pip uninstall -y \
  vocalinux-remote-build-fixture vocalinux-remote-runtime-fixture \
  && rm '$INSTALL_HOME/remote-gate.trace'" >/dev/null
AWAY_SHA="$(su - "$INSTALL_USER" -c "cd '$CLONE_DIR' && \
  printf '\\nexit 98\\n' >> install.sh && git add install.sh && \
  GIT_AUTHOR_NAME=gate GIT_AUTHOR_EMAIL=gate@local \
  GIT_COMMITTER_NAME=gate GIT_COMMITTER_EMAIL=gate@local \
  git commit-tree \"\$(git write-tree)\" -p HEAD -m moved")"
su - "$INSTALL_USER" -c "git -C '$CLONE_DIR' reset --hard '$AWAY_SHA' \
  && git -C '$CLONE_DIR' update-ref -d 'refs/tags/$GATE_TAG'" \
  || fail "could not move the clone off $GATE_TAG for the re-run arm"
[ "$(git -C "$CLONE_DIR" rev-parse HEAD)" = "$AWAY_SHA" ] \
  || fail "the clone did not move off $GATE_TAG; the re-run proves nothing"
[ -z "$(git -C "$CLONE_DIR" tag -l "$GATE_TAG")" ] \
  || fail "the clone kept refs/tags/$GATE_TAG; the re-run proves nothing"
run_remote_install_piped || fail "the terminal-backed piped install exited non-zero over the existing clone"
grep -l "Updating existing clone" "$CASE_OUTPUT" >/dev/null 2>&1 \
  || fail "no install log shows 'Updating existing clone'; the fetch arm did not run"
assert_remote_install "$GATE_TAG" explicit 1.0
assert_api_unused

echo "== Run 3: --upgrade moves the existing install to the latest release and keeps user settings =="
# Keep the old export witnesses installed: real pip must replace 1.0 with 2.0,
# not pass on packages inherited from the previous release.
CASE_OUTPUT="$WORK/upgrade.log"
LATEST_RESPONSE="$WORK/latest.json"
UPGRADE_FROM_VERSION="$(grep -oP '__version__\s*=\s*"\K[^"]+' "$CLONE_DIR/src/vocalinux/version.py")"
UPGRADE_VENV_ID="$(stat -c '%d:%i' "$REMOTE_VENV")"
cat > "$WORK/upgrade-config.json" <<'JSON'
{
  "speech_recognition": {"engine": "remote_api", "remote_api_url": "http://127.0.0.1:9999/transcribe"},
  "shortcuts": {"mode": "toggle", "toggle_recognition": "ctrl+alt+space"},
  "ui": {"show_notifications": false},
  "remote_gate_custom_setting": "keep this, including whitespace"
}
JSON
install -o "$INSTALL_USER" -g "$INSTALL_USER" -m 0600 \
  "$WORK/upgrade-config.json" "$INSTALL_HOME/.config/vocalinux/config.json"
su - "$INSTALL_USER" -c "printf '%s\\n' '$GATE_TAG' > '$REMOTE_VENV/remote-gate.keep' \
  && rm '$INSTALL_HOME/remote-gate.trace'"
run_remote_install --upgrade || fail "cross-release remote upgrade failed"
grep -Fq "Upgrade mode: keeping configured engine 'remote_api'." "$CASE_OUTPUT" \
  || fail "--upgrade did not reach the tagged installer or retain the configured engine"
grep -Fq 'Updating existing clone' "$CASE_OUTPUT" || fail "upgrade did not fetch the new release"
grep -qx latest "$INSTALL_HOME/remote-gate.api" || fail "upgrade did not consult the latest API"
cmp "$WORK/upgrade-config.json" "$INSTALL_HOME/.config/vocalinux/config.json" \
  || fail "upgrade changed config.json"
[ "$(stat -c '%d:%i' "$REMOTE_VENV")" = "$UPGRADE_VENV_ID" ] \
  && grep -qx "$GATE_TAG" "$REMOTE_VENV/remote-gate.keep" \
  || fail "upgrade replaced the existing venv"
assert_remote_install "$LATEST_TAG" latest 2.0
[ "$(grep -oP '__version__\s*=\s*"\K[^"]+' "$CLONE_DIR/src/vocalinux/version.py")" != "$UPGRADE_FROM_VERSION" ] \
  || fail "the upgrade fixture did not change the app version"

echo "== Run 4: no --tag selects the controlled latest release on a fresh install =="
select_scenario latest
LATEST_RESPONSE="$WORK/latest.json"
run_remote_install || fail "controlled latest-release installation failed"
grep -qx latest "$INSTALL_HOME/remote-gate.api" || fail "no latest-release API request was observed"
assert_remote_install "$LATEST_TAG" latest 2.0

echo "== Run 5: unavailable latest API without --tag fails with EXIT_NETWORK and a hint =="
select_scenario api-unavailable
LATEST_RESPONSE=unavailable
expect_failure 3 'No release tag available: the GitHub API was unreachable and no --tag was given.'
grep -Fq 'Re-run with an explicit release tag' "$CASE_OUTPUT" || fail "API failure gave no --tag hint"
[ ! -e "$CLONE_DIR" ] || fail "unresolved latest release continued into a clone"

echo "== Run 6: a nonexistent tag cannot fall back to another revision =="
select_scenario missing-tag
expect_failure 3 'Failed to clone Vocalinux repository' "--tag=$GATE_TAG-nonexistent"
grep -Fq "Remote branch $GATE_TAG-nonexistent not found" "$CASE_OUTPUT" \
  || fail "the clone did not fail because the requested tag was missing"
[ ! -e "$CLONE_DIR/.git" ] || fail "a missing tag left a checkout of another revision"
assert_api_unused

echo "== Run 7: a missing required installer module fails in the selected tree =="
select_scenario missing-module
expect_failure 1 "Installer module is missing or unreadable: $CLONE_DIR/install.d/system_dependencies.sh" \
  "--tag=$MISSING_MODULE_TAG"
assert_selected_revision "$MISSING_MODULE_TAG"
[ ! -e "$REMOTE_VENV" ] || fail "a missing module continued into venv setup"
assert_api_unused

echo "== Run 8: missing runtime pins cannot install an unpinned project =="
select_scenario missing-runtime
expect_failure 3 "Missing or empty pinned requirements: $CLONE_DIR/requirements/runtime.txt" \
  "--tag=$MISSING_RUNTIME_TAG"
assert_selected_revision "$MISSING_RUNTIME_TAG"
assert_trace explicit
assert_api_unused

echo "== Run 9: missing build-tool pins cannot bootstrap an unpinned toolchain =="
select_scenario missing-build
expect_failure 3 "Missing or empty pinned requirements: $CLONE_DIR/requirements/installer-build.txt" \
  "--tag=$MISSING_BUILD_TAG"
assert_selected_revision "$MISSING_BUILD_TAG"
assert_trace explicit
assert_api_unused

echo "== Run 10: mutation control rejects continuing the bootstrap instead of handing off =="
select_scenario no-handoff
BOOTSTRAP="$WORK/no-handoff.sh"
expect_failure 97 'REMOTE_GATE: bootstrap continued past tagged handoff' "--tag=$GATE_TAG"
assert_selected_revision "$GATE_TAG"
[ "$(cat "$INSTALL_HOME/remote-gate.trace")" = bootstrap ] || fail "handoff mutation ran the tagged installer"
[ ! -e "$REMOTE_VENV" ] || fail "handoff mutation continued into dependency installation"

echo "PASS: remote release selection, revision integrity, clone/fetch/streaming handoff, cross-release upgrade, app smoke, and fail-closed releases on ${NAME:-this distro}"
