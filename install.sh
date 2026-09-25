#!/bin/bash
# Vocalinux Installer
# This script installs the Vocalinux application and its dependencies

# -E: ERR trap propagates into functions/subshells
# -e: exit on unhandled command failure   -u: error on unset variables
# -o pipefail: a pipeline fails if any stage fails
set -Eeuo pipefail
INSTALLER_ARGS=("$@")

# Exit codes (see --help). 1 remains the generic/unclassified failure.
EXIT_OK=0
EXIT_MISSING_DEPS=2   # required system tools/packages could not be installed
EXIT_NETWORK=3        # connectivity failure or download/clone failure
EXIT_USER_ABORT=4     # user declined a prompt

# Keep the venv isolated from ~/.local site packages while still allowing
# --system-site-packages to expose distro-provided GTK/PyGObject bindings.
export PYTHONNOUSERSITE=1

# Function to display colored output
print_info() {
    echo -e "\e[1;34m[INFO]\e[0m $1"
}

print_success() {
    echo -e "\e[1;32m[SUCCESS]\e[0m $1"
}

# Diagnostics go to stderr, not stdout: `exec > >(tee ...) 2>&1` keeps them in the
# log and on screen either way, but stdout is what every $( ) captures. Writing
# them there let the ERR trap's own message land inside a captured value.
print_error() {
    echo -e "\e[1;31m[ERROR]\e[0m $1" >&2
}

print_warning() {
    echo -e "\e[1;33m[WARNING]\e[0m $1" >&2
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# The installer must build its venv from the *system* Python: distro PyGObject
# (python3-gi / python3-gobject) is compiled for that interpreter only. When the
# script starts inside an activated virtualenv — a shell left in uv's .venv
# after `just deps`, for instance — a bare `python3` resolves to that venv's
# interpreter instead, and a venv created from it cannot import gi even with
# --system-site-packages. Undo the activation for the installer's own process
# before anything looks up an interpreter.
deactivate_inherited_virtualenv() {
    local venv_bin cleaned entry

    [ -z "${VIRTUAL_ENV:-}" ] && return 0

    print_warning "Running inside an activated virtualenv ($VIRTUAL_ENV)."
    print_info "Ignoring it so the installation uses the system Python."

    venv_bin="${VIRTUAL_ENV%/}/bin"
    cleaned=""
    while IFS= read -r entry; do
        [ "$entry" = "$venv_bin" ] && continue
        cleaned="${cleaned:+$cleaned:}$entry"
    done < <(printf '%s\n' "${PATH//:/$'\n'}")

    PATH="$cleaned"
    export PATH
    unset VIRTUAL_ENV
    unset PYTHONHOME
}

deactivate_inherited_virtualenv

# HTTP-level connectivity check. ICMP ping is blocked on many networks
# (corporate firewalls, public Wi-Fi, CI runners), so probe the actual
# endpoints the installer depends on. Returns 0 if any probe succeeds.
check_connectivity() {
    local url
    for url in https://pypi.org/simple/ https://api.github.com/ https://huggingface.co/; do
        if command_exists curl; then
            if curl -fsI --connect-timeout 5 --max-time 10 -o /dev/null "$url" 2>/dev/null; then
                return 0
            fi
        elif command_exists wget; then
            if wget -q --spider --timeout=10 "$url" 2>/dev/null; then
                return 0
            fi
        else
            return 1
        fi
    done
    return 1
}

is_kde_plasma_session() {
    local desktop="${XDG_CURRENT_DESKTOP:-} ${DESKTOP_SESSION:-} ${GDMSESSION:-}"
    local kde_session="${KDE_FULL_SESSION:-}"
    local desktop_lower="${desktop,,}"
    local kde_session_lower="${kde_session,,}"

    [[ "$desktop_lower" == *kde* || "$desktop_lower" == *plasma* || "$kde_session_lower" == "true" ]]
}

print_kde_wayland_ibus_hint() {
    print_warning "KDE Plasma Wayland detected."
    print_info "For direct dictation into apps, open System Settings -> Keyboard -> Virtual Keyboard and select 'IBus Wayland'."
    print_info "After changing it, restart Vocalinux or log out and back in."
}

# Read a numeric PID from a file (instance.lock / engine.pid). Empty if missing/invalid.
read_pid_file() {
    local file="$1"
    local pid=""

    [ -f "$file" ] || return 0
    pid=$(tr -d '[:space:]' < "$file" 2>/dev/null || true)
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
        echo "$pid"
    fi
}

# True only for the Vocalinux app / IBus engine — not editors, shells, or tests
# whose argv merely contains the string "vocalinux" (e.g. cwd under the repo).
is_vocalinux_process() {
    local pid="$1"

    if [ "$pid" = "$$" ] || [ "$pid" = "$PPID" ]; then
        return 1
    fi
    [ -r "/proc/$pid/cmdline" ] || return 1

    local stat
    stat=$(ps -o stat= -p "$pid" 2>/dev/null | awk '{print $1}')
    if [[ "$stat" == Z* ]]; then
        return 1
    fi

    local cmdline
    cmdline=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
    [ -n "$cmdline" ] || return 1

    # Never target the installer/uninstaller themselves
    if [[ "$cmdline" == *"install.sh"* || "$cmdline" == *"uninstall.sh"* ]]; then
        return 1
    fi

    # python -m vocalinux.main [--flags]
    if [[ "$cmdline" == *"-m vocalinux.main"* ]]; then
        return 0
    fi

    # IBus engine: .../vocalinux/.../ibus_engine.py
    if [[ "$cmdline" == *"ibus_engine.py"* && "$cmdline" == *"vocalinux"* ]]; then
        return 0
    fi

    # Console-script entrypoints. Setuptools scripts are executed as
    # `python …/bin/vocalinux`, so argv0 is python — scan every arg for the
    # script path (require …/bin/vocalinux to avoid matching a repo directory).
    local arg
    while IFS= read -r -d '' arg; do
        case "$arg" in
            vocalinux|vocalinux-gui|*/bin/vocalinux|*/bin/vocalinux-gui)
                return 0
                ;;
        esac
    done < "/proc/$pid/cmdline"

    return 1
}

# Prefer the PIDs the app writes; fall back to narrow entrypoint patterns only.
# Deliberately does NOT use `pgrep -f vocalinux` (matches editors/shells/cwd paths).
get_vocalinux_pids() {
    local data_home="${XDG_DATA_HOME:-$HOME/.local/share}"
    local -A seen=()
    local pid candidate
    local -a candidates=()

    for candidate in \
        "$(read_pid_file "$data_home/vocalinux/instance.lock")" \
        "$(read_pid_file "$data_home/vocalinux-ibus/engine.pid")"
    do
        [ -n "$candidate" ] && candidates+=("$candidate")
    done

    # Fallback when PID files are missing/stale: exact process name or known argv.
    while read -r candidate; do
        [ -n "$candidate" ] && candidates+=("$candidate")
    done < <(
        pgrep -u "$(id -u)" -x vocalinux 2>/dev/null || true
        pgrep -u "$(id -u)" -x vocalinux-gui 2>/dev/null || true
        pgrep -u "$(id -u)" -f -- '-m vocalinux\.main' 2>/dev/null || true
        pgrep -u "$(id -u)" -f -- 'vocalinux/.*/ibus_engine\.py' 2>/dev/null || true
    )

    for pid in "${candidates[@]}"; do
        [ -n "${seen[$pid]:-}" ] && continue
        seen[$pid]=1
        if is_vocalinux_process "$pid"; then
            echo "$pid"
        fi
    done
}

check_running_processes() {
    local PIDS
    PIDS=$(get_vocalinux_pids || true)

    if [ -n "$PIDS" ]; then
        print_warning "Found running Vocalinux process(es):"
        local pid
        for pid in $PIDS; do
            local cmd
            cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || echo "?")
            print_warning "  PID $pid: $cmd"
        done
        echo ""

        if [[ "$NON_INTERACTIVE" == "yes" ]]; then
            print_info "Non-interactive mode: stopping Vocalinux automatically..."
        else
            read -p "Vocalinux must be stopped before installation. Kill running process(es)? (Y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Nn]$ ]]; then
                print_error "Cannot proceed with installation while Vocalinux is running."
                print_info "Please stop Vocalinux manually and run the installer again."
                exit "$EXIT_USER_ABORT"
            fi
        fi

        print_info "Stopping Vocalinux..."
        # shellcheck disable=SC2086
        echo $PIDS | xargs -r kill -TERM 2>/dev/null || true
        sleep 2

        local REMAINING_PIDS
        REMAINING_PIDS=$(get_vocalinux_pids || true)

        if [ -n "$REMAINING_PIDS" ]; then
            print_warning "Some processes still running, forcing termination..."
            # shellcheck disable=SC2086
            echo $REMAINING_PIDS | xargs -r kill -KILL 2>/dev/null || true
            sleep 1
        fi

        local FINAL_PIDS
        FINAL_PIDS=$(get_vocalinux_pids || true)
        if [ -n "$FINAL_PIDS" ]; then
            print_error "Could not terminate all Vocalinux processes: $FINAL_PIDS"
            print_error "Please manually kill these processes and run the installer again."
            exit "$EXIT_USER_ABORT"
        else
            print_success "All Vocalinux processes stopped"
        fi
    fi
}

# Parse command line arguments
INSTALL_MODE="user"
RUN_TESTS="no"
DEV_MODE="no"
VENV_DIR="venv"
SKIP_MODELS="no"
SKIP_SYSTEM_DEPS="no"
NON_INTERACTIVE="no"
INTERACTIVE_MODE="yes"  # Default to interactive mode
AUTO_MODE="no"
REBUILD_WHISPERCPP="ask"
# Pinned pywhispercpp release (sdist, built from source). Keep in sync with
# uv.lock and the requirements/ exports.
PYWHISPERCPP_VERSION="1.5.0"
HAS_NVIDIA_GPU="unknown"
GPU_NAME=""
GPU_MEMORY=""
HAS_VULKAN="no"
VULKAN_DEVICE=""
VULKAN_SOFTWARE_DEVICE=""
# Initialize mode/state variables that are set later by flags or prompts so
# that every read under `set -u` is well-defined in every code path.
INSTALL_TAG=""
SELECTED_ENGINE=""
WHISPERCPP_BACKEND=""
WHISPERCPP_ALREADY_INSTALLED="false"
REMOTE_API_URL=""

# Detect if running non-interactively (e.g., via curl | bash)
# If stdin is a pipe but /dev/tty exists, redirect stdin so user input works normally.
# If no terminal is available at all (headless/CI), fall back to automatic mode.
if [ ! -t 0 ]; then
    if [ -e /dev/tty ] && [ -r /dev/tty ]; then
        if { true < /dev/tty; } 2>/dev/null; then
            exec < /dev/tty
            INTERACTIVE_MODE="ask"
        else
            AUTO_MODE="yes"
            INTERACTIVE_MODE="no"
            NON_INTERACTIVE="yes"
        fi
    else
        AUTO_MODE="yes"
        INTERACTIVE_MODE="no"
        NON_INTERACTIVE="yes"
    fi
fi

while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            DEV_MODE="yes"
            shift
            ;;
        --test)
            RUN_TESTS="yes"
            shift
            ;;
        --venv-dir=*)
            VENV_DIR="${1#*=}"
            shift
            ;;
        --skip-models)
            SKIP_MODELS="yes"
            shift
            ;;
        --skip-system-deps)
            SKIP_SYSTEM_DEPS="yes"
            shift
            ;;
        --rebuild-whispercpp)
            REBUILD_WHISPERCPP="yes"
            shift
            ;;
        --no-rebuild-whispercpp)
            REBUILD_WHISPERCPP="no"
            shift
            ;;
        --engine=*)
            SELECTED_ENGINE="${1#*=}"
            shift
            ;;
        --interactive|-i)
            INTERACTIVE_MODE="yes"
            shift
            ;;
        --tag=*)
            INSTALL_TAG="${1#*=}"
            shift
            ;;
        --auto)
            AUTO_MODE="yes"
            INTERACTIVE_MODE="no"
            NON_INTERACTIVE="yes"
            shift
            ;;
        --help)
            echo "Vocalinux Installer"
            echo ""
            echo "Usage: $0 [options]"
            echo ""
            echo "Installation Modes:"
            echo "  (no flags)       Interactive mode - guided setup with recommendations"
            echo "  --auto           Automatic mode - install with defaults (whisper.cpp)"
            echo "  --auto --engine=whisper   Auto mode with specific engine"
            echo ""
            echo "Options:"
            echo "  --interactive, -i  Force interactive mode (default)"
            echo "  --auto           Non-interactive automatic installation"
            echo "  --engine=NAME    Speech engine: whisper_cpp (default), whisper, vosk, parakeet, faster_whisper, remote_api"
            echo "  --dev            Install in development mode with all dev dependencies"
            echo "  --test           Run tests after installation"
            echo "  --venv-dir=PATH  Specify custom virtual environment directory"
            echo "  --skip-models    Skip downloading speech models during installation"
            echo "  --skip-system-deps"
            echo "                  Skip package-manager dependency installation (advanced)"
            echo "  --rebuild-whispercpp     Rebuild/reinstall pywhispercpp even if already installed"
            echo "  --no-rebuild-whispercpp  Reuse existing pywhispercpp when present (auto-mode default)"
            echo "  --tag=TAG        Install specific release tag (default: latest release)"
            echo "  --help           Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                           # Interactive mode (recommended)"
            echo "  $0 --auto                    # Auto-install with whisper.cpp"
            echo "  $0 --auto --engine=vosk      # Auto-install VOSK only"
            echo "  $0 --auto --engine=faster_whisper  # Auto-install faster-whisper"
            echo "  $0 --dev --test              # Dev mode with tests"
            echo ""
            echo "During installation a full transcript is saved to"
            echo "  ~/.local/state/vocalinux/install-<timestamp>.log"
            echo ""
            echo "Exit codes:"
            echo "  0  success"
            echo "  1  generic failure"
            echo "  2  required system dependencies could not be installed"
            echo "  3  network / download failure"
            echo "  4  user aborted at a prompt"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help to see available options"
            exit 1
            ;;
    esac
done

# If dev mode is enabled, automatically run tests
if [[ "$DEV_MODE" == "yes" ]]; then
    RUN_TESTS="yes"
fi

# ---------------------------------------------------------------------------
# Global install log: everything (stdout + stderr) is teed to this file so
# failures can be debugged after the fact. The path is printed at exit.
# ---------------------------------------------------------------------------
INSTALL_LOG_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/vocalinux"
if ! mkdir -p "$INSTALL_LOG_DIR" 2>/dev/null; then
    INSTALL_LOG_DIR="${TMPDIR:-/tmp}"
fi
INSTALL_LOG_FILE="$INSTALL_LOG_DIR/install-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$INSTALL_LOG_FILE") 2>&1

# Scratch directory for pip logs, model downloads, and other temps.
# Removed on success; kept for inspection (with a notice) when the install fails.
# Exporting TMPDIR routes pip/wget/curl scratch files into this directory.
VOCALINUX_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/vocalinux-install.XXXXXXXX")"
export TMPDIR="$VOCALINUX_TMP_DIR"

