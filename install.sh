#!/bin/bash
# Vocalinux Installer
# This script installs the Vocalinux application and its dependencies

# -E: ERR trap propagates into functions/subshells
# -e: exit on unhandled command failure   -u: error on unset variables
# -o pipefail: a pipeline fails if any stage fails
set -Eeuo pipefail

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

print_error() {
    echo -e "\e[1;31m[ERROR]\e[0m $1"
}

print_warning() {
    echo -e "\e[1;33m[WARNING]\e[0m $1"
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
            echo "  --engine=NAME    Speech engine: whisper_cpp (default), whisper, vosk, remote_api"
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
CLEANUP_ON_EXIT="no"

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

    # When running remotely, install venv to user's home directory
    VENV_DIR="$HOME/.local/share/vocalinux/venv"
fi

# Change to install directory
cd "$INSTALL_DIR"

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

# Detect Vulkan support for whisper.cpp
detect_vulkan() {
    # Check for vulkaninfo command
    if command -v vulkaninfo >/dev/null 2>&1; then
        # (|| true guards against pipefail aborts: head closes the pipe early
        # and grep exits 1 when there is no match)
        local vulkan_output
        vulkan_output=$(vulkaninfo --summary 2>/dev/null | head -20 || true)
        if [ -n "$vulkan_output" ]; then
            HAS_VULKAN="yes"
            # Try to extract GPU name
            VULKAN_DEVICE=$(echo "$vulkan_output" | grep -i "deviceName" | head -1 | cut -d'=' -f2 | xargs || true)
            if [ -z "$VULKAN_DEVICE" ]; then
                VULKAN_DEVICE="Vulkan-compatible GPU"
            fi
            return 0
        fi
    fi
    HAS_VULKAN="no"
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

    # Software renderers and virtual devices to skip (not real hardware GPUs)
    # These are CPU-based implementations that shouldn't affect compatibility detection
    local SOFTWARE_RENDERER_PATTERNS=(
        "llvmpipe"
        "swiftshader"
        "lavapipe"
        "zink"
        "virtio"
        "venus"
    )

    # Check if vulkaninfo is available
    if ! command -v vulkaninfo >/dev/null 2>&1; then
        echo "unknown:vulkaninfo not available"
        return 1
    fi

    # Get all device names from vulkaninfo
    local DEVICE_NAMES_RAW
    DEVICE_NAMES_RAW=$(vulkaninfo --summary 2>/dev/null | awk -F'=' '/deviceName/ {gsub(/^[ \t]+|[ \t]+$/, "", $2); if ($2 != "") print $2}' || true)

    # Separate hardware GPUs from software renderers
    local HARDWARE_GPUS=""
    local HARDWARE_GPU_COUNT=0
    while IFS= read -r device_name; do
        [ -z "$device_name" ] && continue

        local is_software=false
        for pattern in "${SOFTWARE_RENDERER_PATTERNS[@]}"; do
            if echo "$device_name" | grep -iq "$pattern"; then
                is_software=true
                break
            fi
        done

        if [ "$is_software" = false ]; then
            if [ -n "$HARDWARE_GPUS" ]; then
                HARDWARE_GPUS="${HARDWARE_GPUS}, ${device_name}"
            else
                HARDWARE_GPUS="$device_name"
            fi
            ((HARDWARE_GPU_COUNT++))
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
    FEATURES_OUTPUT=$(vulkaninfo --features 2>/dev/null)

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

        # Skip software renderers
        local is_software=false
        for pattern in "${SOFTWARE_RENDERER_PATTERNS[@]}"; do
            if echo "$device_name" | grep -iq "$pattern"; then
                is_software=true
                break
            fi
        done
        [ "$is_software" = true ] && continue

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
        COMPAT_RESULT=$(check_vulkan_gpu_compatibility)
        VULKAN_COMPATIBLE=$(echo "$COMPAT_RESULT" | cut -d':' -f1)
        VULKAN_COMPAT_REASON=$(echo "$COMPAT_RESULT" | cut -d':' -f2-)
    elif [[ "$HAS_NVIDIA_GPU" == "yes" ]]; then
        # NVIDIA GPUs use CUDA, so Vulkan compatibility is irrelevant
        VULKAN_COMPATIBLE="not_applicable"
        VULKAN_COMPAT_REASON="NVIDIA GPU uses CUDA"
    fi

    # Determine recommendation (Priority: CUDA > Vulkan > CPU)
    # IMPORTANT: The installer WILL install dev libraries (libvulkan-dev, glslc, CUDA) later,
    # so we recommend GPU if there's a compatible GPU regardless of current library status.
    local RECOMMENDED_BACKEND="cpu"
    local RECOMMENDED_REASON=""
    local CAN_BUILD_GPU=false

    # NVIDIA GPU - best option, uses CUDA
    if [[ "$HAS_NVIDIA_GPU" == "yes" ]]; then
        RECOMMENDED_BACKEND="cuda"
        if [[ "$HAS_CUDA_DEV" == "true" ]]; then
            RECOMMENDED_REASON="NVIDIA GPU with CUDA toolkit installed"
        else
            RECOMMENDED_REASON="NVIDIA GPU detected (CUDA toolkit will be installed)"
        fi
        CAN_BUILD_GPU=true
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

# Print section header for interactive mode
clear_screen() {
    if [ -t 1 ] && command -v clear >/dev/null 2>&1 && [ -n "${TERM:-}" ]; then
        clear >/dev/null 2>&1 || true
    fi
}

print_header() {
    local title="$1"
    echo ""
    echo "============================================================"
    echo "  $title"
    echo "============================================================"
}

# Function to run interactive guided installation
run_interactive_install() {
    clear_screen
    cat << "EOF"

                 Interactive Installation Guide
                 ===============================

EOF

    echo "Welcome! This guided installation will help you set up Vocalinux"
    echo "with the best options for your system."
    echo ""
    echo "All speech engines are 100% offline, local, and private."
    echo "Your voice data never leaves your computer."
    echo ""

    # Step 1: Detect and display system info
    print_header "Step 1: Your System"
    echo "Detected: $DISTRO_NAME $DISTRO_VERSION"

    # Get hardware recommendation
    local RECOMMENDATION=$(get_engine_recommendation)
    local RECOMMENDED_ENGINE=$(echo "$RECOMMENDATION" | cut -d':' -f1)
    local RECOMMENDED_ICON=$(echo "$RECOMMENDATION" | cut -d':' -f2)
    local RECOMMENDED_REASON=$(echo "$RECOMMENDATION" | cut -d':' -f3-)

    echo "Hardware: $RECOMMENDED_REASON"
    echo ""

    # Step 2: Choose speech recognition engine
    print_header "Step 2: Choose Speech Recognition Engine"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  1. WHISPER.CPP  * RECOMMENDED                              │"
    echo "  │     • Fastest, most accurate, works with any GPU            │"
    echo "  │     • Supports NVIDIA (CUDA), AMD, Intel (Vulkan)           │"
    echo "  │     • CPU-only mode available for older systems             │"
    echo "  │     • Models: tiny (39MB) to large (1.5GB)                  │"
    echo "  │     • 99+ languages with auto-detection                     │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  2. WHISPER (OpenAI)                                        │"
    echo "  │     • PyTorch-based, high accuracy                          │"
    echo "  │     • Only supports NVIDIA GPUs (CUDA)                      │"
    echo "  │     • Larger download (~2GB with CUDA)                      │"
    echo "  │     • Good for development/research                         │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  ┌─────────────────────────────────────────────────────────────┐"
    echo "  │  3. VOSK                                                    │"
    echo "  │     • Lightweight and fast                                  │"
    echo "  │     • Works on older/low-RAM systems                        │"
    echo "  │     • ~40MB download                                        │"
    echo "  │     • Good for basic dictation needs                        │"
    echo "  └─────────────────────────────────────────────────────────────┘"
    echo ""
    echo "  ┌───────────────────────────────────────────────────────────────┐"
    echo "  │  4. REMOTE API (ADVANCED)                                     │"
    echo "  │     • Offload processing to a GPU server on your network      │"
    echo "  │     • Ideal for laptops without GPU                           │"
    echo "  │     • Supports whisper.cpp server & OpenAI-compatible APIs    │"
    echo "  │     • Minimal local resources needed                          │"
    echo "  │     • Requires a remote server to be running                  │"
    echo "  └───────────────────────────────────────────────────────────────┘"
    echo ""

    # Show recommendation
    case "$RECOMMENDED_ENGINE" in
        whisper_cpp)
            echo "  → Recommendation: whisper.cpp (best performance for your hardware)"
            DEFAULT_CHOICE="1"
            ;;
        vosk)
            echo "  → Recommendation: VOSK (lightweight option for your system)"
            DEFAULT_CHOICE="3"
            ;;
        *)
            echo "  → Recommendation: whisper.cpp (best overall experience)"
            DEFAULT_CHOICE="1"
            ;;
    esac
    echo ""

    read -p "Choose engine [1-4] (default: $DEFAULT_CHOICE): " ENGINE_CHOICE
    ENGINE_CHOICE=${ENGINE_CHOICE:-$DEFAULT_CHOICE}

    case "$ENGINE_CHOICE" in
        1)
            SELECTED_ENGINE="whisper_cpp"
            ENGINE_DISPLAY="Whisper.cpp (Recommended)"
            ;;
        2)
            SELECTED_ENGINE="whisper"
            ENGINE_DISPLAY="Whisper (OpenAI)"
            ;;
        3)
            SELECTED_ENGINE="vosk"
            ENGINE_DISPLAY="VOSK (Lightweight)"
            ;;
        4)
            SELECTED_ENGINE="remote_api"
            ENGINE_DISPLAY="Remote API"
            ;;
        *)
            SELECTED_ENGINE="whisper_cpp"
            ENGINE_DISPLAY="Whisper.cpp (Recommended)"
            ;;
    esac

    # Step 3: Whisper.cpp backend selection (if whisper.cpp chosen)
    if [[ "$SELECTED_ENGINE" == "whisper_cpp" ]]; then
        print_header "Step 3: Choose Whisper.cpp Backend"
        echo ""

        # Detect available backends
        local BACKEND_INFO=$(detect_whispercpp_backends)
        local RECOMMENDED_BACKEND=$(echo "$BACKEND_INFO" | cut -d':' -f1)
        local RECOMMENDED_REASON=$(echo "$BACKEND_INFO" | cut -d':' -f2)
        local CAN_BUILD_GPU=$(echo "$BACKEND_INFO" | cut -d':' -f3)
        local HAS_VULKAN=$(echo "$BACKEND_INFO" | cut -d':' -f4)
        local HAS_NVIDIA=$(echo "$BACKEND_INFO" | cut -d':' -f5)
        local HAS_VULKAN_DEV=$(echo "$BACKEND_INFO" | cut -d':' -f6)
        local HAS_CUDA_DEV=$(echo "$BACKEND_INFO" | cut -d':' -f7)
        local VULKAN_COMPAT=$(echo "$BACKEND_INFO" | cut -d':' -f8)
        local VULKAN_COMPAT_REASON=$(echo "$BACKEND_INFO" | cut -d':' -f9)

        # Show warning for incompatible GPUs
        if [[ "$VULKAN_COMPAT" == "incompatible" ]]; then
            echo ""
            print_warning "═══════════════════════════════════════════════════════════════"
            print_warning "  ⚠️  INCOMPATIBLE GPU DETECTED"
            print_warning "═══════════════════════════════════════════════════════════════"
            print_warning ""
            print_warning "  Your GPU: $VULKAN_COMPAT_REASON"
            print_warning ""
            print_warning "  This Intel GPU lacks VK_KHR_16bit_storage support, which is"
            print_warning "  required for whisper.cpp Vulkan acceleration."
            print_warning ""
            print_warning "  The CPU backend will be used instead, which is still fast!"
            print_warning ""
            print_warning "═══════════════════════════════════════════════════════════════"
            echo ""
        fi

        echo "Whisper.cpp can use different backends for speech recognition:"
        echo ""

        if [[ "$CAN_BUILD_GPU" == "true" ]]; then
            echo "  ┌─────────────────────────────────────────────────────────────┐"
            echo "  │  1. GPU (Vulkan/CUDA)  * RECOMMENDED                        │"
            echo "  │     • Fastest performance with GPU acceleration             │"
            echo "  │     • $RECOMMENDED_REASON                                   │"
            echo "  │     • Requires building from source (takes ~2-5 min)        │"
            echo "  └─────────────────────────────────────────────────────────────┘"
            echo ""
            echo "  ┌─────────────────────────────────────────────────────────────┐"
            echo "  │  2. CPU (Pre-built)                                         │"
            echo "  │     • Works on all systems                                  │"
            echo "  │     • Faster installation (no compilation)                  │"
            echo "  │     • Good performance on modern CPUs                       │"
            echo "  └─────────────────────────────────────────────────────────────┘"
            echo ""
            echo "  → Recommendation: GPU backend for best performance"
            local DEFAULT_BACKEND="1"
        else
            echo "  ┌─────────────────────────────────────────────────────────────┐"
            echo "  │  1. GPU (Vulkan/CUDA)                                       │"
            echo "  │     • ⚠️  GPU libraries not detected                        │"
            echo "  │     • Requires: libvulkan-dev, glslc/glslang-tools (Vulkan) │"
            echo "  │              or: CUDA toolkit (NVIDIA)                      │"
            echo "  └─────────────────────────────────────────────────────────────┘"
            echo ""
            echo "  ┌─────────────────────────────────────────────────────────────┐"
            echo "  │  2. CPU (Pre-built)  * RECOMMENDED                          │"
            echo "  │     • Works on all systems                                  │"
            echo "  │     • Fast installation (no compilation)                    │"
            echo "  │     • Good performance on modern CPUs                       │"
            echo "  └─────────────────────────────────────────────────────────────┘"
            echo ""

            if [[ "$HAS_VULKAN" == "yes" && "$HAS_VULKAN_DEV" != "true" ]]; then
                echo "  💡 Tip: Install 'libvulkan-dev' and a shader compiler for GPU support:"
                echo "     sudo apt install libvulkan-dev glslc 2>/dev/null || sudo apt install libvulkan-dev glslang-tools"
                echo ""
            elif [[ "$HAS_NVIDIA" == "yes" && "$HAS_CUDA_DEV" != "true" ]]; then
                echo "  💡 Tip: Install CUDA toolkit for NVIDIA GPU support:"
                echo "     https://developer.nvidia.com/cuda-downloads"
                echo ""
            fi

            echo "  → Recommendation: CPU backend (GPU libraries not detected)"
            local DEFAULT_BACKEND="2"
        fi

        read -p "Choose backend [1-2] (default: $DEFAULT_BACKEND): " BACKEND_CHOICE
        BACKEND_CHOICE=${BACKEND_CHOICE:-$DEFAULT_BACKEND}

        if [[ "$BACKEND_CHOICE" == "1" ]]; then
            WHISPERCPP_BACKEND="gpu"
            BACKEND_DISPLAY="GPU (Vulkan/CUDA)"
        else
            WHISPERCPP_BACKEND="cpu"
            BACKEND_DISPLAY="CPU (Pre-built)"
        fi

        echo ""
    fi

    # Step 3 for Remote API: Configure server URL
    if [[ "$SELECTED_ENGINE" == "remote_api" ]]; then
        print_header "Step 3: Configure Remote Server"
        echo ""
        print_info "You need a speech recognition server running on your local network."
        echo ""
        echo "  Supported servers:"
        echo "    • whisper.cpp server:  ./server -m model.bin --host 0.0.0.0 --port 8080"
        echo "    • LocalAI:            docker run -p 8080:8080 localai/localai"
        echo "    • Faster Whisper:      faster-whisper-server --host 0.0.0.0 --port 8080"
        echo "    • Any OpenAI-compatible speech API"
        echo ""
        read -p "Enter remote server URL (or leave blank to set later): " REMOTE_API_URL_INPUT
        if [ -n "$REMOTE_API_URL_INPUT" ]; then
            REMOTE_API_URL="$REMOTE_API_URL_INPUT"
            REMOTE_DISPLAY="$REMOTE_API_URL"
        else
            REMOTE_API_URL=""
            REMOTE_DISPLAY="(configure later in Settings)"
        fi
        echo ""
    fi

    # Step 4: Model download preference (skip for remote_api)
    if [[ "$SELECTED_ENGINE" != "remote_api" ]]; then
    print_header "Step 4: Model Download"
    echo ""
    echo "Speech recognition models can be downloaded now or later."
    echo ""
    echo "  1. Download now (recommended)"
    echo "     • Faster first run - ready to use immediately"
    echo "     • Offline capable right after install"
    echo ""
    echo "  2. Download later"
    echo "     • Smaller initial install"
    echo "     • Models download automatically on first use"
    echo ""

    read -p "Download models now? [1-2] (default: 1): " MODELS_CHOICE
    MODELS_CHOICE=${MODELS_CHOICE:-1}

    if [[ "$MODELS_CHOICE" == "2" ]]; then
        SKIP_MODELS="yes"
        MODELS_DISPLAY="Download on first use"
    else
        MODELS_DISPLAY="Download now (recommended)"
    fi
    else
        # Remote API: No need to download model
        SKIP_MODELS="yes"
        MODELS_DISPLAY="Not needed (remote processing)"
    fi

    # Summary
    print_header "Installation Summary"
    echo ""
    echo "  Speech Engine: $ENGINE_DISPLAY"
    if [[ "$SELECTED_ENGINE" == "whisper_cpp" ]]; then
        echo "  Backend: ${BACKEND_DISPLAY:-CPU (Pre-built)}"
        if [[ "${WHISPERCPP_BACKEND}" == "gpu" ]]; then
            echo "  Note: GPU build will compile from source (2-5 minutes)"
        fi
    fi
    if [[ "$SELECTED_ENGINE" == "remote_api" ]]; then
        echo "  Remote Server: $REMOTE_DISPLAY"
    fi
    echo "  Models: $MODELS_DISPLAY"
    echo "  Install Location: ${INSTALL_DIR:-\$HOME/.local/share/vocalinux}"
    echo ""
    read -p "Press Enter to continue with installation, or Ctrl+C to cancel..."
    echo ""
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
    # Default to whisper.cpp for best performance
    SELECTED_ENGINE="whisper_cpp"
    print_info "Automatic mode: Installing with whisper.cpp (default engine)"
    print_info "For other engines, use: --engine=whisper or --engine=vosk or --engine=remote_api"
    echo ""
