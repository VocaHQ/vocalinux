#!/bin/bash
# Vocalinux Uninstaller
# This script removes Vocalinux and cleans up the environment

# Don't exit on error to allow for more robust cleanup
# set -e

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

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
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

# Function to safely remove a file or directory
safe_remove() {
    local path="$1"
    local description="$2"

    # -e follows symlinks (false for a broken link), so also test -L to catch
    # dangling symlinks left behind by an install.
    if [ -e "$path" ] || [ -L "$path" ]; then
        print_info "Removing $description: $path"
        rm -rf "$path" && {
            print_success "Successfully removed $description"
            return 0
        } || {
            print_error "Failed to remove $description: $path"
            return 1
        }
    else
        print_info "$description not found: $path"
        return 0
    fi
}

# Function to kill running Vocalinux processes
kill_vocalinux_processes() {
    print_info "Checking for running Vocalinux processes..."
    
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
        
        if [[ "$NON_INTERACTIVE" != "yes" ]]; then
            read -p "Kill running Vocalinux process(es)? (Y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Nn]$ ]]; then
                print_warning "Processes not killed. Uninstallation may be incomplete."
                return 0
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
            print_error "Warning: Could not terminate all Vocalinux processes: $FINAL_PIDS"
            print_error "You may need to manually kill these processes before continuing."
        else
            print_success "All Vocalinux processes stopped"
        fi
    else
        print_info "No running Vocalinux processes found"
    fi
}

print_info "Vocalinux Uninstaller"
print_info "=============================="
echo ""

# Parse command line arguments
KEEP_CONFIG="no"
KEEP_DATA="no"
VENV_DIR="venv"
NON_INTERACTIVE="no"

# Detect if running non-interactively
if [ ! -t 0 ]; then
    NON_INTERACTIVE="yes"
fi

while [[ $# -gt 0 ]]; do
    case $1 in
        --keep-config)
            KEEP_CONFIG="yes"
            shift
            ;;
        --keep-data)
            KEEP_DATA="yes"
            shift
            ;;
        --venv-dir=*)
            VENV_DIR="${1#*=}"
            shift
            ;;
        -y|--yes)
            NON_INTERACTIVE="yes"
            shift
            ;;
        --help)
            echo "Vocalinux Uninstaller"
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --keep-config     Keep configuration files"
            echo "  --keep-data       Keep application data (models, etc.)"
            echo "  --venv-dir=PATH   Specify custom virtual environment directory (default: venv)"
            echo "  -y, --yes         Non-interactive mode (no confirmation prompts)"
            echo "  --help            Show this help message"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help to see available options"
            exit 1
            ;;
    esac
done

# Define XDG directories
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/vocalinux"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux"
IBUS_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux-ibus"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"
ICON_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"

# Directories created by curl-based installation
CURL_INSTALL_DIR="$HOME/.local/share/vocalinux-install"
CURL_VENV_DIR="$HOME/.local/share/vocalinux/venv"
CURL_BIN_DIR="$HOME/.local/bin"

echo "Uninstallation options:"
echo "- Local virtual environment: $VENV_DIR"
echo "- Curl-installed venv: $CURL_VENV_DIR"
echo "- Curl-installed repo: $CURL_INSTALL_DIR"
echo

if [[ "$NON_INTERACTIVE" == "yes" ]]; then
    print_info "Non-interactive mode: proceeding with uninstallation..."
else
    read -p "This will remove Vocalinux from your system. Continue? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Uninstallation cancelled."
        exit 0
    fi
    
    if [[ "$KEEP_DATA" != "yes" ]]; then
        read -p "Do you want to keep your data (models, config)? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            KEEP_DATA="yes"
            KEEP_CONFIG="yes"
            print_info "Data and configuration will be preserved."
        fi
    fi
fi

# Function to handle virtual environment removal
remove_virtual_environment() {
    # Deactivate the virtual environment if it's active
    if [[ -n "$VIRTUAL_ENV" ]]; then
        print_warning "Virtual environment is active. Deactivating..."
        deactivate 2>/dev/null || {
            print_warning "Failed to deactivate virtual environment. This is not critical."
        }
    fi
    
    # Remove local venv (if running from repo)
    if [ -d "$VENV_DIR" ]; then
        print_info "Removing local virtual environment..."
        safe_remove "$VENV_DIR" "local virtual environment directory"
    else
        print_info "Local virtual environment not found: $VENV_DIR"
    fi
    
    # Remove curl-installed venv
    if [ -d "$CURL_VENV_DIR" ]; then
        print_info "Removing curl-installed virtual environment..."
        safe_remove "$CURL_VENV_DIR" "curl-installed virtual environment"
    fi
    
    # Remove the vocalinux data directory if empty (contains venv)
    local VOCALINUX_DATA_DIR="$HOME/.local/share/vocalinux"
    if [ -d "$VOCALINUX_DATA_DIR" ] && [ -z "$(ls -A "$VOCALINUX_DATA_DIR" 2>/dev/null)" ]; then
        safe_remove "$VOCALINUX_DATA_DIR" "empty vocalinux data directory"
    fi
}

