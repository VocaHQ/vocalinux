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

**Other audio.** Settings → Audio → Other audio can lower speakers and headphones while the microphone is open, then put that volume back. It stays off until you turn it on. Level while dictating is a percent of the current volume (0 is silent). Quitting mid-dictation puts the volume back; if the app crashes first, the next launch does.

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

### Language

Pick the language you dictate in from **Language**, or leave it on auto-detect.

If you work in more than one language and switch keyboard layouts to do it, turn
on **Follow keyboard layout** instead. Vocalinux then reads your active layout at
the start of every dictation and uses the matching language, so switching layout
switches dictation language with it. The Language picker greys out while this is
on and shows what your current layout resolves to; turning it off pins that
language.

Available for whisper.cpp, Whisper, Faster Whisper, and Remote API. VOSK loads a
separate model per language, so following a layout would mean a model reload on
the hotkey; Parakeet does not use the language picker at all. Active-layout
detection uses GNOME's input-source settings; on other desktops it falls back to
the configured primary layout.

### Activation via a KDE Plasma global shortcut

Instead of the built-in hotkey listener, you can let your desktop's global
shortcut system trigger Vocalinux. On Wayland the built-in listener reads
`/dev/input` (requiring membership in the `input` group and effectively acting
as a system-wide key reader). Delegating activation to the compositor avoids
this entirely: no `/dev/input` access and no `input` group needed just to
start/stop dictation. Text injection is unaffected.

Enable it in Vocalinux:

1. Open **Settings → Shortcuts** (the Keyboard Shortcuts group on the Dictation page)
2. Turn on **External Activation (Desktop Shortcut)**

The change applies immediately; you do not need to restart. The built-in key
listener stops, and a running instance exposes a D-Bus service on the session
bus (`com.vocalinux.Vocalinux`). The CLI can forward commands to it:

```bash
vocalinux --toggle   # start if idle, stop if active
vocalinux --start    # start voice typing
vocalinux --stop     # stop voice typing
```

Then bind a compositor shortcut to `vocalinux --toggle`. On KDE Plasma:

1. Open **System Settings -> Keyboard -> Shortcuts -> Add New -> Command or Script**
   (older Plasma: **System Settings -> Shortcuts -> Custom Shortcuts -> Edit ->
   New -> Global Shortcut -> Command/URL**).

2. Bind a key combination of your choice to the command `vocalinux --toggle`.

Now your chosen key combination toggles dictation, handled by the compositor
rather than by Vocalinux reading the keyboard directly. This works the same way
on other compositors that support binding a key to a command (e.g. GNOME custom
shortcuts, Sway/Hyprland `bindsym`/`bind`).

As an advanced alternative, you can set the same option in
`~/.config/vocalinux/config.json` under `shortcuts`:

```json
"shortcuts": {
    "disable_internal_hotkey": true
}
```

Quit Vocalinux before editing that file so the running app cannot overwrite
the edit from its cached config. Start Vocalinux again after saving.

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

In **Settings → Performance → Unload When Idle**, enable **Record while model
reloads** to speak as soon as you press the dictation shortcut. Audio stays in
memory while the model loads, then joins the rest of the recording for
transcription. Releasing the shortcut before loading finishes still submits the
recorded speech. Wait for that transcription to finish before starting another
recording. This option is off by default.

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
vocalinux --transcribe-file meeting.wav   # diarized transcript on stdout, then exits
```

## Custom Dictionary Support

Open **Settings → Custom Dictionary** to configure two separate capabilities:

- **Custom terms** bias recognition toward product names, people, and jargon.
  They are read from `~/.config/vocalinux/dictionary.txt` by default, as UTF-8
  with one term per line. Blank lines and `#` comments are allowed, so the same
  file remains friendly to an accessibility scanner. Use the add/remove editor
  or choose a different readable terms file with the file picker.
- **Transcript corrections** replace a known misheard word or phrase after
  transcription, for example `super base` with `Supabase`. Corrections are
  stored separately in `~/.config/vocalinux/custom-dictionary-corrections.json`.

VocaLinux re-reads both files before each completed dictation segment, so an
external edit applies to the next segment without restarting the app. Vocabulary
bias works with Whisper, whisper.cpp, and Faster Whisper. Corrections work with
every engine, including VOSK, Parakeet, and the configured remote API.

Corrections run before voice-command interpretation. This can prevent a
command-like misrecognition from acting, but avoid replacements that create a
voice command unless that is intentional. Correction replacements are not
automatically added to recognition bias.

For a one-session terms override, start Vocalinux with:

```bash
vocalinux --dictionary-file /path/to/dictionary.txt
```

This temporarily enables terms from that file without changing saved settings;
the Custom terms controls are disabled for the session. It does not disable
transcript corrections.

`--transcribe-file` uses the TinyDiarize model (`small.en-tdrz`) and needs it downloaded first — the tray "Transcribe Audio File…" entry fetches it on demand.

### Post-Processing

Vocalinux can pipe each transcription result through a user-defined script before injecting it into your application. This lets you apply custom transformations — for example, grammar correction, abbreviation expansion, or domain-specific formatting.

**To configure:**
1. Open Settings from the tray icon menu (right-click)
2. Go to the **Post-Processing** tab
3. Enter the path to your script, or click **Browse…** to select it
4. Leave the field empty to disable post-processing

**Script contract:**
- The script receives the transcription on **stdin**
- It must write the replacement text to **stdout**
- stdout is injected verbatim — trailing newlines are preserved (e.g. paragraph breaks), except a single trailing newline that line-oriented tools like `echo` add when the transcription had none
- A non-zero exit code or a script that times out (10 s) causes the original text to be used unchanged
- Scripts run on a dedicated worker so a slow script cannot interrupt dictation

**Example** — a shell script that uppercases everything:
```bash
#!/bin/bash
tr '[:lower:]' '[:upper:]'
```
Make the script executable (`chmod +x`) before setting the path in Vocalinux.

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
| `portal` | RemoteDesktop portal (Wayland; the sandboxed path, asks for permission once, works under Flatpak) |
| `wtype` | wtype virtual keyboard (Wayland) |
| `ydotool` | ydotool uinput (Wayland; needs `ydotoold`) |
| `xdotool` | xdotool (X11). On Wayland it only turns IBus off -- the Wayland tool is still picked automatically |

The setting takes effect on the next start. `auto` leaves normal autodetection
in place and may select IBus. An explicit non-IBus pin (`portal`, `wtype`,
`ydotool`, or `xdotool`) skips IBus selection.

On Wayland, when IBus is not selected, autodetection tries the RemoteDesktop
portal first -- it is the only injection path Wayland officially supports and
it needs no uinput device or helper daemon -- then `ydotool`, `wtype`, and
finally `xdotool` under XWayland.

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
fallback selection. `portal` needs a desktop implementing the
`org.freedesktop.portal.RemoteDesktop` interface (GNOME and KDE Plasma do;
most wlroots compositors do not). `ydotool` also needs a usable `/dev/uinput`
and a working `ydotoold` setup. `xdotool` types into X11/XWayland windows,
not native Wayland windows. A live test in the target application is still the
final confirmation that text is delivered.