fi

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check if a package is installed (for apt-based systems)
apt_package_installed() {
    dpkg -s "$1" >/dev/null 2>&1
}

# Function to check if a package is installed (for dnf-based systems)
dnf_package_installed() {
    rpm -q "$1" >/dev/null 2>&1
}

# Function to check if a package is installed (for pacman-based systems)
pacman_package_installed() {
    pacman -Q "$1" >/dev/null 2>&1
}

# Install an AppIndicator/StatusNotifierItem provider, preferring the
# actively maintained Ayatana fork over the legacy Canonical package
# (unmaintained since ~2013). The legacy package can install and import
# without error yet silently fail to register a tray icon with KDE's
# StatusNotifierWatcher, leaving no icon and no logged error. $1 is the
# package-manager install command (e.g. "sudo dnf install -y"), $2/$3 are
# the Ayatana/legacy package names for that package manager, $4 is the
# "is this package installed" checker function name.
install_preferred_appindicator() {
    local install_cmd="$1"
    local ayatana_pkg="$2"
    local legacy_pkg="$3"
    local checker="$4"

    if "$checker" "$ayatana_pkg"; then
        return 0
    fi

    if $install_cmd "$ayatana_pkg" 2>/dev/null; then
        print_info "Installed $ayatana_pkg (Ayatana AppIndicator; required for a working KDE tray icon)"
        return 0
    fi

    if "$checker" "$legacy_pkg"; then
        print_info "$ayatana_pkg not available; $legacy_pkg is already installed but may not show a tray icon on KDE Plasma"
        return 0
    fi

    print_info "$ayatana_pkg not available, falling back to $legacy_pkg (may not show a tray icon on KDE Plasma)..."
    if $install_cmd "$legacy_pkg"; then
        return 0
    fi

    print_error "Failed to install an AppIndicator package (tried $ayatana_pkg and $legacy_pkg)"
    return 1
}

suse_python_package_prefix() {
    python3 -c 'import sys; print(f"python{sys.version_info.major}{sys.version_info.minor}")' 2>/dev/null || echo "python3"
}

