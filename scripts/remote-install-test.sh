#!/usr/bin/env bash
# Exercise install.sh's remote bootstrap and tagged handoff in an Ubuntu container.
#
# Usage (normally through `just remote-install-gate`):
#   docker run --rm -v "$PWD:$PWD:ro" -e REPO="$PWD" ubuntu:24.04 \
#     bash "$PWD/scripts/remote-install-test.sh"
#
# The public GitHub URL is redirected with Git's test-environment `insteadOf`
# setting to a local bare repository. No installer URL override is added. The
# bootstrap comes from the commit under test, while the selected fixture tags
# carry an execution marker. That difference makes a skipped tagged handoff
# observable instead of letting two identical trees produce a false green.
set -euo pipefail

REPO="${REPO:-/repo}"
INSTALL_USER="${INSTALL_USER:-installer}"
INSTALL_HOME="/home/$INSTALL_USER"
WORK="/opt/vocalinux-remote-install-test"
FIXTURE_TREE="$WORK/fixture-tree"
FIXTURE_BARE="$WORK/vocalinux.git"
BOOTSTRAP="$WORK/bootstrap.sh"
FAKE_BIN="$WORK/bin"
RUN_DIR="$INSTALL_HOME/remote-bootstrap"
REMOTE_CLONE="$INSTALL_HOME/.local/share/vocalinux-install"
VENV="$INSTALL_HOME/.local/share/vocalinux/venv"
TAG_MARKER="$INSTALL_HOME/tagged-installer-marker"
TAG_ARGS="$INSTALL_HOME/tagged-installer-args"
EXPECTED_ARGS="$WORK/expected-args"
RUN_LOG="$WORK/bootstrap.log"
FALLTHROUGH_MARKER="$INSTALL_HOME/bootstrap-fell-through"
LATEST_TAG="v0.0.0-remote-e2e-a"
UPDATE_TAG="v0.0.0-remote-e2e-b"
BROKEN_TAG="v0.0.0-remote-e2e-broken"
BROKEN_EXPORT_TAG="v0.0.0-remote-e2e-broken-export"

fail() {
  echo "FAIL: $*" >&2
  dump_install_log
  exit 1
}

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

retry() {
  local attempt
  for attempt in 1 2 3; do
    "$@" && return 0
    echo "   '$1' failed (attempt $attempt); retrying" >&2
    sleep 5
  done
  return 1
}

instrument_fixture_installer() {
  local marker="$1"
  local installer="$FIXTURE_TREE/install.sh"
  local rewritten="$installer.remote-test"

  head -n1 "$installer" >"$rewritten"
  cat >>"$rewritten" <<EOF
if [ "\${VOCALINUX_REMOTE_INSTALL:-no}" = yes ] && [ -n "\${REMOTE_INSTALL_TEST_MARKER_FILE:-}" ]; then
  printf '%s\n' '$marker' >"\$REMOTE_INSTALL_TEST_MARKER_FILE"
  printf '%s\\0' "\$@" >"\$REMOTE_INSTALL_TEST_ARGS_FILE"
fi
EOF
  tail -n +2 "$installer" >>"$rewritten"
  chmod --reference="$installer" "$rewritten"
  mv "$rewritten" "$installer"
}

replace_fixture_marker() {
  local old="$1"
  local new="$2"
  sed -i "s/printf '%s\\\\n' '$old'/printf '%s\\\\n' '$new'/" "$FIXTURE_TREE/install.sh"
}

commit_fixture() {
  local tag="$1"
  local message="$2"
  printf '%s\n' "$tag" >"$FIXTURE_TREE/.remote-install-fixture"
  # This marker is packaged, so a successful checkout followed by a stale/no-op
  # reinstall cannot pass by importing the previous version from the venv.
  printf 'TAG = "%s"\n' "$tag" >"$FIXTURE_TREE/src/vocalinux/_remote_install_fixture.py"
  git -C "$FIXTURE_TREE" add -A
  git -C "$FIXTURE_TREE" commit -q -m "$message"
  git -C "$FIXTURE_TREE" tag "$tag"
}

