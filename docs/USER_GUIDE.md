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
| **Faster Whisper** | CPU Whisper (CTranslate2 / INT8) | Optional CUDA | Similar model sizes to Whisper |
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

- **Auto-pause apps**: unload the model while listed apps run
- **Model keep-alive**: unload after idle timeout to free GPU/CPU

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
vocalinux --engine faster_whisper
vocalinux --engine parakeet
vocalinux --model medium.en-q5_0
vocalinux --wayland
vocalinux --start-minimized
```

## Troubleshooting

```bash
vocalinux --debug
```

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for tray, audio, injection, and model issues. Distro notes: [DISTRO_COMPATIBILITY.md](DISTRO_COMPATIBILITY.md). Updates: [UPDATE.md](UPDATE.md). Help channels: [SUPPORT.md](../SUPPORT.md).

### Text injection backend

Vocalinux types your dictated text using one of several backends. It picks one
automatically, and on most desktops the automatic choice is correct.

Autodetection can be wrong, though, and it fails in a way that is easy to
misread: on a compositor that does not relay IBus commits to native Wayland
applications, IBus reports the text as delivered while nothing appears. If
dictation works in some windows (typically XWayland ones, like a browser) but
silently does nothing in others, that is the symptom.

Pin the backend explicitly in `~/.config/vocalinux/config.json`:

```json
{
  "text_injection": {
    "backend": "wtype"
  }
}
```

| Value | Backend |
|---|---|
| `auto` | Autodetect (default; autodetection may select IBus) |
| `ibus` | IBus input method; on Wayland, bypasses compositor checks and may silently do nothing in native Wayland apps |
| `wtype` | wtype virtual keyboard (Wayland) |
| `ydotool` | ydotool uinput (Wayland; needs `ydotoold`) |
| `xdotool` | xdotool (X11). On Wayland it only turns IBus off -- the Wayland tool is still picked automatically |

The setting takes effect on the next start. `auto` leaves normal autodetection
in place and may select IBus. An explicit non-IBus pin (`wtype`, `ydotool`, or
`xdotool`) skips IBus selection.

On X11 the injection tool is `xdotool` regardless of which non-`ibus` value you
pin, so `xdotool` is the name to use there when IBus is unreliable in a
particular application. Pinning `ibus` keeps the IBus path; pinning anything
else turns it off.

To try a backend for a single run without changing the saved setting, set
`VOCALINUX_FORCE_BACKEND`, which overrides the config value. Set it to `auto`
to ignore a saved pin for that run:

```bash
VOCALINUX_FORCE_BACKEND=wtype vocalinux --debug
```

The setting and environment override are read at startup, so restart Vocalinux
after editing `config.json`. The startup log first records a backend pin request;
it does not prove the backend was available or that text reached the focused
application. Later logs identify a fallback when a pin was not applied.

If a pinned tool is unavailable, Vocalinux warns and continues with its normal
fallback selection. `ydotool` also needs a usable `/dev/uinput` and a working
`ydotoold` setup. `xdotool` types into X11/XWayland windows, not native Wayland
windows. A live test in the target application is still the final confirmation
that text is delivered.
