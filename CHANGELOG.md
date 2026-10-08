# Changelog

Release history for Vocalinux.

## Where to read notes

| Source | Contents |
|--------|----------|
| [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases) | Canonical release notes per tag |
| [docs/UPDATE.md](docs/UPDATE.md) | Upgrade steps plus retained release notes for recent versions |
| [vocalinux.com/changelog](https://vocalinux.com/changelog) | Shorter website changelog |

## Current stable

**[v0.18.1](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.1)** (2026-10-08)

Patch on the stable line: a Settings Proxy page for model downloads and update checks behind SOCKS5/HTTP proxies, opt-in JSONL transcript persistence so a failed injection no longer loses the text, .deb and .rpm release packages for Debian and Fedora, a slimmer tray menu (Start on Login and About now live only in Settings), and reliability fixes for the Dictation Pad on Wayland, evdev keyboard discovery, KDE Plasma 6 letter case, a dead Initial Prompt field in Settings, save dialogs that could double the `.txt` extension, and a Speech Model picker that stages changes until you confirm the download.

See [docs/UPDATE.md](docs/UPDATE.md#whats-new-in-v0181) for the highlight table, or the [GitHub Release](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.1).

## Earlier versions

Browse tags on [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases). Version history used for maintainer planning also appears in [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).

## Format

We follow [Semantic Versioning](https://semver.org/). Pre-releases use suffixes such as `-alpha`, `-beta`, and `-rc.N`. Maintainer release steps: [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).