run_bootstrap() {
  local api_mode="$1"
  shift
  local quoted_args=""
  local arg
  for arg in "$@"; do
    printf -v quoted_args '%s %q' "$quoted_args" "$arg"
  done

  rm -f "$TAG_MARKER" "$TAG_ARGS" "$FALLTHROUGH_MARKER"
  printf '%s\0' "$@" "--venv-dir=$VENV" >"$EXPECTED_ARGS"

  # exec during handoff can close the pipe before cat finishes (SIGPIPE).
  # The inner pipeline must report the installer's status, not the producer's.
  su - "$INSTALL_USER" -c \
    "cd '$RUN_DIR' && cat '$BOOTSTRAP' | env \
      PATH='$FAKE_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
      REMOTE_INSTALL_TEST_API_MODE='$api_mode' \
      REMOTE_INSTALL_TEST_LATEST_TAG='$LATEST_TAG' \
      REMOTE_INSTALL_TEST_MARKER_FILE='$TAG_MARKER' \
      REMOTE_INSTALL_TEST_ARGS_FILE='$TAG_ARGS' \
      bash -s --$quoted_args" 2>&1 | tee "$RUN_LOG"
}

expect_bootstrap_failure() {
  local expected="$1"
  local api_mode="$2"
  local diagnostic="$3"
  shift 3
  local rc

  set +e
  run_bootstrap "$api_mode" "$@"
  rc=$?
  set -e
  [ "$rc" -eq "$expected" ] || fail "remote bootstrap exited $rc; expected $expected"
  grep -F -q -- "$diagnostic" "$RUN_LOG" \
    || fail "remote bootstrap failed for an unexpected reason; expected: $diagnostic"
}

assert_checked_out() {
  local tag="$1"
  local expected
  local actual
  expected="$(git --git-dir="$FIXTURE_BARE" rev-parse "$tag^{commit}")"
  actual="$(su - "$INSTALL_USER" -c "git -C '$REMOTE_CLONE' rev-parse HEAD")"
  [ "$actual" = "$expected" ] || fail "remote clone is $actual, expected $tag at $expected"
  [ "$(cat "$REMOTE_CLONE/.remote-install-fixture")" = "$tag" ] \
    || fail "remote clone does not carry the $tag fixture marker"
}

assert_tagged_installer_ran() {
  local tag="$1"
  [ -f "$TAG_MARKER" ] || fail "tagged installer wrote no execution marker"
  [ "$(cat "$TAG_MARKER")" = "$tag" ] \
    || fail "installer marker is '$(cat "$TAG_MARKER")', expected '$tag'"
  cmp -s "$EXPECTED_ARGS" "$TAG_ARGS" \
    || fail "tagged installer arguments differ from original arguments plus remote venv"
  [ ! -e "$FALLTHROUGH_MARKER" ] \
    || fail "bootstrap continued after handoff instead of execing the tagged installer"
}