# Function to remove curl-installed files
remove_curl_install_files() {
    print_info "Removing curl-installation files..."
    
    # Remove cloned repository
    safe_remove "$CURL_INSTALL_DIR" "cloned repository"

    # Launcher scripts/symlinks in ~/.local/bin are removed in
    # remove_application_files() (they exist for both curl and repo installs).

    # Remove activation script in ~/.local/bin
    safe_remove "$CURL_BIN_DIR/activate-vocalinux.sh" "activation script in ~/.local/bin"
}

# Function to remove application files
remove_application_files() {
    # Remove local activation script (if running from repo)
    safe_remove "activate-vocalinux.sh" "local activation script"

    # Remove launcher wrappers in ~/.local/bin created by install.sh. These are
    # regular files in a repo/dev install and may be symlinks in a curl install;
    # safe_remove handles both (and dangling symlinks).
    safe_remove "$CURL_BIN_DIR/vocalinux" "vocalinux launcher script"
    safe_remove "$CURL_BIN_DIR/vocalinux-gui" "vocalinux-gui launcher script"

    # Remove desktop entry
    safe_remove "$DESKTOP_DIR/vocalinux.desktop" "desktop entry"

    safe_remove "$AUTOSTART_DIR/vocalinux.desktop" "autostart desktop entry"
    
    # Remove icons
    print_info "Removing application icons..."
    local ICONS=(
        "vocalinux.svg"
        "vocalinux-microphone.svg"
        "vocalinux-microphone-off.svg"
        "vocalinux-microphone-process.svg"
    )
    
    for icon in "${ICONS[@]}"; do
        safe_remove "$ICON_DIR/$icon" "icon"
    done
    
    # Update icon cache
    if command_exists gtk-update-icon-cache; then
        print_info "Updating icon cache..."
        gtk-update-icon-cache -f -t "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || {
            print_warning "Failed to update icon cache. This is not critical."
        }
    fi
}

# Function to remove configuration and data
remove_config_and_data() {
    # Remove configuration if not keeping it
    if [[ "$KEEP_CONFIG" != "yes" ]]; then
        safe_remove "$CONFIG_DIR" "configuration directory"
    else
        print_info "Keeping configuration directory as requested: $CONFIG_DIR"
    fi
    
    # Remove data if not keeping it
    if [[ "$KEEP_DATA" != "yes" ]]; then
        safe_remove "$DATA_DIR" "application data directory"
    else
        print_info "Keeping application data directory as requested: $DATA_DIR"
    fi

    # IBus runtime data (socket, PID file, logs) is recreated on next launch.
    safe_remove "$IBUS_DATA_DIR" "IBus runtime data directory"
}

# Function to clean up build artifacts
cleanup_build_artifacts() {
    print_info "Cleaning up build artifacts..."
    
    # Remove Python package build directories
    safe_remove "build/" "build directory"
    safe_remove "dist/" "distribution directory"
    safe_remove "*.egg-info/" "egg-info directory"
    
    # Find and remove egg-info directories in src
    find src -name "*.egg-info" -type d -exec rm -rf {} \; 2>/dev/null || {
        print_warning "Failed to remove some egg-info directories."
    }
    
    # Find and remove __pycache__ directories
    find . -name "__pycache__" -type d -exec rm -rf {} \; 2>/dev/null || {
        print_warning "Failed to remove some __pycache__ directories."
    }
    
    # Clean up any temporary or generated files
    print_info "Cleaning up temporary files..."
    find . -name "*.pyc" -delete 2>/dev/null
    find . -name "*.pyo" -delete 2>/dev/null
    find . -name ".pytest_cache" -type d -exec rm -rf {} \; 2>/dev/null
    find . -name ".coverage" -delete 2>/dev/null
    
    # Remove wrapper script if it exists
    safe_remove "vocalinux-run.py" "wrapper script"
}

