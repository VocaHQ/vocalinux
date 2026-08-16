# Updating Vocalinux

This guide explains how to update Vocalinux to the latest version.

## What's New in v0.15.0

0.15.0 is a **minor** release on the stable line. It redesigns settings navigation, adds AppImage packages, expands the speech-language catalog (Hungarian and many more), cleans up continuous dictation spacing/capitalization, adds power/GPU controls, and improves Wayland IBus on compositors that ship `ibus-wayland`, on top of the 0.14 packaging work (Flatpak, AUR, configurable hotkeys).

### Highlights

| Feature | Description |
|---------|-------------|
| **Searchable settings** | Sidebar navigation with search replaces the seven-tab notebook (#601) |
| **AppImage** | Self-contained x86_64 and aarch64 builds attached to GitHub Releases (#573, #602) |
| **Language catalog** | ~33 selectable speech languages plus Auto-detect (incl. Hungarian); CLI choices derived from the same catalog; VOSK hides Whisper-only langs (#616, fixes #565) |
| **Dictation polish** | Auto-capitalize after `.` / `!` / `?`; append a trailing space after each completed utterance (#554, #608) |
| **Auto-pause + keep-alive** | Unload the model while configured apps run, or after an idle timeout (#592) |
| **Vulkan GPU selection** | Prefer a discrete GPU automatically; pick a device under Advanced settings (#590) |
| **ibus-wayland** | Prefer IBus on previously “unbridged” compositors when `ibus-wayland` is running (#614) |
| **CLI `--version`** | Print the installed version and exit (#563) |

### New Features

- **Searchable sidebar settings** — Topic pages in a sidebar with live search instead of seven notebook tabs (#601)
- **AppImage packaging** — Relocatable x86_64 and aarch64 AppImages built in the release workflow (#573, #602)
- **Expanded speech languages** — Hungarian plus many high-demand Whisper languages in Settings/CLI; official Alphacephei VOSK models where available; Whisper-only languages stay hidden in the VOSK dropdown (#616 by @jatinkrmalik, fixes #565)
- **Sidebar dictation controls** — Recognition status, mic level, Test Dictation, and Close stay visible in the settings sidebar footer while switching pages (#618)
- **Sentence capitalization** — Capitalize at the start of dictation and after sentence-ending punctuation (#554, closes #553)
- **Trailing space between utterances** — Completed transcriptions leave a trailing space so the next session does not glue onto the previous sentence (#608, fixes #605)
- **Auto-pause apps + model keep-alive** — Optional unload while selected processes run; idle timeout unload for battery/Optimus laptops (#592, closes #445, #591)
- **Vulkan discrete GPU auto-select + manual device** — Prefer discrete devices; override in Advanced settings (#590, closes #589)
- **IBus via ibus-wayland** — On compositors previously treated as unbridged, use IBus when `ibus-wayland` is available (#614 by @eiseleb47, closes #607)
- **`vocalinux --version`** — Print package version (#563, closes #555)

### Bug Fixes

- **Settings**: Restore Custom Shortcut entry / Record / Set controls after the sidebar settings refactor (#619)
- **Languages**: Map English (India) (`en-in`) to Whisper code `en` for whisper.cpp / Whisper / remote API (#617)
- **Audio**: Stop Bluetooth mic probing from corrupting the heap — one PortAudio open per capture session, stop-before-close, no stereo probe on mono-only devices (#599, fixes #567)
- **IBus**: Keep engine teardown correct when parent `do_destroy` fails (#613 by @eiseleb47, fixes #606)
- **Settings UI**: Flatten info notices so helper text matches the rest of the dialog (#615)
- **KDE Plasma Wayland**: Skip unbridged IBus when `ibus-wayland` is not present so injection does not silently fail (#577, fixes #574)
- **xdotool**: Preserve input focus after injection (#564, fixes #549)
- **Uninstall**: Remove IBus data dir; stop the app by PID file; remove `~/.local/bin` launcher wrappers reliably (#597, #569)
- **Installer**: Prefer both libgirepository 1.0 and 2.0 when present (#583, fixes #571)
- **AUR**: Virtual `python-pywhispercpp` dependency; clipboard/wtype tools as optdepends (#579, #586)
- **UI**: First-run dialog response without `Gtk.Dialog.do_response` (#580, fixes #566)
- **Vosk**: Italian and English-India entries in medium/large model tables (#551, fixes #550)
- **Docs**: Correct ydotool service setup guidance (#560, fixes #557)

### Docs / website

- Marketing site redesign with workstation craft (#582)
- Languages marketing page with honest per-engine badges (#616)
- Multi-distro tray icon FAQ (#584)
- robots.txt no longer blocks indexable pages (#610)
- Website CI lint / action warning cleanup (#611)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.15.0).

---

## What's New in v0.14.2

0.14.2 is a stability patch on the **0.14 series**. The feature set is the same as 0.14.x; this release fixes IBus reliability and settings dialog sizing.

### 0.14 series highlights

| Feature | Description |
|---------|-------------|
| **Configurable Shortcuts** | Bind any modifier combination to a key — e.g. `Alt+R`, `Ctrl+Shift+V`, or `Super+F10` |
| **FunASR / SenseVoice Remote API** | Remote-API engine supports FunASR and SenseVoice via OpenAI-compatible endpoints |
| **Flatpak packaging** | Universal Flatpak (whisper.cpp) with sandbox-aware paths, global hotkeys, and Wayland paste injection |
| **AUR package** | Official Arch packaging and CI publish path |
| **Layout-aware hotkeys** | Combo keys respect non-US layouts |
| **Wayland / IBus reliability** | GNOME and KDE injection fixes, first-dictation FocusIn gate, engine process launch restored |
| **Audio / hybrid-CPU** | Recording device-index crash fixed; whisper.cpp no longer defaults to all cores on hybrid CPUs |

### Bug fixes in v0.14.2

- **IBus**: Restore engine process launch after the Flatpak XDG path import change. `start_engine_process` and the IBus component exec run `ibus_engine.py` by path, so the relative import failed with `ImportError` and Vocalinux fell back to ydotool/clipboard paste (#534)
- **IBus**: Wait for FocusIn before commit on scoped injection. Cold first activation on GNOME Wayland could commit before mutter bound a client context, so the first dictation of a session was dropped while logs still reported success (#533, fixes #523)
- **Settings UI**: Wrap each notebook tab in a vertical ScrolledWindow so the dialog fits 1080p monitors instead of growing past the screen; forward wheel events from unfocused combos/spins to the tab scroller and drop nested Advanced ScrolledWindow shadows (#538, #541)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.14.2).

---

## What's New in v0.14.1

### Highlights

| Feature | Description |
|---------|-------------|
| **Flatpak packaging** | Universal Flatpak (whisper.cpp) with sandbox-aware paths, global hotkeys, and Wayland paste injection |
| **AUR package** | Official Arch packaging and CI publish path |
| **Layout-aware hotkeys** | Combo keys respect non-US layouts |
| **Installer / injection fixes** | `sg` on Ubuntu 26.04/Debian 13; XIM `none` treated as unset |

### New Features

- **Flatpak packaging** — GNOME Platform 50, whisper.cpp + Vulkan, ydotool/wl-copy injection, evdev global shortcuts; build via `packaging/flatpak/` (#484, closes #167)
- **AUR release package** — PKGBUILD and CI publish for Arch Linux (#518)

### Bug Fixes

- **Hotkeys**: Layout-aware combo keys for non-US layouts (#514)
- **Installer**: `sg` not found on Ubuntu 26.04 / Debian 13 (#524)
- **Text injection**: Treat XIM `none` as unset (#512)
- **Web**: Dependabot npm alerts in package-lock (#515)

### Docs

- Refreshed v0.14 UI screenshots and website gallery (#521)
- README Star History and related polish

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.14.1).

---

## What's New in v0.14.0-beta

### Highlights

| Feature | Description |
|---------|-------------|
| **Configurable Shortcuts** | Bind any modifier combination to a key — e.g. `Alt+R`, `Ctrl+Shift+V`, or `Super+F10` |
| **FunASR / SenseVoice Remote API** | Remote-API engine now supports FunASR and SenseVoice models via OpenAI-compatible endpoints |
| **GNOME Wayland IBus Reliability** | Text injection works again on GNOME Wayland with bare `xkb` layouts and engine restore fallbacks are fixed |
| **Audio Crash Fix** | Recording no longer crashes when the system audio device index changes between sessions |
| **Hybrid-CPU Efficiency** | whisper.cpp no longer defaults to all cores on hybrid Intel/AMD processors |

### ✨ New Features

- **Configurable modifier+key hotkeys** — The Settings dialog now lets you set custom shortcuts using any combination of Ctrl, Alt, Shift, and Super plus a letter/number key. The legacy defaults still work, and you can now bind combinations like `Alt+R` or `Ctrl+Shift+V` (#493)
- **Remote API FunASR/SenseVoice support** — OpenAI-compatible remote endpoints can specify FunASR/SenseVoice model names (e.g. `sensevoice`) and return richer response shapes; SenseVoice metadata labels are stripped before text injection (#468)

### 🐛 Bug Fixes

- **GNOME Wayland/IBus**: Restore text injection when only a bare `xkb` engine is configured; the engine restore fallback now picks the correct IM engine instead of silently dropping text (#506, #500)
- **KDE Wayland/IBus**: Restore the KDE Plasma Wayland IBus text-injection path that was regressed in recent compositor-detection changes (#502)
- **Wayland injection**: Wait for held modifiers (Ctrl/Alt/Shift/Super) to release before injecting text, preventing accidental shortcut triggers and garbled output on modifier-heavy workflows (#494)
- **Shortcuts UI**: Keep preset and custom shortcut selection exclusive — selecting a preset now clears the custom field, and setting a custom combo selects the "Custom Shortcut" preset (#509)
- **whisper.cpp**: Stop defaulting to all CPU cores on hybrid processors (Intel Performance + Efficient cores), which caused UI lag and excess battery drain (#492)
- **Audio**: Fix a crash on recording start when the selected audio device index no longer matches the current system enumeration (#499)
- **Installer**: Include `xsel` as a fallback for the Wayland clipboard path when `xclip` is unavailable (#496)

### 🔧 Improvements

- **Code style** — Removed an outdated long comment about whisper.cpp default thread counts (#505)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.14.0-beta).

---

## What's New in v0.13.0-beta

### 🚀 Highlights

| Feature | Description |
|---------|-------------|
| **🎙️ Guided Whisper Models** | Pick a whisper.cpp size and specialization (English-only, quantized, Turbo) with in-app guidance |
| **🔌 Hotplug Keyboard Support** | Shortcuts keep working on keyboards connected after startup |
| **✍️ Dictation Spacing** | Spacing preserved between speech segments separated by a pause in the same session |
| **🖥️ Wayland Reliability** | Fixes silent text drops on wlroots/COSMIC compositors and garbled non-US-layout output |

### ✨ New Features

- **Guided whisper.cpp model variants** — The Settings dialog now splits whisper.cpp selection into **Model Size** and **Specialization**, exposing English-only, quantized (Q5/Q8), Large v3 Turbo, and legacy large models with language-aware recommendations and hover guidance. Exact model IDs (e.g. `medium.en-q5_0`, `large-v3-turbo`) can also be passed to `--model` (#465)

### 🐛 Bug Fixes

- **Dictation**: Preserve spacing between speech segments separated by a pause (#464)
- **Shortcuts**: Rescan for hotplugged keyboards so shortcuts work on devices connected after startup (#467)
- **KDE Plasma Wayland**: Detect KDE Plasma Wayland sessions and guide you to enable IBus Wayland when `wtype` injection fails (#466)
- **Wayland**: Fix garbled output on non-US keyboard layouts and a clipboard-copy hang; ydotool now pastes through the clipboard (#480)
- **Wayland/IBus**: Use wtype/ydotool instead of IBus on compositors that don't bridge IBus to native apps like COSMIC, Sway, and Hyprland (#486)
- **Wayland/IBus**: Require a real IM engine on Wayland so a bare `xkb` layout no longer causes silent text drops on GNOME/Mutter and similar (#478)
- **Wayland**: Preserve the keyboard layout on Wayland by not running `setxkbmap` (was flipping XWayland apps to `us`) (#474)
- **UI**: Cap the settings dialog height on high-resolution displays (#465)

### 🔧 Improvements

- **Performance**: Faster ydotool text injection via an explicit `--key-delay` (#488)
- **Website**: New documentation pages for Remote API, Silero VAD, advanced whisper.cpp settings, and desktop reliability (#470)
- **CI**: Automatic pull-request labeling by changed files (#473)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.13.0-beta).

---

## What's New in v0.12.0-beta

### 🚀 Highlights

| Feature | Description |
|---------|-------------|
| **🌐 Remote API Engine** | New backend for compatible remote transcription services |
| **🎙️ Silero VAD** | Neural VAD drops silence-only buffers for cleaner dictation |
| **🧵 Thread Safety** | Hardened Remote API, IBus, and text injection threading behavior |
| **🔌 IBus Reliability** | Preserves user engines for dead keys and scoped activation |
| **⚙️ Settings Polish** | Advanced-only Remote Server controls and lower dialog height |
| **📦 Installer & Models** | CUDA auto-remediation and corrected model download metadata |

### ✨ New Features

- **Remote API speech recognition engine** — Configure compatible remote transcription services alongside local engines (#335)
- **Silero VAD** — Neural voice activity detection filters silence-only buffers when ONNX Runtime support is installed (#447)

### 🐛 Bug Fixes

- **Threading**: Harden Remote API, IBus, and text injection thread safety (#452)
- **IBus**: Preserve user engines for dead keys and capture the current engine during scoped activation (#457, #458)
- **UI**: Keep the Remote Server section behind the Advanced toggle and reduce settings dialog height (#454, #456)
- **Installer**: Harden CUDA diagnostics with auto-remediation and behavioral tests (#451)
- **Models**: Correct whisper.cpp and VOSK download size metadata (#453)
- **Startup**: Allow launch without the pynput backend (#448)
- **Website**: Clarify speech demo browser support (#449)

### 🔧 Improvements

- **Developer docs** — Remote API test server instructions for backend testing (#455)
- **Community** — GitHub Sponsors funding configuration added
- **Behavioral coverage** — CUDA diagnostics and release-facing reliability fixes include targeted tests

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.12.0-beta).

---

## What's New in v0.10.2-beta

### 🚀 Highlights

| Feature | Description |
|---------|-------------|
| **🌍 Non-ASCII Text Injection** | ydotool now falls back to clipboard paste for non-ASCII characters (á, é, ñ, etc.) |
| **🔌 IBus on Wayland** | IBus now detected and started correctly on Wayland without legacy env vars |
| **🚀 IBus Engine Startup** | Engine process now starts before registration check — fixes startup on some systems |
| **📦 Pop!\_OS / Ubuntu 24.04+** | Added missing system dependencies (cmake, libcairo2-dev, libgirepository1.0-dev) |
| **⚡ Code Quality** | Systematic refactor across 20 quality dimensions |
| **🖼️ Website OG Image** | Redesigned Open Graph image — cleaner and more professional |

### 🐛 Bug Fixes

- **#362 / #376**: Handle non-ASCII characters with ydotool via clipboard paste fallback
- **#360 / #361**: Start IBus engine process before checking registration
- **#381**: Detect IBus on Wayland without legacy env vars and fix text injection
- **#379**: Add missing dependencies for Pop!_OS and Ubuntu 24.04+

### 🔧 Improvements

- Systematic code quality refactor across 20 dimensions (#377)
- Clarify missing GNOME AppIndicator support on Debian (#385)
- Redesigned OG image for vocalinux.com (#392)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.10.2-beta).

---

## What's New in v0.10.1-beta

### 🚀 Highlights

| Feature | Description |
|---------|-------------|
| **🖼️ Tray Resource Reliability** | Bundled package resources now prevent missing system tray icons |
| **🧠 Engine Switch Safety** | Recognition now stops before engine changes to avoid segfaults |
| **⌨️ Keyboard Layout Preservation** | XKB layout is preserved when activating the Vocalinux IBus engine |
| **🪟 Settings Dialog Compatibility** | Added an explicit Close button for improved WM interoperability |
| **⚡ Suspend/Resume Recovery** | App now automatically recovers speech recognition and keyboard shortcuts after system suspend/resume |
| **🎤 Push-to-Talk Reliability** | Fixed premature transcription triggering on silence during push-to-talk mode |

### ✨ Scope

- **Patch-focused release** — No new feature surface; this version is dedicated to stability and compatibility fixes
- **Desktop reliability hardening** — Improved behavior across tray, engine switching, settings dialog actions, and keyboard layout handling
- **Suspend/Resume stability** — New D-Bus handler ensures app survives system sleep cycles

### 🐛 Bug Fixes

- **#349 / #354**: Bundle resources in package to fix missing system tray icons
- **#350 / #355**: Stop recognition before switching engines to prevent segfaults
- **#323 / #356**: Add Close button to settings dialog for WM compatibility
- **#292 / #343**: Preserve XKB layout when activating Vocalinux IBus engine
- **#359**: Prevent premature transcription during push-to-talk silence
- **#367 / #369**: Auto-recover speech recognition after system resume via new suspend handler
- **#371**: Restart keyboard shortcut backend after system resume
- **#372**: Delay keyboard restart to allow USB device re-enumeration after resume

### 🔧 Improvements

- Bumped npm/yarn dependency group across the web workspace (#346)
- Bumped `brace-expansion` in development dependencies (#357)
- Disabled copy-to-clipboard by default in Settings (#370)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.10.1-beta).

---

## What's New in v0.9.0-beta

### 🚀 Highlights

| Feature | Description |
|---------|-------------|
| **⌨️ Left/Right Modifier Keys** | Choose Left Ctrl vs Right Ctrl (etc.) as your shortcut trigger |
| **🔔 Sound Effects Toggle** | Enable or disable audio feedback from the Settings dialog |
| **📋 Wayland Clipboard Fallback** | Automatic clipboard copy when virtual keyboard injection isn't available |
| **🛠️ Installation Polish** | Better pipx/Debian guidance and headless display detection |

### ✨ New Features

- **Left/Right Modifier Key Distinction** — Shortcuts now support `Left Ctrl`, `Right Alt`, etc., with grouped UI in Settings
- **Sound Effects Toggle** — New Audio Settings toggle to silence start/stop/error sounds
- **Clipboard Fallback for Wayland** — Auto-copies text via `wl-copy`/`xclip` when injection unavailable (KDE Plasma etc.)
- **Display Availability Check** — Graceful error message when running in headless environments

### 🐛 Bug Fixes

- **#308**: Distinguish left vs right modifier keys (evdev + pynput backends)
- **#307**: Remove unwanted leading space when starting a new transcription session
- **#305**: Pass configured shortcut mode to `KeyboardShortcutManager` on startup
- **#299**: Add clipboard fallback for Wayland compositors without virtual keyboard support
- **#289**: Improve Debian/pipx installation error messages and cross-distro dependency guidance

### 🔧 Improvements

- **Grouped shortcut selector** — Settings dropdown now organises shortcuts by Either/Left/Right side
- **pipx documentation** — New `DISTRO_COMPATIBILITY.md` section for pipx users

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.9.0-beta).

---

## What's New in v0.8.0-beta

### 🚀 Highlights

| Feature | Description |
|---------|-------------|
| **🎤 Push-to-Talk Mode** | Hold the shortcut key to speak, release to stop |
| **⚙️ Voice Commands Toggle** | Enable or disable voice commands, with VOSK auto-enable in auto mode |
| **⌨️ Shortcut Reliability** | Improved callback lifecycle and mode switching stability |
| **🧠 Input Compatibility** | Better IBus detection and audio device/channel compatibility |

### ✨ New Features

- **Push-to-Talk Shortcut Mode** — Added hold-to-speak mode alongside double-tap toggle mode
- **Mode-aware Shortcut UI** — Updated settings text and behavior for toggle vs push-to-talk workflows
- **Voice Commands Optional** — Voice commands can be disabled, with automatic enable behavior for VOSK

### 🐛 Bug Fixes

- **#277**: Detect active IBus input method before using IBus injection
- **#275**: Detect and use device-supported channel count
- **#268**: Prevent GTK startup dialog crash on Fedora
- **#261**: Resolve text injection issues for better reliability
- **#259**: Prevent recognition thread state flicker
- **#262/#263**: Auto-detect audio sample rate for better hardware compatibility

### 🔧 Improvements

- **Web SEO Enhancements** — Added 8 additional optimized pages for discoverability
- **Homepage Refresh** — Updated voice-themed visual polish on the web landing page

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.8.0-beta).

---

## Quick Update

Vocalinux checks GitHub Releases in the background about every six hours (and shortly after startup). When a newer build is on your selected channel, the tray menu gains an **Update Available…** entry and Settings → About shows a green **New** badge; open that page for release notes and download links. Updates are not installed automatically — re-run the installer (or your package manager) as below.

### If You Installed via curl (Recommended)

Simply re-run the installation command:

```bash
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh | bash
```

The installer will:
- ✅ Detect and stop any running Vocalinux processes
- ✅ Update your existing installation
- ✅ Preserve your configuration and models
- ✅ Install any new dependencies
- ✅ Attempt to install neural VAD support, falling back safely if ONNX Runtime is unavailable

### If You Installed from Source

```bash
cd vocalinux
git fetch origin
git checkout v0.15.0
./install.sh
```

Or to get the latest development version:

```bash
cd vocalinux
git pull origin main
./install.sh
```

---

## Checking Your Current Version

```bash
python3 -c "import vocalinux; print(vocalinux.version.__version__)"
```

---

## Troubleshooting

### Update Issues?

If your update doesn't go smoothly, try a clean reinstall:

```bash
# Uninstall (keeps your config and models by default)
./uninstall.sh --keep-config --keep-data

# Or uninstall completely
./uninstall.sh

# Reinstall fresh
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh | bash
```

### Old Version Still Running

```bash
# Prefer stopping from the tray, or kill by the PID in the lock file:
kill "$(tr -d '[:space:]' < "${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux/instance.lock")"

# If you used IBus injection, also stop the engine:
kill "$(tr -d '[:space:]' < "${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux-ibus/engine.pid")"

# Start fresh
vocalinux
```

Avoid `pkill -f vocalinux` — it matches any process whose command line
mentions the repo path (editors, shells, test runners) and can kill unrelated work.

### Missing Dependencies

If you see dependency errors:

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0

# Fedora
sudo dnf install -y python3-gobject gtk3

# Arch
sudo pacman -S python-gobject gtk3
```

---

## Need Help?

- 📖 [Installation Guide](INSTALL.md)
- 🐛 [Report Issues](https://github.com/VocaHQ/vocalinux/issues)
- 💬 [Discussions](https://github.com/VocaHQ/vocalinux/discussions)
