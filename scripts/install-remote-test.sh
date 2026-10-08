#!/usr/bin/env bash
# Run install.sh's remote path end to end in a distro container and check what
# it installed.
#
# Usage (a read-only mount is enough; the tag is published from git, not the
# tree):
#   docker run --rm -v "$PWD:/repo:ro" debian:12 bash /repo/scripts/install-remote-test.sh
#   or: just remote-install-gate debian:12
#
# The path under test is the one a `curl | bash` user takes and
# scripts/install-test.sh never reaches: bootstrap outside a checkout, --tag
# selection, clone of the selected tag, handoff to the tagged installer with
# the original arguments plus the remote venv path, then a second run's
# fetch+reset over the existing clone.
#
# The remote is a local mirror so the gate answers for *this commit*: the tag
# is published from HEAD's tree and VOCALINUX_REPO_URL points the bootstrap at
# it. A gate that cloned the public repo would install the last release, not
# the checkout under test. The tag's own install.sh is the bootstrap: the #701
# guardrail allows the bootstrap to come from main, and this commit's copy is
# what a merged PR would serve anyway.
#
# Flags the installer sees: --auto (no TTY), --skip-models (a model is 40-75 MB
# per run and the download path is checksum-verified elsewhere), --tag (the
# selection under test). Not --skip-system-deps: the per-distro package
# installation is the point.
#
# Fail closed: after the install, the clone's tree must equal HEAD's tree —
# the #701 guardrail that installer, sourced modules and requirement exports
# all come from the selected tag is only as strong as that equality.
set -euo pipefail

REPO="${REPO:-/repo}"
INSTALL_USER="${INSTALL_USER:-installer}"
INSTALL_HOME="/home/$INSTALL_USER"
# Opaque on purpose: a name the public repository cannot already carry, so a
# silent fallback to GitHub fails loudly instead of installing the wrong ref.
GATE_TAG="${GATE_TAG:-v0.0.0-remote-gate}"
MIRROR="/srv/vocalinux-remote.git"
BOOTSTRAP="/tmp/vl.sh"
CLONE_DIR="$INSTALL_HOME/.local/share/vocalinux-install"
REMOTE_VENV="$INSTALL_HOME/.local/share/vocalinux/venv"

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
# The minimum for install.sh to start, and nothing it should install itself.
# git is for the mirror below; the remote path ensures it again for real users.
# Same arms as scripts/install-test.sh so `just remote-install-gate <distro>`
# works everywhere the local gate does.
case "$ID" in
  ubuntu | debian)
    export DEBIAN_FRONTEND=noninteractive
    retry apt-get update -qq
    retry apt-get install -y -qq sudo git ca-certificates >/dev/null
    ;;
  fedora | rhel | centos)
    retry dnf install -y -q sudo git shadow-utils >/dev/null
    ;;
  arch)
    # -Syu, never -Sy: archlinux:latest lags the mirrors, and a partial upgrade
    # would be this script's breakage rather than the installer's.
    retry pacman -Syu --noconfirm --needed sudo git >/dev/null
    ;;
  opensuse-tumbleweed | opensuse-leap | sles)
    retry zypper --non-interactive --gpg-auto-import-keys refresh >/dev/null
    retry zypper --non-interactive install -y sudo git >/dev/null
    ;;
  *)
    fail "no bootstrap arm for ID='$ID'; add one when adding the container"
    ;;
esac

id -u "$INSTALL_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$INSTALL_USER"
echo "$INSTALL_USER ALL=(ALL) NOPASSWD: ALL" >"/etc/sudoers.d/$INSTALL_USER"
chmod 0440 "/etc/sudoers.d/$INSTALL_USER"

echo "== Publish HEAD's tree as tag $GATE_TAG in a local mirror =="
# safe.directory: the mounted checkout and, for a linked worktree, its mounted
# common gitdir are owned by another uid.
git config --global --add safe.directory '*'
# CI checks out with fetch-depth 1, and a shallow boundary commit can neither
# be pushed nor fetched into a ref ("shallow update not allowed"). The tag
# therefore carries an orphan commit built from HEAD's tree: a root commit is
# not a shallow root, and tree equality below still binds the gate to this
# commit's exact contents.
SOURCE_TREE="$(git -C "$REPO" rev-parse 'HEAD^{tree}')" \
  || fail "$REPO is not a git checkout; the gate publishes the tag from git"
git clone --quiet --depth 1 "file://$REPO" /tmp/gate-source
# commit-tree needs an identity the bare container does not carry.
EXPECTED_SHA="$(GIT_AUTHOR_NAME=gate GIT_AUTHOR_EMAIL=gate@local \
  GIT_COMMITTER_NAME=gate GIT_COMMITTER_EMAIL=gate@local \
  git -C /tmp/gate-source commit-tree "$SOURCE_TREE" -m "remote-install gate")"
git init --bare "$MIRROR" >/dev/null
git -C /tmp/gate-source push "$MIRROR" "$EXPECTED_SHA:refs/tags/$GATE_TAG" >/dev/null
[ "$(git -C "$MIRROR" rev-parse "$GATE_TAG^{tree}")" = "$SOURCE_TREE" ] \
  || fail "the mirror's $GATE_TAG does not carry HEAD's tree"