suse_python_package_candidates() {
    local suffix="$1"
    local PY_PREFIX
    PY_PREFIX=$(suse_python_package_prefix)

    if [[ "$PY_PREFIX" != "python3" ]]; then
        echo "${PY_PREFIX}-${suffix} python3-${suffix}"
    else
        echo "python3-${suffix}"
    fi
}

suse_package_installed() {
    rpm -q "$1" >/dev/null 2>&1
}

suse_install_first_available() {
    local DESCRIPTION="$1"
    shift

    local PKG
    for PKG in "$@"; do
        [ -z "$PKG" ] && continue

        if suse_package_installed "$PKG"; then
            print_info "$DESCRIPTION is already installed ($PKG)."
            return 0
        fi

        if sudo zypper install -y "$PKG" 2>/dev/null; then
            print_success "Installed $DESCRIPTION ($PKG)."
            return 0
        fi

        print_info "$DESCRIPTION package '$PKG' not available, trying next option..."
    done

    return 1
}

suse_appindicator_gi_available() {
    python3 - <<'PY' >/dev/null 2>&1
import importlib
import gi

for namespace in ("AppIndicator3", "AyatanaAppIndicator3", "AyatanaAppindicator3"):
    try:
        gi.require_version(namespace, "0.1")
        importlib.import_module(f"gi.repository.{namespace}")
        raise SystemExit(0)
    except (ImportError, ValueError):
        pass

raise SystemExit(1)
PY
}

suse_install_appindicator_runtime() {
    local APPINDICATOR_PACKAGES=(
        "typelib-1_0-AyatanaAppIndicator3-0_1"
        "typelib-1_0-AppIndicator3-0_1"
        "typelib-1_0-AyatanaAppIndicator-0_1"
        "libayatana-appindicator3-1"
        "libappindicator3-1"
        "libappindicator-gtk3"
    )

    if suse_appindicator_gi_available; then
        print_info "AppIndicator/Ayatana GI namespace is already available."
        return 0
    fi

    local PKG
    for PKG in "${APPINDICATOR_PACKAGES[@]}"; do
        if suse_package_installed "$PKG"; then
            print_info "AppIndicator/Ayatana package is already installed ($PKG); verifying GI namespace..."
        elif sudo zypper install -y "$PKG" 2>/dev/null; then
            print_success "Installed AppIndicator/Ayatana package ($PKG)."
            # Refresh the shared-library cache so the GI typelib is discoverable
            sudo ldconfig 2>/dev/null || true
        else
            print_info "AppIndicator/Ayatana package '$PKG' not available, trying next option..."
            continue
        fi

        if suse_appindicator_gi_available; then
            print_success "AppIndicator/Ayatana GI namespace is available."
            return 0
        fi
    done

    return 1
}

suse_shader_compiler_available() {
    command_exists glslc || command_exists glslangValidator
}