smoke_install() {
  local tag="$1"
  echo "== Smoke the remote installation =="
  [ -x "$VENV/bin/python" ] || fail "no remote venv interpreter at $VENV/bin/python"
  [ -x "$INSTALL_HOME/.local/bin/vocalinux" ] || fail "no wrapper at ~/.local/bin/vocalinux"
  [ -x "$INSTALL_HOME/.local/bin/activate-vocalinux.sh" ] \
    || fail "no remote activation helper at ~/.local/bin/activate-vocalinux.sh"
  grep -F -q "source \"$VENV/bin/activate\"" \
    "$INSTALL_HOME/.local/bin/activate-vocalinux.sh" \
    || fail "activation helper does not point at the remote venv"
  [ -f "$INSTALL_HOME/.local/share/applications/vocalinux.desktop" ] \
    || fail "no desktop entry"
  grep -F -q '"engine": "remote_api"' \
    "$INSTALL_HOME/.config/vocalinux/config.json" \
    || fail "--engine=remote_api did not survive the tagged handoff"
  [ -f "$REMOTE_CLONE/src/vocalinux/utils/model_checksums.txt" ] \
    || fail "the tagged tree ships no model checksum manifest"

  for tool in xclip xsel wl-copy; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is not on PATH"
  done

  su - "$INSTALL_USER" -c "'$INSTALL_HOME/.local/bin/vocalinux' --version" \
    || fail "the installed wrapper cannot report a version"
  local installed_tag
  installed_tag="$(su - "$INSTALL_USER" -c "cd '$RUN_DIR' && '$VENV/bin/python' -c \
    'from vocalinux._remote_install_fixture import TAG; print(TAG)'")"
  [ "$installed_tag" = "$tag" ] || fail "installed app is from $installed_tag, expected $tag"

  su - "$INSTALL_USER" -c "'$VENV/bin/python' -" <<'PY' \
    || fail "the remote installation does not import"
import gi
import vocalinux.main
import vocalinux.speech_recognition.recognition_manager
import vocalinux.text_injection.text_injector
import vocalinux.ui.tray_indicator
from vocalinux.ui.keyboard_backends import EVDEV_AVAILABLE, PYNPUT_AVAILABLE

assert EVDEV_AVAILABLE or PYNPUT_AVAILABLE, "no keyboard backend is importable"
gi.require_version("Gtk", "3.0")
gi.require_version("IBus", "1.0")
from gi.repository import Gtk, IBus  # noqa: F401

print(
    "   main, tray, recognition, injection, Gtk and IBus import;"
    f" keyboard backends: evdev={EVDEV_AVAILABLE} pynput={PYNPUT_AVAILABLE}"
)
PY
}

[ -f "$REPO/install.sh" ] || fail "$REPO/install.sh not found; mount the checkout at \$REPO"
. /etc/os-release
[ "${ID:-}" = ubuntu ] && [ "${VERSION_ID:-}" = 24.04 ] \
  || fail "remote gate requires ubuntu:24.04, got ${ID:-unknown}:${VERSION_ID:-unknown}"

echo "== Ubuntu 24.04 bootstrap tools and unprivileged user =="
export DEBIAN_FRONTEND=noninteractive
retry apt-get update -qq
retry apt-get install -y -qq sudo git curl ca-certificates >/dev/null
id -u "$INSTALL_USER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$INSTALL_USER"
echo "$INSTALL_USER ALL=(ALL) NOPASSWD: ALL" >"/etc/sudoers.d/$INSTALL_USER"
chmod 0440 "/etc/sudoers.d/$INSTALL_USER"

echo "== Build distinct tagged fixtures from this commit =="
rm -rf "$WORK"
mkdir -p "$FIXTURE_TREE" "$FAKE_BIN" "$RUN_DIR"
git config --global --add safe.directory '*'
git -C "$REPO" rev-parse --verify HEAD >/dev/null \
  || fail "$REPO is not a git checkout; the fixture needs this commit"
git -C "$REPO" archive HEAD | tar -x -C "$FIXTURE_TREE"
# Use the same committed snapshot for both sides, even with a dirty worktree.
cp "$FIXTURE_TREE/install.sh" "$BOOTSTRAP"
git -C "$FIXTURE_TREE" init -q -b fixture
git -C "$FIXTURE_TREE" config user.name "Vocalinux remote install gate"
git -C "$FIXTURE_TREE" config user.email "remote-install-gate@invalid"

instrument_fixture_installer "$LATEST_TAG"
commit_fixture "$LATEST_TAG" "fixture: latest remote install tag"
replace_fixture_marker "$LATEST_TAG" "$UPDATE_TAG"
commit_fixture "$UPDATE_TAG" "fixture: remote install update tag"
replace_fixture_marker "$UPDATE_TAG" "$BROKEN_TAG"
rm "$FIXTURE_TREE/install.d/models.sh"
commit_fixture "$BROKEN_TAG" "fixture: tagged tree missing a required module"
git -C "$FIXTURE_TREE" switch -q -c broken-export "$UPDATE_TAG"
replace_fixture_marker "$UPDATE_TAG" "$BROKEN_EXPORT_TAG"
rm "$FIXTURE_TREE/requirements/installer-build.txt"
commit_fixture "$BROKEN_EXPORT_TAG" "fixture: tagged tree missing a required export"
git clone -q --bare "$FIXTURE_TREE" "$FIXTURE_BARE"
# Publish the update tag only after the first clone, so skipping fetch fails.
git --git-dir="$FIXTURE_BARE" tag -d "$UPDATE_TAG" >/dev/null