# Function to verify uninstallation
verify_uninstallation() {
    print_info "Verifying uninstallation..."
    local ISSUES=0
    
    # Check if local virtual environment still exists
    if [ -d "$VENV_DIR" ]; then
        print_warning "Local virtual environment still exists: $VENV_DIR"
        ((ISSUES++))
    fi
    
    # Check if curl-installed virtual environment still exists
    if [ -d "$CURL_VENV_DIR" ]; then
        print_warning "Curl-installed venv still exists: $CURL_VENV_DIR"
        ((ISSUES++))
    fi
    
    # Check if cloned repository still exists
    if [ -d "$CURL_INSTALL_DIR" ]; then
        print_warning "Cloned repository still exists: $CURL_INSTALL_DIR"
        ((ISSUES++))
    fi
    
    # Check if launcher wrappers (files or symlinks) still exist
    for launcher in vocalinux vocalinux-gui; do
        if [ -e "$CURL_BIN_DIR/$launcher" ] || [ -L "$CURL_BIN_DIR/$launcher" ]; then
            print_warning "Launcher script still exists: $CURL_BIN_DIR/$launcher"
            ((ISSUES++))
        fi
    done
    
    # Check if desktop entry still exists
    if [ -f "$DESKTOP_DIR/vocalinux.desktop" ]; then
        print_warning "Desktop entry still exists: $DESKTOP_DIR/vocalinux.desktop"
        ((ISSUES++))
    fi

    if [ -f "$AUTOSTART_DIR/vocalinux.desktop" ]; then
        print_warning "Autostart desktop entry still exists: $AUTOSTART_DIR/vocalinux.desktop"
        ((ISSUES++))
    fi
    
    # Check if any icons still exist
    local ICON_COUNT=0
    for icon in vocalinux.svg vocalinux-microphone.svg vocalinux-microphone-off.svg vocalinux-microphone-process.svg; do
        if [ -f "$ICON_DIR/$icon" ]; then
            ((ICON_COUNT++))
        fi
    done
    
    if [ "$ICON_COUNT" -gt 0 ]; then
        print_warning "$ICON_COUNT icons still exist in $ICON_DIR"
        ((ISSUES++))
    fi
    
    # Check if configuration still exists (only if not keeping it)
    if [[ "$KEEP_CONFIG" != "yes" && -d "$CONFIG_DIR" ]]; then
        print_warning "Configuration directory still exists: $CONFIG_DIR"
        ((ISSUES++))
    fi
    
    # Check if data still exists (only if not keeping it)
    if [[ "$KEEP_DATA" != "yes" && -d "$DATA_DIR" ]]; then
        print_warning "Application data directory still exists: $DATA_DIR"
        ((ISSUES++))
    fi

    # IBus runtime data should always be removed
    if [ -d "$IBUS_DATA_DIR" ]; then
        print_warning "IBus runtime data directory still exists: $IBUS_DATA_DIR"
        ((ISSUES++))
    fi
    
    # Return the number of issues found
    return $ISSUES
}

# Function to print uninstallation summary
print_uninstallation_summary() {
    local ISSUES=$1
    
    echo
    echo "=============================="
    echo "   UNINSTALLATION SUMMARY"
    echo "=============================="
    echo
    
    if [ "$ISSUES" -eq 0 ]; then
        print_success "Uninstallation completed successfully with no issues!"
    else
        print_warning "Uninstallation completed with $ISSUES potential issue(s)."
        print_warning "Some files or directories may still exist."
    fi
    
    echo
    if [[ "$KEEP_CONFIG" == "yes" ]]; then
        print_info "Configuration directory was kept: $CONFIG_DIR"
    fi
    
    if [[ "$KEEP_DATA" == "yes" ]]; then
        print_info "Application data directory was kept: $DATA_DIR"
    fi
    
    echo
    print_info "Your system has been cleaned up and is ready for a fresh installation."
    
    if [ "$ISSUES" -gt 0 ]; then
        echo
        print_warning "If you encounter any problems, please report them at:"
        print_warning "https://github.com/VocaHQ/vocalinux/issues"
    fi
}

# Kill any running Vocalinux processes first
kill_vocalinux_processes

# Perform uninstallation steps
remove_virtual_environment
remove_curl_install_files
remove_application_files
remove_config_and_data
cleanup_build_artifacts

# Verify uninstallation
verify_uninstallation
UNINSTALL_ISSUES=$?

# Print uninstallation summary
print_uninstallation_summary $UNINSTALL_ISSUES

print_success "Uninstallation process completed!"