cleanup_on_exit() {
    local rc=$?
    if [ "$rc" -eq "$EXIT_OK" ]; then
        rm -rf "$VOCALINUX_TMP_DIR"
    else
        print_error ""
        print_error "Installation did not complete (exit code $rc)."
        print_error "Full install log: $INSTALL_LOG_FILE"
        print_error "Scratch files kept for inspection: $VOCALINUX_TMP_DIR"
    fi
}
trap cleanup_on_exit EXIT
trap 'print_error "Unexpected error near line $LINENO (exit code $?); see $INSTALL_LOG_FILE"' ERR
trap 'print_warning "Interrupted by user"; exit 130' INT
trap 'print_warning "Terminated by signal"; exit 143' TERM

# Display ASCII art banner
cat << "EOF"

  ▗▖  ▗▖ ▗▄▖  ▗▄▄▖ ▗▄▖ ▗▖   ▗▄▄▄▖▗▖  ▗▖▗▖ ▗▖▗▖  ▗▖
  ▐▌  ▐▌▐▌ ▐▌▐▌   ▐▌ ▐▌▐▌     █  ▐▛▚▖▐▌▐▌ ▐▌ ▝▚▞▘
  ▐▌  ▐▌▐▌ ▐▌▐▌   ▐▛▀▜▌▐▌     █  ▐▌ ▝▜▌▐▌ ▐▌  ▐▌
   ▝▚▞▘ ▝▚▄▞▘▝▚▄▄▖▐▌ ▐▌▐▙▄▄▖▗▄█▄▖▐▌  ▐▌▝▚▄▞▘▗▞▘▝▚▖

                    Voice Dictation for Linux

EOF

print_info "Vocalinux Installer"
print_info "=============================="
echo ""

check_running_processes

resolve_install_tag() {
    if [ -n "$INSTALL_TAG" ]; then
        return 0
    fi
    if command_exists curl; then
        local latest
        # (|| true: pipefail would otherwise abort when head closes the pipe
        # early or the API is unreachable; empty means "not resolved")
        latest=$(curl -fsSL --connect-timeout 5 --retry 2 \
            "https://api.github.com/repos/VocaHQ/vocalinux/releases/latest" \
            2>/dev/null | grep '"tag_name"' | head -1 | cut -d'"' -f4 || true)
        if [ -n "$latest" ]; then
            INSTALL_TAG="$latest"
            return 0
        fi
    fi
    # No hardcoded fallback tag: silently installing a stale release is worse
    # than failing. The remote-install path below aborts with a --tag hint if
    # INSTALL_TAG is still empty; in-repo installs do not need a tag at all.
    print_warning "Could not determine the latest release tag (GitHub API unreachable?)."
    return 0
}

resolve_install_tag

# Check if running from within the vocalinux repo or remotely (via curl)
REPO_URL="https://github.com/VocaHQ/vocalinux.git"
INSTALL_DIR=""
CLEANUP_ON_EXIT="${VOCALINUX_REMOTE_INSTALL:-no}"

handoff_to_tagged_installer() {
    local tagged_installer="$INSTALL_DIR/install.sh"
    local remote_venv="$HOME/.local/share/vocalinux/venv"

    if grep -q 'CLEANUP_ON_EXIT="${VOCALINUX_REMOTE_INSTALL:-no}"' "$tagged_installer"; then
        export VOCALINUX_REMOTE_INSTALL=yes
        export TMPDIR="$(dirname "$VOCALINUX_TMP_DIR")"
        rmdir "$VOCALINUX_TMP_DIR"
        exec bash "$tagged_installer" "${INSTALLER_ARGS[@]}" "--venv-dir=$remote_venv"
    fi

    bash "$tagged_installer" "${INSTALLER_ARGS[@]}" "--venv-dir=$remote_venv" || return $?
    if [ ! -f "$INSTALL_DIR/activate-vocalinux.sh" ]; then
        print_error "The tagged installer did not create activate-vocalinux.sh."
        return 1
    fi
    mkdir -p "$HOME/.local/bin"
    mv "$INSTALL_DIR/activate-vocalinux.sh" "$HOME/.local/bin/activate-vocalinux.sh"
}

# Function to check and install git if needed
ensure_git_installed() {
    if command -v git >/dev/null 2>&1; then
        return 0
    fi

    print_warning "git is not installed. Attempting to install git..."

    # Detect distribution for package manager selection
    local DISTRO_FAMILY="unknown"
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "ubuntu" || "${ID_LIKE:-}" == *"ubuntu"* || "$ID" == "pop" || "$ID" == "linuxmint" || "$ID" == "elementary" || "$ID" == "zorin" ]]; then
            DISTRO_FAMILY="ubuntu"
        elif [[ "$ID" == "debian" || "${ID_LIKE:-}" == *"debian"* ]]; then
            DISTRO_FAMILY="debian"
        elif [[ "$ID" == "fedora" || "${ID_LIKE:-}" == *"fedora"* || "$ID" == "rhel" || "$ID" == "centos" || "$ID" == "rocky" || "$ID" == "almalinux" ]]; then
            DISTRO_FAMILY="fedora"
        elif [[ "$ID" == "arch" || "${ID_LIKE:-}" == *"arch"* || "$ID" == "manjaro" || "$ID" == "endeavouros" ]]; then
            DISTRO_FAMILY="arch"
        elif [[ "$ID" == "opensuse" || "${ID_LIKE:-}" == *"suse"* ]]; then
            DISTRO_FAMILY="suse"
        elif [[ "$ID" == "gentoo" ]]; then
            DISTRO_FAMILY="gentoo"
        elif [[ "$ID" == "alpine" ]]; then
            DISTRO_FAMILY="alpine"
        elif [[ "$ID" == "void" ]]; then
            DISTRO_FAMILY="void"
        elif [[ "$ID" == "solus" ]]; then
            DISTRO_FAMILY="solus"
        elif [[ "$ID" == "mageia" ]]; then
            DISTRO_FAMILY="mageia"
        fi
    fi

    case "$DISTRO_FAMILY" in
        ubuntu|debian)
            sudo apt update && sudo apt install -y git || {
                print_error "Failed to install git. Please install git manually and run the installer again."
                print_error "  Ubuntu/Debian: sudo apt install git"
                exit "$EXIT_MISSING_DEPS"
            }
            ;;
        fedora)
            sudo dnf install -y git || {
                print_error "Failed to install git. Please install git manually and run the installer again."
                print_error "  Fedora: sudo dnf install git"
                exit "$EXIT_MISSING_DEPS"
            }
            ;;
        arch)
            sudo pacman -S --noconfirm git || {
                print_error "Failed to install git. Please install git manually and run the installer again."
                print_error "  Arch: sudo pacman -S git"
                exit "$EXIT_MISSING_DEPS"
            }
            ;;
        suse)
            sudo zypper install -y git || {
                print_error "Failed to install git. Please install git manually and run the installer again."
                print_error "  openSUSE: sudo zypper install git"
                exit "$EXIT_MISSING_DEPS"
            }
            ;;
        gentoo)
            sudo emerge git || {
                print_error "Failed to install git. Please install git manually and run the installer again."
                print_error "  Gentoo: sudo emerge git"
                exit "$EXIT_MISSING_DEPS"
            }
            ;;
        alpine)
            sudo apk add git || {
                print_error "Failed to install git. Please install git manually and run the installer again."
                print_error "  Alpine: sudo apk add git"
                exit "$EXIT_MISSING_DEPS"
            }
            ;;
        void)
            sudo xbps-install -Sy git || {
                print_error "Failed to install git. Please install git manually and run the installer again."
                print_error "  Void: sudo xbps-install -Sy git"
                exit "$EXIT_MISSING_DEPS"
            }
            ;;
        solus)
            sudo eopkg install git || {
                print_error "Failed to install git. Please install git manually and run the installer again."
                print_error "  Solus: sudo eopkg install git"
                exit "$EXIT_MISSING_DEPS"
            }
            ;;
        mageia)
            if command -v dnf >/dev/null 2>&1; then
                sudo dnf install -y git || {
                    print_error "Failed to install git. Please install git manually and run the installer again."
                    exit "$EXIT_MISSING_DEPS"
                }
            else
                sudo urpmi --force git || {
                    print_error "Failed to install git. Please install git manually and run the installer again."
                    exit "$EXIT_MISSING_DEPS"
                }
            fi
            ;;
        *)
            print_error "git is not installed and could not auto-detect your distribution."
            print_error "Please install git manually and run the installer again:"
            print_error "  Ubuntu/Debian: sudo apt install git"
            print_error "  Fedora/RHEL: sudo dnf install git"
            print_error "  Arch: sudo pacman -S git"
            print_error "  openSUSE: sudo zypper install git"
            exit "$EXIT_MISSING_DEPS"
            ;;
    esac

    print_success "git installed successfully!"
}

# Check if running from within the vocalinux repository
# Validate that pyproject.toml/setup.py actually belongs to vocalinux before entering local repo mode
IS_VOCALINUX_LOCAL=false
if [ -f "pyproject.toml" ] && grep -q 'name = "vocalinux"' "pyproject.toml" 2>/dev/null; then
    IS_VOCALINUX_LOCAL=true
elif [ -f "setup.py" ] && grep -q "vocalinux" "setup.py" 2>/dev/null; then
    IS_VOCALINUX_LOCAL=true
fi

