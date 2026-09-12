# Updating Vocalinux

How to upgrade an existing install, plus release notes for the current series.

## Quick update

Vocalinux checks GitHub Releases in the background about every six hours (and shortly after startup). When a newer build is on your selected channel, the tray menu gains an **Update Available...** entry and Settings -> About shows a green **New** badge; open that page for release notes and download links. Updates are not installed automatically. Re-run the installer (or your package manager) as below.

### Official installer

```bash
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh
bash /tmp/vl.sh
```

The installer detects a running instance, updates in place, preserves configuration and models, and pulls new dependencies (including neural VAD when available).

### Installed from source

```bash
cd vocalinux
git fetch origin
git checkout v0.16.2
./install.sh
```

Latest development tree:

```bash
cd vocalinux
git pull origin main
./install.sh
```

### Other install methods

| Method | Upgrade |
|--------|---------|
| AUR | `yay -S vocalinux` (or your AUR helper) |
| AppImage | Download the new file from [Releases](https://github.com/VocaHQ/vocalinux/releases) |
| Snap | `sudo snap refresh vocalinux` (`--edge` until stable is promoted). **v0.16.2** has no `uinput` plug, so `snap connect vocalinux:uinput` fails and typing stays XWayland-only. After **0.17** is on edge, refresh, then `sudo snap connect vocalinux:uinput` for native Wayland apps. |
| Flatpak (release bundle) | Install the new `.flatpak` from Releases; bundles do not auto-update |
| PyPI | Reinstall in the same venv after system packages are current |

### Check your version

```bash
vocalinux --version
# or
python3 -c "import vocalinux; print(vocalinux.version.__version__)"
```

### Update problems

Clean reinstall (keeps config and models by default):

```bash
./uninstall.sh --keep-config --keep-data
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh
bash /tmp/vl.sh
```

If an old process is stuck, stop via the tray or the PID in the instance lock file (do not use `pkill -f vocalinux`; it can kill unrelated processes):

```bash
kill "$(tr -d '[:space:]' < "${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux/instance.lock")"
# If you use IBus injection:
kill "$(tr -d '[:space:]' < "${XDG_DATA_HOME:-$HOME/.local/share}/vocalinux-ibus/engine.pid")"
vocalinux
```

Missing system packages: see [INSTALL.md](INSTALL.md) or [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md).

---

## What's New in v0.16.2

0.16.2 is a **stability patch** on the 0.16 series. The feature set is the same as 0.16.x. This release fixes KDE leftover IBus so dictation types into real apps, Wayland and IBus keyboard shortcuts through wtype/ydotool, real BackSpace for "delete that", Fedora/Arch installer glslc packages, nightly version stamping, and release integrity pins. CI now gates AUR PKGBUILD builds and the distros the docs promise.

### 0.16 series highlights

| Feature | Description |
|---------|-------------|
| **Update checker** | Settings → About checks stable/nightly; tray shows Update Available for newer GitHub releases (#631, #645) |
| **Right Alt PTT default** | New installs default to hold Right Alt (push-to-talk); existing configs keep their shortcut (#648) |
| **Searchable languages** | Type to filter the Speech Model language list (#672) |
| **Delete unused models** | Remove leftover downloaded speech models from Settings (#671) |
| **AGPL-3.0** | License aligned with other VocaHQ projects (#660) |
| **Family mic icons** | App icon, tray states, and site favicons use the shared Voca family mic (#704) |
| **Tone picker** | Settings → Audio: Lift, Flick, Ember, Step, Voca, Soft, Chirp, Scale, Drop, Glass, Off, plus Preview. New installs default to Voca. Catalog uses family preview WAVs (#707, #708) |
| **Installer** | Justfile, uv lockfiles, distro python3-gi required (no pip sdist of PyGObject). Epic #701 still open (#700, #705, #706) |

### Bug fixes in v0.16.2

- **KDE inject**: skip leftover IBus when it is not the session IM so dictation types into Kate, browsers, and terminals (#753 by @jatinkrmalik, fixes #752 by @justTravis)
- **Wayland shortcuts**: wtype and ydotool deliver real chords instead of refusing or silently doing nothing (#715 by @eiseleb47)
- **IBus shortcuts**: route X11_IBUS through xdotool and WAYLAND_IBUS through wtype/ydotool (#716 by @eiseleb47)
- **Delete that**: send real BackSpace key events instead of U+0008 text (#714 by @eiseleb47)
- **Installer**: Fedora and Arch need glslc/shaderc packages, not glslang (#763 by @jatinkrmalik, see #604)
- **Nightly**: stamp `version.py` before `python -m build` so wheel metadata matches the filename (#762 by @sesav)
- **Release integrity**: checksums, signatures, and pinned builders for release artifacts (#759 by @sesav, epic #701 phase 5)
- **CI**: gate AUR PKGBUILD builds on every PR (#772 by @sesav)
- **CI / docs**: test the distros the docs promise and fix docs drift (#773 by @sesav)
- **Site**: VocaGateway family card is Beta; README logo, badges, and privacy copy (#765 by @jatinkrmalik, #764)
- **Snap**: v0.16.2 `latest/edge` (rev 7) has no `uinput` plug. `sudo snap connect vocalinux:uinput` errors with `snap "vocalinux" has no plug named "uinput"`. Dictation only reaches XWayland apps. 0.17 ships ydotool and the plug; then `snap refresh` and `snap connect vocalinux:uinput` (#823)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.16.2).

---

## What's New in v0.16.1

0.16.1 is a **stability patch** on the 0.16 series. The feature set is the same as 0.16.x. This release fixes wrong-model startup, leftover tray state after toggle stop, paste into terminals, GNOME XWayland layout after inject, and AppImages that needed a glibc newer than Debian 12. The installer now requires Python 3.11 and verifies model downloads.

### 0.16 series highlights

| Feature | Description |
|---------|-------------|
| **Update checker** | Settings → About checks stable/nightly; tray shows Update Available for newer GitHub releases (#631, #645) |
| **Right Alt PTT default** | New installs default to hold Right Alt (push-to-talk); existing configs keep their shortcut (#648) |
| **Searchable languages** | Type to filter the Speech Model language list (#672) |
| **Delete unused models** | Remove leftover downloaded speech models from Settings (#671) |
| **AGPL-3.0** | License aligned with other VocaHQ projects (#660) |
| **Family mic icons** | App icon, tray states, and site favicons use the shared Voca family mic (#704) |
| **Tone picker** | Settings → Audio: Lift, Flick, Ember, Step, Voca, Soft, Chirp, Scale, Drop, Glass, Off, plus Preview. New installs default to Voca. Catalog uses family preview WAVs (#707, #708) |
| **Installer** | Justfile, uv lockfiles, distro python3-gi required (no pip sdist of PyGObject). Epic #701 still open (#700, #705, #706) |

### Bug fixes in v0.16.1

- **Startup**: resolve model size per engine instead of the leftover generic `model_size` key, so a VOSK save does not make whisper.cpp look for a missing medium model (#684 by @kacperpaczos, fixes #681)
- **Settings**: save the model only after the engine loaded it, so a cancelled or failed download does not leave config pointing at a file that is not on disk (#685 by @kacperpaczos)
- **Settings**: unused downloads list sized to its real rows so leftover models are not clipped (#686 by @kacperpaczos, fixes #683)
- **Config**: one ConfigManager for the process so Settings writes are not overwritten by a stale cache (#691 by @kacperpaczos, fixes #689)
- **Tray**: stay idle after leftover transcription on toggle stop (#741)
- **Tray**: the missing-model notification can download the recommended model (#687 by @kacperpaczos)
- **Injection**: Ctrl+Shift+V when pasting into terminals, so Ctrl+V is not treated as verbatim insert (#734)
- **IBus**: sync the XWayland layout from GNOME after scoped inject (#742)
- **Installer**: survive a release without a checksum manifest; stop inventing GPUs (#736 by @sesav)
- **Installer**: leftover engine repair, just `--no-sync`, ggml verify from #713 (#732)
- **AppImage**: build against a glibc floor Debian 12 can run; boot tests on six distros (#743, #744 by @sesav)
- **Installer**: Python 3.11 floor, uv tooling, verified model downloads (epic #701 phases 2.5 and 5) (#713 by @sesav)
- **Settings / About**: even dropdowns, quieter About, family platform marks (#754)
- **AUR**: `python -m build --no-isolation` works with Arch extra setuptools 84 (was capped at `<82`, AUR comment by simona). Skip `context_params` on AUR pywhispercpp 1.4.x so startup no longer dies with `whisper_full_params` (AUR comments by avocadoboat, Masalababa; GitHub #625)
- **Docs**: canonical VocaHQ Discord invite; VocaWin is unsigned beta; screenshots page says v0.16; README family/on-device copy (#749, #733, #735, #737)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.16.1).

---

## What's New in v0.16.0

0.16.0 is a **minor** release on the stable line. It adds an in-app update checker with tray notifications, defaults new installs to hold Right Alt push-to-talk, makes the language picker searchable, lets you delete unused downloaded models, and adds a family dictation tone picker. The license is AGPL-3.0. The installer is hardened (Justfile, uv lockfiles, distro python3-gi). The app icon, tray states, and site favicons use the shared Voca family mic.

### Highlights

| Feature | Description |
|---------|-------------|
| **Update checker** | Settings → About checks stable/nightly; tray shows Update Available for newer GitHub releases (#631, #645) |
| **Right Alt PTT default** | New installs default to hold Right Alt (push-to-talk); existing configs keep their shortcut (#648) |
| **Searchable languages** | Type to filter the Speech Model language list (#672) |
| **Delete unused models** | Remove leftover downloaded speech models from Settings (#671) |
| **AGPL-3.0** | License aligned with other VocaHQ projects (#660) |
| **Family mic icons** | App icon, tray states, and site favicons use the shared Voca family mic (#704) |
| **Tone picker** | Settings → Audio: Lift, Flick, Ember, Step, Voca, Soft, Chirp, Scale, Drop, Glass, Off, plus Preview. New installs default to Voca. Catalog uses family preview WAVs (#707, #708) |
| **Installer** | Justfile, uv lockfiles, distro python3-gi required (no pip sdist of PyGObject). Epic #701 still open (#700, #705, #706) |

### New Features

- **In-app update checker**: Settings → About with stable/nightly channels (#631)
- **Update notifications**: Tray menu Update Available entry and About badge when a newer release exists (#645)
- **Right Alt push-to-talk default**: New installs only; existing configs are unchanged (#648)
- **Searchable language combobox**: Filter the long language list by name or code (#672, fixes #652)
- **Delete unused models**: Remove leftover downloaded speech models from Settings (#671, fixes #650)
- **Disable missing-tray warning**: Settings toggle for desktops that false-positive the tray check (#628, fixes #620)
- **Family mic icons**: App icon, tray states, and site favicons use the shared Voca family mic instead of the old Linux rounded-rect (#704)
- **Family dictation tone picker**: Settings → Audio dropdown (Lift, Flick, Ember, Step, Voca, Soft, Chirp, Scale, Drop, Glass, Off) plus Preview. New installs and unknown saved names default to Voca. A saved catalog id, including Off, is left alone. Enable remains the master mute; Off skips start/stop only (#707)
- **About page**: Settings → About groups this app, VocaHQ family sites, and talk-to-us (GitHub issues, Discord, X, email) (#718)

### Bug Fixes

- **IBus**: Require a restorable engine for scoped injection (#623); restore engine after `register_component` teardown (#643, fixes #558); restore XKB layout after scoped injection on X11 (#665, fixes #664)
- **Injection**: Stop typing `test` during the wtype probe (#627, fixes #622)
- **whisper.cpp**: Skip unsupported `context_params` on pywhispercpp 1.4 (#626, fixes #625); use CUDA device 0 when CUDA-backed (#636); honor bundled GPU libs and skip software Vulkan devices (#674)
- **Audio**: Filter unsafe virtual capture devices (#629, fixes #624); open stereo mics at native channel count (#673, fixes #666); catalog tones are the family preview WAVs, not the synthesized #707 files. `generate_sounds.py` does not clobber catalog ids (#708)
- **Tray / Settings**: Prefer Ayatana AppIndicator on KDE (#621); reuse Settings/Logs windows (#669, fixes #653); separate Close from Test Dictation (#670, fixes #651)
- **Settings**: Test Dictation no longer reports no speech when recognition never started (missing model / auto-pause / live engine out of sync) (#702)
- **Clipboard**: Restore after ydotool clipboard-paste (#588); text-only reads and safer overlapping restore (#646)
- **AppImage**: Ship transitive GI typelibs for non-Debian hosts (also hotfixed onto the v0.15.0 AppImages on 2026-08-03) (#637); pin pywhispercpp to the version `install.sh` declares so a newer PyPI wheel cannot break the Vulkan rebuild (#718)
- **Installer**: Distro python3-gi is required; pip no longer builds PyGObject from sdist. Unset `XDG_SESSION_TYPE` / `XDG_CURRENT_DESKTOP` no longer crash under `set -u` (#706)
- **Installer / downloads / tests**: Gate `util-linux-extra` to Ubuntu 24.04+ (#635, fixes #526); report failed model downloads (#690); stop the suite from overwriting real `config.json` (#694)

### Docs / maintenance

- Website screenshot refresh for v0.15 (#630)
- Prefer Ayatana AppIndicator in Fedora/Arch packaging hints (#638)
- CUDA device 0 note for dual NVIDIA (#644)
- Discord and VocaHQ README shields; VocaHQ URL migration; VocaGateway rename (#695, #696, #697)
- Discord invite and X handle point at VocaHQ (#722)
- vocalinux.com restyled to the Voca family workbench; Open Graph card uses the flat Tux (#728, #729)
- Website copy drops the stale 100% offline claim and marks VocaWin as alpha on the site (#717)
- Codeberg mirror tag force-push (#633)
- Installer hardening, Justfile in place of Makefile, and uv lockfiles with pinned build inputs. Epic #701 remains open (#700, #705 by @sesav)

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.16.0).

---

## Older releases

Notes for v0.15.0 and earlier live on GitHub Releases:

- [v0.15.0](https://github.com/VocaHQ/vocalinux/releases/tag/v0.15.0)
- [v0.14.2](https://github.com/VocaHQ/vocalinux/releases/tag/v0.14.2)
- [v0.14.1](https://github.com/VocaHQ/vocalinux/releases/tag/v0.14.1)
- [v0.14.0-beta](https://github.com/VocaHQ/vocalinux/releases/tag/v0.14.0-beta)

Full history: https://github.com/VocaHQ/vocalinux/releases

---

## Need help?

- [Installation guide](INSTALL.md)
- [Troubleshooting](TROUBLESHOOTING.md)
- [User guide](USER_GUIDE.md)
- [Support](../SUPPORT.md)
- [Report issues](https://github.com/VocaHQ/vocalinux/issues)
- [Discussions](https://github.com/VocaHQ/vocalinux/discussions)
- [Discord](https://discord.gg/t6muquAJbm)
