# Security policy

## Supported versions

Only the current stable minor line receives security fixes:

| Version | Supported |
| ------- | --------- |
| 0.17.x  | Yes |
| 0.16.x  | No |
| 0.15.x  | No |
| older   | No |

Upgrade to the latest release for security and reliability fixes. See [docs/UPDATE.md](docs/UPDATE.md).

## Reporting a vulnerability

Do not open a public GitHub issue for security vulnerabilities.

**Preferred:** email the maintainer at **jatinkrmalik@gmail.com** with subject:

`Vocalinux Security Vulnerability Report`

Include:

- Clear description of the issue
- Steps to reproduce
- Potential impact
- Suggested fix (optional)

You should receive acknowledgment within 48 hours. We will assess severity, share an expected timeline, coordinate disclosure, and credit you in release notes if you want credit.

If email is unavailable, use [GitHub private vulnerability reporting](https://github.com/VocaHQ/vocalinux/security/advisories/new) when enabled for the repository.

## Privacy design

Vocalinux is built for local-first dictation:

- Local engines process audio on-device after you download a model
- No Voca account is required for local engines
- No usage telemetry in the installed application
- Models download once and stay in local cache
- Downloads are checked against pinned checksums before install

### Remote API (optional)

When the user enables **Remote API**, audio is uploaded to the configured server over HTTP(S). That path is off by default. Operators should use TLS and authentication for any network outside a trusted LAN. See [docs/HTTP_REMOTE.md](docs/HTTP_REMOTE.md).

### Engines

| Engine | Processing | Notes |
|--------|------------|--------|
| whisper.cpp (default) | Local | Vulkan GPU optional; models cached under XDG data |
| OpenAI Whisper | Local | PyTorch; NVIDIA/CUDA common |
| Faster Whisper | Local | CTranslate2 / INT8 Whisper on CPU; optional extra |
| VOSK | Local | Lightweight CPU path |
| Parakeet | Local | NVIDIA NeMo ASR via sherpa-onnx; CPU |
| Remote API | User-configured server | Opt-in only |

### File locations

| Path | Purpose | Permissions (typical) |
|------|---------|------------------------|
| `~/.config/vocalinux/` | Configuration | User-only (mode 700) |
| `~/.local/share/vocalinux/` | Data and models | User-only (mode 700) |

### Known limitations

1. **Text injection** uses tools such as xdotool, wtype, ydotool, or IBus; desktop input APIs have their own privilege model
2. **Global shortcuts** need access to input devices (e.g. evdev on some setups)
3. **Virtual environments** isolate Python packages but do not sandbox the desktop session

## Keeping installs current

```bash
# Re-run the official installer (preserves config and models)
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh -o /tmp/vl.sh
bash /tmp/vl.sh
```

Or follow [docs/UPDATE.md](docs/UPDATE.md) for source, AUR, AppImage, Snap, and Flatpak paths.

## Contact

| Topic | Contact |
|-------|---------|
| Security | jatinkrmalik@gmail.com |
| General bugs | https://github.com/VocaHQ/vocalinux/issues |
