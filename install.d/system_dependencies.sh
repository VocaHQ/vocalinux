#!/bin/bash
# Sourced by install.sh after it has resolved the local or tagged repository.
# Keep this file declarative: function definitions only, with no top-level actions.

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

resolve_debian_package_map_key() {
    local DEBIAN_MAJOR="${DISTRO_VERSION%%.*}"

    # Only Debian's own VERSION_ID identifies a Debian release. Derivatives
    # often use an unrelated product version, so select their compatible map
    # by probing the package inventory instead.
    if [[ "$DISTRO_ID" == "debian" && "$DEBIAN_MAJOR" =~ ^[0-9]+$ ]]; then
        if [ "$DEBIAN_MAJOR" -lt 12 ]; then
            print_error "Debian 12 or newer is required (detected Debian $DEBIAN_MAJOR)." >&2
            return "$EXIT_MISSING_DEPS"
        elif [ "$DEBIAN_MAJOR" -ge 13 ]; then
            echo "debian_13_plus"
        else
            echo "debian_12"
        fi
    else
        # A missing cache is not evidence of an older Debian base. Refresh
        # before probing; keep command substitution's stdout for the key only.
        sudo apt update >&2 || {
            print_error "Failed to refresh package indexes for Debian base detection." >&2
            return "$EXIT_NETWORK"
        }
        if apt-cache show "$DEBIAN_13_PLUS_PROBE_PACKAGE" &>/dev/null 2>&1; then
            echo "debian_13_plus"
        else
            echo "debian_12"
        fi
    fi
}