# Function to install system dependencies based on the detected distribution
install_system_dependencies() {
    print_info "Installing system dependencies..."

    # Determine which Vulkan shader package is available (glslc for Ubuntu 24.04+, glslang-tools for 22.04)
    local VULKAN_SHADER_PKG="glslang-tools"  # Default fallback
    if apt-cache show glslc &>/dev/null 2>&1; then
        VULKAN_SHADER_PKG="glslc"
    fi

    # Define package names for different distributions
    # GObject Introspection / GLib headers for building PyGObject and friends.
    # Prefer libgirepository-2.0-dev when available (Ubuntu 24.04+, Pop!_OS Cosmic+,
    # Debian 13+). When both 1.0 and 2.0 packages exist, install both: 2.0 provides
    # the modern GLib GI headers that pip builds need, while 1.0 still pulls
    # gobject-introspection tooling. Older distros that only ship 1.0 keep that.
    # See #571 (installer previously kept 1.0 whenever apt-cache still listed it).
    local GI_DEV_PKG="libgirepository1.0-dev"
    if apt-cache show libgirepository-2.0-dev &>/dev/null 2>&1; then
        if apt-cache show libgirepository1.0-dev &>/dev/null 2>&1; then
            GI_DEV_PKG="libgirepository-2.0-dev libgirepository1.0-dev"
        else
            GI_DEV_PKG="libgirepository-2.0-dev"
        fi
    fi

    # libssl-dev, autoconf, automake, libtool, patchelf are required for pywhispercpp source
    # builds on Debian. On Ubuntu these are typically pulled in transitively, but on a clean
    # Debian install they are absent and cause CMake's bootstrap to fail (Hurdle 2 from
    # https://medium.com/@cslev/talking-to-my-linux-box-without-talking-to-the-cloud-vocalinux-on-debian-without-the-tears-10bf053ea21b).
    local PYWHISPERCPP_BUILD_DEPS="libssl-dev autoconf automake libtool patchelf"
    local APT_PACKAGES_UBUNTU="python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 gir1.2-ibus-1.0 $GI_DEV_PKG libcairo2-dev cmake python3-dev build-essential portaudio19-dev python3-venv pkg-config wget curl unzip vulkan-tools libvulkan-dev $VULKAN_SHADER_PKG xclip xsel wl-clipboard $PYWHISPERCPP_BUILD_DEPS"
    local APT_PACKAGES_DEBIAN_BASE="python3-pip python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-ibus-1.0 libcairo2-dev cmake python3-dev build-essential portaudio19-dev python3-venv pkg-config wget curl unzip vulkan-tools libvulkan-dev $VULKAN_SHADER_PKG xclip xsel wl-clipboard $PYWHISPERCPP_BUILD_DEPS"
    local APT_PACKAGES_DEBIAN_11_12="$APT_PACKAGES_DEBIAN_BASE libgirepository1.0-dev gir1.2-ayatanaappindicator3-0.1"
    local APT_PACKAGES_DEBIAN_13_PLUS="$APT_PACKAGES_DEBIAN_BASE libgirepository-2.0-dev gir1.2-ayatanaappindicator3-0.1"
    local DNF_PACKAGES="python3-pip python3-gobject gtk3 ibus-devel gobject-introspection-devel python3-devel portaudio-devel python3-virtualenv pkg-config cmake wget curl unzip vulkan-tools vulkan-loader-devel glslang xclip xsel wl-clipboard"
    local PACMAN_PACKAGES="python-pip python-gobject gtk3 ibus gobject-introspection python-cairo portaudio python-virtualenv pkg-config cmake wget curl unzip base-devel vulkan-tools vulkan-headers glslang xclip xsel wl-clipboard"
    local ZYPPER_PACKAGES="gtk3 ibus-devel gobject-introspection-devel portaudio-devel pkg-config cmake wget curl unzip xclip xsel wl-clipboard typelib-1_0-Notify-0_7 libnotify4"
    # Gentoo uses Portage and different package naming convention
    local EMERGE_PACKAGES="dev-python/pygobject:3 x11-libs/gtk+:3 dev-libs/libayatana-appindicator media-libs/portaudio dev-lang/python:3.11 pkgconf cmake dev-util/glslang x11-misc/xclip x11-misc/xsel gui-apps/wl-clipboard"
    # Alpine Linux uses apk and has musl libc
    local APK_PACKAGES="py3-gobject3 py3-pip gtk+3.0 py3-cairo portaudio-dev py3-virtualenv pkgconf cmake wget curl unzip glslang vulkan-tools xclip xsel wl-clipboard"
    # Void Linux uses xbps
    local XBPS_PACKAGES="python3-pip python3-gobject gtk+3 libappindicator-gtk3 gobject-introspection portaudio-devel python3-devel pkg-config cmake wget curl unzip glslang Vulkan-Tools xclip xsel wl-clipboard"
    # Solus uses eopkg
    local EOPKG_PACKAGES="python3-pip python3-gobject gtk3 libappindicator gobject-introspection-devel portaudio-devel python3-virtualenv pkg-config cmake wget curl unzip glslang vulkan-tools xclip xsel wl-clipboard"

    local MISSING_PACKAGES=""
    local INSTALL_CMD=""
    local UPDATE_CMD=""

    case "$DISTRO_FAMILY" in
        ubuntu|debian)
            local APT_PACKAGES="$APT_PACKAGES_UBUNTU"
            if [[ "$DISTRO_FAMILY" == "debian" ]]; then
                local DEBIAN_MAJOR="${DISTRO_VERSION%%.*}"
                if [[ "$DEBIAN_MAJOR" =~ ^[0-9]+$ ]] && [ "$DEBIAN_MAJOR" -ge 13 ]; then
                    APT_PACKAGES="$APT_PACKAGES_DEBIAN_13_PLUS"
                else
                    APT_PACKAGES="$APT_PACKAGES_DEBIAN_11_12"
                fi
            fi

            # util-linux-extra only exists on newer Ubuntu/Debian (24.04+, Debian 13+).
            # On 22.04 those tools ship in the main util-linux package (always installed).
            # apt-cache probe handles Ubuntu derivatives (Mint, Zorin) whose VERSION_ID
            # does not track the Ubuntu base release.
            if apt-cache show util-linux-extra &>/dev/null 2>&1; then
                APT_PACKAGES="$APT_PACKAGES util-linux-extra"
            fi

            # Check for missing packages
            for pkg in $APT_PACKAGES; do
                if ! apt_package_installed "$pkg"; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing missing packages:$MISSING_PACKAGES"
                sudo apt update || { print_error "Failed to update package lists"; exit "$EXIT_NETWORK"; }

                # Handle appindicator package for Ubuntu (old package deprecated in newer releases)
                if echo "$MISSING_PACKAGES" | grep -q "gir1.2-appindicator3-0.1"; then
                    FILTERED_PACKAGES=$(echo "$MISSING_PACKAGES" | sed 's/gir1.2-appindicator3-0.1//' | xargs)

                    if ! DEBIAN_FRONTEND=noninteractive sudo apt install -y gir1.2-appindicator3-0.1 2>/dev/null; then
                        print_info "gir1.2-appindicator3-0.1 not available, trying gir1.2-ayatanaappindicator3-0.1..."
                        if ! DEBIAN_FRONTEND=noninteractive sudo apt install -y gir1.2-ayatanaappindicator3-0.1; then
                            print_error "Failed to install appindicator package (tried both gir1.2-appindicator3-0.1 and gir1.2-ayatanaappindicator3-0.1)"
                            exit "$EXIT_MISSING_DEPS"
                        fi
                        print_info "Successfully installed gir1.2-ayatanaappindicator3-0.1 (modern replacement)"
                    fi

                    if [ -n "$FILTERED_PACKAGES" ]; then
                        DEBIAN_FRONTEND=noninteractive sudo apt install -y $FILTERED_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
                    fi
                else
                    DEBIAN_FRONTEND=noninteractive sudo apt install -y $MISSING_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
                fi
            else
                print_info "All required packages are already installed."
            fi
            ;;

        fedora)
            # For Fedora/RHEL-based systems
            if command_exists dnf; then
                INSTALL_CMD="sudo dnf install -y"
                UPDATE_CMD="sudo dnf check-update"
            elif command_exists yum; then
                INSTALL_CMD="sudo yum install -y"
                UPDATE_CMD="sudo yum check-update"
            else
                print_error "No supported package manager found (dnf/yum)"
                exit "$EXIT_MISSING_DEPS"
            fi

            # Check for missing packages
            for pkg in $DNF_PACKAGES; do
                if ! dnf_package_installed "$pkg"; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing missing packages:$MISSING_PACKAGES"
                $UPDATE_CMD || true  # dnf check-update returns 100 if updates available
                $INSTALL_CMD $MISSING_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
            else
                print_info "All required packages are already installed."
            fi

            install_preferred_appindicator "$INSTALL_CMD" "libayatana-appindicator-gtk3" "libappindicator-gtk3" dnf_package_installed || exit "$EXIT_MISSING_DEPS"
            ;;

        arch)
            # For Arch-based systems
            if ! command_exists pacman; then
                print_error "Pacman package manager not found"
                exit "$EXIT_MISSING_DEPS"
            fi

            # Check for missing packages
            for pkg in $PACMAN_PACKAGES; do
                if ! pacman_package_installed "$pkg"; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing missing packages:$MISSING_PACKAGES"
                sudo pacman -Sy
                sudo pacman -S --noconfirm $MISSING_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
            else
                print_info "All required packages are already installed."
            fi

            install_preferred_appindicator "sudo pacman -S --noconfirm" "libayatana-appindicator" "libappindicator-gtk3" pacman_package_installed || exit "$EXIT_MISSING_DEPS"
            ;;

        suse)
            # For openSUSE
            if ! command_exists zypper; then
                print_error "Zypper package manager not found"
                exit "$EXIT_MISSING_DEPS"
            fi

            sudo zypper refresh || true

            if [[ "${SELECTED_ENGINE:-whisper_cpp}" == "whisper_cpp" && "${WHISPERCPP_BACKEND:-}" != "cpu" ]]; then
                ZYPPER_PACKAGES="$ZYPPER_PACKAGES vulkan-tools vulkan-devel"
            fi

            local MISSING_ZYPPER_PACKAGES=()
            for pkg in $ZYPPER_PACKAGES; do
                if ! suse_package_installed "$pkg"; then
                    MISSING_ZYPPER_PACKAGES+=("$pkg")
                fi
            done

            if [ "${#MISSING_ZYPPER_PACKAGES[@]}" -gt 0 ]; then
                print_info "Installing missing packages: ${MISSING_ZYPPER_PACKAGES[*]}"
                sudo zypper install -y "${MISSING_ZYPPER_PACKAGES[@]}" || {
                    print_error "Failed to install openSUSE base dependencies"
                    exit "$EXIT_MISSING_DEPS"
                }
            else
                print_info "All base openSUSE packages are already installed."
            fi

            local PY_PIP_CANDIDATES=()
            local PY_GOBJECT_CANDIDATES=()
            local PY_GOBJECT_CAIRO_CANDIDATES=()
            local PY_DEVEL_CANDIDATES=()
            local PY_VIRTUALENV_CANDIDATES=()
            local PY_VENV_CANDIDATES=()

            read -r -a PY_PIP_CANDIDATES <<< "$(suse_python_package_candidates "pip")"
            read -r -a PY_GOBJECT_CANDIDATES <<< "$(suse_python_package_candidates "gobject")"
            read -r -a PY_GOBJECT_CAIRO_CANDIDATES <<< "$(suse_python_package_candidates "gobject-cairo")"
            read -r -a PY_DEVEL_CANDIDATES <<< "$(suse_python_package_candidates "devel")"
            read -r -a PY_VIRTUALENV_CANDIDATES <<< "$(suse_python_package_candidates "virtualenv")"
            read -r -a PY_VENV_CANDIDATES <<< "$(suse_python_package_candidates "venv")"

            print_info "Resolving openSUSE Python packages for $(suse_python_package_prefix)..."

            if ! suse_install_first_available "Python pip" "${PY_PIP_CANDIDATES[@]}"; then
                print_error "Failed to install Python pip package (tried: ${PY_PIP_CANDIDATES[*]})"
                exit "$EXIT_MISSING_DEPS"
            fi

            if ! suse_install_first_available "PyGObject bindings" "${PY_GOBJECT_CANDIDATES[@]}"; then
                print_error "Failed to install PyGObject package (tried: ${PY_GOBJECT_CANDIDATES[*]})"
                exit "$EXIT_MISSING_DEPS"
            fi

            if ! suse_install_first_available "PyGObject Cairo bindings" "${PY_GOBJECT_CAIRO_CANDIDATES[@]}"; then
                print_error "Failed to install PyGObject Cairo package (tried: ${PY_GOBJECT_CAIRO_CANDIDATES[*]})"
                exit "$EXIT_MISSING_DEPS"
            fi

            if ! suse_install_first_available "Python development headers" "${PY_DEVEL_CANDIDATES[@]}"; then
                print_error "Failed to install Python development headers (tried: ${PY_DEVEL_CANDIDATES[*]})"
                exit "$EXIT_MISSING_DEPS"
            fi

            if ! suse_install_first_available "Python virtualenv/venv" "${PY_VIRTUALENV_CANDIDATES[@]}" "${PY_VENV_CANDIDATES[@]}"; then
                print_warning "Python virtualenv/venv package was not found (tried: ${PY_VIRTUALENV_CANDIDATES[*]} ${PY_VENV_CANDIDATES[*]})"
                print_warning "Continuing because python3 -m venv may still be available."
            fi

            if ! suse_install_appindicator_runtime; then
                print_error "Failed to install a working AppIndicator/Ayatana GI runtime on openSUSE."
                print_error "Try manually: sudo zypper install typelib-1_0-AyatanaAppIndicator3-0_1 libayatana-appindicator3-1"
                exit "$EXIT_MISSING_DEPS"
            fi

            if [[ "${SELECTED_ENGINE:-whisper_cpp}" == "whisper_cpp" && "${WHISPERCPP_BACKEND:-}" != "cpu" ]]; then
                if ! suse_shader_compiler_available; then
                    if ! suse_install_first_available "Vulkan shader compiler" shaderc glslang-devel glslang; then
                        print_warning "No Vulkan shader compiler found - whisper.cpp Vulkan build may fail"
                        print_warning "Install shaderc manually for glslc support if you want GPU acceleration."
                    fi
                fi

                if ! suse_shader_compiler_available; then
                    print_warning "glslc/glslangValidator is still unavailable; CPU fallback will be used if Vulkan build fails."
                fi
            fi
            ;;

        gentoo)
            # For Gentoo Linux
            if ! command_exists emerge; then
                print_error "Emerge package manager not found"
                exit "$EXIT_MISSING_DEPS"
            fi

            print_info "Gentoo detected. Installing dependencies..."
            print_warning "Gentoo uses emerge. This may take longer as packages are compiled from source."

            # Check for missing packages
            MISSING_PACKAGES=""
            for pkg in $EMERGE_PACKAGES; do
                # Gentoo uses qlist to check if packages are installed
                if ! qlist -I "$pkg" >/dev/null 2>&1; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing packages:$MISSING_PACKAGES"
                # Update Portage tree first
                sudo emerge --sync || { print_error "Failed to sync Portage tree"; exit "$EXIT_NETWORK"; }
                # Install missing packages
                sudo emerge $MISSING_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
            else
                print_info "All required packages are already installed."
            fi
            ;;

        alpine)
            # For Alpine Linux
            if ! command_exists apk; then
                print_error "Apk package manager not found"
                exit "$EXIT_MISSING_DEPS"
            fi

            print_info "Alpine Linux detected."
            print_warning "Alpine uses musl libc. Some Python packages may not have pre-built wheels."

            # Check for missing packages
            MISSING_PACKAGES=""
            for pkg in $APK_PACKAGES; do
                if ! apk info -e "$pkg" >/dev/null 2>&1; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing packages:$MISSING_PACKAGES"
                sudo apk update || { print_error "Failed to update package indexes"; exit "$EXIT_NETWORK"; }
                sudo apk add $MISSING_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
            else
                print_info "All required packages are already installed."
            fi
            ;;

        void)
            # For Void Linux
            if ! command_exists xbps; then
                print_error "Xbps package manager not found"
                exit "$EXIT_MISSING_DEPS"
            fi

            print_info "Void Linux detected."

            # Check for missing packages
            MISSING_PACKAGES=""
            for pkg in $XBPS_PACKAGES; do
                if ! xbps-query "$pkg" >/dev/null 2>&1; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing packages:$MISSING_PACKAGES"
                sudo xbps-install -Sy $MISSING_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
            else
                print_info "All required packages are already installed."
            fi
            ;;

        solus)
            # For Solus
            if ! command_exists eopkg; then
                print_error "Eopkg package manager not found"
                exit "$EXIT_MISSING_DEPS"
            fi

            print_info "Solus detected."

            # Check for missing packages
            MISSING_PACKAGES=""
            for pkg in $EOPKG_PACKAGES; do
                if ! eopkg list-installed | grep -qw "$pkg"; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing packages:$MISSING_PACKAGES"
                sudo eopkg install $MISSING_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
            else
                print_info "All required packages are already installed."
            fi
            ;;

        mageia)
            # For Mageia
            if command_exists dnf; then
                INSTALL_CMD="sudo dnf install -y"
                UPDATE_CMD="sudo dnf check-update"
            elif command_exists urpmi; then
                INSTALL_CMD="sudo urpmi --force"
                UPDATE_CMD="sudo urpmi.update -a"
            else
                print_error "No supported package manager found (dnf/urpmi)"
                exit "$EXIT_MISSING_DEPS"
            fi

            # Use similar packages to Fedora/RHEL
            for pkg in $DNF_PACKAGES; do
                # Mageia uses rpm like Fedora
                if ! rpm -q "$pkg" >/dev/null 2>&1; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing missing packages:$MISSING_PACKAGES"
                $UPDATE_CMD 2>/dev/null || true
                $INSTALL_CMD $MISSING_PACKAGES || { print_error "Failed to install dependencies"; exit "$EXIT_MISSING_DEPS"; }
            else
                print_info "All required packages are already installed."
            fi
            ;;

        *)
            print_error "Unsupported distribution family: $DISTRO_FAMILY"
            print_info ""
            print_info "Your distribution ($DISTRO_NAME) is not officially supported."
            print_info "However, you can still install Vocalinux manually:"
            print_info ""
            print_info "1. Run the dependency checker:"
            print_info "   bash scripts/check-system-deps.sh"
            print_info ""
            print_info "2. Install missing dependencies using your package manager"
            print_info ""
            print_info "3. Run the installer with --skip-system-deps:"
            print_info "   ./install.sh --skip-system-deps"
            print_info ""
            print_info "4. Or install from source in a virtual environment:"
            print_info "   /usr/bin/python3 -m venv --system-site-packages venv"
            print_info "   source venv/bin/activate"
            print_info "   pip install -e .[whisper,vad]"
            print_info ""
            print_info "For more information, see the project wiki:"
            print_info "  https://github.com/VocaHQ/vocalinux/wiki"
            print_info ""
            if [[ "$NON_INTERACTIVE" != "yes" ]]; then
                read -p "Continue anyway? (y/n) " -n 1 -r
                echo
                if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                    exit "$EXIT_USER_ABORT"
                fi
            else
                print_info "Non-interactive mode: continuing (dependencies may be missing)..."
            fi
            ;;
    esac
}

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