cat >>"$BOOTSTRAP" <<EOF
touch '$FALLTHROUGH_MARKER'
exit 97
EOF

cat >"$FAKE_BIN/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
for arg in "$@"; do
  if [ "$arg" = "https://api.github.com/repos/VocaHQ/vocalinux/releases/latest" ]; then
    if [ "${REMOTE_INSTALL_TEST_API_MODE:-success}" = success ]; then
      printf '{"tag_name":"%s"}\n' "${REMOTE_INSTALL_TEST_LATEST_TAG:?}"
      exit 0
    fi
    exit 22
  fi
done
exec /usr/bin/curl "$@"
EOF
chmod 0755 "$FAKE_BIN/curl" "$BOOTSTRAP"
chown -R "$INSTALL_USER:$INSTALL_USER" "$RUN_DIR"
chmod -R a+rX "$WORK"

# Redirect only Git. The API response is controlled by the curl wrapper above;
# all other curl calls still reach /usr/bin/curl and the real network.
su - "$INSTALL_USER" -c \
  "git config --global --add safe.directory '$FIXTURE_BARE' && \
   git config --global url.'file://$FIXTURE_BARE'.insteadOf 'https://github.com/VocaHQ/vocalinux.git'"

echo "== Fail closed when latest cannot be resolved =="
expect_bootstrap_failure 3 fail 'No release tag available:' --auto --skip-models --engine=remote_api

echo "== Fail closed for an explicit nonexistent tag =="
expect_bootstrap_failure 3 success 'Remote branch v0.0.0-remote-e2e-missing not found' \
  --auto --skip-models --engine=remote_api \
  --tag=v0.0.0-remote-e2e-missing

echo "== Install from the controlled latest tag through the piped bootstrap =="
run_bootstrap success --auto --skip-models --engine=remote_api
assert_checked_out "$LATEST_TAG"
assert_tagged_installer_ran "$LATEST_TAG"
smoke_install "$LATEST_TAG"

echo "== Re-run through the existing-clone fetch path with an explicit tag =="
if su - "$INSTALL_USER" -c "git -C '$REMOTE_CLONE' rev-parse --verify 'refs/tags/$UPDATE_TAG'"; then
  fail "update tag was already present before it was published"
fi
git --git-dir="$FIXTURE_BARE" tag "$UPDATE_TAG" \
  "$(git -C "$FIXTURE_TREE" rev-parse "$UPDATE_TAG^{commit}")"
run_bootstrap fail --auto --skip-models --engine=remote_api --tag="$UPDATE_TAG"
assert_checked_out "$UPDATE_TAG"
assert_tagged_installer_ran "$UPDATE_TAG"
smoke_install "$UPDATE_TAG"

echo "== Fail when the selected tagged tree lacks a required module =="
expect_bootstrap_failure 1 fail "Installer module is missing or unreadable: $REMOTE_CLONE/install.d/models.sh" \
  --auto --skip-models --engine=remote_api --tag="$BROKEN_TAG"
assert_checked_out "$BROKEN_TAG"
assert_tagged_installer_ran "$BROKEN_TAG"

echo "== Fail before pip when the selected tag lacks a required export =="
expect_bootstrap_failure 3 fail "Missing or empty pinned requirements: $REMOTE_CLONE/requirements/installer-build.txt" \
  --auto --skip-models --engine=remote_api \
  --tag="$BROKEN_EXPORT_TAG"
assert_checked_out "$BROKEN_EXPORT_TAG"
assert_tagged_installer_ran "$BROKEN_EXPORT_TAG"

echo "PASS: remote bootstrap selects, installs, updates, and fails closed on tagged trees"
