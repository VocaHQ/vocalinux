#!/bin/bash
# Sourced by install.sh after it has resolved the local or tagged repository.
# Keep this file declarative: function definitions only, with no top-level actions.

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