if [ "$IS_VOCALINUX_LOCAL" = true ]; then
    # Running from within the vocalinux repo
    INSTALL_DIR="$(pwd)"
    print_info "Running from local repository: $INSTALL_DIR"
    # Convert relative VENV_DIR to absolute for wrapper scripts.
    # Absolute --venv-dir= paths must not be re-prefixed with INSTALL_DIR.
    case "$VENV_DIR" in
        /*) ;;
        *) VENV_DIR="$INSTALL_DIR/$VENV_DIR" ;;
    esac
else
    # Running remotely (e.g., via curl | bash)
    if [ -z "$INSTALL_TAG" ]; then
        print_error "No release tag available: the GitHub API was unreachable and no --tag was given."
        print_error "Re-run with an explicit release tag, e.g.: --tag=<release>"
        exit "$EXIT_NETWORK"
    fi
    print_info "Installing Vocalinux version: ${INSTALL_TAG}"

    # Ensure git is installed before attempting to clone
    ensure_git_installed

    INSTALL_DIR="$HOME/.local/share/vocalinux-install"
    mkdir -p "$INSTALL_DIR"

    if [ -d "$INSTALL_DIR/.git" ]; then
        print_info "Updating existing clone..."
        cd "$INSTALL_DIR"
        if ! git fetch origin tag "$INSTALL_TAG" || ! git reset --hard "$INSTALL_TAG"; then
            print_error "Failed to update the Vocalinux clone to $INSTALL_TAG."
            print_error "Check the install log and your network connection: $INSTALL_LOG_FILE"
            exit "$EXIT_NETWORK"
        fi
    else
        rm -rf "$INSTALL_DIR"
        git clone --depth 1 --branch "$INSTALL_TAG" "$REPO_URL" "$INSTALL_DIR" || {
            print_error "Failed to clone Vocalinux repository"
            exit "$EXIT_NETWORK"
        }
        cd "$INSTALL_DIR"
    fi
    CLEANUP_ON_EXIT="yes"
    print_info "Repository cloned to: $INSTALL_DIR"

    # Keep the installer and exports on the selected tag. Legacy tags do not
    # understand the remote marker, so the handoff relocates their helper.
    handoff_to_tagged_installer
    exit "$EXIT_OK"
fi

# Change to install directory
cd "$INSTALL_DIR"

# The bootstrap above must stay self-contained because it is also served by the
# curl installer. Once the local or tagged repository is available, load the
# implementation modules from that same revision.
source_installer_module() {
    local module="$INSTALL_DIR/install.d/$1"
    if [ ! -r "$module" ]; then
        print_error "Installer module is missing or unreadable: $module"
        return 1
    fi
    # shellcheck source=/dev/null
    source "$module"
}

# Shared by the model installer module and the runtime downloader.
MODEL_CHECKSUMS_FILE="$INSTALL_DIR/src/vocalinux/utils/model_checksums.txt"

for INSTALLER_MODULE in interactive.sh system_dependencies.sh models.sh desktop.sh; do
    source_installer_module "$INSTALLER_MODULE" || exit 1
done
unset INSTALLER_MODULE

print_info "Using virtual environment: $VENV_DIR"
[[ "$DEV_MODE" == "yes" ]] && print_info "Installing in development mode"
[[ "$RUN_TESTS" == "yes" ]] && print_info "Tests will be run after installation"
echo ""

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Please do not run this script as root or with sudo."
    exit 1
fi

# Detect Linux distribution and version
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO_NAME="${NAME:-unknown}"
        DISTRO_ID="${ID:-unknown}"
        DISTRO_VERSION="${VERSION_ID:-}"
        DISTRO_FAMILY="unknown"

        # Determine distribution family
        if [[ "$ID" == "ubuntu" || "${ID_LIKE:-}" == *"ubuntu"* || "$ID" == "pop" || "$ID" == "linuxmint" || "$ID" == "elementary" || "$ID" == "zorin" ]]; then
            DISTRO_FAMILY="ubuntu"
        elif [[ "$ID" == "debian" || "${ID_LIKE:-}" == *"debian"* ]]; then
            DISTRO_FAMILY="debian"
        elif [[ "$ID" == "fedora" || "${ID_LIKE:-}" == *"fedora"* || "$ID" == "rhel" || "$ID" == "centos" || "$ID" == "rocky" || "$ID" == "almalinux" ]]; then
            DISTRO_FAMILY="fedora"
        elif [[ "$ID" == "arch" || "${ID_LIKE:-}" == *"arch"* || "$ID" == "manjaro" || "$ID" == "endeavouros" ]]; then
            DISTRO_FAMILY="arch"
        elif [[ "$ID" == "opensuse" || "${ID_LIKE:-}" == *"suse"* ]]; then
            DISTRO_FAMILY="suse"
        elif [[ "$ID" == "gentoo" ]]; then
            DISTRO_FAMILY="gentoo"
        elif [[ "$ID" == "alpine" ]]; then
            DISTRO_FAMILY="alpine"
        elif [[ "$ID" == "void" ]]; then
            DISTRO_FAMILY="void"
        elif [[ "$ID" == "solus" ]]; then
            DISTRO_FAMILY="solus"
        elif [[ "$ID" == "mageia" ]]; then
            DISTRO_FAMILY="mageia"
        fi

        print_info "Detected: $DISTRO_NAME $DISTRO_VERSION ($DISTRO_FAMILY family)"
        return 0
    else
        print_error "Could not detect Linux distribution (missing /etc/os-release)"
        return 1
    fi
}

# Detect NVIDIA GPU presence
detect_nvidia_gpu() {
    # Check if nvidia-smi command exists and can successfully query GPU
    if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
        # Extract GPU information for user feedback
        # (|| true: nvidia-smi may fail mid-pipeline; pipefail must not abort)
        GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1 || true)
        GPU_MEMORY=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader 2>/dev/null | head -n1 || true)
        HAS_NVIDIA_GPU="yes"
        return 0
    else
        HAS_NVIDIA_GPU="no"
        return 1
    fi
}

cuda_toolkit_root_has_runtime_library() {
    local CUDA_ROOT="$1"

    compgen -G "$CUDA_ROOT/lib64/libcudart.so*" >/dev/null && return 0
    compgen -G "$CUDA_ROOT/lib/libcudart.so*" >/dev/null && return 0
    compgen -G "$CUDA_ROOT/lib/x86_64-linux-gnu/libcudart.so*" >/dev/null && return 0
    compgen -G "$CUDA_ROOT/targets/x86_64-linux/lib/libcudart.so*" >/dev/null && return 0
    compgen -G "$CUDA_ROOT/targets/aarch64-linux/lib/libcudart.so*" >/dev/null && return 0
    compgen -G "$CUDA_ROOT/targets/sbsa-linux/lib/libcudart.so*" >/dev/null && return 0
    return 1
}

validate_cuda_toolkit_root() {
    local CUDA_ROOT="$1"

    [ -n "$CUDA_ROOT" ] || return 1
    [ -x "$CUDA_ROOT/bin/nvcc" ] || return 1
    [ -f "$CUDA_ROOT/include/cuda_runtime.h" ] || return 1
    cuda_toolkit_root_has_runtime_library "$CUDA_ROOT" || return 1
}

candidate_cuda_toolkit_roots() {
    local CUDA_VAR
    for CUDA_VAR in CUDAToolkit_ROOT CUDA_HOME CUDA_PATH; do
        local CUDA_ROOT="${!CUDA_VAR:-}"
        [ -n "$CUDA_ROOT" ] && printf '%s\n' "$CUDA_ROOT"
    done

    if command -v nvcc >/dev/null 2>&1; then
        local NVCC_PATH
        local NVCC_ROOT
        NVCC_PATH=$(readlink -f "$(command -v nvcc)" 2>/dev/null || command -v nvcc)
        NVCC_ROOT=$(cd "$(dirname "$NVCC_PATH")/.." 2>/dev/null && pwd -P)
        [ -n "$NVCC_ROOT" ] && printf '%s\n' "$NVCC_ROOT"
    fi

    local CUDA_ROOT
    for CUDA_ROOT in /usr/local/cuda /usr/local/cuda-* /opt/cuda; do
        [ -d "$CUDA_ROOT" ] && printf '%s\n' "$CUDA_ROOT"
    done
}

find_valid_cuda_toolkit_root() {
    local QUIET="${1:-no}"
    local SEEN_ROOTS=""
    local CUDA_ROOT

    while IFS= read -r CUDA_ROOT; do
        [ -n "$CUDA_ROOT" ] || continue

        local NORMALIZED_ROOT
        NORMALIZED_ROOT=$(cd "$CUDA_ROOT" 2>/dev/null && pwd -P) || NORMALIZED_ROOT="$CUDA_ROOT"

        if [[ ":$SEEN_ROOTS:" == *":$NORMALIZED_ROOT:"* ]]; then
            continue
        fi
        SEEN_ROOTS="${SEEN_ROOTS:+$SEEN_ROOTS:}$NORMALIZED_ROOT"

        if validate_cuda_toolkit_root "$NORMALIZED_ROOT"; then
            printf '%s\n' "$NORMALIZED_ROOT"
            return 0
        fi

        if [[ "$QUIET" != "quiet" ]]; then
            print_warning "Ignoring incomplete CUDA toolkit root: $NORMALIZED_ROOT" >&2
            print_warning "  Required: bin/nvcc, include/cuda_runtime.h, and libcudart.so*" >&2
        fi
    done < <(candidate_cuda_toolkit_roots)

    return 1
}

detect_nvidia_compute_architectures() {
    command -v nvidia-smi >/dev/null 2>&1 || return 1

    local COMPUTE_CAPS
    COMPUTE_CAPS=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null || true)
    [ -n "$COMPUTE_CAPS" ] || return 1

    printf '%s\n' "$COMPUTE_CAPS" | awk '
        {
            gsub(/[[:space:]]/, "", $1)
            if ($1 ~ /^[0-9]+(\.[0-9]+)?$/) {
                split($1, parts, ".")
                minor = parts[2]
                if (minor == "") {
                    minor = "0"
                }
                print parts[1] minor "-real"
            }
        }
    ' | sort -u | paste -sd ';' -
}

cuda_toolkit_supports_architectures() {
    local CUDA_ROOT="$1"
    local CUDA_ARCHS="$2"
    [ -n "$CUDA_ARCHS" ] || return 0

    local NVCC_ARCHS
    NVCC_ARCHS=$("$CUDA_ROOT/bin/nvcc" --list-gpu-arch 2>/dev/null || true)
    if [ -z "$NVCC_ARCHS" ]; then
        print_warning "Could not query supported CUDA architectures from $CUDA_ROOT/bin/nvcc" >&2
        print_warning "Continuing with detected CMAKE_CUDA_ARCHITECTURES=$CUDA_ARCHS" >&2
        return 0
    fi

    local IFS=';'
    local CUDA_ARCH
    for CUDA_ARCH in $CUDA_ARCHS; do
        local ARCH_DIGITS="${CUDA_ARCH%%-*}"
        if ! printf '%s\n' "$NVCC_ARCHS" | grep -q "compute_$ARCH_DIGITS"; then
            print_warning "CUDA toolkit at $CUDA_ROOT cannot target compute capability $ARCH_DIGITS." >&2
            print_warning "Install a newer CUDA toolkit, such as CUDA 11.8+ for RTX 40/Ada GPUs." >&2
            return 1
        fi
    done

    return 0
}

get_cuda_cmake_args() {
    local CUDA_ROOT="$1"
    local CUDA_ARGS="-DCUDAToolkit_ROOT=$CUDA_ROOT -DCMAKE_CUDA_COMPILER=$CUDA_ROOT/bin/nvcc"
    local CUDA_ARCHS

    CUDA_ARCHS=$(detect_nvidia_compute_architectures || true)
    if [ -n "$CUDA_ARCHS" ]; then
        cuda_toolkit_supports_architectures "$CUDA_ROOT" "$CUDA_ARCHS" || return 1
        CUDA_ARGS="$CUDA_ARGS -DCMAKE_CUDA_ARCHITECTURES=$CUDA_ARCHS"
    fi

    printf '%s\n' "$CUDA_ARGS"
}

# CPU implementations of Vulkan. whisper.cpp on these is slower than its own CPU
# backend, so they must never be reported as a GPU. One list, read by both
# detect_vulkan and check_vulkan_gpu_compatibility.
VULKAN_SOFTWARE_PATTERNS=(llvmpipe swiftshader lavapipe zink virtio venus)

is_software_renderer() {
    local name="$1" pattern
    for pattern in "${VULKAN_SOFTWARE_PATTERNS[@]}"; do
        if printf '%s' "$name" | grep -iq "$pattern"; then
            return 0
        fi
    done
    return 1
}

# List the Vulkan devices vulkaninfo reports, one per line.
vulkan_device_names() {
    command -v vulkaninfo >/dev/null 2>&1 || return 1
    # (|| true: no match must not abort pipefail.)
    vulkaninfo --summary 2>/dev/null | awk -F'=' '/deviceName/ {gsub(/^[ \t]+|[ \t]+$/, "", $2); if ($2 != "") print $2}' || true
}

# Detect Vulkan support for whisper.cpp
detect_vulkan() {
    # Only a hardware deviceName counts. The loader prints a header even when no
    # ICD resolves, and a software renderer is not a GPU -- reporting either as
    # one is what made Step 1 promise Vulkan performance the machine cannot give.
    HAS_VULKAN="no"
    VULKAN_DEVICE=""
    VULKAN_SOFTWARE_DEVICE=""

    local devices name
    devices=$(vulkan_device_names) || return 1
    [ -n "$devices" ] || return 1

    while IFS= read -r name; do
        [ -z "$name" ] && continue
        if is_software_renderer "$name"; then
            [ -n "$VULKAN_SOFTWARE_DEVICE" ] || VULKAN_SOFTWARE_DEVICE="$name"
            continue
        fi
        HAS_VULKAN="yes"
        VULKAN_DEVICE="$name"
        return 0
    done <<< "$devices"

    return 1
}

# Check for incompatible Intel GPUs that don't support VK_KHR_16bit_storage
# These GPUs will fail with "device does not support 16-bit storage" error
# Affected: Intel Gen7 and older (Ivy Bridge, Haswell, Sandy Bridge)
# See: https://github.com/VocaHQ/vocalinux/issues/238
#
# IMPORTANT: This check filters out software renderers (llvmpipe, etc.) and only
# evaluates real hardware GPUs. Modern AMD, Intel (Gen8+), and NVIDIA GPUs all
# support VK_KHR_16bit_storage, so this mainly catches very old Intel Gen7 GPUs.
check_vulkan_gpu_compatibility() {
    # List of known incompatible GPU patterns (old Intel Gen7 and older)
    local INCOMPATIBLE_PATTERNS=(
        "Ivy Bridge"
        "Haswell"
        "Sandy Bridge"
        "HD Graphics 2500"
        "HD Graphics 4000"
        "HD Graphics 4400"
        "HD Graphics 4600"
        "HD Graphics P4600"
        "HD Graphics P4700"
        "IVB"
        "HSW"
        "SNB"
    )

    # Check if vulkaninfo is available
    if ! command -v vulkaninfo >/dev/null 2>&1; then
        echo "unknown:vulkaninfo not available"
        return 1
    fi

    # Get all device names from vulkaninfo
    local DEVICE_NAMES_RAW
    DEVICE_NAMES_RAW=$(vulkan_device_names || true)

    # Separate hardware GPUs from software renderers
    local HARDWARE_GPUS=""
    while IFS= read -r device_name; do
        [ -z "$device_name" ] && continue
        if is_software_renderer "$device_name"; then
            continue
        fi
        if [ -n "$HARDWARE_GPUS" ]; then
            HARDWARE_GPUS="${HARDWARE_GPUS}, ${device_name}"
        else
            HARDWARE_GPUS="$device_name"
        fi
    done <<< "$DEVICE_NAMES_RAW"

    # If no hardware GPUs found, we can't determine compatibility
    if [ -z "$HARDWARE_GPUS" ]; then
        echo "unknown:No hardware GPU found (only software renderers)"
        return 1
    fi

    # Get Vulkan features and check for VK_KHR_16bit_storage
    # Modern GPUs (AMD, Intel Gen8+, NVIDIA) all support this extension
    local FEATURES_OUTPUT
    # Exits non-zero on drivers that still print usable output; the text is what matters.
    FEATURES_OUTPUT=$(vulkaninfo --features 2>/dev/null) || true

    if [ -n "$FEATURES_OUTPUT" ]; then
        # Check for VK_KHR_16bit_storage extension or equivalent features
        if echo "$FEATURES_OUTPUT" | grep -q "VK_KHR_16bit_storage"; then
            echo "compatible:${HARDWARE_GPUS}"
            return 0
        fi

        # Alternative: check for 16-bit storage features directly
        if echo "$FEATURES_OUTPUT" | grep -Eq "storageBuffer16BitAccess[[:space:]]*=[[:space:]]*true|uniformAndStorageBuffer16BitAccess[[:space:]]*=[[:space:]]*true"; then
            echo "compatible:${HARDWARE_GPUS}"
            return 0
        fi
    fi

    # If Vulkan features check didn't confirm support, check against known incompatible patterns
    # This handles systems where vulkaninfo --features doesn't show the extension
    local INCOMPATIBLE_GPUS=""
    local HAS_COMPATIBLE_GPU=false

    while IFS= read -r device_name; do
        [ -z "$device_name" ] && continue

        if is_software_renderer "$device_name"; then
            continue
        fi

        # Check against known incompatible patterns
        local is_incompatible=false
        for pattern in "${INCOMPATIBLE_PATTERNS[@]}"; do
            if echo "$device_name" | grep -iq "$pattern"; then
                is_incompatible=true
                break
            fi
        done

        if [ "$is_incompatible" = true ]; then
            if [ -n "$INCOMPATIBLE_GPUS" ]; then
                INCOMPATIBLE_GPUS="${INCOMPATIBLE_GPUS}, ${device_name}"
            else
                INCOMPATIBLE_GPUS="$device_name"
            fi
        else
            # GPU doesn't match known incompatible patterns - assume compatible
            HAS_COMPATIBLE_GPU=true
        fi
    done <<< "$DEVICE_NAMES_RAW"

    if [ "$HAS_COMPATIBLE_GPU" = true ]; then
        echo "compatible:${HARDWARE_GPUS}"
        return 0
    fi

    if [ -n "$INCOMPATIBLE_GPUS" ]; then
        echo "incompatible:${INCOMPATIBLE_GPUS}"
        return 1
    fi

    echo "unknown:Could not classify Vulkan GPU compatibility"
    return 1
}

# Detect available GPU backends for whisper.cpp and recommend the best option
detect_whispercpp_backends() {
    detect_nvidia_gpu || true
    detect_vulkan || true

    # Check for Vulkan dev libraries
    local HAS_VULKAN_DEV=false
    if pkg-config --exists vulkan 2>/dev/null || [ -f /usr/include/vulkan/vulkan.h ]; then
        HAS_VULKAN_DEV=true
    fi

    # Check for CUDA
    local HAS_CUDA_DEV=false
    if find_valid_cuda_toolkit_root quiet >/dev/null 2>&1; then
        HAS_CUDA_DEV=true
    fi

    # Check Vulkan GPU compatibility (Gen7 and older Intel GPUs lack 16-bit storage support)
    # Skip this check for NVIDIA GPUs since they use CUDA, not Vulkan
    local VULKAN_COMPATIBLE="unknown"
    local VULKAN_COMPAT_REASON=""
    if [[ "$HAS_VULKAN" == "yes" && "$HAS_NVIDIA_GPU" != "yes" ]]; then
        local COMPAT_RESULT
        # Returns non-zero for "unknown"/"incompatible", which are answers, not errors.
        COMPAT_RESULT=$(check_vulkan_gpu_compatibility) || true
        VULKAN_COMPATIBLE=$(echo "$COMPAT_RESULT" | cut -d':' -f1)
        VULKAN_COMPAT_REASON=$(echo "$COMPAT_RESULT" | cut -d':' -f2-)
    elif [[ "$HAS_NVIDIA_GPU" == "yes" ]]; then
        # NVIDIA GPUs use CUDA, so Vulkan compatibility is irrelevant
        VULKAN_COMPATIBLE="not_applicable"
        VULKAN_COMPAT_REASON="NVIDIA GPU uses CUDA"
    fi

    # Determine recommendation (Priority: Vulkan > CUDA fallback > CPU).
    # install_whispercpp_with_gpu_support tries Vulkan first on every GPU,
    # including NVIDIA. CUDA is used only when Vulkan is unavailable or the
    # Vulkan build fails, and only if a complete toolkit is already present.
    # The installer never installs the CUDA toolkit.
    # IMPORTANT: Vulkan *dev* libraries (libvulkan-dev, glslc) are installed
    # later, so we recommend GPU when a compatible GPU is present even if
    # those packages are not installed yet.
    local RECOMMENDED_BACKEND="cpu"
    local RECOMMENDED_REASON=""
    local CAN_BUILD_GPU=false

    if [[ "$HAS_NVIDIA_GPU" == "yes" ]]; then
        CAN_BUILD_GPU=true
        if [[ "$HAS_VULKAN" == "yes" ]]; then
            RECOMMENDED_BACKEND="vulkan"
            RECOMMENDED_REASON="NVIDIA GPU detected (Vulkan)"
        elif [[ "$HAS_CUDA_DEV" == "true" ]]; then
            RECOMMENDED_BACKEND="cuda"
            RECOMMENDED_REASON="NVIDIA GPU with CUDA toolkit installed"
        else
            RECOMMENDED_BACKEND="vulkan"
            RECOMMENDED_REASON="NVIDIA GPU detected"
        fi
    # Vulkan-compatible GPU (AMD, Intel Gen8+) - second choice
    elif [[ "$HAS_VULKAN" == "yes" && "$VULKAN_COMPATIBLE" == "compatible" ]]; then
        RECOMMENDED_BACKEND="vulkan"
        if [[ "$HAS_VULKAN_DEV" == "true" ]]; then
            RECOMMENDED_REASON="Vulkan GPU detected with dev libraries"
        else
            RECOMMENDED_REASON="Vulkan GPU detected (dev libraries will be installed)"
        fi
        CAN_BUILD_GPU=true
    # Vulkan GPU but compatibility unknown - allow GPU build as fallback
    elif [[ "$HAS_VULKAN" == "yes" && "$VULKAN_COMPATIBLE" == "unknown" ]]; then
        RECOMMENDED_BACKEND="vulkan"
        RECOMMENDED_REASON="Possible Vulkan GPU (will verify during build)"
        CAN_BUILD_GPU=true
    # Incompatible Vulkan GPU (old Intel Gen7) - CPU only
    elif [[ "$VULKAN_COMPATIBLE" == "incompatible" ]]; then
        RECOMMENDED_BACKEND="cpu"
        RECOMMENDED_REASON="Incompatible GPU ($VULKAN_COMPAT_REASON) - CPU mode recommended"
        CAN_BUILD_GPU=false
    else
        RECOMMENDED_BACKEND="cpu"
        RECOMMENDED_REASON="No compatible GPU detected"
        CAN_BUILD_GPU=false
    fi

    echo "${RECOMMENDED_BACKEND}:${RECOMMENDED_REASON}:${CAN_BUILD_GPU}:${HAS_VULKAN}:${HAS_NVIDIA_GPU}:${HAS_VULKAN_DEV}:${HAS_CUDA_DEV}:${VULKAN_COMPATIBLE}:${VULKAN_COMPAT_REASON}"
}

# Detect hardware and recommend best engine
get_engine_recommendation() {
    detect_nvidia_gpu || true
    detect_vulkan || true

    # Get RAM info
    local TOTAL_RAM_GB=$(free -g 2>/dev/null | awk '/^Mem:/{print $2}' || echo "0")

    if [[ "$HAS_NVIDIA_GPU" == "yes" ]]; then
        # NVIDIA GPU detected - whisper.cpp can use CUDA
        echo "whisper_cpp:✓:NVIDIA GPU detected ($GPU_NAME) - Best performance with whisper.cpp"
    elif [[ "$HAS_VULKAN" == "yes" ]]; then
        # Non-NVIDIA GPU with Vulkan support
        echo "whisper_cpp:✓:$VULKAN_DEVICE detected - Great performance with whisper.cpp Vulkan"
    elif [ -n "$VULKAN_SOFTWARE_DEVICE" ]; then
        echo "whisper_cpp:✓:Software Vulkan only ($VULKAN_SOFTWARE_DEVICE) - whisper.cpp CPU mode"
    elif [ "$TOTAL_RAM_GB" -ge 8 ]; then
        # No GPU but decent RAM
        echo "whisper_cpp:✓:No GPU detected, but ${TOTAL_RAM_GB}GB RAM - whisper.cpp CPU mode"
    else
        # Low RAM, no GPU
        echo "vosk:⚠:Low RAM (${TOTAL_RAM_GB}GB) and no GPU - VOSK recommended for best performance"
    fi
}

# Detect GI_TYPELIB_PATH for cross-distro compatibility
detect_typelib_path() {
    # Try pkg-config first (most reliable)
    if command -v pkg-config >/dev/null 2>&1; then
        local path=$(pkg-config --variable=typelibdir gobject-introspection-1.0 2>/dev/null)
        if [ -n "$path" ] && [ -d "$path" ]; then
            echo "$path"
            return 0
        fi
    fi

    # Fallback to common distribution-specific paths
    # Order matters: more specific paths first
    for path in \
        /usr/lib/x86_64-linux-gnu/girepository-1.0 \
        /usr/lib/aarch64-linux-gnu/girepository-1.0 \
        /usr/lib/arm-linux-gnueabihf/girepository-1.0 \
        /usr/lib/riscv64-linux-gnu/girepository-1.0 \
        /usr/lib/powerpc64le-linux-gnu/girepository-1.0 \
        /usr/lib/s390x-linux-gnu/girepository-1.0 \
        /usr/lib64/girepository-1.0 \
        /usr/lib/girepository-1.0 \
        /usr/local/lib/girepository-1.0 \
        /usr/local/lib64/girepository-1.0; do
        if [ -d "$path" ]; then
            echo "$path"
            return 0
        fi
    done

    # Ultimate fallback - will cause issues if wrong, but at least we try
    echo "/usr/lib/girepository-1.0"
    return 1
}

# Detect distribution
detect_distro

# Check compatibility. These tiers mirror docs/DISTRO_COMPATIBILITY.md, and the
# distro matrix builds on ubuntu, debian and fedora. Nothing here decides whether
# the install can proceed: what Vocalinux needs is an interpreter at the floor
# and that interpreter's distro PyGObject, checked by check_python_version()
# (fatal) and require_distro_gi() further down. This block only says how much
# help the package step is likely to be, so it must not turn away a distro the
# project documents as supported, and it must not key off a release label:
# derivatives carry their own numbering, so Linux Mint 22 and elementary OS 8
# report "22" and "8" while being built on Ubuntu 24.04 with Python 3.12.
case "$DISTRO_FAMILY" in
    debian)
        print_info "Detected Debian — fully supported. Continuing with Debian-specific configuration."
        ;;
    ubuntu|fedora|arch|suse)
        print_info "Detected $DISTRO_NAME ($DISTRO_FAMILY family) — supported."
        ;;
    *)
        print_warning "This installer has not been tested on $DISTRO_NAME; you may need to install dependencies manually."
        print_warning "Vocalinux itself does not care which distribution it runs on, only that Python and PyGObject are new enough."
        if [[ "$NON_INTERACTIVE" == "yes" ]]; then
            print_info "Non-interactive mode: continuing anyway..."
        else
            read -p "Do you want to continue anyway? (y/n) " -n 1 -r
            echo
            if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                exit "$EXIT_USER_ABORT"
            fi
        fi
        ;;
esac

# Handle installation mode selection
if [[ "$INTERACTIVE_MODE" == "ask" ]]; then
    # Running via curl pipe but we have a terminal - ask user preference
    echo ""
    echo "Installation Mode:"
    echo "  1. Interactive (recommended) - guided setup with recommendations"
    echo "  2. Automatic - quick install with defaults (whisper.cpp)"
    echo ""
    read -p "Choose mode [1-2] (default: 1): " MODE_CHOICE
    MODE_CHOICE=${MODE_CHOICE:-1}

    if [[ "$MODE_CHOICE" == "2" ]]; then
        AUTO_MODE="yes"
        INTERACTIVE_MODE="no"
        NON_INTERACTIVE="yes"
    else
        INTERACTIVE_MODE="yes"
        NON_INTERACTIVE="no"
    fi
    echo ""
fi

# Run interactive installation if selected
if [[ "$INTERACTIVE_MODE" == "yes" ]]; then
    # Check if we have a TTY (required for interactive mode)
    if [ ! -t 0 ]; then
        print_error "Interactive mode requires a terminal (TTY)."
        print_error "Download and run the installer directly from a terminal:"
        print_error "  curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh && bash /tmp/vl.sh"
        exit 1
    fi

    # Run interactive installation
    run_interactive_install
fi

# Set default engine for auto/non-interactive mode
if [[ "$NON_INTERACTIVE" == "yes" ]] && [[ -z "$SELECTED_ENGINE" ]]; then
    SELECTED_ENGINE="whisper_cpp"
    print_info "Automatic mode: Installing with whisper.cpp (default engine)"
    print_info "For other engines, use: --engine=whisper, --engine=vosk, --engine=parakeet, --engine=faster_whisper, or --engine=remote_api"
fi


# Install system dependencies
if [[ "$SKIP_SYSTEM_DEPS" == "yes" ]]; then
    print_warning "Skipping system dependency installation (--skip-system-deps specified)."
    print_warning "Make sure GTK, PyGObject, AppIndicator/Ayatana, PortAudio, and text input tools are installed."
else
    install_system_dependencies
fi

# Define XDG directories
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/vocalinux"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

# Install text input tools based on session type
install_text_input_tools

# Create necessary directories
print_info "Creating application directories..."
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR/models"
mkdir -p "$DESKTOP_DIR"
mkdir -p "$ICON_DIR"

# Interpreter the venv is built from. Resolved by select_python_interpreter();
# nothing below may fall back to a bare `python3` for venv creation.
PYTHON_CMD="python3"

# The distro interpreter its GTK/PyGObject packages are built for. Overridable
# (SYSTEM_PYTHON=/usr/bin/python3.12 ./install.sh) for systems that ship several.
SYSTEM_PYTHON="${SYSTEM_PYTHON:-/usr/bin/python3}"

python_version_of() {
    "$1" -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>/dev/null
}

python_version_at_least() {
    local version
    version=$(python_version_of "$1") || return 1
    [ -n "$version" ] || return 1
    [[ $(printf '%s\n%s\n' "$version" "$2" | sort -V | head -n1) == "$2" ]]
}

python_has_gi() {
    "$1" -c "import gi" >/dev/null 2>&1
}

# Pick the interpreter to build the venv from. Distro PyGObject is compiled for
# exactly one Python, so prefer a candidate that can already import gi:
# $SYSTEM_PYTHON is probed explicitly because PATH may expose a different
# interpreter (pyenv, uv, /usr/local) that the distro packages were never built
# for. Falls back to the newest-enough candidate when none of them has gi yet —
# require_distro_gi() reports that case with a proper message later on.
select_python_interpreter() {
    local min_version="$1"
    local candidates=() candidate seen="" first="" ok_version="" ok_system=""

    if command_exists python3; then
        candidates+=("$(command -v python3)")
    fi
    if [ -x "$SYSTEM_PYTHON" ]; then
        candidates+=("$SYSTEM_PYTHON")
    fi

    for candidate in ${candidates[@]+"${candidates[@]}"}; do
        case ":$seen:" in
            *":$candidate:"*) continue ;;
        esac
        seen="${seen:+$seen:}$candidate"

        [ -n "$first" ] || first="$candidate"
        python_version_at_least "$candidate" "$min_version" || continue
        [ -n "$ok_version" ] || ok_version="$candidate"
        if [ "$candidate" = "$SYSTEM_PYTHON" ]; then
            ok_system="$candidate"
        fi

        if python_has_gi "$candidate"; then
            PYTHON_CMD="$candidate"
            return 0
        fi
    done

    # No candidate has gi yet; it may be installed later in this run. Prefer the
    # distro interpreter, because its PyGObject is the one that will show up.
    PYTHON_CMD="${ok_system:-${ok_version:-$first}}"
    [ -n "$PYTHON_CMD" ]
}

# Check Python version
check_python_version() {
    # Keep in sync with requires-python in pyproject.toml.
    local MIN_VERSION="3.11"

    if ! select_python_interpreter "$MIN_VERSION"; then
        print_error "Python 3 is not installed or not in PATH"
        return 1
    fi

    local PY_VERSION
    PY_VERSION=$(python_version_of "$PYTHON_CMD" || true)
    print_info "Detected Python version: ${PY_VERSION:-unknown} ($PYTHON_CMD)"

    if python_version_at_least "$PYTHON_CMD" "$MIN_VERSION"; then
        return 0
    fi

    print_error "This application requires Python $MIN_VERSION or newer. Detected: ${PY_VERSION:-unknown}"
    return 1
}

# An existing venv built by a different interpreter than the selected one is the
# classic cause of "distro PyGObject is not importable": PyGObject lives in the
# system Python's site-packages and --system-site-packages only exposes it to a
# venv of the *same* version. Such a venv otherwise survives every re-run,
# because the installer reuses whatever it finds.
# Where an interpreter's installation lives. For a venv this is the interpreter
# it was built from, which is what decides whether distro gi is visible.
python_base_prefix() {
    "$1" -c "import sys; print(sys.base_prefix)" 2>/dev/null
}

venv_matches_selected_python() {
    local venv_python="$VENV_DIR/bin/python"
    local venv_base selected_base

    [ -x "$venv_python" ] || return 1

    # Compare installations, not the X.Y string: a distro 3.12 and a pyenv/uv
    # 3.12 are not interchangeable, because distro PyGObject is importable only
    # from the one it was built for.
    venv_base=$(python_base_prefix "$venv_python") || return 1
    selected_base=$(python_base_prefix "$PYTHON_CMD") || return 1
    [ -n "$venv_base" ] && [ "$venv_base" = "$selected_base" ]
}

# Set up virtual environment with error handling
setup_virtual_environment() {
    print_info "Setting up Python virtual environment in $VENV_DIR..."

    # Discard a venv left behind by another interpreter before the reuse logic
    # below can adopt it.
    if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ] && ! venv_matches_selected_python; then
        print_warning "Existing virtual environment in $VENV_DIR was built by a different Python than $PYTHON_CMD."
        print_warning "Recreating it — distro PyGObject would stay invisible inside it otherwise."
        rm -rf "$VENV_DIR"
    fi

    # Check if virtual environment already exists
    if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
        print_warning "Virtual environment already exists in $VENV_DIR"
        if [[ "$NON_INTERACTIVE" == "yes" ]]; then
            # In non-interactive mode, reuse existing venv
            print_info "Non-interactive mode: using existing virtual environment."
            source "$VENV_DIR/bin/activate" || { print_error "Failed to activate virtual environment"; exit "$EXIT_MISSING_DEPS"; }
            return 0
        else
            read -p "Do you want to recreate it? (y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                print_info "Removing existing virtual environment..."
                rm -rf "$VENV_DIR"
            else
                print_info "Using existing virtual environment."
                source "$VENV_DIR/bin/activate" || { print_error "Failed to activate virtual environment"; exit "$EXIT_MISSING_DEPS"; }
                return 0
            fi
        fi
    fi

    # Create virtual environment
    # Use --system-site-packages to access pre-compiled system packages like PyGObject
    # This avoids build failures with Python 3.13+ where PyGObject may not build from source
    "$PYTHON_CMD" -m venv --system-site-packages "$VENV_DIR" || {
        print_warning "$PYTHON_CMD -m venv failed, trying $PYTHON_CMD -m virtualenv..."
        "$PYTHON_CMD" -m virtualenv --system-site-packages "$VENV_DIR" || {
            print_error "Failed to create virtual environment. Please check your Python installation."
            exit "$EXIT_MISSING_DEPS"
        }
    }

    # Activate virtual environment
    source "$VENV_DIR/bin/activate" || { print_error "Failed to activate virtual environment"; exit "$EXIT_MISSING_DEPS"; }

    print_info "Virtual environment activated successfully."
}

# Check Python version. Not advisory: distro PyGObject is built for the system
# interpreter, so a venv below the floor cannot import gi, and the install would
# fail later somewhere less obvious.
if ! check_python_version; then
    print_error "Point SYSTEM_PYTHON at a newer interpreter if one is installed:"
    print_error "  SYSTEM_PYTHON=/usr/bin/python3.12 ./install.sh"
    exit "$EXIT_MISSING_DEPS"
fi

# Set up virtual environment
setup_virtual_environment

# Also run for reused venvs: setup_virtual_environment returns early for those.
# Wheels only here so bootstrapping cannot itself resolve unpinned build deps.
install_pinned_build_tools() {
    local reqs_file="$INSTALL_DIR/requirements/installer-build.txt"
    if [ ! -s "$reqs_file" ]; then
        print_error "Missing or empty pinned requirements: $reqs_file"
        return 1
    fi
    print_info "Installing pinned pip and source-build tools..."
    "$VENV_DIR/bin/python" -m pip install --require-hashes --no-deps \
        --only-binary=:all: --ignore-installed \
        -r "$reqs_file" --log "$VOCALINUX_TMP_DIR/bootstrap.log"
}
install_pinned_build_tools || {
    print_error "Failed to install the pinned build tools. Check requirements/installer-build.txt."
    exit "$EXIT_NETWORK"
}

# Create activation script for users
# Put it in ~/.local/bin when running remotely, or current dir when running locally
if [[ "$CLEANUP_ON_EXIT" == "yes" ]]; then
    ACTIVATION_SCRIPT_DIR="$HOME/.local/bin"
    mkdir -p "$ACTIVATION_SCRIPT_DIR"
else
    ACTIVATION_SCRIPT_DIR="."
fi
ACTIVATION_SCRIPT="$ACTIVATION_SCRIPT_DIR/activate-vocalinux.sh"

cat > "$ACTIVATION_SCRIPT" << EOF
#!/bin/bash
# This script activates the Vocalinux virtual environment
export PYTHONNOUSERSITE=1
source "$VENV_DIR/bin/activate"
echo "Vocalinux virtual environment activated."
echo "To start the application, run: vocalinux"
EOF
chmod +x "$ACTIVATION_SCRIPT"
print_info "Created activation script: $ACTIVATION_SCRIPT"

get_pywhispercpp_library_path() {
    [ -x "$VENV_DIR/bin/python" ] || return 1
    "$VENV_DIR/bin/python" - <<'PY' 2>/dev/null
from pathlib import Path
import site
import sys
import sysconfig

roots = []
for attr in ("getsitepackages",):
    get_paths = getattr(site, attr, None)
    if get_paths is None:
        continue
    try:
        roots.extend(get_paths())
    except Exception:
        pass

user_site = getattr(site, "getusersitepackages", lambda: None)()
if user_site and getattr(site, "ENABLE_USER_SITE", False):
    roots.append(user_site)

for key in ("platlib", "purelib"):
    path = sysconfig.get_paths().get(key)
    if path:
        roots.append(path)

roots.extend(path for path in sys.path if path)

dirs = []
seen = set()
for root in roots:
    root_path = Path(root)
    candidates = [
        root_path / "pywhispercpp.libs",
        root_path / "pywhispercpp" / ".libs",
        root_path / "pywhispercpp" / "lib",
        root_path,
    ]
    for candidate in candidates:
        try:
            resolved = str(candidate.resolve())
        except OSError:
            continue
        if resolved in seen or not candidate.is_dir():
            continue
        if any(candidate.glob("libwhisper*.so*")) or any(candidate.glob("libggml*.so*")):
            seen.add(resolved)
            dirs.append(resolved)

print(":".join(dirs))
PY
}

is_pywhispercpp_gpu_capable() {
    local LIB_DIRS
    LIB_DIRS=$(get_pywhispercpp_library_path || true)
    [ -n "$LIB_DIRS" ] || return 1

    local IFS=:
    for dir in $LIB_DIRS; do
        if [ -f "$dir/libggml-vulkan.so" ] || [ -f "$dir/libggml-cuda.so" ]; then
            return 0
        fi
    done
    return 1
}

is_pywhispercpp_backend_capable() {
    local BACKEND
    BACKEND=$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')

    local LIB_DIRS
    LIB_DIRS=$(get_pywhispercpp_library_path || true)
    [ -n "$LIB_DIRS" ] || return 1

    local EXPECTED_LIB=""
    case "$BACKEND" in
        cuda)
            EXPECTED_LIB="libggml-cuda.so"
            ;;
        vulkan)
            EXPECTED_LIB="libggml-vulkan.so"
            ;;
        *)
            return 1
            ;;
    esac

    local IFS=:
    local LIB_DIR
    for LIB_DIR in $LIB_DIRS; do
        if compgen -G "$LIB_DIR/$EXPECTED_LIB*" >/dev/null; then
            return 0
        fi
    done

    return 1
}

is_pywhispercpp_cuda_linkage_usable() {
    if ! command -v readelf >/dev/null 2>&1; then
        print_warning "readelf not found; skipping CUDA linkage verification." >&2
        return 0
    fi

    local LIB_DIRS
    LIB_DIRS=$(get_pywhispercpp_library_path || true)
    [ -n "$LIB_DIRS" ] || return 1

    local HAS_PATCHELF=false
    if command -v patchelf >/dev/null 2>&1; then
        HAS_PATCHELF=true
    fi

    local IFS=:
    local LIB_DIR
    for LIB_DIR in $LIB_DIRS; do
        local CUDA_LIB
        for CUDA_LIB in "$LIB_DIR"/libggml-cuda.so*; do
            [ -f "$CUDA_LIB" ] || continue
            local BUNDLED_LIBS
            BUNDLED_LIBS=$(readelf -d "$CUDA_LIB" 2>/dev/null | sed -En 's/.*Shared library: \[(libcuda-[^]]+\.so).*/\1/p')
            if [ -z "$BUNDLED_LIBS" ]; then
                continue
            fi

            local BUNDLED_LIB
            while IFS= read -r BUNDLED_LIB; do
                [ -n "$BUNDLED_LIB" ] || continue
                print_warning "CUDA backend links against bundled $BUNDLED_LIB instead of libcuda.so.1:"
                print_warning "  $CUDA_LIB"

                if [[ "$HAS_PATCHELF" == "true" ]]; then
                    print_info "Attempting to relink with patchelf ($BUNDLED_LIB → libcuda.so.1)..."
                    if patchelf --replace-needed "$BUNDLED_LIB" libcuda.so.1 "$CUDA_LIB" 2>/dev/null; then
                        print_success "Successfully relinked $CUDA_LIB to libcuda.so.1"
                    else
                        print_warning "patchelf relink failed for $CUDA_LIB"
                        print_warning "Treating CUDA verification as failed so the installer does not report broken GPU support."
                        return 1
                    fi
                else
                    print_warning "Install patchelf to attempt automatic relinking: sudo apt install patchelf"
                    print_warning "Treating CUDA verification as failed so the installer does not report broken GPU support."
                    return 1
                fi
            done <<< "$BUNDLED_LIBS"
        done
    done

    return 0
}