# Function to detect and install text input tools
install_text_input_tools() {
    if [[ "$SKIP_SYSTEM_DEPS" == "yes" ]]; then
        print_warning "Skipping text input tool installation (--skip-system-deps specified)."
        return 0
    fi

    # Detect session type more robustly
    local SESSION_TYPE="unknown"

    # Check XDG_SESSION_TYPE first. These are often unset without a login
    # session even when DISPLAY is set; ${var:-} keeps set -u from aborting.
    if [ -n "${XDG_SESSION_TYPE:-}" ]; then
        SESSION_TYPE="${XDG_SESSION_TYPE:-}"
    # Check for Wayland-specific environment variables
    elif [ -n "${WAYLAND_DISPLAY:-}" ]; then
        SESSION_TYPE="wayland"
    # Check if X server is running
    elif [ -n "${DISPLAY:-}" ] && command_exists xset && xset q &>/dev/null; then
        SESSION_TYPE="x11"
    # Check loginctl if available
    elif command_exists loginctl; then
        SESSION_TYPE=$(loginctl show-session $(loginctl | grep $(whoami) | awk '{print $1}') -p Type | cut -d= -f2 || true)
    fi

    print_info "Detected session type: $SESSION_TYPE"
    if [[ "$SESSION_TYPE" == "wayland" ]] && is_kde_plasma_session; then
        print_kde_wayland_ibus_hint
    fi

    # Install appropriate tools based on session type and distribution
    case "$SESSION_TYPE" in
        wayland)
            print_info "Installing Wayland text input tools..."
            case "$DISTRO_FAMILY" in
                ubuntu|debian)
                    if ! apt_package_installed "wtype"; then
                        DEBIAN_FRONTEND=noninteractive sudo apt install -y wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                fedora)
                    if command_exists dnf && ! dnf_package_installed "wtype"; then
                        sudo dnf install -y wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    elif command_exists yum && ! rpm -q wtype &>/dev/null; then
                        sudo yum install -y wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                arch)
                    if ! pacman_package_installed "wtype"; then
                        sudo pacman -S --noconfirm wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                suse)
                    sudo zypper install -y wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    ;;
                gentoo)
                    if ! qlist -I wtype >/dev/null 2>&1; then
                        sudo emerge wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                alpine)
                    if ! apk info -e wtype >/dev/null 2>&1; then
                        sudo apk add wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                void)
                    if ! xbps-query wtype >/dev/null 2>&1; then
                        sudo xbps-install -Sy wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                solus)
                    if ! eopkg list-installed | grep -qw wtype; then
                        sudo eopkg install wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                mageia)
                    if command_exists dnf && ! rpm -q wtype >/dev/null 2>&1; then
                        sudo dnf install -y wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    elif command_exists urpmi && ! rpm -q wtype >/dev/null 2>&1; then
                        sudo urpmi -y wtype || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                *)
                    print_warning "Unsupported distribution for Wayland text input tools."
                    print_warning "Please install 'wtype' manually for Wayland text input support."
                    ;;
            esac

            # Try to install ydotool as additional fallback for Wayland
            # ydotool works better with some compositors (like GNOME) where wtype may fail
            print_info "Attempting to install ydotool for better Wayland compatibility..."
            case "$DISTRO_FAMILY" in
                ubuntu|debian)
                    if ! apt_package_installed "ydotool"; then
                        if ! DEBIAN_FRONTEND=noninteractive sudo apt install -y ydotool 2>/dev/null; then
                            if [[ "$DISTRO_FAMILY" == "debian" ]]; then
                                print_warning "ydotool is not packaged in Debian's standard repos."
                                print_info "For full Wayland input support, you can compile ydotool from source:"
                                print_info "  sudo apt install -y git cmake libevdev-dev"
                                print_info "  git clone https://github.com/ReimuNotMoe/ydotool.git /tmp/ydotool"
                                print_info "  cmake -S /tmp/ydotool -B /tmp/ydotool/build && sudo cmake --build /tmp/ydotool/build --target install"
                                print_info "  sudo systemctl enable --now ydotoold"
                                print_info "Alternatively, wtype (already installed) will handle most Wayland compositors."
                            else
                                print_info "ydotool not available in repos (optional)"
                            fi
                        fi
                    fi
                    ;;
                fedora)
                    if command_exists dnf; then
                        sudo dnf install -y ydotool 2>/dev/null || print_info "ydotool not available in repos (optional)"
                    fi
                    ;;
                arch)
                    if ! pacman_package_installed "ydotool"; then
                        sudo pacman -S --noconfirm ydotool 2>/dev/null || print_info "ydotool not available in repos (optional)"
                    fi
                    ;;
            esac

            # Add user to input group for ydotool/dotool support
            if ! groups | grep -q '\binput\b'; then
                print_info "Adding $USER to 'input' group for text injection..."
                sudo usermod -aG input "$USER" || print_warning "Failed to add user to input group"
                print_warning "You will need to LOG OUT and back in for text injection to work with ydotool/dotool"
            fi

            # Install udev rule for ydotool/dotool
            if [ ! -f /etc/udev/rules.d/80-dotool.rules ]; then
                print_info "Installing udev rule for input device access..."
                echo 'KERNEL=="uinput", GROUP="input", MODE="0620", OPTIONS+="static_node=uinput"' \
                    | sudo tee /etc/udev/rules.d/80-dotool.rules >/dev/null 2>&1 || print_warning "Failed to install udev rule"
                sudo udevadm control --reload 2>/dev/null || true
                sudo udevadm trigger 2>/dev/null || true
            fi
            ;;

        x11|"")
            print_info "Installing X11 text input tools..."
            case "$DISTRO_FAMILY" in
                ubuntu|debian)
                    if ! apt_package_installed "xdotool"; then
                        DEBIAN_FRONTEND=noninteractive sudo apt install -y xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                fedora)
                    if command_exists dnf && ! dnf_package_installed "xdotool"; then
                        sudo dnf install -y xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    elif command_exists yum && ! rpm -q xdotool &>/dev/null; then
                        sudo yum install -y xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                arch)
                    if ! pacman_package_installed "xdotool"; then
                        sudo pacman -S --noconfirm xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                suse)
                    sudo zypper install -y xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    ;;
                gentoo)
                    if ! qlist -I xdotool >/dev/null 2>&1; then
                        sudo emerge xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                alpine)
                    if ! apk info -e xdotool >/dev/null 2>&1; then
                        sudo apk add xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                void)
                    if ! xbps-query xdotool >/dev/null 2>&1; then
                        sudo xbps-install -Sy xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                solus)
                    if ! eopkg list-installed | grep -qw xdotool; then
                        sudo eopkg install xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                mageia)
                    if command_exists dnf && ! rpm -q xdotool >/dev/null 2>&1; then
                        sudo dnf install -y xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    elif command_exists urpmi && ! rpm -q xdotool >/dev/null 2>&1; then
                        sudo urpmi -y xdotool || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                *)
                    print_warning "Unsupported distribution for X11 text input tools."
                    print_warning "Please install 'xdotool' manually for X11 text input support."
                    ;;
            esac
            ;;

        *)
            print_warning "Unknown session type: $SESSION_TYPE"
            print_warning "Installing both Wayland and X11 text input tools for compatibility..."

            # Install both tools based on distribution
            case "$DISTRO_FAMILY" in
                ubuntu|debian)
                    DEBIAN_FRONTEND=noninteractive sudo apt install -y xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                fedora|mageia)
                    if command_exists dnf; then
                        sudo dnf install -y xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    elif command_exists yum; then
                        sudo yum install -y xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    fi
                    # Mageia also supports urpmi
                    if [[ "$DISTRO_FAMILY" == "mageia" ]] && command_exists urpmi; then
                        sudo urpmi -y xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    fi
                    ;;
                arch)
                    sudo pacman -S --noconfirm xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                suse)
                    sudo zypper install -y xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                gentoo)
                    sudo emerge xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                alpine)
                    sudo apk add xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                void)
                    sudo xbps-install -Sy xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                solus)
                    sudo eopkg install xdotool wtype || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                *)
                    print_warning "Unsupported distribution for text input tools."
                    print_warning "Please install 'xdotool' and 'wtype' manually for text input support."
                    ;;
            esac
            ;;
    esac
}

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

    # Update pip and setuptools
    print_info "Updating pip, setuptools, and wheel..."
    pip install --upgrade pip setuptools wheel || { print_error "Failed to update pip, setuptools, and wheel"; exit "$EXIT_NETWORK"; }

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
        pip install --verbose --force-reinstall --no-cache-dir "pywhispercpp==${PYWHISPERCPP_VERSION}" --log "$PIP_LOG_FILE"
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
                pip install --verbose --force-reinstall --no-cache-dir --no-binary pywhispercpp "pywhispercpp==${PYWHISPERCPP_VERSION}" --log "$PIP_LOG_FILE" 2>&1; then
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
                        pip install --verbose --force-reinstall --no-cache-dir --no-binary pywhispercpp "pywhispercpp==${PYWHISPERCPP_VERSION}" --log "$PIP_LOG_FILE" 2>&1; then
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
                print_info "    Fedora: sudo dnf install vulkan-loader-devel vulkan-tools glslang"
                print_info "    Arch: sudo pacman -S vulkan-headers vulkan-tools glslang"
                print_info "    openSUSE: sudo zypper install vulkan-devel vulkan-tools shaderc"
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
        if [ ! -f "$FALLBACK_VOSK_CONFIG" ]; then
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

