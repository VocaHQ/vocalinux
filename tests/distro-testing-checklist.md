# Distribution Testing Checklist

Use this checklist when testing Vocalinux on a new Linux distribution.

## Pre-Installation

### System Information
- [ ] Record distribution name and version
  ```bash
  cat /etc/os-release
  ```

- [ ] Record desktop environment
  ```bash
  echo $XDG_CURRENT_DESKTOP
  ```

- [ ] Record display server
  ```bash
  echo $XDG_SESSION_TYPE
  echo $WAYLAND_DISPLAY  # For Wayland
  echo $DISPLAY          # For X11
  ```

- [ ] Record architecture
  ```bash
  uname -m
  ```

- [ ] Run the dependency checker
  ```bash
  bash scripts/check-system-deps.sh
  ```

- [ ] Note missing packages
- [ ] Note any special requirements (musl libc, specific library versions, etc.)

## Installation

### Standard Installation
- [ ] Download installer
  ```bash
  curl -fsSL https://raw.githubusercontent.com/jatinkrmalik/vocalinux/main/install.sh -o /tmp/vl.sh
  ```

- [ ] Run installer
  ```bash
  bash /tmp/vl.sh
  ```

- [ ] Check for errors during installation
- [ ] Verify virtual environment was created
  ```bash
  ls -la ~/.local/share/vocalinux/venv/
  ```

- [ ] Check wrapper scripts exist
  ```bash
  ls -la ~/.local/bin/vocalinux*
  ```

- [ ] Check desktop entry was created
  ```bash
  ls -la ~/.local/share/applications/vocalinux.desktop
  ```

- [ ] Check icons were installed
  ```bash
  ls -la ~/.local/share/icons/hicolor/scalable/apps/vocalinux*
  ```

## Post-Installation

### Launch from Terminal
- [ ] Launch from terminal
  ```bash
  ~/.local/bin/vocalinux-gui
  ```

- [ ] Check for startup errors
- [ ] Verify the application starts
- [ ] Check that tray icon appears
- [ ] Verify keyboard shortcut works (Hold Right Alt by default)

### Launch from Application Menu
- [ ] Launch from desktop environment's application menu
- [ ] Verify the application starts
- [ ] Check that tray icon appears

### Core Functionality Tests

#### Tray Icon and Menu
- [ ] Left-click tray icon opens menu
- [ ] Right-click tray icon opens settings menu
- [ ] "Start Recording" menu item works
- [ ] "Stop Recording" menu item works
- [ ] "Settings" menu item opens settings dialog
- [ ] "Quit" menu item exits the application

#### Keyboard Shortcuts
- [ ] Default shortcut (Hold Right Alt) starts push-to-talk recording
- [ ] Custom shortcuts can be configured in Settings
- [ ] Shortcut works in different applications (terminal, text editor, browser)

#### Audio Recording
- [ ] Recording starts without errors
- [ ] Default audio device is detected
  ```bash
  # Check audio devices
  pactl list sources short  # PulseAudio
  # or
  arecord -l                 # ALSA
  ```

- [ ] Audio levels are adequate
- [ ] Start sound plays (ascending tone)
- [ ] Stop sound plays (descending tone)