# Function to install system dependencies based on the detected distribution
install_system_dependencies() {
    print_info "Installing system dependencies..."

    local PACKAGE_MAP_KEY="$DISTRO_FAMILY"
    if [[ "$DISTRO_FAMILY" == "debian" ]]; then
        PACKAGE_MAP_KEY=$(resolve_debian_package_map_key) || exit "$?"
    fi
    case "$PACKAGE_MAP_KEY" in
        ubuntu|debian_12|debian_13_plus|fedora|arch|suse|gentoo|alpine|void|solus|mageia)
            load_distro_package_map "$PACKAGE_MAP_KEY" || exit "$EXIT_MISSING_DEPS"
            ;;
    esac

    # GObject Introspection / GLib headers for building PyGObject and friends.
    # Prefer libgirepository-2.0-dev when available (Ubuntu 24.04+, Pop!_OS Cosmic+,
    # Debian 13+). When both 1.0 and 2.0 packages exist, install both: 2.0 provides
    # the modern GLib GI headers that pip builds need, while 1.0 still pulls
    # gobject-introspection tooling. Older distros that only ship 1.0 keep that.
    # See #571 (installer previously kept 1.0 whenever apt-cache still listed it).
    if [[ "$DISTRO_FAMILY" == "ubuntu" ]]; then
        local GI_DEV_PACKAGE
        local GI_DEV_FOUND="no"
        for GI_DEV_PACKAGE in "${GI_DEVELOPMENT_PACKAGES[@]}"; do
            if apt-cache show "$GI_DEV_PACKAGE" &>/dev/null 2>&1; then
                SYSTEM_PACKAGES+=("$GI_DEV_PACKAGE")
                GI_DEV_FOUND="yes"
            fi
        done
        if [[ "$GI_DEV_FOUND" == "no" ]]; then
            SYSTEM_PACKAGES+=("${GI_DEVELOPMENT_PACKAGES[1]}")
        fi
        SYSTEM_PACKAGES+=("${APPINDICATOR_PACKAGES[0]}")
    fi

    if [[ "$DISTRO_FAMILY" == "ubuntu" || "$DISTRO_FAMILY" == "debian" ]]; then
        local SHADER_PACKAGE="${SHADER_COMPILER_PACKAGES[1]}"
        local SHADER_CANDIDATE
        for SHADER_CANDIDATE in "${SHADER_COMPILER_PACKAGES[@]}"; do
            if apt-cache show "$SHADER_CANDIDATE" &>/dev/null 2>&1; then
                SHADER_PACKAGE="$SHADER_CANDIDATE"
                break
            fi
        done
        SYSTEM_PACKAGES+=("$SHADER_PACKAGE")

        local OPTIONAL_PACKAGE
        for OPTIONAL_PACKAGE in "${OPTIONAL_SYSTEM_PACKAGES[@]}"; do
            if apt-cache show "$OPTIONAL_PACKAGE" &>/dev/null 2>&1; then
                SYSTEM_PACKAGES+=("$OPTIONAL_PACKAGE")
            fi
        done
    fi

    local MISSING_PACKAGES=""
    local INSTALL_CMD=""
    local UPDATE_CMD=""

    case "$DISTRO_FAMILY" in
        ubuntu|debian)
            # Check for missing packages
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
                if ! apt_package_installed "$pkg"; then
                    MISSING_PACKAGES="$MISSING_PACKAGES $pkg"
                fi
            done

            if [ -n "$MISSING_PACKAGES" ]; then
                print_info "Installing missing packages:$MISSING_PACKAGES"
                sudo apt update || { print_error "Failed to update package lists"; exit "$EXIT_NETWORK"; }

                # Handle appindicator package for Ubuntu (old package deprecated in newer releases)
                if [[ "$DISTRO_FAMILY" == "ubuntu" ]] && echo "$MISSING_PACKAGES" | grep -q "${APPINDICATOR_PACKAGES[0]}"; then
                    FILTERED_PACKAGES=$(echo "$MISSING_PACKAGES" | sed "s/${APPINDICATOR_PACKAGES[0]}//" | xargs)

                    if ! DEBIAN_FRONTEND=noninteractive sudo apt install -y "${APPINDICATOR_PACKAGES[0]}" 2>/dev/null; then
                        print_info "${APPINDICATOR_PACKAGES[0]} not available, trying ${APPINDICATOR_PACKAGES[1]}..."
                        if ! DEBIAN_FRONTEND=noninteractive sudo apt install -y "${APPINDICATOR_PACKAGES[1]}"; then
                            print_error "Failed to install appindicator package (tried both ${APPINDICATOR_PACKAGES[*]})"
                            exit "$EXIT_MISSING_DEPS"
                        fi
                        print_info "Successfully installed ${APPINDICATOR_PACKAGES[1]} (modern replacement)"
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
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
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

            install_preferred_appindicator "$INSTALL_CMD" "${APPINDICATOR_PACKAGES[0]}" "${APPINDICATOR_PACKAGES[1]}" dnf_package_installed || exit "$EXIT_MISSING_DEPS"
            ;;

        arch)
            # For Arch-based systems
            if ! command_exists pacman; then
                print_error "Pacman package manager not found"
                exit "$EXIT_MISSING_DEPS"
            fi

            # Check for missing packages
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
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

            install_preferred_appindicator "sudo pacman -S --noconfirm" "${APPINDICATOR_PACKAGES[0]}" "${APPINDICATOR_PACKAGES[1]}" pacman_package_installed || exit "$EXIT_MISSING_DEPS"
            ;;

        suse)
            # For openSUSE
            if ! command_exists zypper; then
                print_error "Zypper package manager not found"
                exit "$EXIT_MISSING_DEPS"
            fi

            sudo zypper refresh || true

            if [[ "${SELECTED_ENGINE:-whisper_cpp}" == "whisper_cpp" && "${WHISPERCPP_BACKEND:-}" != "cpu" ]]; then
                SYSTEM_PACKAGES+=("${VULKAN_PACKAGES[@]}")
            fi

            local MISSING_ZYPPER_PACKAGES=()
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
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

            read -r -a PY_PIP_CANDIDATES <<< "$(suse_python_package_candidates "$PYTHON_PIP_SUFFIX")"
            read -r -a PY_GOBJECT_CANDIDATES <<< "$(suse_python_package_candidates "$PYTHON_GOBJECT_SUFFIX")"
            read -r -a PY_GOBJECT_CAIRO_CANDIDATES <<< "$(suse_python_package_candidates "$PYTHON_GOBJECT_CAIRO_SUFFIX")"
            read -r -a PY_DEVEL_CANDIDATES <<< "$(suse_python_package_candidates "$PYTHON_DEVEL_SUFFIX")"
            read -r -a PY_VIRTUALENV_CANDIDATES <<< "$(suse_python_package_candidates "$PYTHON_VIRTUALENV_SUFFIX")"
            read -r -a PY_VENV_CANDIDATES <<< "$(suse_python_package_candidates "$PYTHON_VENV_SUFFIX")"

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
                print_error "Try manually: sudo zypper install ${APPINDICATOR_PACKAGES[0]} ${APPINDICATOR_PACKAGES[3]}"
                exit "$EXIT_MISSING_DEPS"
            fi

            if [[ "${SELECTED_ENGINE:-whisper_cpp}" == "whisper_cpp" && "${WHISPERCPP_BACKEND:-}" != "cpu" ]]; then
                if ! suse_shader_compiler_available; then
                    if ! suse_install_first_available "Vulkan shader compiler" "${SHADER_COMPILER_PACKAGES[@]}"; then
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
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
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
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
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
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
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
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
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
            for pkg in "${SYSTEM_PACKAGES[@]}"; do
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