# The installer clones as $INSTALL_USER, and git refuses a root-owned remote
# for anyone else as "dubious ownership".
chown -R "$INSTALL_USER:$INSTALL_USER" "$MIRROR"

# A remote user downloads install.sh over HTTPS; the gate takes the same file
# out of the tag instead. The tagged copy is this commit's bootstrap, and the
# handoff target is identical either way.
git -C "$MIRROR" show "$GATE_TAG:install.sh" >"$BOOTSTRAP"
chmod 0644 "$BOOTSTRAP"

run_remote_install() {
  # cd to $INSTALL_HOME so the bootstrap sees no checkout: local mode is chosen
  # by a pyproject.toml naming vocalinux in the working directory, and the
  # remote path is the one under test.
  su - "$INSTALL_USER" -c "cd '$INSTALL_HOME' && VOCALINUX_REPO_URL='file://$MIRROR' bash '$BOOTSTRAP' --auto --skip-models '--tag=$GATE_TAG'"
}

assert_remote_install() {
  echo "== Assert: the clone is exactly the selected tag =="
  [ -d "$CLONE_DIR/.git" ] || fail "remote install left no clone at $CLONE_DIR"
  local cloned_sha cloned_tree
  cloned_sha="$(git -C "$CLONE_DIR" rev-parse HEAD)" \
    || fail "the clone at $CLONE_DIR is not a git checkout"
  [ "$cloned_sha" = "$EXPECTED_SHA" ] || fail \
    "installed from the wrong revision: clone HEAD is $cloned_sha, $GATE_TAG is $EXPECTED_SHA"
  [ "$(git -C "$CLONE_DIR" rev-parse "$GATE_TAG^{commit}" 2>/dev/null || true)" = "$EXPECTED_SHA" ] \
    || fail "the clone does not carry the selected tag ref $GATE_TAG"
  # The tag's commit is an orphan; tree equality is the check that installer,
  # modules and exports are this commit's files and not a neighbour revision's.
  cloned_tree="$(git -C "$CLONE_DIR" rev-parse 'HEAD^{tree}')"
  [ "$cloned_tree" = "$SOURCE_TREE" ] || fail \
    "the clone's tree $cloned_tree is not HEAD's tree $SOURCE_TREE"

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
  version_output="$(su - "$INSTALL_USER" -c "'$INSTALL_HOME/.local/bin/vocalinux' --version")" \
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

  su - "$INSTALL_USER" -c "'$REMOTE_VENV/bin/python' - " <<'PY' || fail "the installation does not import"
import vocalinux.main
import vocalinux.ui.tray_indicator
import vocalinux.speech_recognition.recognition_manager
import vocalinux.text_injection.text_injector
from vocalinux.ui.keyboard_backends import EVDEV_AVAILABLE, PYNPUT_AVAILABLE
import gi

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

echo "== Run 1: remote install (fresh clone) as $INSTALL_USER =="
START=$(date +%s)
run_remote_install || fail "the remote install exited non-zero on a fresh clone"
echo "   install took $(( $(date +%s) - START ))s"
assert_remote_install

echo "== Run 2: re-run over the existing clone (fetch + reset) =="
# The second bootstrap sees $CLONE_DIR/.git and updates it instead of cloning:
# the arm a user re-running curl|bash takes on every release after the first.
# Move the clone off the tag and drop its local tag ref first: a run that only
# had to notice the right commit was already checked out would pass even if
# the fetch and reset were both no-ops.
AWAY_SHA="$(su - "$INSTALL_USER" -c "cd '$CLONE_DIR' && \
  GIT_AUTHOR_NAME=gate GIT_AUTHOR_EMAIL=gate@local \
  GIT_COMMITTER_NAME=gate GIT_COMMITTER_EMAIL=gate@local \
  git commit-tree 'HEAD^{tree}' -p HEAD -m moved")"
su - "$INSTALL_USER" -c "git -C '$CLONE_DIR' reset --hard '$AWAY_SHA' \
  && git -C '$CLONE_DIR' update-ref -d 'refs/tags/$GATE_TAG'" \
  || fail "could not move the clone off $GATE_TAG for the re-run arm"
[ "$(git -C "$CLONE_DIR" rev-parse HEAD)" = "$AWAY_SHA" ] \
  || fail "the clone did not move off $GATE_TAG; the re-run proves nothing"
[ -z "$(git -C "$CLONE_DIR" tag -l "$GATE_TAG")" ] \
  || fail "the clone kept refs/tags/$GATE_TAG; the re-run proves nothing"
run_remote_install || fail "the remote install exited non-zero over the existing clone"
grep -l "Updating existing clone" "$INSTALL_HOME"/.local/state/vocalinux/install-*.log >/dev/null 2>&1 \
  || fail "no install log shows 'Updating existing clone'; the fetch arm did not run"
assert_remote_install

echo "PASS: the remote install path (bootstrap -> tag -> clone/fetch -> handoff) installs ${NAME:-this distro}'s app"