verify_pywhispercpp_backend_install() {
    local BACKEND="$1"

    if ! is_pywhispercpp_installed; then
        print_warning "pywhispercpp installed but import verification failed for $BACKEND backend."
        return 1
    fi

    if ! is_pywhispercpp_backend_capable "$BACKEND"; then
        print_warning "pywhispercpp installed but $BACKEND backend libraries were not found."
        return 1
    fi

    if [[ "$BACKEND" == "CUDA" ]] && ! is_pywhispercpp_cuda_linkage_usable; then
        return 1
    fi

    return 0
}

print_pip_log_tail() {
    local PIP_LOG_FILE="$1"
    local LINE_COUNT="${2:-80}"

    if [ -s "$PIP_LOG_FILE" ]; then
        print_warning "Last $LINE_COUNT lines from pip build log ($PIP_LOG_FILE):"
        tail -n "$LINE_COUNT" "$PIP_LOG_FILE" | sed 's/^/    /'
    else
        print_warning "Pip build log is empty or missing: $PIP_LOG_FILE"
    fi
}

with_pywhispercpp_library_path() {
    local PYWHISPERCPP_LIBRARY_PATH
    PYWHISPERCPP_LIBRARY_PATH=$(get_pywhispercpp_library_path || true)

    if [ -n "$PYWHISPERCPP_LIBRARY_PATH" ]; then
        LD_LIBRARY_PATH="$PYWHISPERCPP_LIBRARY_PATH${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$@"
    else
        "$@"
    fi
}

