# User guide

How to use Vocalinux day to day. Install first: [INSTALL.md](INSTALL.md).

## Getting started

1. Launch Vocalinux (`vocalinux` or the application menu)
2. Find the microphone icon in the system tray
3. Start dictation with the tray menu or your keyboard shortcut
4. Speak into the focused application; text is injected when an utterance completes
5. Stop by releasing the key (push-to-talk, default on new installs) or with the same shortcut (toggle)

### Start on login

Enable **Start on Login** from the first-run dialog, tray menu, or Settings. Vocalinux writes an XDG autostart entry (`~/.config/autostart/vocalinux.desktop`) and starts as a normal user app (`--start-minimized`). It does not create a systemd service.

Works on common desktop environments (GNOME, KDE, Xfce, Cinnamon, MATE, LXQt). Minimal window-manager sessions may need their own autostart helper.

### Status icons

| Icon state | Meaning |
|------------|---------|
| Gray (off) | Inactive |
| Blue (on) | Listening |
| Orange | Processing speech |

### Dictation formatting

Vocalinux capitalizes the start of dictation and letters after `.`, `!`, or `?`. Each completed utterance leaves a trailing space so the next session does not glue onto the previous sentence.

### Dictating into terminals

When Vocalinux injects through the clipboard (the usual Wayland / ydotool path), it sends **Ctrl+V** in ordinary text fields and **Ctrl+Shift+V** in terminal emulator windows. Auto-detect works on X11 and on Hyprland, Sway, and niri. On GNOME or KDE Wayland, set **Settings → Dictation → Clipboard Paste Shortcut** to **Ctrl+Shift+V**.

On non-US layouts such as German Neo, that chord uses the key that types **v** on the active layout (not physical KEY_V). Nested terminal panels inside an IDE are often invisible to window-class detection. If paste lands as a literal `^V` or does nothing, open **Settings → Dictation → Clipboard Paste Shortcut** and choose **Ctrl+Shift+V**.

## Shortcuts

Configure under **Settings → Shortcuts**:

| Mode | Behavior |
|------|----------|
| **Push-to-talk** (default on new installs) | Hold Right Alt (Option on Mac-layout keyboards) while speaking; release to stop |
| **Toggle** | Double-tap the configured shortcut key to start/stop |

Existing configs keep their saved shortcut. Left/right modifier keys and custom modifier+key combos (for example `Alt+R`) are supported.

## Voice commands

Optional spoken commands for punctuation and editing (can be disabled in Settings).
English phrases always work. With a non-English recognition language, matching
punctuation and line-break phrases in that language are also recognized
(Italian *virgola* / *punto*, French *virgule* / *point*, and similar).

| Command | Action |
|---------|--------|
| "new line" / "new paragraph" | Line break |
| "period" / "full stop" / "dot" | `.` |
| "comma" | `,` |
| "question mark" | `?` |
| "exclamation point" / "exclamation mark" | `!` |
| "semicolon" | `;` |
| "colon" | `:` |
| "delete that" / "scratch that" | Delete last sentence |
| "capitalize" / "uppercase" | Capitalize next word |
| "all caps" | Next word in ALL CAPS |

Editing and formatting action phrases (`delete that`, `undo`, `capitalize`, and similar)
are currently English-only.

## Engines and models

Open **Settings → Speech Model**. The page starts with a simple setup (language and speed/accuracy). Expand **Advanced** for engine, model size, and specialization. Sidebar search (Ctrl+F) works across pages.

### Engines

| Engine | Best for | GPU | Footprint |
|--------|----------|-----|-----------|
| **whisper.cpp** (default) | Most users | Vulkan (AMD, Intel, NVIDIA) | ~74MB default model |
| **Whisper** (OpenAI) | PyTorch/CUDA workflows | NVIDIA/CUDA | Large (PyTorch stack) |
| **VOSK** | Low RAM / older machines | CPU | ~40MB |
| **Parakeet** | CPU dictation; 25 European languages | CPU | ~639MB v3-european |
| **Remote API** | Offload to a server | N/A (server-side) | Opt-in; see [HTTP_REMOTE.md](HTTP_REMOTE.md) |

Parakeet runs NVIDIA NeMo ASR models through sherpa-onnx. The default bundle is **v3-european** (25 European languages). **v2-english** is English-only. Parakeet ignores the catalog language picker (language is treated as auto).

### Model size (whisper.cpp / Whisper)

| Size | Approx. size | Tradeoff |
|------|--------------|----------|
| tiny | ~74MB | Fastest; real-time friendly |
| base | ~141MB | Balance of speed and accuracy |
| small | ~465MB | Better accuracy |
| medium | ~1.5GB | High accuracy |
| large | ~3.0GB | Best accuracy; heavier |

For whisper.cpp, also pick a **Specialization**: standard multilingual, English-only, quantized (lower memory), Turbo, or legacy large. English-only specializations limit the language selector to English. Exact IDs (for example `medium.en-q5_0`, `large-v3-turbo`) work with `--model`.

### Removing unused models

If leftover files are on disk that are not the model currently selected, **Unused downloads** appears under the model info card. Expand it to delete leftovers one at a time. Confirming removes those files from `~/.local/share/vocalinux`. Packaged system-wide VOSK models are left alone.

### GPU

whisper.cpp prefers Vulkan when the bundled pywhispercpp libraries include it, then CUDA, then CPU. Host tools such as `vulkaninfo` only describe the machine. The engine follows the libraries actually loaded. On multi-GPU machines a discrete Vulkan device is preferred; override under **Settings → Performance → Vulkan GPU**. Check logs with `vocalinux --debug`.

Pip wheels of pywhispercpp are often CUDA builds. In that case Vocalinux uses CUDA device 0. `install.sh` rebuilds pywhispercpp with Vulkan or CUDA when it can.

### Auto-pause and keep-alive

Under Settings:

- **Auto-pause apps** — unload the model while listed apps run
- **Model keep-alive** — unload after idle timeout to free GPU/CPU

## Tips for better recognition

1. Use a decent microphone and reduce background noise when you can
2. Speak clearly at a natural pace
3. Prefer `tiny`/`base` for snappy dictation; larger models when accuracy matters more than latency
4. English-only or quantized specializations help when they match your use case
5. Confirm Vulkan/CUDA in debug logs if transcription is slower than expected

## CLI

```bash
vocalinux --help
vocalinux --version
vocalinux --debug
vocalinux --engine whisper_cpp
vocalinux --engine parakeet
vocalinux --model medium.en-q5_0
vocalinux --wayland
vocalinux --start-minimized
```

## Troubleshooting

Run with debug logging:

```bash
vocalinux --debug
```

Install, audio, tray, and injection issues: [INSTALL.md](INSTALL.md). Distro-specific notes: [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md). Updates: [UPDATE.md](UPDATE.md).

Still stuck? [GitHub Issues](https://github.com/VocaHQ/vocalinux/issues) or [Discussions](https://github.com/VocaHQ/vocalinux/discussions).
