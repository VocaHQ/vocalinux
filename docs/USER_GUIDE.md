# User Guide

This guide explains how to use Vocalinux effectively.

## Getting Started

After installing Vocalinux (see the [Installation Guide](INSTALL.md)), you can start the application from the terminal and optionally enable start-on-login.

## Start on Login (Autostart)

Vocalinux supports login autostart using the standard Linux desktop-session mechanism.

- **Where to enable it**:
  - First-run welcome dialog
  - Tray menu: **Start on Login**
  - Settings dialog: **Start on Login**
- **What Vocalinux creates**:
  - `vocalinux.desktop` in `$XDG_CONFIG_HOME/autostart/` or `~/.config/autostart/`
- **How it starts**:
  - As a regular user GUI app in your desktop session (`--start-minimized`)
- **What it does not do**:
  - It does not create a `systemd` service/unit for autostart

### Desktop Compatibility Notes

- Works on most mainstream desktop environments (GNOME, KDE, Xfce, Cinnamon, MATE, LXQt)
- On minimal/custom window managers, autostart may require an autostart manager or desktop-specific startup hook

## Basic Usage

### Starting and Stopping Voice Typing

1. **Launch the application**: Run `vocalinux` in a terminal or launch it from your application menu
2. **Find the tray icon**: Look for the microphone icon in your system tray
3. **Start voice typing**: Hold Right Alt (Option) by default, or use the tray menu / your configured shortcut
4. **Speak clearly**: As you speak, your words will be transcribed into the currently focused application
5. **Stop voice typing**: Release the key in push-to-talk (default), double-tap again in toggle mode, or use the tray menu

### Dictation formatting

Vocalinux capitalizes the start of dictation and letters after `.`, `!`, or `?`. Each completed utterance also leaves a trailing space so the next push-to-talk or toggle session does not glue onto the previous sentence (`Hello.This` → `Hello. This`).

### Understanding the Status Icons

- **Microphone off** (gray): Voice typing is inactive
- **Microphone on** (blue): Voice typing is active and listening
- **Microphone processing** (orange): Voice typing is processing your speech

## Voice Commands

Vocalinux supports several commands that you can speak to control formatting:

| Command | Action |
|---------|--------|
| "new line" or "new paragraph" | Inserts a line break |
| "period" or "full stop" | Types a period (.) |
| "comma" | Types a comma (,) |
| "question mark" | Types a question mark (?) |
| "exclamation point" or "exclamation mark" | Types an exclamation point (!) |
| "semicolon" | Types a semicolon (;) |
| "colon" | Types a colon (:) |
| "delete that" or "scratch that" | Deletes the last sentence |
| "capitalize" or "uppercase" | Capitalizes the next word |
| "all caps" | Makes the next word ALL CAPS |

## Tips for Better Recognition

1. **Use a good microphone**: A quality microphone significantly improves recognition accuracy
2. **Speak clearly**: Enunciate your words clearly but naturally
3. **Moderate pace**: Don't speak too quickly or too slowly
4. **Quiet environment**: Minimize background noise when possible
5. **Learn commands**: Familiarize yourself with voice commands for punctuation and formatting
6. **Use GPU acceleration**: If you have a GPU (AMD, Intel, or NVIDIA), whisper.cpp will automatically use it for faster transcription
7. **Choose the right model**:
   - For real-time dictation: Use `tiny` or `base` (fastest)
   - For better accuracy: Use `small`, `medium`, or `large`
   - For English-only dictation: Choose an `.en` specialization
   - For lower-memory systems: Choose a quantized specialization such as `q5_0` or `q5_1`
8. **Check debug logs**: Run `vocalinux --debug` to see which backend is being used (Vulkan, CUDA, or CPU)

## Customization

### Keyboard Shortcut

Vocalinux supports two shortcut modes for controlling voice typing:

- **Push-to-talk mode (default)**: Hold Right Alt (Option on Mac-layout keyboards) to speak, then release to stop
- **Toggle mode**: Double-tap the configured shortcut key to start/stop voice typing
- Configure mode and key in **Settings -> Shortcuts**

### Model Settings

You can change the speech recognition engine and model for better accuracy or faster performance:

### Choosing Your Engine

Vocalinux now offers **three speech recognition engines**:

1. **whisper.cpp** ⭐ (Default) - High-performance C++ engine
   - Fastest installation (~1-2 min)
   - Works with AMD, Intel, NVIDIA GPUs via Vulkan
   - True multi-threading (no Python GIL)
   - Best for most users

2. **Whisper** (OpenAI) - PyTorch-based engine
   - NVIDIA GPU only (requires CUDA)
   - Larger download (~2.3GB with PyTorch)
   - Installation takes ~5-10 min
   - Use if you specifically need PyTorch features

3. **VOSK** - Lightweight engine
   - Smallest footprint (~40MB)
   - CPU only
   - Great for older systems or minimal resource usage

### Changing Engine and Model

1. Open settings from the tray icon menu (right-click)
2. Open the **Speech Engine** page in the settings sidebar (search works if you prefer)
3. Select your **Speech Engine**:
   - whisper_cpp (recommended)
   - whisper
   - vosk
4. Select your **Model Size**:
   - **tiny** (~74MB) - Fastest, good for real-time dictation
   - **base** (~141MB) - Good balance
   - **small** (~465MB) - Better accuracy
   - **medium** (~1.5GB) - High accuracy
   - **large** (~3.0GB) - Best accuracy, slower
5. For whisper.cpp, select a **Specialization**:
   - **Standard multilingual** - Best default for auto-detect or non-English dictation
   - **English-only** - Choose when you dictate only in English
   - **Quantized** - Lower memory and smaller downloads with a possible accuracy tradeoff
   - **Turbo** - Faster large-v3 option with strong accuracy
   - **Legacy large** - Use only if you specifically need an older large model version

English-only whisper.cpp specializations limit the language selector to English.

### Removing unused models

Open Settings and go to **Speech Model**. If leftover files are on disk that are
not the model currently selected, **Unused downloads** appears under the model
info card. Expand it to delete leftovers one at a time. Confirming removes those
files from `~/.local/share/vocalinux`. Vocalinux will download a model again if
you select it later. Packaged system-wide VOSK models are left alone. The section
is hidden when there is nothing unused to delete.

### When to Use Each Model

**For real-time dictation:** Use **tiny** or **base** - they're fast enough to keep up with your speech.

**For transcription:** Use **small** or **medium** - better accuracy for recorded audio.

**For maximum accuracy:** Use **large** - best results but requires more RAM and GPU power.

**For lower-memory systems:** Use a quantized whisper.cpp specialization such as **Q5** or **Q8**.

**For English-only dictation:** Use an **English-only** specialization and keep the language set to English.

### GPU Acceleration

**whisper.cpp** automatically uses GPU acceleration when available:

- **Vulkan** (AMD, Intel, NVIDIA) - Automatically detected and used
- **CUDA** (NVIDIA only) - Fallback if Vulkan not available
- **CPU** - Always works as fallback

On multi-GPU machines, Vocalinux prefers a **discrete** Vulkan device when one is present. You can override the device under **Advanced** settings (`whispercpp_gpu_device`).

Pip wheels of pywhispercpp are often CUDA builds. In that case Vocalinux always uses CUDA device 0 (the first NVIDIA GPU), because Vulkan GPU indices do not match CUDA ordinals. On a hybrid laptop the NVIDIA GPU is usually Vulkan GPU 1; feeding that index into CUDA would land on the CPU fallback instead.

If you need a second NVIDIA GPU, either set `CUDA_VISIBLE_DEVICES` before starting Vocalinux or install a Vulkan-built pywhispercpp so the Advanced GPU picker applies.

To check which backend is being used, look for these log messages when starting Vocalinux:
```
[INFO] whisper.cpp using Vulkan GPU backend: AMD Radeon RX 6800
[INFO] whisper.cpp configured with n_threads=16
```

### Auto-pause and model keep-alive

Optional power-saving controls live under settings:

- **Auto-pause apps** — unload the speech model while configured apps/games are running, then reload when they exit
- **Model keep-alive** — unload the model after a configurable idle timeout so idle dictation does not keep GPU/CPU resources warm

## Troubleshooting

If you encounter issues, check the [Installation Guide](INSTALL.md) troubleshooting section or run the application with debug logging:

```bash
vocalinux --debug
```

Check the logs for error messages and possible solutions.