get_pywhispercpp_cmake_args() {
    printf '%s\n' '-DCMAKE_INSTALL_RPATH=$ORIGIN -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON'
}

install_cpu_pywhispercpp() {
    local PIP_LOG_FILE="$1"
    local PYWHISPERCPP_CMAKE_ARGS
    PYWHISPERCPP_CMAKE_ARGS=$(get_pywhispercpp_cmake_args)

    CMAKE_ARGS="${CMAKE_ARGS:+$CMAKE_ARGS }$PYWHISPERCPP_CMAKE_ARGS" \
        pip_reinstall_pywhispercpp "$PIP_LOG_FILE"
}

pip_reinstall_pywhispercpp() {
    local pip_log="$1"
    shift
    local reqs_file="$VOCALINUX_TMP_DIR/pywhispercpp.txt"
    "$VENV_DIR/bin/python" "$INSTALL_DIR/scripts/installer_requirements.py" \
        "$INSTALL_DIR/requirements/runtime.txt" "$reqs_file" --package pywhispercpp || return 1
    # --no-deps preserves the locked runtime and avoids reinstalling numpy
    # while replacing only the backend. Build tools were bootstrapped above.
    "$VENV_DIR/bin/python" -m pip install --require-hashes --no-deps --no-build-isolation \
        --verbose --force-reinstall --no-cache-dir -r "$reqs_file" --log "$pip_log" "$@"
}

is_pywhispercpp_installed() {
    [ -x "$VENV_DIR/bin/python" ] || return 1
    with_pywhispercpp_library_path "$VENV_DIR/bin/python" -c "from pywhispercpp.model import Model" >/dev/null 2>&1
}

get_pywhispercpp_version() {
    [ -x "$VENV_DIR/bin/python" ] || return 1
    "$VENV_DIR/bin/python" - <<'PY' 2>/dev/null
from importlib import metadata

try:
    print(metadata.version("pywhispercpp"))
except metadata.PackageNotFoundError:
    raise SystemExit(1)
PY
}

should_rebuild_whispercpp() {
    local INSTALLED_VERSION
    INSTALLED_VERSION=$(get_pywhispercpp_version || true)

    print_success "Found existing pywhispercpp installation${INSTALLED_VERSION:+ (version $INSTALLED_VERSION)}"

    case "$REBUILD_WHISPERCPP" in
        yes)
            print_info "Rebuilding pywhispercpp because --rebuild-whispercpp was specified."
            return 0
            ;;
        no)
            print_info "Reusing existing pywhispercpp installation."
            return 1
            ;;
    esac

    if [[ "$NON_INTERACTIVE" == "yes" ]]; then
        if [[ "$HAS_NVIDIA_GPU" == "yes" || "$HAS_VULKAN" == "yes" ]] && ! is_pywhispercpp_gpu_capable; then
            print_info "Non-interactive mode: GPU detected but pywhispercpp lacks GPU support. Rebuilding..."
            return 0
        fi
        print_info "Non-interactive mode: reusing existing pywhispercpp installation."
        print_info "Use --rebuild-whispercpp to force a rebuild."
        return 1
    fi

    if [[ "$HAS_NVIDIA_GPU" == "yes" || "$HAS_VULKAN" == "yes" ]] && ! is_pywhispercpp_gpu_capable; then
        print_info "GPU detected but pywhispercpp lacks GPU support. Rebuilding..."
        return 0
    fi

    read -p "Rebuild/reinstall pywhispercpp? This can take several minutes. (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        return 0
    fi

    print_info "Reusing existing pywhispercpp installation."
    return 1
}

# Module each engine needs, and the pip name that provides it. Defined here so
# the whisper.cpp -> vosk fallback can rewrite an existing config.json; the
# writers above used to skip a file that already existed.
engine_import_module() {
    case "$1" in
        vosk) echo "vosk" ;;
        whisper) echo "whisper" ;;
        whisper_cpp) echo "pywhispercpp.model" ;;
        parakeet) echo "sherpa_onnx" ;;
        faster_whisper) echo "faster_whisper" ;;
        *) echo "" ;;
    esac
}

engine_pip_name() {
    case "$1" in
        vosk) echo "vosk" ;;
        whisper) echo "openai-whisper" ;;
        whisper_cpp) echo "pywhispercpp" ;;
        parakeet) echo "sherpa-onnx" ;;
        faster_whisper) echo "faster-whisper" ;;
        *) echo "" ;;
    esac
}

venv_can_import() {
    [ -x "$VENV_DIR/bin/python" ] || return 1
    "$VENV_DIR/bin/python" -c "import $1" >/dev/null 2>&1
}

# Point config.json at engine $2. Non-zero if it could not be rewritten.
set_configured_engine() {
    "$VENV_DIR/bin/python" - "$1" "$2" <<'PY' 2>/dev/null
import json
import sys

path, engine = sys.argv[1], sys.argv[2]
with open(path) as handle:
    config = json.load(handle)
config.setdefault("speech_recognition", {})["engine"] = engine
with open(path, "w") as handle:
    json.dump(config, handle, indent=2)
    handle.write("\n")
PY
}