# Distro python3-gi provides `gi`, but apt does not drop pip-visible
# PyGObject dist-info. `pip install .` then tries to build pygobject from
# sdist and dies (needs girepository-2.0). Same skip as uv export's
# --no-emit-package pygobject: install the other deps, then the project
# with --no-deps. Do not use requirements/*.txt hashes here (Phase 2).
write_pip_reqs_skip_pygobject() {
    local dest="$1"
    shift
    "$VENV_DIR/bin/python" - "$dest" "$@" <<'PY'
from pathlib import Path
import re
import sys

dest = Path(sys.argv[1])
extras = sys.argv[2:]
text = Path("pyproject.toml").read_text()


def quoted_strings(block: str):
    return re.findall(r'"([^"]+)"', block)


reqs = []
if not extras:
    match = re.search(r"^dependencies = \[(.*?)\]", text, re.M | re.S)
    for req in quoted_strings(match.group(1) if match else ""):
        pkg = re.split(r"[<>=!~;\[]", req, 1)[0].strip()
        if pkg.lower() == "pygobject":
            continue
        reqs.append(req)
else:
    opt = re.search(
        r"^\[project\.optional-dependencies\](.*?)(\n\[|\Z)", text, re.M | re.S
    )
    opt_text = opt.group(1) if opt else ""
    for extra in extras:
        match = re.search(rf"^{re.escape(extra)} = \[(.*?)\]", opt_text, re.M | re.S)
        if match:
            reqs.extend(quoted_strings(match.group(1)))

dest.write_text("\n".join(reqs) + ("\n" if reqs else ""))
PY
}

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
        return 0
    fi
    pip install -r "$reqs_file" --log "$pip_log"
}

pip_install_project_skip_pygobject() {
    local pip_log="$1"
    shift
    require_distro_gi
    write_pip_reqs_skip_pygobject "$VOCALINUX_TMP_DIR/runtime-deps.txt"
    pip_install_reqs_file "$pip_log" "$VOCALINUX_TMP_DIR/runtime-deps.txt" || return 1
    pip install --no-deps --log "$pip_log" "$@"
}

pip_install_extras_skip_pygobject() {
    local pip_log="$1"
    shift
    write_pip_reqs_skip_pygobject "$VOCALINUX_TMP_DIR/extra-deps.txt" "$@"
    pip_install_reqs_file "$pip_log" "$VOCALINUX_TMP_DIR/extra-deps.txt"
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
        pip install pytest pytest-mock pytest-cov --log "$PIP_LOG_FILE" || {
            print_warning "Failed to install some test dependencies. Tests may not run correctly."
        }

        # Install all optional dependencies for development
        print_info "Installing all optional dependencies for development..."
        pip_install_extras_skip_pygobject "$PIP_LOG_FILE" whisper dev || {
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

                # Install PyTorch and whisper
                print_info "Installing PyTorch..."
                if pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu --log "$PIP_LOG_FILE" 2>&1; then
                    print_success "PyTorch installed successfully"

                    print_info "Installing openai-whisper..."
                    if pip install openai-whisper --log "$PIP_LOG_FILE" 2>&1; then
                        # Verify the installation by importing the module
                        if "$VENV_DIR/bin/python" -c "import whisper" 2>/dev/null; then
                            WHISPER_INSTALL_SUCCESS=true
                            print_success "Whisper installed and verified successfully"
                        else
                            print_error "Whisper package installed but import failed"
                        fi
                    else
                        print_error "Failed to install openai-whisper package"
                    fi
                else
                    print_error "Failed to install PyTorch"
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

                # Ensure requests library is installed
                print_info "Installing requests library..."
                pip install requests --log "$PIP_LOG_FILE" || {
                    print_error "Failed to install requests library"
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
# Model integrity verification
#
# Models are 40MB-2GB downloads that end up being loaded by native code, so no
# model is installed without matching a digest pinned in this repository.
# src/vocalinux/utils/model_checksums.txt is the same manifest the application
# uses at runtime; it is regenerated by scripts/generate-model-checksums.py.
#
# A model that cannot be verified is deleted and the function returns 1, which
# callers already treat as "leave it for first run" rather than aborting the
# install. The app re-downloads and re-verifies it later.
# ---------------------------------------------------------------------------
MODEL_CHECKSUMS_FILE="$INSTALL_DIR/src/vocalinux/utils/model_checksums.txt"

# Print the digest of $1 using algorithm $2, trying the tools most likely present.
compute_file_digest() {
    local file="$1" algo="$2"

    case "$algo" in
        sha256)
            if command_exists sha256sum; then sha256sum "$file" | cut -d' ' -f1
            elif command_exists shasum; then shasum -a 256 "$file" | cut -d' ' -f1
            elif command_exists openssl; then openssl dgst -sha256 "$file" | awk '{print $NF}'
            else return 1; fi
            ;;
        *)
            return 1
            ;;
    esac
}

# Compare $1 against algorithm $2 and digest $3. $4 labels the file in messages.
verify_digest() {
    local file="$1" algo="$2" expected="$3" label="$4" actual

    if ! actual=$(compute_file_digest "$file" "$algo") || [ -z "$actual" ]; then
        print_error "Cannot compute the $algo digest of $label: no sha256sum, shasum or openssl found."
        return 1
    fi

    if [ "$actual" != "$expected" ]; then
        print_error "$label failed $algo verification."
        print_error "  expected: $expected"
        print_error "  actual:   $actual"
        print_error "The file does not match the digest pinned in this release."
        return 1
    fi

    print_success "$label verified ($algo)"
    return 0
}

# Verify $1 against the manifest entry named $2 (defaults to $1's basename).
verify_model_checksum() {
    local file="$1"
    local key="${2:-$(basename "$file")}"
    local algo expected size actual_size

    if [ ! -f "$MODEL_CHECKSUMS_FILE" ]; then
        print_error "Checksum manifest not found at $MODEL_CHECKSUMS_FILE."
        print_error "Cannot verify $key; refusing to install an unverified model."
        return 1
    fi

    # Manifest columns: filename  algorithm  digest  size-in-bytes
    algo=$(awk -v k="$key" '$1==k {print $2; exit}' "$MODEL_CHECKSUMS_FILE")
    expected=$(awk -v k="$key" '$1==k {print $3; exit}' "$MODEL_CHECKSUMS_FILE")
    size=$(awk -v k="$key" '$1==k {print $4; exit}' "$MODEL_CHECKSUMS_FILE")

    if [ -z "$algo" ] || [ -z "$expected" ]; then
        print_error "No checksum is pinned for $key in $MODEL_CHECKSUMS_FILE."
        print_error "Regenerate it with scripts/generate-model-checksums.py."
        return 1
    fi

    # Size first: it is free, and it reports a truncated download as truncation
    # rather than as a digest mismatch that reads like tampering.
    if [ -n "$size" ] && [ "$size" != "0" ]; then
        actual_size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo "")
        if [ -n "$actual_size" ] && [ "$actual_size" != "$size" ]; then
            print_error "$key is $actual_size bytes, expected $size (truncated download?)."
            return 1
        fi
    fi

    verify_digest "$file" "$algo" "$expected" "$key"
}

# Verify an OpenAI Whisper checkpoint against the sha256 embedded in its own URL
# (they publish each file under a path segment that is its digest).
verify_openai_model_checksum() {
    local file="$1" url="$2" label="$3" expected

    expected=$(printf '%s\n' "$url" | grep -oE '/[0-9a-f]{64}/' | tr -d '/' | head -n1)
    if [ -z "$expected" ]; then
        print_error "$url carries no sha256 path segment; refusing to install an unverified model."
        return 1
    fi

    verify_digest "$file" "sha256" "$expected" "$label"
}

# Download $1 to $2, preferring wget and falling back to curl. $3 labels the
# model in error messages. Leaves no partial file behind on failure.
download_model_file() {
    local url="$1" dest="$2" label="$3"

    if command_exists wget; then
        if ! wget --progress=bar:force:noscroll --tries=3 --timeout=60 -O "$dest" "$url" 2>&1; then
            print_error "Failed to download $label with wget"
            rm -f "$dest"
            return 1
        fi
    elif command_exists curl; then
        # -f: fail on HTTP errors instead of saving the error page as the model
        if ! curl -fL --progress-bar --retry 3 --retry-delay 2 -o "$dest" "$url"; then
            print_error "Failed to download $label with curl"
            rm -f "$dest"
            return 1
        fi
    else
        print_error "Neither wget nor curl is available to download $label"
        return 1
    fi

    if [ ! -s "$dest" ]; then
        print_error "Downloaded $label is empty or missing"
        rm -f "$dest"
        return 1
    fi
}

# Print the digest pinned for manifest entry $1, or nothing when unpinned.
pinned_digest_for() {
    [ -f "$MODEL_CHECKSUMS_FILE" ] || return 1
    awk -v k="$1" '$1==k {print $3; exit}' "$MODEL_CHECKSUMS_FILE"
}

# The Hugging Face commit the whisper.cpp digests were taken at.
whispercpp_pinned_revision() {
    [ -f "$MODEL_CHECKSUMS_FILE" ] || return 1
    awk '/^#[[:space:]]*whispercpp-revision:/ {print $3; exit}' "$MODEL_CHECKSUMS_FILE"
}