#### Speech Recognition
- [ ] Speech is transcribed accurately
- [ ] Transcription appears in target application
- [ ] Punctuation works
- [ ] Capitalization works
- [ ] No backslash escapes in output (no \\', \\", etc.)

#### Text Injection

##### X11 (if applicable)
- [ ] Text injection works with xdotool
- [ ] Works in different applications:
  - [ ] Terminal (gnome-terminal, konsole, etc.)
  - [ ] Text editor (gedit, kate, mousepad, etc.)
  - [ ] Browser (Firefox, Chromium, etc.)
  - [ ] LibreOffice Writer
  - [ ] Chat applications (Discord, Telegram, etc.)

##### Wayland (if applicable)
- [ ] Text injection works with wtype
- [ ] Works in Wayland-native applications
- [ ] XWayland fallback works if needed
- [ ] Works in same applications as X11 test list

##### Universal (ydotool if available)
- [ ] Text injection works with ydotool
- [ ] Works across both X11 and Wayland

### Settings Dialog
- [ ] Settings dialog opens from tray menu
- [ ] Can configure audio input device
- [ ] Can configure keyboard shortcuts
- [ ] Can enable/disable sounds
- [ ] Can configure recognition engine (VOSK/Whisper)
- [ ] Can configure language
- [ ] Settings persist after restart
- [ ] Config file is created correctly
  ```bash
  cat ~/.config/vocalinux/config.json
  ```

### Model Download (if using Whisper)
- [ ] Model download works
- [ ] Download progress is shown
- [ ] Model is saved to correct location
  ```bash
  ls -la ~/.local/share/vocalinux/models/
  ```

### Error Handling
- [ ] Graceful handling when no microphone is available
- [ ] Graceful handling when text injection fails
- [ ] Error messages are helpful
- [ ] Application doesn't crash on errors

## Performance

- [ ] Application starts within reasonable time (< 5 seconds)
- [ ] Recording starts/stops responsively
- [ ] Transcription appears without significant lag
- [ ] Memory usage is reasonable
  ```bash
  # Check memory usage
  ps aux | grep vocalinux
  ```

- [ ] CPU usage is reasonable during idle
- [ ] CPU usage is reasonable during recording

## Cleanup and Uninstallation

- [ ] Application can be quit cleanly
- [ ] No processes left running
  ```bash
  ps aux | grep vocalinux
  ```

- [ ] Uninstallation works
  ```bash
  bash ~/.local/share/vocalinux/uninstall.sh  # if exists
  # or manual cleanup
  rm -rf ~/.local/share/vocalinux
  rm -rf ~/.config/vocalinux
  rm ~/.local/share/applications/vocalinux.desktop
  rm ~/.local/bin/vocalinux*
  ```

## Known Issues

Record any issues found during testing:

### Distribution-Specific Issues

| Issue | Severity | Workaround | Notes |
|-------|----------|------------|-------|
| | | | |

### Desktop Environment Issues

| DE | Issue | Severity | Workaround | Notes |
|----|-------|----------|------------|-------|
| GNOME | | | | |
| KDE Plasma | | | | |
| Xfce | | | | |
| sway | | | | |
| i3 | | | | |

### Application-Specific Issues

| Application | Issue | Severity | Workaround | Notes |
|-------------|-------|----------|------------|-------|
| Firefox | | | | |
| Chromium | | | | |
| LibreOffice | | | | |
| Terminal | | | | |

## Sign-Off

**Tester:** ____________________

**Date:** ____________________

**Distribution:** ____________________ ____________________

**Desktop Environment:** ____________________

**Display Server:** ____________________

**Overall Status:** ☐ Pass / ☐ Pass with Issues / ☐ Fail

**Additional Comments:**

---

## Submitting Results

After completing the checklist:

1. **Create a GitHub issue** with the title:
   `Distro Test Results: [Distribution Name] [Version]`

2. **Include the checklist** (either filled out or as a summary)

3. **Attach logs** if there were errors:
   - Installer output
   - Application output from terminal
   - Journal logs: `journalctl --user -u vocalinux -b`

4. **Mention any workarounds** you found

5. **Suggest improvements** to the documentation or installer

## Testing Tips

1. **Test early, test often** - Don't wait until everything is installed to test
2. **Keep notes** - Document everything, even things that seem minor
3. **Be thorough** - Test with multiple applications if possible
4. **Be patient** - Some distributions may require workarounds
5. **Share your findings** - Even negative results are valuable

## Quick Reference Commands

```bash
# Check distribution
cat /etc/os-release

# Check desktop environment
echo $XDG_CURRENT_DESKTOP

# Check display server
echo $XDG_SESSION_TYPE

# Check audio devices
pactl list sources short  # PulseAudio
arecord -l                 # ALSA

# Check for running processes
ps aux | grep vocalinux

# Check memory usage
ps aux | grep vocalinux | awk '{print $6}'

# Check logs
journalctl --user -b | grep vocalinux

# Run dependency checker
bash scripts/check-system-deps.sh

# Test installation
bash -n install.sh

# Verify installation
ls -la ~/.local/bin/vocalinux*
ls -la ~/.local/share/vocalinux/
ls -la ~/.config/vocalinux/
```