install_whispercpp_with_gpu_support() {
    local PIP_LOG_FILE="$1"

    print_info ""
    print_info "╔════════════════════════════════════════════════════════╗"
    print_info "║  Installing WHISPER.CPP (Recommended)                  ║"
    print_info "╠════════════════════════════════════════════════════════╣"
    print_info "║  • Fastest speech recognition                          ║"
    print_info "║  • Works with any GPU: NVIDIA, AMD, Intel              ║"
    print_info "║  • Uses Vulkan for GPU acceleration                    ║"
    print_info "║  • CPU-only mode available                             ║"
    print_info "╚════════════════════════════════════════════════════════╝"
    print_info ""

    # Detect GPU and install pywhispercpp with appropriate GPU support
    detect_nvidia_gpu || true
    detect_vulkan || true

    local GPU_BACKEND="CPU"
    local GPU_INSTALL_SUCCESS=false
    local SKIP_WHISPERCPP_INSTALL=false
    local PYWHISPERCPP_CMAKE_ARGS
    PYWHISPERCPP_CMAKE_ARGS=$(get_pywhispercpp_cmake_args)

    if [[ "$WHISPERCPP_ALREADY_INSTALLED" == "true" ]]; then
        GPU_BACKEND="existing"
        if should_rebuild_whispercpp; then
            print_info "Existing pywhispercpp will be replaced."
        else
            SKIP_WHISPERCPP_INSTALL=true
        fi
    fi

    # Check if user explicitly chose CPU backend in interactive mode
    if [[ "$SKIP_WHISPERCPP_INSTALL" == "true" ]]; then
        print_info "Skipping pywhispercpp reinstall; existing compiled bindings remain in place."
    elif [[ "${WHISPERCPP_BACKEND}" == "cpu" ]]; then
        print_info "ℹ Installing CPU-only version (as requested)..."
        GPU_BACKEND="CPU"
    else
        # Try Vulkan first (works with all GPUs: NVIDIA, AMD, Intel)
        if [[ "$HAS_VULKAN" == "yes" ]]; then
            print_info "✓ Vulkan detected: $VULKAN_DEVICE"
            print_info "  Installing pywhispercpp with Vulkan support..."
            GPU_BACKEND="Vulkan"
            print_info "Installing pywhispercpp ($GPU_BACKEND backend)..."
            if CMAKE_ARGS="${CMAKE_ARGS:+$CMAKE_ARGS }$PYWHISPERCPP_CMAKE_ARGS" \
                GGML_VULKAN=1 \
                pip_reinstall_pywhispercpp "$PIP_LOG_FILE" --no-binary pywhispercpp 2>&1; then
                if verify_pywhispercpp_backend_install "$GPU_BACKEND"; then
                    GPU_INSTALL_SUCCESS=true
                else
                    print_pip_log_tail "$PIP_LOG_FILE"
                fi
            else
                print_warning "Vulkan build failed; checking for NVIDIA GPU to try CUDA..."
                print_pip_log_tail "$PIP_LOG_FILE"
            fi
        fi

        # If Vulkan failed or not available, try CUDA for NVIDIA GPUs
        if [[ "$GPU_INSTALL_SUCCESS" != "true" && "$HAS_NVIDIA_GPU" == "yes" ]]; then
            print_info "✓ NVIDIA GPU detected: $GPU_NAME"
            print_info "  Installing pywhispercpp with CUDA support..."
            GPU_BACKEND="CUDA"

            local CUDA_TOOLKIT_ROOT=""
            local CUDA_CMAKE_ARGS=""
            if CUDA_TOOLKIT_ROOT=$(find_valid_cuda_toolkit_root); then
                if CUDA_CMAKE_ARGS=$(get_cuda_cmake_args "$CUDA_TOOLKIT_ROOT"); then
                    print_info "Using CUDA toolkit: $CUDA_TOOLKIT_ROOT"
                    print_info "Installing pywhispercpp ($GPU_BACKEND backend)..."
                    if CMAKE_ARGS="${CMAKE_ARGS:+$CMAKE_ARGS }$PYWHISPERCPP_CMAKE_ARGS $CUDA_CMAKE_ARGS" \
                        GGML_CUDA=1 \
                        pip_reinstall_pywhispercpp "$PIP_LOG_FILE" --no-binary pywhispercpp 2>&1; then
                        if verify_pywhispercpp_backend_install "$GPU_BACKEND"; then
                            GPU_INSTALL_SUCCESS=true
                        else
                            print_pip_log_tail "$PIP_LOG_FILE"
                        fi
                    else
                        print_warning "CUDA build failed."
                        print_pip_log_tail "$PIP_LOG_FILE"
                    fi
                else
                    print_warning "Skipping CUDA build because the detected toolkit cannot target this NVIDIA GPU."
                fi
            else
                print_warning "No complete CUDA toolkit root found; skipping CUDA build."
                print_info "  Required CUDA files: bin/nvcc, include/cuda_runtime.h, and libcudart.so*"
            fi
        fi
    fi

    # Fall back to CPU version if GPU install failed or no GPU detected
    if [[ "$SKIP_WHISPERCPP_INSTALL" != "true" && "$GPU_INSTALL_SUCCESS" != "true" ]]; then
        if [[ "$GPU_BACKEND" != "CPU" ]]; then
            print_warning "Failed to install pywhispercpp with $GPU_BACKEND support, falling back to CPU version..."

            # Provide helpful error messages for common issues
            if [[ "$GPU_BACKEND" == "Vulkan" ]]; then
                print_info "  To use Vulkan GPU acceleration, please install Vulkan development libraries:"
                print_info "    Ubuntu/Debian: sudo apt install libvulkan-dev vulkan-tools glslc || glslang-tools"
                print_info "    Fedora: sudo dnf install vulkan-loader-devel vulkan-tools glslc patchelf"
                print_info "    Arch: sudo pacman -S vulkan-headers vulkan-tools shaderc patchelf"
                print_info "    openSUSE: sudo zypper install vulkan-devel vulkan-tools shaderc patchelf"
            elif [[ "$GPU_BACKEND" == "CUDA" ]]; then
                print_info "  To use CUDA GPU acceleration, please install CUDA toolkit:"
                print_info "    Visit: https://developer.nvidia.com/cuda-downloads"
            fi
        elif [[ "${WHISPERCPP_BACKEND}" != "cpu" ]]; then
            print_info "ℹ No GPU detected - installing CPU-only version"
            print_info "  CPU mode is still very fast!"
        fi
        if [[ "$GPU_BACKEND" != "CPU" ]]; then
            print_warning "Continuing with CPU-only pywhispercpp; GPU acceleration is not active."
        fi
        GPU_BACKEND="CPU"
        print_info "Installing pywhispercpp ($GPU_BACKEND backend)..."
        install_cpu_pywhispercpp "$PIP_LOG_FILE" || {
            print_error "Failed to install pywhispercpp"
            return 1
        }
    fi

    if [[ "$SKIP_WHISPERCPP_INSTALL" == "true" ]]; then
        print_success "pywhispercpp reused from existing installation"
    else
        print_success "pywhispercpp installed with $GPU_BACKEND backend"
    fi

    if ! is_pywhispercpp_installed; then
        print_warning "pywhispercpp installed but import verification failed."
        print_warning "This can happen when libwhisper.so is installed beside the Python extension without a runtime library path."

        if [[ "$SKIP_WHISPERCPP_INSTALL" != "true" ]]; then
            print_warning "Trying RPATH-aware CPU pywhispercpp fallback..."
            GPU_BACKEND="CPU"
            if install_cpu_pywhispercpp "$PIP_LOG_FILE"; then
                print_success "CPU pywhispercpp fallback installed"
            else
                print_warning "CPU pywhispercpp fallback installation failed"
            fi
        fi
    fi

    if ! is_pywhispercpp_installed; then
        print_warning "pywhispercpp is still unavailable; setting VOSK as the default engine so Vocalinux can start."
        print_warning "You can switch back to whisper.cpp from Settings after reinstalling pywhispercpp."
        SELECTED_ENGINE="vosk"

        # vosk is an optional extra; make sure it is importable before
        # falling back to it
        if ! "$VENV_DIR/bin/python" -c "import vosk" 2>/dev/null; then
            pip_install_extras_skip_pygobject "$PIP_LOG_FILE" vosk || \
                print_warning "Could not install vosk; install it manually or pick another engine in Settings."
        fi

        # Writing engine=vosk when the import still fails only moves the failure
        # to startup, where it surfaces as ModuleNotFoundError: No module named
        # 'vosk' and the app never comes up.
        if ! "$VENV_DIR/bin/python" -c "import vosk" 2>/dev/null; then
            print_warning "vosk is still not importable; leaving the engine configuration untouched."
            SELECTED_ENGINE=""
            return 0
        fi

        local FALLBACK_VOSK_CONFIG="$CONFIG_DIR/config.json"
        if [ -f "$FALLBACK_VOSK_CONFIG" ]; then
            if set_configured_engine "$FALLBACK_VOSK_CONFIG" "vosk"; then
                print_success "Switched $FALLBACK_VOSK_CONFIG to the vosk engine."
            else
                print_warning "Could not rewrite $FALLBACK_VOSK_CONFIG to vosk."
            fi
        else
            mkdir -p "$CONFIG_DIR"
            cat > "$FALLBACK_VOSK_CONFIG" << 'FALLBACK_VOSK_CONFIG'
{
    "speech_recognition": {
        "engine": "vosk",
        "model_size": "small",
        "vosk_model_size": "small",
        "whisper_model_size": "tiny",
        "whisper_cpp_model_size": "tiny",
        "vad_sensitivity": 3,
        "silence_timeout": 2.0
    },
    "audio": {
        "device_index": null,
        "device_name": null
    },
    "shortcuts": {
        "toggle_recognition": "right_alt+right_alt",
        "mode": "push_to_talk"
    },
    "ui": {
        "start_minimized": false,
        "show_notifications": true,
        "show_missing_tray_warning": true
    },
    "advanced": {
        "debug_logging": false,
        "wayland_mode": false
    }
}
FALLBACK_VOSK_CONFIG
        fi
    fi
    echo ""
}

# Exports use --no-emit-package pygobject: distro GI remains visible through
# --system-site-packages. Install the locked dependencies first, then the local
# project with --no-deps and --no-build-isolation so neither step re-resolves.

require_distro_gi() {
    if ! "$VENV_DIR/bin/python" -c "import gi" 2>/dev/null; then
        print_error "Distro PyGObject (python3-gi / python3-gobject) is not importable in the venv."
        print_error "The venv was built from $PYTHON_CMD (Python $(python_version_of "$PYTHON_CMD" || echo unknown))."
        print_error "Install it with your package manager. Pip cannot build PyGObject here."
        exit "$EXIT_MISSING_DEPS"
    fi
}

pip_install_reqs_file() {
    local pip_log="$1"
    local reqs_file="$2"
    if [ ! -s "$reqs_file" ]; then
        print_error "Missing or empty pinned requirements: $reqs_file"
        return 1
    fi
    "$VENV_DIR/bin/python" -m pip install --require-hashes --no-deps --no-build-isolation \
        -r "$reqs_file" --log "$pip_log"
}

pip_install_project_skip_pygobject() {
    local pip_log="$1"
    shift
    require_distro_gi || return 1
    pip_install_reqs_file "$pip_log" "$INSTALL_DIR/requirements/runtime.txt" || return 1
    "$VENV_DIR/bin/python" -m pip install --no-deps --no-build-isolation --log "$pip_log" "$@"
}

pip_install_extras_skip_pygobject() {
    local pip_log="$1"
    shift
    local extra
    for extra in "$@"; do
        # uv normalizes underscores to dashes in export filenames.
        case "$extra" in
            vad|vosk|parakeet|faster_whisper|whisper|dev) ;;
            *) print_error "Unknown dependency extra: $extra"; return 1 ;;
        esac
        pip_install_reqs_file "$pip_log" "$INSTALL_DIR/requirements/${extra//_/-}.txt" || return 1
    done
}