# Function to download and install Whisper tiny model
install_whisper_model() {
    print_info "Installing Whisper tiny model (~75MB)..."

    # Create whisper models directory
    local WHISPER_DIR="$DATA_DIR/models/whisper"
    mkdir -p "$WHISPER_DIR"

    # Whisper tiny model URL and path
    local TINY_MODEL_URL="https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt"
    local TINY_MODEL_PATH="$WHISPER_DIR/tiny.pt"

    # An existing file is not a verified file: it may predate checksum
    # verification, or have been replaced since. Hash it before trusting it,
    # and re-download rather than keep something that does not match.
    if [ -f "$TINY_MODEL_PATH" ]; then
        if verify_openai_model_checksum "$TINY_MODEL_PATH" "$TINY_MODEL_URL" "Whisper tiny model"; then
            print_info "Whisper tiny model already exists at $TINY_MODEL_PATH"
            return 0
        fi
        print_warning "The existing Whisper tiny model does not match its pinned digest; replacing it."
        rm -f "$TINY_MODEL_PATH"
    fi

    # Check internet connectivity
    if ! command -v wget >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
        print_warning "Neither wget nor curl found. Cannot download Whisper model."
        print_warning "Model will be downloaded on first application run."
        return 1
    fi

    # Test internet connectivity (HTTP probes; ICMP ping is often blocked)
    if ! check_connectivity; then
        print_warning "No internet connection detected (HTTP probes to pypi.org/api.github.com/huggingface.co failed)."
        print_warning "Whisper model will be downloaded on first application run."
        return 1
    fi

    print_info "Downloading Whisper tiny model..."
    print_info "This may take a few minutes depending on your internet connection."

    local TEMP_FILE="$VOCALINUX_TMP_DIR/tiny.pt"

    if ! download_model_file "$TINY_MODEL_URL" "$TEMP_FILE" "Whisper model"; then
        return 1
    fi

    # Verify before the file reaches its final location, so a failed download is
    # never installed. (The "already exists" path above hashes what it finds.)
    if ! verify_openai_model_checksum "$TEMP_FILE" "$TINY_MODEL_URL" "Whisper tiny model"; then
        rm -f "$TEMP_FILE"
        print_warning "Whisper model will be downloaded and verified on first application run."
        return 1
    fi

    # Move to final location
    mv "$TEMP_FILE" "$TINY_MODEL_PATH"

    # Verify the model file
    if [ -f "$TINY_MODEL_PATH" ]; then
        local MODEL_SIZE=$(du -h "$TINY_MODEL_PATH" | cut -f1)
        print_success "Whisper tiny model installed successfully ($MODEL_SIZE)"

        # Create a marker file to indicate this model was pre-installed
        echo "$(date)" > "$WHISPER_DIR/.vocalinux_preinstalled"

        return 0
    else
        print_error "Whisper model installation failed"
        return 1
    fi
}

# Function to download and install VOSK models
install_vosk_models() {
    print_info "Installing VOSK speech recognition models..."

    # Create models directory
    local MODELS_DIR="$DATA_DIR/models"
    mkdir -p "$MODELS_DIR"

    # Define model information
    local SMALL_MODEL_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
    local SMALL_MODEL_NAME="vosk-model-small-en-us-0.15"
    local SMALL_MODEL_PATH="$MODELS_DIR/$SMALL_MODEL_NAME"

    local SMALL_MODEL_ARCHIVE="$SMALL_MODEL_NAME.zip"
    # The extracted tree has no digest of its own — the pin covers the zip, which
    # is deleted after unpacking. So whoever unpacks it records the verified zip
    # digest in a stamp (here, and in the app's own downloader), and the directory
    # is trusted only while that stamp matches what we pin today.
    local SMALL_MODEL_STAMP="$SMALL_MODEL_PATH/.vocalinux_verified"
    local EXPECTED_ZIP_DIGEST
    EXPECTED_ZIP_DIGEST=$(pinned_digest_for "$SMALL_MODEL_ARCHIVE" || true)
    if [ -d "$SMALL_MODEL_PATH" ]; then
        if [ -n "$EXPECTED_ZIP_DIGEST" ] && [ -f "$SMALL_MODEL_STAMP" ] &&
           [ "$(cat "$SMALL_MODEL_STAMP" 2>/dev/null)" = "$EXPECTED_ZIP_DIGEST" ]; then
            print_info "Small VOSK model already exists at $SMALL_MODEL_PATH (verified)"
            return 0
        fi
        # Unverified is not the same as known-bad, and this runs on every install:
        # a tree unpacked before stamps existed, or by the app itself, simply has
        # no stamp. Deleting it here would trade a working model for no model
        # whenever the download, unzip or network that follows fails. Fetch and
        # verify the replacement first; the swap below is what removes this tree.
        print_warning "The existing VOSK model carries no matching verification stamp; re-downloading it."
    fi

    # Check internet connectivity
    if ! command -v wget >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
        print_warning "Neither wget nor curl found. Cannot download VOSK models."
        print_warning "Models will be downloaded on first application run."
        return 1
    fi

    # Test internet connectivity (HTTP probes; ICMP ping is often blocked)
    if ! check_connectivity; then
        print_warning "No internet connection detected (HTTP probes to pypi.org/api.github.com/huggingface.co failed)."
        print_warning "VOSK models will be downloaded on first application run."
        return 1
    fi

    print_info "Downloading small VOSK model (approximately 40MB)..."
    print_info "This may take a few minutes depending on your internet connection."

    local TEMP_ZIP="$VOCALINUX_TMP_DIR/$(basename $SMALL_MODEL_URL)"

    if ! download_model_file "$SMALL_MODEL_URL" "$TEMP_ZIP" "VOSK model"; then
        return 1
    fi

    # Verify before extracting: a zip that fails its pinned digest must not get
    # as far as writing files into the models directory.
    if ! verify_model_checksum "$TEMP_ZIP"; then
        rm -f "$TEMP_ZIP"
        print_warning "VOSK model will be downloaded and verified on first application run."
        return 1
    fi

    print_info "Extracting VOSK model..."

    if ! command -v unzip >/dev/null 2>&1; then
        print_error "unzip command not found. Cannot extract VOSK model."
        rm -f "$TEMP_ZIP"
        return 1
    fi

    # Unpack beside the model rather than over it: any model already installed
    # stays usable until a complete, verified replacement exists, and staging in
    # MODELS_DIR keeps the swap a same-filesystem rename.
    local STAGING_DIR="$MODELS_DIR/.vosk-staging.$$"
    # A run killed mid-swap leaves its scratch directories behind; they are named
    # so they can be recognised and are of no use to a later run.
    find "$MODELS_DIR" -maxdepth 1 -type d \
        \( -name '.vosk-staging.*' -o -name '.*.replaced.*' \) \
        -exec rm -rf {} + 2>/dev/null || true
    if ! mkdir -p "$STAGING_DIR"; then
        print_error "Failed to create a staging directory under $MODELS_DIR"
        rm -f "$TEMP_ZIP"
        return 1
    fi

    if ! unzip -q "$TEMP_ZIP" -d "$STAGING_DIR"; then
        print_error "Failed to extract VOSK model"
        rm -f "$TEMP_ZIP"
        rm -rf "$STAGING_DIR"
        return 1
    fi
    rm -f "$TEMP_ZIP"

    if [ ! -d "$STAGING_DIR/$SMALL_MODEL_NAME" ]; then
        print_error "VOSK model extraction failed - $SMALL_MODEL_NAME not found in the archive"
        rm -rf "$STAGING_DIR"
        return 1
    fi

    chmod -R 755 "$STAGING_DIR/$SMALL_MODEL_NAME"
    echo "$(date)" > "$STAGING_DIR/$SMALL_MODEL_NAME/.vocalinux_preinstalled"

    # Record the digest this tree was extracted from, so a later run can tell a
    # verified model from one that merely exists. Written before the swap: an
    # unstamped tree is one this function would download all over again.
    if [ -z "$EXPECTED_ZIP_DIGEST" ] ||
       ! printf '%s\n' "$EXPECTED_ZIP_DIGEST" > "$STAGING_DIR/$SMALL_MODEL_NAME/.vocalinux_verified"; then
        print_error "Could not record the verified digest for $SMALL_MODEL_NAME"
        rm -rf "$STAGING_DIR"
        return 1
    fi

    # Swap. The old tree is moved aside rather than deleted, so a failed rename
    # can put it back.
    local REPLACED_DIR="$MODELS_DIR/.$SMALL_MODEL_NAME.replaced.$$"
    if [ -d "$SMALL_MODEL_PATH" ] && ! mv "$SMALL_MODEL_PATH" "$REPLACED_DIR"; then
        print_error "Could not move the existing VOSK model aside; keeping it"
        rm -rf "$STAGING_DIR"
        return 1
    fi
    if ! mv "$STAGING_DIR/$SMALL_MODEL_NAME" "$SMALL_MODEL_PATH"; then
        print_error "Failed to install the verified VOSK model"
        if [ -d "$REPLACED_DIR" ]; then
            mv "$REPLACED_DIR" "$SMALL_MODEL_PATH"
        fi
        rm -rf "$STAGING_DIR"
        return 1
    fi
    rm -rf "$REPLACED_DIR" "$STAGING_DIR"

    print_success "VOSK small model installed successfully at $SMALL_MODEL_PATH"
    return 0
}