# Function to detect and install text input tools
install_text_input_tools() {
    if [[ "$SKIP_SYSTEM_DEPS" == "yes" ]]; then
        print_warning "Skipping text input tool installation (--skip-system-deps specified)."
        return 0
    fi

    # Unsupported distros can continue past install_system_dependencies in
    # non-interactive mode, but they have no generated package inventory.
    if [[ -z "${XDOTOOL_PACKAGES+x}" ]]; then
        print_warning "No text input package map is available for $DISTRO_NAME."
        print_warning "Install xdotool or wtype manually for your display server."
        return 0
    fi

    local XDOTOOL_PKG="${XDOTOOL_PACKAGES[0]}"
    local WTYPE_PKG="${WTYPE_PACKAGES[0]}"
    local YDOTOOL_PKG="${YDOTOOL_PACKAGES[0]}"

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
                    if ! apt_package_installed "$WTYPE_PKG"; then
                        DEBIAN_FRONTEND=noninteractive sudo apt install -y "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                fedora)
                    if command_exists dnf && ! dnf_package_installed "$WTYPE_PKG"; then
                        sudo dnf install -y "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    elif command_exists yum && ! rpm -q "$WTYPE_PKG" &>/dev/null; then
                        sudo yum install -y "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                arch)
                    if ! pacman_package_installed "$WTYPE_PKG"; then
                        sudo pacman -S --noconfirm "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                suse)
                    sudo zypper install -y "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    ;;
                gentoo)
                    if ! qlist -I "$WTYPE_PKG" >/dev/null 2>&1; then
                        sudo emerge "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                alpine)
                    if ! apk info -e "$WTYPE_PKG" >/dev/null 2>&1; then
                        sudo apk add "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                void)
                    if ! xbps-query "$WTYPE_PKG" >/dev/null 2>&1; then
                        sudo xbps-install -Sy "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                solus)
                    if ! eopkg list-installed | grep -qw "$WTYPE_PKG"; then
                        sudo eopkg install "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    else
                        print_info "wtype is already installed."
                    fi
                    ;;
                mageia)
                    if command_exists dnf && ! rpm -q "$WTYPE_PKG" >/dev/null 2>&1; then
                        sudo dnf install -y "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
                    elif command_exists urpmi && ! rpm -q "$WTYPE_PKG" >/dev/null 2>&1; then
                        sudo urpmi -y "$WTYPE_PKG" || { print_warning "Failed to install wtype. Text injection may not work properly."; }
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
                    if ! apt_package_installed "$YDOTOOL_PKG"; then
                        if ! DEBIAN_FRONTEND=noninteractive sudo apt install -y "$YDOTOOL_PKG" 2>/dev/null; then
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
                        sudo dnf install -y "$YDOTOOL_PKG" 2>/dev/null || print_info "ydotool not available in repos (optional)"
                    fi
                    ;;
                arch)
                    if ! pacman_package_installed "$YDOTOOL_PKG"; then
                        sudo pacman -S --noconfirm "$YDOTOOL_PKG" 2>/dev/null || print_info "ydotool not available in repos (optional)"
                    fi
                    ;;
            esac

            # Add user to input group for ydotool/dotool support
            if ! groups | grep -q '\binput\b'; then
                print_info "Adding $USER to 'input' group for text injection..."
                sudo usermod -aG input "$USER" || print_warning "Failed to add user to input group"
                print_warning "You will need to LOG OUT and back in for text injection to work with ydotool/dotool"
            fi

            # Install udev rule for ydotool/dotool — and for the evdev
            # backend's uinput clone, which opens /dev/uinput O_RDWR, so the
            # rule needs 0660 (0620 is write-only). Appending (not overwriting)
            # preserves any rules the user already keeps in this file; when an
            # older MODE=0620 line is present our later line still wins.
            UINPUT_UDEV_RULE='KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"'
            if ! grep -qxF "$UINPUT_UDEV_RULE" /etc/udev/rules.d/80-dotool.rules 2>/dev/null; then
                print_info "Installing udev rule for input device access..."
                printf '\n%s\n' "$UINPUT_UDEV_RULE" \
                    | sudo tee -a /etc/udev/rules.d/80-dotool.rules >/dev/null 2>&1 || print_warning "Failed to install udev rule"
                sudo udevadm control --reload 2>/dev/null || true
                sudo udevadm trigger 2>/dev/null || true
            fi
            ;;

        x11|"")
            print_info "Installing X11 text input tools..."
            case "$DISTRO_FAMILY" in
                ubuntu|debian)
                    if ! apt_package_installed "$XDOTOOL_PKG"; then
                        DEBIAN_FRONTEND=noninteractive sudo apt install -y "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                fedora)
                    if command_exists dnf && ! dnf_package_installed "$XDOTOOL_PKG"; then
                        sudo dnf install -y "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    elif command_exists yum && ! rpm -q "$XDOTOOL_PKG" &>/dev/null; then
                        sudo yum install -y "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                arch)
                    if ! pacman_package_installed "$XDOTOOL_PKG"; then
                        sudo pacman -S --noconfirm "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                suse)
                    sudo zypper install -y "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    ;;
                gentoo)
                    if ! qlist -I "$XDOTOOL_PKG" >/dev/null 2>&1; then
                        sudo emerge "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                alpine)
                    if ! apk info -e "$XDOTOOL_PKG" >/dev/null 2>&1; then
                        sudo apk add "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                void)
                    if ! xbps-query "$XDOTOOL_PKG" >/dev/null 2>&1; then
                        sudo xbps-install -Sy "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                solus)
                    if ! eopkg list-installed | grep -qw "$XDOTOOL_PKG"; then
                        sudo eopkg install "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    else
                        print_info "xdotool is already installed."
                    fi
                    ;;
                mageia)
                    if command_exists dnf && ! rpm -q "$XDOTOOL_PKG" >/dev/null 2>&1; then
                        sudo dnf install -y "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
                    elif command_exists urpmi && ! rpm -q "$XDOTOOL_PKG" >/dev/null 2>&1; then
                        sudo urpmi -y "$XDOTOOL_PKG" || { print_warning "Failed to install xdotool. Text injection may not work properly."; }
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
                    DEBIAN_FRONTEND=noninteractive sudo apt install -y "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                fedora|mageia)
                    if command_exists dnf; then
                        sudo dnf install -y "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    elif command_exists yum; then
                        sudo yum install -y "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    fi
                    # Mageia also supports urpmi
                    if [[ "$DISTRO_FAMILY" == "mageia" ]] && command_exists urpmi; then
                        sudo urpmi -y "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    fi
                    ;;
                arch)
                    sudo pacman -S --noconfirm "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                suse)
                    sudo zypper install -y "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                gentoo)
                    sudo emerge "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                alpine)
                    sudo apk add "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                void)
                    sudo xbps-install -Sy "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                solus)
                    sudo eopkg install "$XDOTOOL_PKG" "$WTYPE_PKG" || { print_warning "Failed to install text input tools. Text injection may not work properly."; }
                    ;;
                *)
                    print_warning "Unsupported distribution for text input tools."
                    print_warning "Please install 'xdotool' and 'wtype' manually for text input support."
                    ;;
            esac
            ;;
    esac
}