# Function to install Python package with error handling and verification
install_python_package() {
    # Pip logs live in the install scratch dir so a failed run can keep them.
    local PIP_LOG_DIR="$VOCALINUX_TMP_DIR/pip"
    mkdir -p "$PIP_LOG_DIR"
    local PIP_LOG_FILE="$PIP_LOG_DIR/pip_log.txt"

    # Detect GI_TYPELIB_PATH early for cross-distro compatibility
    # This ensures the path is available for both verification and wrapper scripts
    # NOTE: global on purpose — install_desktop_entry (top level) reuses it.
    GI_TYPELIB_DETECTED=$(detect_typelib_path || true)
    print_info "Detected GI_TYPELIB_PATH: $GI_TYPELIB_DETECTED"

    local WHISPERCPP_ALREADY_INSTALLED=false
    if is_pywhispercpp_installed; then
        WHISPERCPP_ALREADY_INSTALLED=true
    fi

    # Function to verify package installation
    verify_package_installed() {
        local PKG_NAME="vocalinux"
        # Use venv python and set GI_TYPELIB_PATH for PyGObject
        # Use the detected path for cross-distro compatibility
        GI_TYPELIB_PATH="$GI_TYPELIB_DETECTED" "$VENV_DIR/bin/python" -c "import $PKG_NAME" 2>/dev/null
        return $?
    }

    # Silero/ONNX Runtime gives much better speech/silence decisions, but
    # onnxruntime wheels are not guaranteed for every Python/platform combo.
    # Install it opportunistically so fresh installs and rerun-updates get the
    # neural VAD when available without blocking the amplitude fallback path.
    install_vad_support() {
        local PIP_LOG_FILE="$1"
        local EDITABLE_MODE="${2:-no}"

        print_info "Installing neural VAD support (Silero / ONNX Runtime)..."
        local VAD_INSTALL_SUCCESS=false
        if pip_install_extras_skip_pygobject "$PIP_LOG_FILE" vad; then
            VAD_INSTALL_SUCCESS=true
        fi

        if [[ "$VAD_INSTALL_SUCCESS" == "true" ]]; then
            if "$VENV_DIR/bin/python" - <<'PY' 2>/dev/null
from vocalinux.speech_recognition.silero_vad import is_silero_available
raise SystemExit(0 if is_silero_available() else 1)
PY
            then
                print_success "Neural VAD support installed and verified successfully."
            else
                print_warning "Neural VAD dependencies installed, but Silero VAD could not be verified."
                print_warning "Vocalinux will use amplitude-based VAD until this is resolved."
            fi
        else
            print_warning "Failed to install neural VAD support."
            print_warning "Vocalinux will still work using amplitude-based VAD."
            print_warning "Check the pip log for details: $PIP_LOG_FILE"
        fi
    }

    if [[ "$DEV_MODE" == "yes" ]]; then
        print_info "Installing Vocalinux in development mode..."

        # Install in development mode with logging
        pip_install_project_skip_pygobject "$PIP_LOG_FILE" -e . || {
            print_error "Failed to install Vocalinux in development mode."
            print_error "Check the pip log for details: $PIP_LOG_FILE"
            return 1
        }

        # Install test dependencies
        print_info "Installing test dependencies..."
        pip_install_extras_skip_pygobject "$PIP_LOG_FILE" dev || {
            print_warning "Failed to install some test dependencies. Tests may not run correctly."
        }

        # Install all optional dependencies for development
        print_info "Installing all optional dependencies for development..."
        pip_install_extras_skip_pygobject "$PIP_LOG_FILE" whisper || {
            print_warning "Failed to install some optional dependencies."
            print_warning "Some features may not work correctly."
        }

        install_vad_support "$PIP_LOG_FILE" yes

        if [[ "${SELECTED_ENGINE:-whisper_cpp}" == "whisper_cpp" ]]; then
            install_whispercpp_with_gpu_support "$PIP_LOG_FILE"
        fi
    else
        print_info "Installing Vocalinux..."

        # Install the package with logging (includes pywhispercpp by default)
        pip_install_project_skip_pygobject "$PIP_LOG_FILE" . || {
            print_error "Failed to install Vocalinux."
            print_error "Check the pip log for details: $PIP_LOG_FILE"
            return 1
        }

        install_vad_support "$PIP_LOG_FILE"

        # Engine installation logic:
        # - SELECTED_ENGINE is set by interactive mode or --engine flag
        # - WHISPERCPP_BACKEND is set by interactive mode ("gpu" or "cpu")
        # - Default is whisper_cpp for best performance
        case "${SELECTED_ENGINE:-whisper_cpp}" in
            whisper_cpp)
                install_whispercpp_with_gpu_support "$PIP_LOG_FILE"
                ;;

            whisper)
                print_info "Installing Whisper (OpenAI) with PyTorch..."
                print_info "Note: This engine requires NVIDIA GPU for acceleration"
                print_info "      For AMD/Intel GPUs, whisper.cpp is recommended"

                local WHISPER_INSTALL_SUCCESS=false

                print_info "Installing pinned Whisper and CPU PyTorch..."
                if pip_install_extras_skip_pygobject "$PIP_LOG_FILE" whisper; then
                    if "$VENV_DIR/bin/python" -c "import whisper" 2>/dev/null; then
                        WHISPER_INSTALL_SUCCESS=true
                        print_success "Whisper installed and verified successfully"
                    else
                        print_error "Whisper package installed but import failed"
                    fi
                else
                    print_error "Failed to install pinned Whisper dependencies"
                fi

                if [[ "$WHISPER_INSTALL_SUCCESS" == "true" ]]; then
                    # Create config with whisper as default
                    local WHISPER_CONFIG="$CONFIG_DIR/config.json"
                    if [ ! -f "$WHISPER_CONFIG" ]; then
                        mkdir -p "$CONFIG_DIR"
                        cat > "$WHISPER_CONFIG" << 'WHISPER_CONFIG'
{
    "speech_recognition": {
        "engine": "whisper",
        "model_size": "tiny",
        "vosk_model_size": "small",
        "whisper_model_size": "tiny",
        "whisper_cpp_model_size": "tiny",
        "vad_sensitivity": 3,
        "silence_timeout": 2.0
    },
    "audio": {
        "device_index": null,
        "device_name": null
    },
    "shortcuts": {
        "toggle_recognition": "right_alt+right_alt",
        "mode": "push_to_talk"
    },
    "ui": {
        "start_minimized": false,
        "show_notifications": true,
        "show_missing_tray_warning": true
    },
    "advanced": {
        "debug_logging": false,
        "wayland_mode": false
    }
}
WHISPER_CONFIG
                    fi
                else
                    print_warning "Failed to install Whisper (OpenAI)"
                    print_warning "Falling back to whisper.cpp (recommended engine)"
                    print_info ""
                    print_info "The Whisper (OpenAI) engine installation failed."
                    print_info "whisper.cpp will be installed instead, which is:"
                    print_info "  - Faster and more accurate"
                    print_info "  - Works with any GPU (NVIDIA, AMD, Intel)"
                    print_info "  - Uses Vulkan for GPU acceleration"
                    print_info ""

                    # Fall back to whisper.cpp installation
                    install_cpu_pywhispercpp "$PIP_LOG_FILE" || {
                        print_error "Failed to install pywhispercpp fallback"
                        print_error "Please try installing manually: pip install pywhispercpp"
                        return 1
                    }
                    print_success "Installed whisper.cpp as fallback"

                    # Create config with whisper_cpp as default
                    local FALLBACK_CONFIG="$CONFIG_DIR/config.json"
                    if [ ! -f "$FALLBACK_CONFIG" ]; then
                        mkdir -p "$CONFIG_DIR"
                        cat > "$FALLBACK_CONFIG" << 'FALLBACK_CONFIG'
{
    "speech_recognition": {
        "engine": "whisper_cpp",
        "model_size": "tiny",
        "vosk_model_size": "small",
        "whisper_model_size": "tiny",
        "whisper_cpp_model_size": "tiny",
        "vad_sensitivity": 3,
        "silence_timeout": 2.0
    },
    "audio": {
        "device_index": null,
        "device_name": null
    },
    "shortcuts": {
        "toggle_recognition": "right_alt+right_alt",
        "mode": "push_to_talk"
    },
    "ui": {
        "start_minimized": false,
        "show_notifications": true,
        "show_missing_tray_warning": true
    },
    "advanced": {
        "debug_logging": false,
        "wayland_mode": false
    }
}
FALLBACK_CONFIG
                    fi
                fi
                ;;

            vosk)
                print_info "Installing VOSK (lightweight option)..."
                print_info "VOSK is fast and works well on older systems."

                # vosk is an optional extra; install it alongside the base package
                pip_install_extras_skip_pygobject "$PIP_LOG_FILE" vosk || {
                    print_error "Failed to install the vosk engine"
                    return 1
                }

                # Create config with vosk as default
                local VOSK_CONFIG_FILE="$CONFIG_DIR/config.json"
                if [ ! -f "$VOSK_CONFIG_FILE" ]; then
                    mkdir -p "$CONFIG_DIR"
                    cat > "$VOSK_CONFIG_FILE" << 'VOSK_CONFIG'
{
    "speech_recognition": {
        "engine": "vosk",
        "model_size": "small",
        "vosk_model_size": "small",
        "whisper_model_size": "tiny",
        "whisper_cpp_model_size": "tiny",
        "vad_sensitivity": 3,
        "silence_timeout": 2.0
    },
    "audio": {
        "device_index": null,
        "device_name": null
    },
    "shortcuts": {
        "toggle_recognition": "right_alt+right_alt",
        "mode": "push_to_talk"
    },
    "ui": {
        "start_minimized": false,
        "show_notifications": true,
        "show_missing_tray_warning": true
    },
    "advanced": {
        "debug_logging": false,
        "wayland_mode": false
    }
}
VOSK_CONFIG
                fi
                ;;

            parakeet)
                print_info "Installing Parakeet (sherpa-onnx)..."
                print_info "Parakeet runs NVIDIA NeMo ASR models on CPU."

                # sherpa-onnx is an optional extra; install it alongside the base package
                pip_install_extras_skip_pygobject "$PIP_LOG_FILE" parakeet || {
                    print_error "Failed to install the parakeet engine"
                    return 1
                }

                # config_manager merges the remaining defaults, but a file with no
                # shortcuts section reads as a pre-push-to-talk config and gets
                # pinned back to ctrl+ctrl/toggle, so seed that section too.
                mkdir -p "$CONFIG_DIR"
                if [ ! -f "$CONFIG_DIR/config.json" ]; then
                    cat > "$CONFIG_DIR/config.json" << 'PARAKEET_CONFIG'
{
    "shortcuts": {
        "toggle_recognition": "right_alt+right_alt",
        "mode": "push_to_talk"
    }
}
PARAKEET_CONFIG
                fi
                set_configured_engine "$CONFIG_DIR/config.json" parakeet ||
                    print_warning "Could not point $CONFIG_DIR/config.json at the parakeet engine."
                ;;

            remote_api)
                print_info "Setting up Remote API engine..."
                print_info ""
                print_info "╔════════════════════════════════════════════════════════╗"
                print_info "║  Setting up REMOTE API Engine                          ║"
                print_info "╠════════════════════════════════════════════════════════╣"
                print_info "║  • Offloads speech recognition to a remote server      ║"
                print_info "║  • Ideal for laptops without GPU                       ║"
                print_info "║  • Supports whisper.cpp server & OpenAI APIs           ║"
                print_info "║  • Requires: a server running on your network          ║"
                print_info "╚════════════════════════════════════════════════════════╝"
                print_info ""

                # requests is already installed from the runtime export.
                "$VENV_DIR/bin/python" -c "import requests" || {
                    print_error "The pinned requests library is not importable"
                    return 1
                }
                print_success "requests library installed"

                # URL was collected upfront by run_interactive_install
                # (or left blank in auto/non-interactive mode).
                local REMOTE_API_URL="${REMOTE_API_URL:-}"

                # Create configuration file
                local REMOTE_CONFIG_FILE="$CONFIG_DIR/config.json"
                if [ ! -f "$REMOTE_CONFIG_FILE" ]; then
                    mkdir -p "$CONFIG_DIR"
                    cat > "$REMOTE_CONFIG_FILE" << REMOTE_CONFIG
{
    "speech_recognition": {
        "engine": "remote_api",
        "model_size": "small",
        "vosk_model_size": "small",
        "whisper_model_size": "tiny",
        "whisper_cpp_model_size": "tiny",
        "remote_api_url": "${REMOTE_API_URL}",
        "remote_api_key": "",
        "vad_sensitivity": 3,
        "silence_timeout": 2.0
    },
    "audio": {
        "device_index": null,
        "device_name": null
    },
    "shortcuts": {
        "toggle_recognition": "right_alt+right_alt",
        "mode": "push_to_talk"
    },
    "ui": {
        "start_minimized": false,
        "show_notifications": true,
        "show_missing_tray_warning": true
    },
    "advanced": {
        "debug_logging": false,
        "wayland_mode": false
    }
}
REMOTE_CONFIG
                fi

                if [ -n "$REMOTE_API_URL" ]; then
                    print_success "Remote API configured with server: $REMOTE_API_URL"
                else
                    print_warning "No server URL configured. You can set it later in Settings."
                fi
                ;;

            faster_whisper)
                print_info "Installing Faster-Whisper engine..."
                print_info "This engine uses CTranslate2 for fast CPU inference."

                if pip_install_extras_skip_pygobject "$PIP_LOG_FILE" faster_whisper; then
                    mkdir -p "$CONFIG_DIR"
                    if [ ! -f "$CONFIG_DIR/config.json" ]; then
                        cat > "$CONFIG_DIR/config.json" << 'FASTER_WHISPER_CONFIG'
{
    "shortcuts": {
        "toggle_recognition": "right_alt+right_alt",
        "mode": "push_to_talk"
    }
}
FASTER_WHISPER_CONFIG
                    fi
                    set_configured_engine "$CONFIG_DIR/config.json" faster_whisper ||
                        print_warning "Could not point $CONFIG_DIR/config.json at the faster_whisper engine."
                else
                    print_error "Failed to install the faster-whisper engine"
                    print_error "Falling back to whisper.cpp (recommended engine)"
                    install_cpu_pywhispercpp "$PIP_LOG_FILE" || {
                        print_error "Failed to install whisper.cpp fallback"
                        return 1
                    }
                    SELECTED_ENGINE="whisper_cpp"
                fi
                ;;
        esac
    fi

    # Verify installation
    if verify_package_installed; then
        print_success "Vocalinux package installed successfully!"
        # Pip logs stay under VOCALINUX_TMP_DIR; the EXIT trap removes that
        # directory on success and keeps it when a later step fails.

        # GI_TYPELIB_PATH was already detected at the start of install_python_package

        # Create wrapper scripts in ~/.local/bin for easy access
        mkdir -p "$HOME/.local/bin"

        # Shared sg check logic for wrapper scripts.
        # Uses sg to activate the input group for Wayland keyboard shortcuts without logout.
        # Single-quoted so install.sh does not expand; the wrapper expands $(whoami)/$EXEC_CMD
        # at runtime. Do not write \$ — that leaves a literal $EXEC_CMD for exec.
        local SG_CHECK='if grep -q "^input:.*\b$(whoami)\b" /etc/group 2>/dev/null && ! groups | grep -q "\binput\b" && command -v sg &>/dev/null; then
    exec sg input -c "$EXEC_CMD"
else
    exec $EXEC_CMD
fi'

        # Create vocalinux wrapper script
        cat > "$HOME/.local/bin/vocalinux" << WRAPPER_EOF
#!/bin/bash
# Wrapper script for Vocalinux that sets required environment variables
# and applies the 'input' group for keyboard shortcuts on Wayland
export PYTHONNOUSERSITE=1
export GI_TYPELIB_PATH=$GI_TYPELIB_DETECTED
PYWHISPERCPP_LIBRARY_PATH=""
PY_SITE_PATHS=\$("$VENV_DIR/bin/python" - <<'PY' 2>/dev/null
import sysconfig

paths = []
for key in ("platlib", "purelib"):
    path = sysconfig.get_paths().get(key)
    if path and path not in paths:
        paths.append(path)
print(" ".join(paths))
PY
)
for PY_SITE in \$PY_SITE_PATHS; do
    for PY_LIB_DIR in "\$PY_SITE/pywhispercpp.libs" "\$PY_SITE/pywhispercpp/.libs" "\$PY_SITE/pywhispercpp/lib"; do
        if [ -d "\$PY_LIB_DIR" ] && { ls "\$PY_LIB_DIR"/libwhisper*.so* >/dev/null 2>&1 || ls "\$PY_LIB_DIR"/libggml*.so* >/dev/null 2>&1; }; then
            if [ -z "\$PYWHISPERCPP_LIBRARY_PATH" ]; then
                PYWHISPERCPP_LIBRARY_PATH="\$PY_LIB_DIR"
            else
                PYWHISPERCPP_LIBRARY_PATH="\$PYWHISPERCPP_LIBRARY_PATH:\$PY_LIB_DIR"
            fi
        fi
    done
done
if [ -n "\$PYWHISPERCPP_LIBRARY_PATH" ]; then
    export LD_LIBRARY_PATH="\$PYWHISPERCPP_LIBRARY_PATH\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
fi

EXEC_CMD="$VENV_DIR/bin/vocalinux \$*"
$SG_CHECK
WRAPPER_EOF
        chmod +x "$HOME/.local/bin/vocalinux"
        print_info "Created wrapper: ~/.local/bin/vocalinux"

        # Create vocalinux-gui wrapper script
        cat > "$HOME/.local/bin/vocalinux-gui" << WRAPPER_EOF
#!/bin/bash
# Wrapper script for Vocalinux GUI that sets required environment variables
# and applies the 'input' group for keyboard shortcuts on Wayland
export PYTHONNOUSERSITE=1
export GI_TYPELIB_PATH=$GI_TYPELIB_DETECTED
PYWHISPERCPP_LIBRARY_PATH=""
PY_SITE_PATHS=\$("$VENV_DIR/bin/python" - <<'PY' 2>/dev/null
import sysconfig

paths = []
for key in ("platlib", "purelib"):
    path = sysconfig.get_paths().get(key)
    if path and path not in paths:
        paths.append(path)
print(" ".join(paths))
PY
)
for PY_SITE in \$PY_SITE_PATHS; do
    for PY_LIB_DIR in "\$PY_SITE/pywhispercpp.libs" "\$PY_SITE/pywhispercpp/.libs" "\$PY_SITE/pywhispercpp/lib"; do
        if [ -d "\$PY_LIB_DIR" ] && { ls "\$PY_LIB_DIR"/libwhisper*.so* >/dev/null 2>&1 || ls "\$PY_LIB_DIR"/libggml*.so* >/dev/null 2>&1; }; then
            if [ -z "\$PYWHISPERCPP_LIBRARY_PATH" ]; then
                PYWHISPERCPP_LIBRARY_PATH="\$PY_LIB_DIR"
            else
                PYWHISPERCPP_LIBRARY_PATH="\$PYWHISPERCPP_LIBRARY_PATH:\$PY_LIB_DIR"
            fi
        fi
    done
done
if [ -n "\$PYWHISPERCPP_LIBRARY_PATH" ]; then
    export LD_LIBRARY_PATH="\$PYWHISPERCPP_LIBRARY_PATH\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
fi

EXEC_CMD="$VENV_DIR/bin/vocalinux-gui \$*"
$SG_CHECK
WRAPPER_EOF
        chmod +x "$HOME/.local/bin/vocalinux-gui"
        print_info "Created wrapper: ~/.local/bin/vocalinux-gui"

        # Check if ~/.local/bin is in PATH
        if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
            print_warning "~/.local/bin is not in your PATH"
            print_info "Add this line to your ~/.bashrc or ~/.zshrc:"
            print_info '  export PATH="$HOME/.local/bin:$PATH"'
        fi

        return 0
    else
        print_error "Vocalinux package installation verification failed."
        print_error "Check the pip log for details: $PIP_LOG_FILE"
        return 1
    fi
}

# Install Python package
if ! install_python_package; then
    print_error "Failed to install Vocalinux package. Installation cannot continue."
    exit "$EXIT_NETWORK"
fi

# ---------------------------------------------------------------------------
# Install desktop entry
install_desktop_entry || print_warning "Desktop entry installation failed"

# Install icons
install_icons || print_warning "Icon installation failed"

# Install resources to venv for runtime discovery
install_resources_to_venv || print_warning "Venv resource installation failed"