# Function to download and install whisper.cpp tiny model
install_whispercpp_model() {
    print_info "Installing whisper.cpp tiny model (~39MB)..."

    # Create whisper.cpp models directory
    local WHISPERCPP_DIR="$DATA_DIR/models/whispercpp"
    mkdir -p "$WHISPERCPP_DIR"

    # whisper.cpp tiny model URL and path. The Hugging Face revision is pinned to
    # the one the digests in model_checksums.txt were taken at, so upstream
    # replacing ggml-tiny.bin cannot turn every install into a checksum failure.
    local WHISPERCPP_REVISION
    WHISPERCPP_REVISION=$(whispercpp_pinned_revision)
    if [ -z "$WHISPERCPP_REVISION" ]; then
        print_error "No whisper.cpp revision is pinned in $MODEL_CHECKSUMS_FILE."
        print_warning "whisper.cpp model will be downloaded and verified on first application run."
        return 1
    fi
    local TINY_MODEL_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/$WHISPERCPP_REVISION/ggml-tiny.bin"
    local TINY_MODEL_PATH="$WHISPERCPP_DIR/ggml-tiny.bin"

    # An existing file is not a verified file: it may predate checksum
    # verification, or have been replaced since. Hash it before trusting it,
    # and re-download rather than keep something that does not match.
    if [ -f "$TINY_MODEL_PATH" ]; then
        if verify_model_checksum "$TINY_MODEL_PATH" "ggml-tiny.bin"; then
            print_info "whisper.cpp tiny model already exists at $TINY_MODEL_PATH"
            return 0
        fi
        print_warning "The existing whisper.cpp tiny model does not match its pinned digest; replacing it."
        rm -f "$TINY_MODEL_PATH"
    fi

    # Check internet connectivity
    if ! command -v wget >/dev/null 2>&1 && ! command -v curl >/dev/null 2>&1; then
        print_warning "Neither wget nor curl found. Cannot download whisper.cpp model."
        print_warning "Model will be downloaded on first application run."
        return 1
    fi

    # Test internet connectivity (HTTP probes; ICMP ping is often blocked)
    if ! check_connectivity; then
        print_warning "No internet connection detected (HTTP probes to pypi.org/api.github.com/huggingface.co failed)."
        print_warning "whisper.cpp model will be downloaded on first application run."
        return 1
    fi

    print_info "Downloading whisper.cpp tiny model..."
    print_info "This may take a few minutes depending on your internet connection."

    local TEMP_FILE="$VOCALINUX_TMP_DIR/ggml-tiny.bin"

    if ! download_model_file "$TINY_MODEL_URL" "$TEMP_FILE" "whisper.cpp model"; then
        return 1
    fi

    # Verify before the file reaches its final location, so a failed download is
    # never installed. (The "already exists" path above hashes what it finds.)
    if ! verify_model_checksum "$TEMP_FILE" "ggml-tiny.bin"; then
        rm -f "$TEMP_FILE"
        print_warning "whisper.cpp model will be downloaded and verified on first application run."
        return 1
    fi

    # Move to final location
    mv "$TEMP_FILE" "$TINY_MODEL_PATH"

    # Verify the model file
    if [ -f "$TINY_MODEL_PATH" ]; then
        local MODEL_SIZE=$(du -h "$TINY_MODEL_PATH" | cut -f1)
        print_success "whisper.cpp tiny model installed successfully ($MODEL_SIZE)"

        # Create a marker file to indicate this model was pre-installed
        echo "$(date)" > "$WHISPERCPP_DIR/.vocalinux_preinstalled"

        return 0
    else
        print_error "whisper.cpp model installation failed"
        return 1
    fi
}

# Function to install desktop entry with error handling
install_desktop_entry() {
    print_info "Installing desktop entry..."

    # Check if desktop entry file exists
    if [ ! -f "vocalinux.desktop" ]; then
        print_error "Desktop entry file not found: vocalinux.desktop"
        return 1
    fi

    # Create desktop directory if it doesn't exist
    mkdir -p "$DESKTOP_DIR" || {
        print_error "Failed to create desktop directory: $DESKTOP_DIR"
        return 1
    }

    # Copy desktop entry
    cp vocalinux.desktop "$DESKTOP_DIR/" || {
        print_error "Failed to copy desktop entry to $DESKTOP_DIR"
        return 1
    }

    # Update the desktop entry to use the wrapper script with GI_TYPELIB_PATH
    WRAPPER_SCRIPT="$HOME/.local/bin/vocalinux-gui"
    if [ ! -f "$WRAPPER_SCRIPT" ]; then
        print_warning "Wrapper script not found at $WRAPPER_SCRIPT"
        print_warning "Desktop entry may not work correctly"
    else
        # Update Exec line to include GI_TYPELIB_PATH for PyGObject
        # Use the detected path for cross-distro compatibility
        sed -i "s|^Exec=vocalinux|Exec=env GI_TYPELIB_PATH=$GI_TYPELIB_DETECTED $WRAPPER_SCRIPT|" "$DESKTOP_DIR/vocalinux.desktop" || {
            print_warning "Failed to update desktop entry path"
        }
        print_info "Updated desktop entry to use wrapper script with GI_TYPELIB_PATH"
    fi

    # Make desktop entry executable
    chmod +x "$DESKTOP_DIR/vocalinux.desktop" || {
        print_warning "Failed to make desktop entry executable"
    }

    return 0
}

# Function to install icons with error handling
install_icons() {
    print_info "Installing application icons..."

    # Create icon directory if it doesn't exist
    mkdir -p "$ICON_DIR" || {
        print_error "Failed to create icon directory: $ICON_DIR"
        return 1
    }

    # Check if icons directory exists
    if [ ! -d "resources/icons/scalable" ]; then
        print_warning "Custom icons not found in resources/icons/scalable directory"
        return 1
    fi

    # List of icons to install
    local ICONS=(
        "vocalinux.svg"
        "vocalinux-microphone.svg"
        "vocalinux-microphone-off.svg"
        "vocalinux-microphone-process.svg"
    )

    # Install each icon
    local INSTALLED_COUNT=0
    for icon in "${ICONS[@]}"; do
        if [ -f "resources/icons/scalable/$icon" ]; then
            cp "resources/icons/scalable/$icon" "$ICON_DIR/" || {
                print_warning "Failed to copy icon: $icon"
                continue
            }
            ((INSTALLED_COUNT++))
        else
            print_warning "Icon not found: resources/icons/scalable/$icon"
        fi
    done

    if [ "$INSTALLED_COUNT" -eq "${#ICONS[@]}" ]; then
        print_success "Installed all custom Vocalinux icons"
        return 0
    elif [ "$INSTALLED_COUNT" -gt 0 ]; then
        print_warning "Installed $INSTALLED_COUNT/${#ICONS[@]} custom Vocalinux icons"
        return 0
    else
        print_error "Failed to install any icons"
        return 1
    fi
}

# Function to update icon cache and desktop database
update_icon_cache() {
    print_info "Updating icon cache..."

    # Check if gtk-update-icon-cache command exists
    if command_exists gtk-update-icon-cache; then
        gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || {
            print_warning "Failed to update icon cache"
        }
    else
        print_warning "gtk-update-icon-cache command not found, skipping icon cache update"
    fi

    # Update desktop database so the app appears in application menus immediately
    print_info "Updating desktop database..."
    if command_exists update-desktop-database; then
        update-desktop-database "${XDG_DATA_HOME:-$HOME/.local/share}/applications" 2>/dev/null || {
            print_warning "Failed to update desktop database"
        }
    else
        print_warning "update-desktop-database command not found - app may not appear in menu until next login"
    fi
}

# Function to install resources (icons, sounds) to the virtual environment
# so the resource_manager can find them at runtime
install_resources_to_venv() {
    print_info "Installing resources to virtual environment..."

    # Target directory: $VENV_DIR/share/vocalinux/resources
    local VENV_RESOURCES_DIR="$VENV_DIR/share/vocalinux/resources"

    # Create directories
    mkdir -p "$VENV_RESOURCES_DIR/icons/scalable" || {
        print_warning "Failed to create venv resources directory"
        return 1
    }
    mkdir -p "$VENV_RESOURCES_DIR/sounds" || {
        print_warning "Failed to create venv sounds directory"
        return 1
    }

    # Copy icons if available
    if [ -d "resources/icons/scalable" ]; then
        cp resources/icons/scalable/*.svg "$VENV_RESOURCES_DIR/icons/scalable/" 2>/dev/null || {
            print_warning "Failed to copy icons to venv resources"
        }
    fi

    # Copy sounds if available
    if [ -d "resources/sounds" ]; then
        cp resources/sounds/*.wav "$VENV_RESOURCES_DIR/sounds/" 2>/dev/null || {
            print_warning "Failed to copy sounds to venv resources"
        }
    fi

    # Verify
    local ICON_COUNT=$(ls "$VENV_RESOURCES_DIR/icons/scalable/"*.svg 2>/dev/null | wc -l)
    local SOUND_COUNT=$(ls "$VENV_RESOURCES_DIR/sounds/"*.wav 2>/dev/null | wc -l)

    if [ "$ICON_COUNT" -gt 0 ] && [ "$SOUND_COUNT" -gt 0 ]; then
        print_success "Installed resources to venv ($ICON_COUNT icons, $SOUND_COUNT sounds)"
    else
        print_warning "Some resources may be missing from venv ($ICON_COUNT icons, $SOUND_COUNT sounds)"
    fi
}

# Install desktop entry
install_desktop_entry || print_warning "Desktop entry installation failed"

# Install icons
install_icons || print_warning "Icon installation failed"

# Install resources to venv for runtime discovery
install_resources_to_venv || print_warning "Venv resource installation failed"

# Install models based on selected engine
# whisper.cpp is now the default engine
if [ "$SKIP_MODELS" = "no" ]; then
    # Check which engines are installed and download appropriate models

    # Install whisper.cpp model (default engine)
    if is_pywhispercpp_installed; then
        print_info "whisper.cpp is installed - downloading tiny model (default engine)..."
        install_whispercpp_model || print_warning "whisper.cpp model download failed - model will be downloaded on first run"
    fi

    # Install OpenAI Whisper model if whisper engine is installed
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
    install_vosk_models || print_warning "VOSK model installation failed - models will be downloaded on first run"
else
    print_info "Skipping VOSK model installation (--skip-models specified)"
    print_info "Models will be downloaded automatically on first application run"
fi

# config.json survives reinstalls — every writer above guards on "file does not
# exist" — so an engine picked by an earlier attempt can outlive the venv that
# supported it. Repair it here instead of letting the app die at startup with
# ModuleNotFoundError.
# Module each engine needs, and the pip name that provides it. whisper_cpp is
# the default engine and the fallback, so it is what a broken config is moved to.
engine_import_module() {
    case "$1" in
        vosk) echo "vosk" ;;
        whisper) echo "whisper" ;;
        whisper_cpp) echo "pywhispercpp.model" ;;
        *) echo "" ;;
    esac
}

engine_pip_name() {
    case "$1" in
        vosk) echo "vosk" ;;
        whisper) echo "openai-whisper" ;;
        whisper_cpp) echo "pywhispercpp" ;;
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

    # Leaving it means the app dies at startup with ModuleNotFoundError, so move
    # the config to the default engine when that one works.
    if [ "$CONFIGURED_ENGINE" != "whisper_cpp" ] && venv_can_import "pywhispercpp.model"; then
        if set_configured_engine "$CONFIG_FILE" "whisper_cpp"; then
            print_success "Switched $CONFIG_FILE to the whisper_cpp engine."
            print_info "Reinstall $(engine_pip_name "$CONFIGURED_ENGINE") and switch back in Settings if you want it."
            return 0
        fi
    fi

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
        pip install pytest pytest-mock pytest-cov || {
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
