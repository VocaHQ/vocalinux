# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.15.x  | :white_check_mark: |
| 0.14.x  | :x:                |
| 0.13.x  | :x:                |
| 0.12.x  | :x:                |
| 0.11.x  | :x:                |
| 0.10.x  | :x:                |
| 0.9.x   | :x:                |
| 0.8.x   | :x:                |
| < 0.8   | :x:                |

## Reporting a Vulnerability

We take security seriously. If you discover a security vulnerability within Vocalinux, please follow these steps:

### Do NOT

- Open a public GitHub issue for security vulnerabilities
- Disclose the vulnerability publicly before it's fixed

### Do

1. **Email the maintainer directly**: Send an email to jatinkrmalik@gmail.com with:
   - A clear description of the vulnerability
   - Steps to reproduce the issue
   - Potential impact assessment
   - Any suggested fixes (optional)

2. **Use the subject line**: "Vocalinux Security Vulnerability Report"

3. **Wait for acknowledgment**: You should receive a response within 48 hours

### What to Expect

1. **Acknowledgment**: We'll confirm receipt within 48 hours
2. **Assessment**: We'll evaluate the severity and impact
3. **Timeline**: We'll provide an estimated fix timeline
4. **Fix**: We'll work on a fix and coordinate disclosure
5. **Credit**: If desired, we'll credit you in the release notes

## Security Considerations

### Privacy

Vocalinux is designed with privacy in mind:

- **Offline by default**: whisper.cpp (default), Whisper, and VOSK engines all work completely offline
- **Local processing**: All speech recognition happens on your device
- **No data collection**: We don't collect or transmit your voice data
- **No telemetry**: We don't track usage or behavior

### whisper.cpp (Default Engine)

whisper.cpp is the default speech recognition engine:
- High-performance C++ implementation
- Processes completely locally on your machine
- Models are downloaded once and cached locally
- No audio data is sent to external servers
- Supports Vulkan GPU acceleration for AMD, Intel, and NVIDIA GPUs

### Whisper AI (OpenAI)

OpenAI's Whisper is also available as an alternative:
- PyTorch-based implementation
- Processes locally on your machine
- Models are downloaded once and cached locally
- No audio data is sent to external servers

### File Permissions

The application stores data in:
- `~/.config/vocalinux/` - Configuration (mode 700)
- `~/.local/share/vocalinux/` - Data and models (mode 700)

### Known Limitations

1. **Text injection**: Uses xdotool/wtype which may have implications for input monitoring
2. **Keyboard shortcuts**: Global keyboard hooks require appropriate permissions
3. **Virtual environments**: Running in a venv provides some isolation

## Updates

Keep your installation updated to receive security fixes:

```bash
cd vocalinux
git pull origin main
pip install --upgrade -e .
```

## Contact

For security concerns: jatinkrmalik@gmail.com

For general issues: https://github.com/VocaHQ/vocalinux/issues
