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
git checkout v0.18.1
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
| Snap | Store: `sudo snap refresh vocalinux` (`--edge` until stable is promoted). Until Canonical lists 0.18.1, sideload `vocalinux_0.18.1_amd64.snap` from the GitHub Release (`sudo snap install --dangerous ./vocalinux_0.18.1_amd64.snap`), then `sudo snap connect vocalinux:uinput`. v0.16.2 rev 7 has no such plug. |
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
# Source checkout
./uninstall.sh --keep-config --keep-data

# Curl install (safe to run from any directory)
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/uninstall.sh -o /tmp/vul.sh
bash /tmp/vul.sh --keep-config --keep-data

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

## What's New in v0.18.1

0.18.1 is a **patch** on the stable line. Default engine is still whisper.cpp. This one is a reliability release: most of it is fixes, and the new features are plumbing you will notice only when you need it. Settings gains a Proxy page so model downloads and update checks work behind SOCKS5 and HTTP proxies, and an opt-in switch that persists transcripts to disk so a failed injection stops meaning a lost sentence. Releases now attach native .deb and .rpm packages, and the tray menu drops Start on Login and About (both already lived in Settings).

### 0.18.1 highlights

| Feature | Description |
|---------|-------------|
| **Proxy settings** | New Settings -> Proxy page: off, system, or manual SOCKS5/HTTP CONNECT with optional auth; covers every model download and the update checker (#909, fixes #655) |
| **Transcript persistence** | Opt-in JSONL history on disk; a transcript survives restarts and failed injections (#907, fixes #758) |
| **Native packages** | Thin .deb and .rpm for Debian/Ubuntu and Fedora, x86_64 and aarch64, attached to the GitHub Release (#913, step 1 of #600) |
| **Slimmer tray menu** | Start on Login and About removed from the tray; both already live in Settings (#905, fixes #654) |
| **Staged model picker** | Speech Model Advanced pickers no longer start a download per click; changes stage until you confirm Download (#908, fixes #894) |
| **Wayland pad fix** | Dictation Pad no longer ghosts away after sitting idle under a Wayland compositor (#912, fixes #896) |

### Also in v0.18.1

- Startup reuses an on-disk same-size whisper.cpp weight instead of re-resolving or re-downloading it (#923, fixes #916 reported by @blacxsnow)
- Text injection ends option parsing before typed text, so a chunk starting with `-` no longer fails as an unrecognized option and truncates the dictation (#922, fixes #921)
- KDE Plasma 6 Wayland: KWin VirtualKeyboard detection fixed, so dictated letter case stops scrambling (#919, fixes #911 reported by @blackde5ert)
- evdev keyboard discovery tightened: pointer-motion devices, multitouch-only touchpads, and devices without a real keyboard key are no longer grabbed as keyboards, so hotkey enablement stops breaking Logitech mice and Goodix touchpads (#902, #917, #918, fixes #900 reported by @brainygamer, #914 reported by @pylame22, #915 reported by @uncletoxa)
- Test Dictation transcription readout moved above its controls in the sidebar footer (#904, fixes #677 reported by @hopsayer)
- `uninstall.sh` no longer deletes files in the directory you ran it from (#901, fixes #897 reported by @SilverChatte)
- Settings > Advanced Initial Prompt accepts typed input again (clicks were being stolen by the enclosing row), and transcript and log saves no longer write a doubled `.txt.txt` name (#927)
- Packaging: `.deb` declares `python3-socks` and `.rpm` declares `python3-pysocks` for SOCKS5 proxy support (#920)
- CI: snap attach uses `--repo`, checksums still publish when an asset attach fails, the Vulkan pywhispercpp build is reused across runs, and the remote `curl | bash` install path is gated end to end (#899, #903, #906)

AppImage, Flatpak, and Snap still ship whisper.cpp only.

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.1).

---

## What's New in v0.18.0

0.18.0 is a **minor** on the stable line. Default engine is still whisper.cpp. The headline fix is a grab of the dictation hotkey so the shortcut stops leaking into the app under it. Alongside it is a set of Wayland-native paths: an in-app Dictation Pad that keeps text off the fragile injection routes entirely, PipeWire capture (microphone and system audio), and a RemoteDesktop portal injection backend. Dictation gains per-language shortcuts, a tray history menu, a floating overlay, and audio ducking. Long-requested contributor work lands here too: D-Bus activation for compositor global shortcuts, bilingual language candidates, a postprocessing script hook, a custom dictionary with corrections, and file transcription with speaker labels.

### 0.18 series highlights

| Feature | Description |
|---------|-------------|
| **Dictation Pad** | In-app window that receives dictation; you copy text out by hand, so Wayland injection quirks cannot touch it (#887, fixes #726) |
| **Hotkey suppression** | evdev grabs the dictation shortcut and forwards everything else through a uinput clone; the key no longer types into the focused app (#873, #893, fixes #871) |
| **PipeWire capture** | Mic and system-audio sources through the native PipeWire path, not just PortAudio (#889, #883, fixes #751, #760) |
| **RemoteDesktop injection** | Wayland text injection through the RemoteDesktop portal, no ydotoold needed (#885, fixes #750) |
| **Per-language shortcuts + history** | A dictation shortcut per language, layout-follow while dictating, and recent dictations in the tray menu (#880, #837, #487, fixes #805, #821) |
| **File transcription with speakers** | `--transcribe-file` with TinyDiarize per-speaker labels, plus a transcript viewer (#884, fixes #756) |
| **D-Bus activation** | Opt-in D-Bus methods so compositor global shortcuts (and scripts) can start dictation (#568, fixes #761) |
| **Custom dictionary** | Terms bias plus transcript corrections from one file (#890) |

### Also in v0.18.0

- Postprocessing script hook pipes transcriptions through a user command (#479 by @karottenreibe)
- Bilingual dictation: configurable second-language Whisper candidates, with deferred settings edits (#424 by @juanfradb)
- Optional verified Orukeet model for the Parakeet engine (#840 by @Nathan-Roll1)
- Keep recording while an idle-unloaded model reloads instead of dropping the utterance (#851 by @mre31)
- Floating glowing dictation overlay and lowering of other audio while dictating (#516, #861)
- `config.json` can pin the text-injection backend (#649 by @HashimAbdulaziz, fixes #476 reported by @waldemar-p)
- Alt+Shift and Win+Space layout switching keeps working on GNOME Wayland (#876, fixes #848 reported by @hopsayer)
- Shortcut recorder learns unmapped F19/F24 and XF86-aliased F13-F23 (#844, fixes #843 reported by @bisgardo)
- Vosk refuses to load a model that would exceed available memory instead of tripping the OOM killer (#850 by @AmirF194, fixes #676 reported by @hopsayer)
- IBus guard no longer flips GNOME/X11 to a US layout (#827 by @AmirF194)
- Model downloads cancel cleanly even when the fetch stalls, and the download dialog shows verifying instead of a stalled 100% (#888, #864 by @guilhermefeitosa66, fixes #679, #863)
- Settings: scrollable category list, Dictation Tone grayed while sound effects are off, Test Dictation textbox artifact and missing transcription fixed, speech-model follow-ups (#886, #877, #853, #836, fixes #678, #849, #847, #720, #834)
- Update checker falls back when GitHub API rate-limits instead of erroring (#846, fixes #845 reported by @lmstud)
- Audio: stop passing an explicit index when zero devices enumerate; View Logs closes via the titlebar X (#891, #892)
- Snap gains `hardware-observe` so hotkeys can read input devices (#858, fixes #857 reported by @RhysU)
- Installer installs hash-pinned dependencies and build tools, and is split into sourced modules with a generated distro package map (#856, #862, #872 by @sesav)
- AUR `vocalinux-bin` ships the AppImage with per-arch digests; releases publish a signed self-hosted Flatpak OSTree remote; a snap-promote workflow gates stable promotion (#879, #875, #881, fixes #817, #785, #783)
- VocaGateway can run locally from Settings → Advanced (podman-first) (#774)
- Dependency advisories cleared and workflow tokens scoped to repository reads (#869, #865, #866 by @Mr-Sunglasses, #870)
- Settings dialog consolidated: guard flags and widget construction in one place each (#878, fixes #793)

AppImage, Flatpak, and Snap still ship whisper.cpp plus the same engine matrix as 0.17.

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.0).

---

## What's New in v0.17.0

0.17.0 is a **minor** on the stable line. Default engine is still whisper.cpp. This release adds two optional local engines (Faster Whisper and Parakeet), a simpler Speech Model page, Snap packaging with native Wayland typing, and Flatpak bundles built by the release workflow. It also fixes XWayland/layout paste, a KDE xdotool crash, push-to-talk tray redraw, clipped start/stop cues, HDA analog mics that abort when opened below native channel count, native GTK installs that ignored OS dark/light, and English-only models that hid every other language.

### 0.17 series highlights

| Feature | Description |
|---------|-------------|
| **Faster Whisper** | Optional CTranslate2 / INT8 Whisper on CPU (`--engine=faster_whisper`) (#543) |
| **Parakeet** | Optional Parakeet TDT 0.6B via sherpa-onnx; default v3-european bundle (`--engine=parakeet`) (#802) |
| **Speech Model simple setup** | Language + speed/accuracy first; engine/size under Advanced (#801) |
| **First-run language** | Seeds from keyboard layout / locale; saved choice is left alone (#796) |
| **Searchable open picker** | Language list filters while open (#798) |
| **Localized punctuation commands** | it/fr/de/es/pt/nl/pl/ru; English phrases still work (#642) |
| **Bare F-keys** | F1–F24 are valid push-to-talk shortcuts (#815) |
| **Snap** | Store listing, ydotool + `uinput` for native Wayland; GitHub `.snap` for sideload while Store review is pending (#519, #823, #822) |
| **Flatpak on the tag** | Workflow attaches `.flatpak` assets and checksums them (#786) |

### Also in v0.17.0

- Recommended model is a button that sets size and specialization together, and will not ignore a suitable file already on disk (#797)
- XWayland xdotool fallback pastes via clipboard so missing-layout characters are not garbled (#680)
- Clipboard paste uses the key that types **v** on the current layout (#788)
- Timed-out ydotool paste releases Ctrl (#675)
- Read `WM_CLASS` with `xprop` instead of crashing `xdotool getwindowclassname` on KDE Plasma Wayland (#807)
- Applying an already-downloaded model no longer freezes Settings (#790)
- Selected language picks the whisper.cpp variant (English → `.en`). Picking another language, or auto-detect, switches off `.en` / `.en-q*` instead of hiding the rest of the list (#795, #780, #826)
- Speech Model labels are nouns (Language, Other languages, Speed vs accuracy). Unused downloads is a sibling expander of Advanced, not nested inside it (#826)
- About family grid includes VocaWin (#826)
- Push-to-talk tray icon turns red on every hold (#809)
- Sink-wake no longer clips start/stop cues (#804)
- Open 3-8 channel HDA analog mics at native layout instead of forcing 2ch/48kHz, so PortAudio no longer aborts after read() (`free(): corrupted unsorted chunks`); capture is downmixed to mono for engines (#829, fixes #813)
- Native GTK installs (AUR / install.sh) follow OS dark/light via the appearance portal then gsettings; skipped when `GTK_THEME` is set so AppImage and user overrides stay in charge (#830, fixes #816)
- Parakeet keeps recognizing after a decode error (#803)
- Flatpak/AUR deps derived from `uv.lock` (#819)
- Hash-pinned exports for VOSK, Parakeet, and Faster Whisper extras so `install.sh` no longer installs those unpinned; extras are version-capped (#828)
- `just verify-release` checks the published GitHub Release (#791)
- Distro matrix runs `install.sh` (#810)
- `install.sh` Faster Whisper box is CPU CTranslate2 / INT8, not NVIDIA CUDA. The whisper.cpp GPU step does not install the CUDA toolkit; Vulkan is first, CUDA only if a toolkit is already on the machine (#826)

AppImage and Flatpak remain whisper.cpp only. Snap ships whisper.cpp plus VOSK. Faster Whisper and Parakeet are optional extras on `install.sh` / source installs.

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.17.0).

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
- **Snap**: v0.16.2 `latest/edge` (rev 7) has no `uinput` plug. `sudo snap connect vocalinux:uinput` errors with `snap "vocalinux" has no plug named "uinput"`. Dictation only reaches XWayland apps. A later store snap ships ydotool and the plug; then `snap refresh` and `snap connect vocalinux:uinput` (#823)

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
