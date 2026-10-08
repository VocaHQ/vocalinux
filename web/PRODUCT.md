# Product (vocalinux.com)

## Platform

web (Next.js marketing site under `web/`)

## Users

Linux desktop users who want voice dictation that stays on their machine: developers, writers, and people reducing keyboard strain. They already live in terminals, browsers, IDEs, and GTK/Qt apps.

## Product purpose

Vocalinux is free, open-source offline voice dictation for Linux. It turns speech into typed text in whatever app has focus, using local engines (whisper.cpp default, Faster Whisper, Whisper, VOSK, Parakeet) or an optional user-configured remote API. Success is: install once, dictate in any app, without cloud transcription or telemetry.

## Positioning

Offline-first Linux voice typing with real desktop integration (system tray, X11 and Wayland text injection, toggle and push-to-talk, Silero VAD, suspend recovery). A cloud SaaS voice product cannot truthfully claim local-only models plus no usage telemetry from the installed app.

## Operating context

- Install via a one-line shell installer, AppImage from GitHub Releases, AUR, Snap (`--edge`), or Flatpak release bundle; then run from PATH, app menu, or the AppImage binary
- System tray indicator and settings GUI (GTK) with searchable sidebar navigation and an always-visible sidebar footer for dictation status / Test Dictation / Close
- Dictation into terminals, browsers, IDEs, office apps
- Engines and models chosen for hardware (CPU, optional Vulkan GPU with discrete-device preference)
- Guides and comparison pages on vocalinux.com; source on GitHub

## Capabilities and constraints

- Engines: whisper.cpp (default), Faster Whisper, OpenAI Whisper, VOSK, Parakeet, optional Remote API
- Speech languages: large selectable catalog (~33 + Auto-detect) shared by Settings/CLI; VOSK only lists languages with official Alphacephei models; remaining Whisper languages available via Auto-detect
- Display servers: X11 and Wayland
- Shortcut modes: push-to-talk default (hold Right Alt / Option); toggle available; left/right modifier distinction; configurable modifier+key combos
- Searchable language combobox; delete unused downloaded speech models from Settings
- Optional voice commands with localized punctuation phrases for common languages; Silero neural VAD with amplitude fallback
- Dictation Pad: in-app window that receives dictation for manual copy-out; the Wayland-safe path that skips text injection entirely
- Per-language dictation shortcuts, optional follow of the active keyboard layout, and a tray history menu with recent dictations
- Floating dictation overlay, optional lowering of other audio while dictating, and custom dictionary terms bias plus transcript corrections
- Audio capture via PipeWire (microphone and system-audio sources) or PortAudio; Wayland text injection via IBus, wtype, ydotool, or the RemoteDesktop portal
- Opt-in D-Bus activation so compositor global shortcuts and scripts can start dictation
- File transcription with per-speaker labels (`--transcribe-file` / tray), powered by TinyDiarize
- Continuous dictation polish: capitalize after sentence punctuation; trailing space after each completed utterance
- Optional auto-pause while configured apps run; optional idle model keep-alive unload
- Optional JSONL persistence of transcription history to disk (off by default)
- Settings Proxy page: outbound SOCKS5 or HTTP CONNECT proxy (optional auth) for model downloads and update checks
- Speech Model Advanced pickers stage engine/size/variant/language changes until Download is confirmed
- In-app update checker (stable/nightly) with tray notification when a newer GitHub release is available
- Settings About page groups this app, VocaHQ family sites, and talk-to-us links (GitHub, Discord, X, email)
- Optional disable of the missing-tray warning dialog
- Settings → Audio family tone picker (Lift, Flick, Ember, Step, Voca, Soft, Chirp, Scale, Drop, Glass, Off) with Preview; new installs default to Voca; catalog files are the family preview WAVs
- Vulkan discrete GPU auto-select with manual device override in Advanced settings
- Native GTK installs follow the OS dark/light preference unless `GTK_THEME` is already set
- Wayland: IBus when `ibus-wayland` is running, including on compositors previously treated as unbridged
- Packaging: install.sh (distro python3-gi required; no pip sdist of PyGObject), .deb/.rpm (x86_64/aarch64), AppImage (x86_64/aarch64), AUR, Flatpak (local/Flathub status as documented); uv.lock pins Python deps; Justfile replaces Makefile
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