# Install models based on selected engine
# whisper.cpp is now the default engine
if [ "$SKIP_MODELS" = "no" ]; then
    # Once, rather than once per engine.
    if ! model_verification_available; then
        print_warning "This release pins no model checksums, so the installer cannot verify"
        print_warning "model downloads. The application will download and verify them on"
        print_warning "first run instead."
        print_warning "(The installer is newer than ${INSTALL_TAG:-the checked-out revision}.)"
    fi

    # Check which engines are installed and download appropriate models

    # Install whisper.cpp model (default engine)
    if is_pywhispercpp_installed; then
        if model_verification_available; then
            print_info "whisper.cpp is installed - downloading tiny model (default engine)..."
            install_whispercpp_model || print_warning "whisper.cpp model download failed - model will be downloaded on first run"
        else
            print_info "Leaving the whisper.cpp model to the first application run."
        fi
    fi

    # Needs no manifest: the sha256 is a path segment of its own URL.
    if "$VENV_DIR/bin/python" -c "import whisper" 2>/dev/null; then
        print_info "Whisper (OpenAI) is installed - downloading tiny model..."
        install_whisper_model || print_warning "Whisper model download failed - model will be downloaded on first run"
    fi
else
    print_info "Skipping model downloads (--skip-models specified)"
    print_info "Models will be downloaded automatically on first application run"
fi

# Install VOSK models (always useful as fallback)
if [ "$SKIP_MODELS" = "no" ]; then
    if model_verification_available; then
        install_vosk_models || print_warning "VOSK model installation failed - models will be downloaded on first run"
    else
        print_info "Leaving the VOSK model to the first application run."
    fi
else
    print_info "Skipping VOSK model installation (--skip-models specified)"
    print_info "Models will be downloaded automatically on first application run"
fi

# config.json survives reinstalls, so an engine picked by an earlier attempt
# can outlive the venv that supported it. Repair it here instead of letting the
# app die at startup with ModuleNotFoundError. Prefer SELECTED_ENGINE when that
# extra is importable (the whisper.cpp -> vosk fallback), then any working extra.
verify_configured_engine() {
    local CONFIG_FILE="$CONFIG_DIR/config.json"
    [ -f "$CONFIG_FILE" ] || return 0

    local CONFIGURED_ENGINE
    CONFIGURED_ENGINE=$("$VENV_DIR/bin/python" - "$CONFIG_FILE" <<'PY' 2>/dev/null || true
import json
import sys

try:
    with open(sys.argv[1]) as handle:
        print(json.load(handle).get("speech_recognition", {}).get("engine", ""))
except Exception:
    pass
PY
)

    local MODULE
    MODULE=$(engine_import_module "$CONFIGURED_ENGINE")
    # remote_api and anything unrecognised need no extra module.
    [ -n "$MODULE" ] || return 0
    venv_can_import "$MODULE" && return 0

    print_warning "$CONFIG_FILE selects the $CONFIGURED_ENGINE engine, but it is not importable in $VENV_DIR."

    # Leaving it means the app dies at startup with ModuleNotFoundError. Prefer
    # SELECTED_ENGINE (set by the whisper.cpp -> vosk fallback), then any extra
    # the venv can actually import.
    local CANDIDATE MODULE_FOR_CANDIDATE TRIED=""
    for CANDIDATE in ${SELECTED_ENGINE:+$SELECTED_ENGINE} whisper_cpp vosk whisper; do
        [ "$CANDIDATE" != "$CONFIGURED_ENGINE" ] || continue
        case " $TRIED " in
            *" $CANDIDATE "*) continue ;;
        esac
        TRIED="$TRIED $CANDIDATE"
        MODULE_FOR_CANDIDATE=$(engine_import_module "$CANDIDATE")
        [ -n "$MODULE_FOR_CANDIDATE" ] || continue
        venv_can_import "$MODULE_FOR_CANDIDATE" || continue
        if set_configured_engine "$CONFIG_FILE" "$CANDIDATE"; then
            print_success "Switched $CONFIG_FILE to the $CANDIDATE engine."
            print_info "Reinstall $(engine_pip_name "$CONFIGURED_ENGINE") and switch back in Settings if you want it."
            return 0
        fi
    done

    print_error "Vocalinux cannot start with this configuration and no working engine is available."
    print_error "Install the engine:  $VENV_DIR/bin/pip install $(engine_pip_name "$CONFIGURED_ENGINE")"
    print_error "or edit $CONFIG_FILE and set speech_recognition.engine to an installed engine."
    return 1
}

if ! verify_configured_engine; then
    exit "$EXIT_MISSING_DEPS"
fi

# Update icon cache
update_icon_cache

# Function to run tests with better error handling
run_tests() {
    print_info "Running tests..."

    # Check if pytest is installed in the virtual environment
    if ! "$VENV_DIR/bin/python" -c "import pytest" &>/dev/null; then
        print_info "Installing pytest and related packages..."
        local PIP_LOG_FILE="$VOCALINUX_TMP_DIR/test-deps.log"
        pip_install_extras_skip_pygobject "$PIP_LOG_FILE" dev || {
            print_error "Failed to install pytest. Cannot run tests."
            return 1
        }
    fi

    # Create a directory for test results
    local TEST_RESULTS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux/test_results"
    mkdir -p "$TEST_RESULTS_DIR"
    local TEST_RESULTS_FILE="$TEST_RESULTS_DIR/pytest_$(date +%Y%m%d_%H%M%S).xml"

    print_info "Running tests with pytest..."
    print_info "This may take a few minutes..."

    # Run the tests with pytest and capture output
    local TEST_OUTPUT_FILE=$(mktemp)
    if pytest -v --junitxml="$TEST_RESULTS_FILE" | tee "$TEST_OUTPUT_FILE"; then
        print_success "All tests passed!"
        print_info "Test results saved to: $TEST_RESULTS_FILE"
        rm -f "$TEST_OUTPUT_FILE"
        return 0
    else
        local FAILED_COUNT=$(grep -c "FAILED" "$TEST_OUTPUT_FILE")
        print_error "$FAILED_COUNT tests failed!"
        print_info "Test results saved to: $TEST_RESULTS_FILE"
        print_info "Check the test output for details."
        rm -f "$TEST_OUTPUT_FILE"
        return 1
    fi
}

# Run tests if requested
if [[ "$RUN_TESTS" == "yes" ]]; then
    if run_tests; then
        print_success "Test suite completed successfully."
    else
        print_warning "Test suite completed with failures."
        print_warning "You can still use the application, but some features might not work as expected."
    fi
fi

# Function to verify the installation
verify_installation() {
    print_info "Verifying installation..."
    local ISSUES=0

    # Check if virtual environment exists and is activated
    if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/activate" ]; then
        print_error "Virtual environment not found or incomplete."
        ISSUES=$((ISSUES + 1))
    fi

    # Check if vocalinux command is available
    if ! command -v vocalinux &>/dev/null && [ ! -f "$VENV_DIR/bin/vocalinux" ]; then
        print_error "Vocalinux command not found."
        ISSUES=$((ISSUES + 1))
    fi

    # Check if desktop entry is installed
    if [ ! -f "$DESKTOP_DIR/vocalinux.desktop" ]; then
        print_warning "Desktop entry not found. Application may not appear in application menu."
        ISSUES=$((ISSUES + 1))
    fi

    # Check if icons are installed
    local ICON_COUNT=0
    for icon in vocalinux.svg vocalinux-microphone.svg vocalinux-microphone-off.svg vocalinux-microphone-process.svg; do
        if [ -f "$ICON_DIR/$icon" ]; then
            ICON_COUNT=$((ICON_COUNT + 1))
        fi
    done

    if [ "$ICON_COUNT" -lt 4 ]; then
        print_warning "Some icons are missing. Application may not display correctly."
        ISSUES=$((ISSUES + 1))
    fi

    # Check if Python package is importable using venv python
    if ! "$VENV_DIR/bin/python" -c "import vocalinux" &>/dev/null; then
        print_error "Vocalinux Python package cannot be imported."
        ISSUES=$((ISSUES + 1))
    fi

    # Smoke-test the selected speech engine's native library at install time so that
    # "installed but does not run" failures (e.g. libwhisper.so.1 not found on Debian)
    # are surfaced here with actionable guidance rather than silently at first launch.
    local selected_engine="${SELECTED_ENGINE:-whisper_cpp}"
    if [[ "$selected_engine" == "whisper_cpp" ]]; then
        if ! is_pywhispercpp_installed; then
            print_error "pywhispercpp (whisper.cpp engine) installed but cannot be imported at runtime."
            print_error "This usually means libwhisper.so.1 is missing or not on the library path."
            print_error ""
            print_error "Diagnostic steps:"
            print_error "  1. Check for unresolved symbols:"
            print_error "     ldd \$(find $VENV_DIR -name '*.so' -path '*/pywhispercpp*' 2>/dev/null | head -1) 2>/dev/null | grep 'not found'"
            print_error "  2. Re-run the installer with: --rebuild-whispercpp"
            print_error "  3. Or switch to VOSK (no native build needed): --engine=vosk"
            ISSUES=$((ISSUES + 1))
        else
            print_success "pywhispercpp (whisper.cpp) import verified successfully."
        fi
    fi

    if [[ "$selected_engine" == "faster_whisper" ]]; then
        if ! "$VENV_DIR/bin/python" -c "import faster_whisper" 2>/dev/null; then
            print_error "faster-whisper package installed but cannot be imported at runtime."
            print_error ""
            print_error "Diagnostic steps:"
            print_error "  1. Check pip installation: $VENV_DIR/bin/pip show faster-whisper"
            print_error "  2. Re-run the installer with: --engine=faster_whisper"
            print_error "  3. Or switch to whisper.cpp: --engine=whisper_cpp"
            ISSUES=$((ISSUES + 1))
        else
            print_success "faster-whisper import verified successfully."
        fi
    fi

    # Return the number of issues found
    return $ISSUES
}

# Function to print beautiful welcome message
print_welcome_message() {
    local ISSUES=$1

    # ASCII art header
    cat << 'EOF'

  ▗▖  ▗▖ ▗▄▖  ▗▄▄▖ ▗▄▖ ▗▖   ▗▄▄▄▖▗▖  ▗▖▗▖ ▗▖▗▖  ▗▖
  ▐▌  ▐▌▐▌ ▐▌▐▌   ▐▌ ▐▌▐▌     █  ▐▛▚▖▐▌▐▌ ▐▌ ▝▚▞▘
  ▐▌  ▐▌▐▌ ▐▌▐▌   ▐▛▀▜▌▐▌     █  ▐▌ ▝▜▌▐▌ ▐▌  ▐▌
   ▝▚▞▘ ▝▚▄▞▘▝▚▄▄▖▐▌ ▐▌▐▙▄▄▖▗▄█▄▖▐▌  ▐▌▝▚▄▞▘▗▞▘▝▚▖

                     ✓ Installation Complete!

EOF

    # Success or warning message
    if [ "$ISSUES" -eq 0 ]; then
        print_success "Vocalinux has been installed successfully!"
    else
        print_warning "Installation complete with $ISSUES minor issue(s)"
        print_warning "The application should still work normally."
    fi

    # Get engine info for display
    local ENGINE_INFO="${SELECTED_ENGINE:-whisper_cpp}"
    local ENGINE_DISPLAY_NAME=""
    local BACKEND_INFO=""

    case "$ENGINE_INFO" in
        whisper_cpp)
            ENGINE_DISPLAY_NAME="Whisper.cpp"
            if [[ "${WHISPERCPP_BACKEND}" == "gpu" ]]; then
                BACKEND_INFO="GPU Accelerated"
            else
                BACKEND_INFO="CPU"
            fi
            ;;
        whisper)
            ENGINE_DISPLAY_NAME="Whisper (OpenAI)"
            BACKEND_INFO="PyTorch/CUDA"
            ;;
        vosk)
            ENGINE_DISPLAY_NAME="VOSK"
            BACKEND_INFO="Lightweight"
            ;;
        parakeet)
            ENGINE_DISPLAY_NAME="Parakeet"
            BACKEND_INFO="CPU"
            ;;
        faster_whisper)
            ENGINE_DISPLAY_NAME="Faster-Whisper"
            BACKEND_INFO="PyTorch/CTranslate2"
            ;;
        remote_api)
            ENGINE_DISPLAY_NAME="Remote API"
            BACKEND_INFO="Network (offloaded to remote server)"
            ;;
    esac

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  📦 What Was Installed"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "  Application:    Vocalinux (voice dictation for Linux)"
    echo "  Engine:         $ENGINE_DISPLAY_NAME"
    if [[ -n "$BACKEND_INFO" ]]; then
        echo "  Backend:        $BACKEND_INFO"
    fi
    echo "  Location:       ${INSTALL_DIR:-\$HOME/.local/share/vocalinux}"
    echo "  Virtual Env:    $VENV_DIR"
    echo "  Config:         $CONFIG_DIR"
    echo ""

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🚀 Getting Started"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "1. Launch Vocalinux"
    echo "   • From app menu: Look for 'Vocalinux'"
    echo "   • From terminal: Run 'vocalinux' command"
    echo ""
    echo "2. Find the icon in your system tray (top bar)"
    echo "   • Click for settings and status"
    echo "   • Right-click for menu options"
    echo ""
    echo "3. Start dictating!"
    echo -e "   \e[1mHold Right Alt\e[0m while you speak, then release to transcribe"
    echo -e "   (push-to-talk default; double-tap \e[1mRight Alt\e[0m in toggle mode)"
    echo ""

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🎤 Testing Your Setup"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "1. Open any text editor (gedit, VS Code, LibreOffice, etc.)"
    echo "2. Hold Right Alt, say: 'Hello world period', then release"
    echo "3. You should see: 'Hello world.'"
    echo ""
    echo "💡 Voice commands: 'period' 'comma' 'new line' 'delete that'"
    echo ""

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  🔧 Managing Vocalinux"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Commands:"
    echo "  vocalinux              Start the application"
    echo "  vocalinux --debug      Start with debug logging"
    echo "  vocalinux-gui          Open settings GUI"
    echo ""
    echo "To activate the virtual environment:"
    echo "  source ${ACTIVATION_SCRIPT:-activate-vocalinux.sh}"
    echo ""
    echo "To uninstall:"
    echo "  ./uninstall.sh"
    echo ""

    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  📚 Need Help?"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "• Issues & Bugs:  https://github.com/VocaHQ/vocalinux/issues"
    echo "• Documentation:  https://github.com/VocaHQ/vocalinux"
    echo "• Star on GitHub: ⭐ https://github.com/VocaHQ/vocalinux"
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo -e "  \e[1m\e[32m✨ Happy Dictating! ✨\e[0m"
    echo ""

    # Installation details (optional, for debugging)
    if [[ "${VERBOSE:-no}" == "yes" ]]; then
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "  🔍 Installation Details (Debug Mode)"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "Virtual environment: $VENV_DIR"
        echo "Desktop entry: $DESKTOP_DIR/vocalinux.desktop"
        echo "Configuration: $CONFIG_DIR"
        echo "Data directory: $DATA_DIR"
        echo "Wrapper script: $HOME/.local/bin/vocalinux"
        echo ""
    fi
}

# Verify the installation
# (guarded: verify_installation returns the number of issues found, which
# would otherwise abort the script under set -e before the summary prints)
INSTALL_ISSUES=0
verify_installation || INSTALL_ISSUES=$?

# Print welcome message
print_welcome_message $INSTALL_ISSUES

print_success "Installation process completed!"
