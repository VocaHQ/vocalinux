# Changelog

Release history for Vocalinux.

## Where to read notes

| Source | Contents |
|--------|----------|
| [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases) | Canonical release notes per tag |
| [docs/UPDATE.md](docs/UPDATE.md) | Upgrade steps plus retained release notes for recent versions |
| [vocalinux.com/changelog](https://vocalinux.com/changelog) | Shorter website changelog |

## Current stable

**[v0.18.3](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.3)** (2026-10-17)

Patch on the stable line: "new line" and "new paragraph" voice commands now insert real line breaks standalone and mid-utterance, hotkeys work again on GNOME Shell X11 and quitting no longer collapses multi-layout keyboards, every packaged channel builds the bundled engine at the portable x86-64 baseline so older CPUs stop crashing, the Snap package drops the `uinput` plug the Store denied so revisions publish again, the Flatpak remote publish warns loudly instead of skipping silently, and Transcribe File's modal download dialog releases its grab so the transcript's buttons are clickable.

See [docs/UPDATE.md](docs/UPDATE.md#whats-new-in-v0183) for the highlight table, or the [GitHub Release](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.3).

**[v0.18.2](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.2)** (2026-10-12)

Patch on the stable line: the dictation overlay orb now pulses and ripples with live mic level, Nix users get a flake package with NixOS and Home Manager modules plus Vulkan GPU inference for whisper.cpp, held keyboards are left ungrabbed at startup so typing during launch cannot strand a key, the bundled engine no longer crashes on older CPUs, and the piped installer keeps working when it needs to prompt you.

See [docs/UPDATE.md](docs/UPDATE.md#whats-new-in-v0182) for the highlight table, or the [GitHub Release](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.2).

**[v0.18.1](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.1)** (2026-10-08)

Patch on the stable line: a Settings Proxy page for model downloads and update checks behind SOCKS5/HTTP proxies, opt-in JSONL transcript persistence so a failed injection no longer loses the text, .deb and .rpm release packages for Debian and Fedora, a slimmer tray menu (Start on Login and About now live only in Settings), and reliability fixes for the Dictation Pad on Wayland, evdev keyboard discovery, KDE Plasma 6 letter case, a dead Initial Prompt field in Settings, save dialogs that could double the `.txt` extension, and a Speech Model picker that stages changes until you confirm the download.

See [docs/UPDATE.md](docs/UPDATE.md#whats-new-in-v0181) for the highlight table, or the [GitHub Release](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.1).

## Earlier versions

Browse tags on [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases). Version history used for maintainer planning also appears in [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).

## Format

We follow [Semantic Versioning](https://semver.org/). Pre-releases use suffixes such as `-alpha`, `-beta`, and `-rc.N`. Maintainer release steps: [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).
