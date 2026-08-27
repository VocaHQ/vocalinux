# Product (vocalinux.com)

## Platform

web (Next.js marketing site under `web/`)

## Users

Linux desktop users who want voice dictation that stays on their machine: developers, writers, and people reducing keyboard strain. They already live in terminals, browsers, IDEs, and GTK/Qt apps.

## Product purpose

Vocalinux is free, open-source offline voice dictation for Linux. It turns speech into typed text in whatever app has focus, using local engines (whisper.cpp default, Whisper, VOSK) or an optional user-configured remote API. Success is: install once, dictate in any app, without cloud transcription or telemetry.

## Positioning

Offline-first Linux voice typing with real desktop integration (system tray, X11 and Wayland text injection, toggle and push-to-talk, Silero VAD, suspend recovery). A cloud SaaS voice product cannot truthfully claim local-only models plus no usage telemetry from the installed app.

## Operating context

- Install via a one-line shell installer, AppImage from GitHub Releases, AUR, or local Flatpak build; then run from PATH, app menu, or the AppImage binary
- System tray indicator and settings GUI (GTK) with searchable sidebar navigation and an always-visible sidebar footer for dictation status / Test Dictation / Close
- Dictation into terminals, browsers, IDEs, office apps
- Engines and models chosen for hardware (CPU, optional Vulkan GPU with discrete-device preference)
- Guides and comparison pages on vocalinux.com; source on GitHub

## Capabilities and constraints

- Engines: whisper.cpp (default), OpenAI Whisper, VOSK, optional Remote API
- Speech languages: large selectable catalog (~33 + Auto-detect) shared by Settings/CLI; VOSK only lists languages with official Alphacephei models; remaining Whisper languages available via Auto-detect
- Display servers: X11 and Wayland
- Shortcut modes: push-to-talk default (hold Right Alt / Option); toggle available; left/right modifier distinction; configurable modifier+key combos
- Searchable language combobox; delete unused downloaded speech models from Settings
- Optional voice commands (English-only); Silero neural VAD with amplitude fallback
- Continuous dictation polish: capitalize after sentence punctuation; trailing space after each completed utterance
- Optional auto-pause while configured apps run; optional idle model keep-alive unload
- In-app update checker (stable/nightly) with tray notification when a newer GitHub release is available
- Settings About page groups this app, VocaHQ family sites, and talk-to-us links (GitHub, Discord, X, email)
- Optional disable of the missing-tray warning dialog
- Settings → Audio family tone picker (Lift, Flick, Ember, Step, Voca, Soft, Chirp, Scale, Drop, Glass, Off) with Preview; new installs default to Voca; catalog files are the family preview WAVs
- Vulkan discrete GPU auto-select with manual device override in Advanced settings
- Wayland: IBus when `ibus-wayland` is running, including on compositors previously treated as unbridged
- Packaging: install.sh (distro python3-gi required; no pip sdist of PyGObject), AppImage (x86_64/aarch64), AUR, Flatpak (local/Flathub status as documented); uv.lock pins Python deps; Justfile replaces Makefile
- No usage telemetry in the installed app
- AGPL-3.0; marketing version string is tracked in site package/version surfaces
- Website is Next.js marketing + SEO guides (static export); languages page documents per-engine support honestly

## Brand commitments

- Name: Vocalinux (part of [VocaHQ](https://vocahq.com) with VocaMac / VocaWin)
- Mark: shared Voca family mic for the app icon, tray states, and site favicons (`public/`)
- Warm paper surfaces and Voca teal, matching the family web standard
- Voice: practical, specific, Linux-native; not hype-first SaaS copy

## Evidence on hand

- Real app screenshots in `public/screenshots/`
- Install/uninstall commands pointing at GitHub raw install scripts
- JSON-LD on the home page (software application, FAQ, how-to)
- Do not invent user counts, testimonials, or benchmarks

## Product principles

1. Privacy is default: local engines process audio on-device; remote only when the user opts in.
2. Ship the install path and real desktop proof, not abstract feature theater.
3. Stay honest about engines, hardware, and what runs offline vs remote.
4. Prefer Linux craft and clarity over generic AI-startup marketing patterns.

## Accessibility

- Respect `prefers-reduced-motion`
- Body text contrast at least 4.5:1; large text at least 3:1
- Keyboard-reachable install copy controls and navigation
