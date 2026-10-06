# Changelog

Release history for Vocalinux.

## Where to read notes

| Source | Contents |
|--------|----------|
| [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases) | Canonical release notes per tag |
| [docs/UPDATE.md](docs/UPDATE.md) | Upgrade steps plus retained release notes for recent versions |
| [vocalinux.com/changelog](https://vocalinux.com/changelog) | Shorter website changelog |

## Current stable

**[v0.18.0](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.0)** (2026-10-02)

Minor on the stable line: in-app Dictation Pad for Wayland-safe dictation, PipeWire capture with system-audio sources, RemoteDesktop portal text injection, per-language dictation shortcuts, tray dictation history, file transcription with speaker labels, opt-in D-Bus activation for compositor global shortcuts, custom dictionary with corrections, postprocessing scripts, a floating dictation overlay, and audio ducking while dictating. The dictation hotkey is grabbed and suppressed so it stops leaking into the focused app. Packaging gains a `vocalinux-bin` AUR package, a self-hosted Flatpak remote, and a gated snap-promote workflow.

See [docs/UPDATE.md](docs/UPDATE.md#whats-new-in-v0180) for the highlight table, or the [GitHub Release](https://github.com/VocaHQ/vocalinux/releases/tag/v0.18.0).

## Earlier versions

Browse tags on [GitHub Releases](https://github.com/VocaHQ/vocalinux/releases). Version history used for maintainer planning also appears in [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).

## Format

We follow [Semantic Versioning](https://semver.org/). Pre-releases use suffixes such as `-alpha`, `-beta`, and `-rc.N`. Maintainer release steps: [docs/RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).
