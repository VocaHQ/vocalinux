# Architecture

Vocalinux is a GTK 3 desktop application. `main.py` wires together the
configuration manager, recognition manager, tray UI, D-Bus service, and text
injector. Audio capture and recognition run outside the GTK event loop.

## Module map

- `main.py` composes the application services and callbacks.
- `audio/capture.py` and `audio/pipewire.py` provide capture sources.
- `speech_recognition/` owns VAD, segment processing, command handling, and
  engine implementations under `engines/`.
- `post_processor.py` runs configured transcript processing scripts.
- `text_injection/` contains `TextInjector`, focused-window detection, IBus,
  and Remote Desktop Portal support.
- `ui/` contains the tray, Settings, dictation pad, history, and keyboard
  backend modules.
- `dbus_service.py` exposes desktop control methods. `gateway_embed/` manages
  the optional local VocaGateway integration.

## Dictation data flow

```text
PortAudio or PipeWire
        |
        v
audio/capture.py and audio/pipewire.py
        |
        v
recognition_manager.py: VAD and silence segmentation
        |                       |
        |                 Silero VAD, when available
        |                 amplitude VAD otherwise
        v
bounded segment queue
        |
        v
recognition worker -> selected speech engine -> corrections and commands
        |
        v
text callback -> post_processor.py -> TextInjector backend
```

`PortAudioCaptureSource` and the PipeWire source provide mono 16 kHz PCM chunks.
The recognition manager owns dictation segmentation. It uses Silero VAD when
available and amplitude thresholds otherwise, then places finalized segments
on a bounded queue. A recognition worker consumes the queue, dispatches each
segment to the selected engine, applies dictionary corrections and voice
command parsing, and invokes callbacks.

The text callback submits work to one ordered post-processing worker. That
worker runs the configured post-processing script, then injects text or places
it in the in-app dictation pad. `TextInjector` selects a backend from the
detected `DesktopEnvironment`: X11 uses xdotool, Wayland can use wtype or
ydotool, and the IBus and Remote Desktop Portal paths support their respective
sessions.

## Threads and state ownership

- The GTK main thread owns widgets, dialog state, tray state, and the GLib main
  loop. UI-facing state callbacks use `GLib.idle_add` where needed; the D-Bus
  control service also marshals Toggle, Start, and Stop calls to this loop.
- The audio capture thread reads the capture source, tracks the current audio
  buffer and VAD state, and enqueues completed segments. The recognition worker
  owns queue consumption and transcription callback execution.
- The recognition manager's model lock protects engine and recognizer access
  during transcription, initialization, and cleanup. The segment queue is
  thread-safe; capture-buffer handoff uses its buffer lock.
- Text callbacks enqueue work on a single post-processing worker so script
  execution and injection stay in spoken order. Clipboard restoration can run
  on a separate worker. `TextInjector` protects its injection and clipboard
  restore bookkeeping with locks and generation state.
- Keyboard backends use listener or monitor threads for pynput and evdev.
  IBus and Remote Desktop Portal injection also use worker threads for their
  input and D-Bus work.
- GLib timeouts drive UI polling and progress updates. Recognition and capture
  workers use their own queue and event waits rather than GTK timers.

## Speech engines

`common_types.SpeechEngine` defines the runtime-checkable engine contract.
`speech_recognition/engines/available_engines()` reports optional engines in
Settings display order without importing the large Whisper packages just to
probe availability. `SettingsDialog` retains a compatibility wrapper for its
legacy engine-to-availability mapping.

`SpeechRecognitionManager._process_audio_buffer()` uses an engine-name dispatch
table to call the existing per-engine transcription methods. The manager owns
engine selection, model lifecycle, segment language snapshots, and the model
lock. Optional engine packages are loaded only when their engine is selected.

## Configuration and Settings

`ui/config_manager.py` defines `DEFAULT_CONFIG`, loads the user's JSON config,
and recursively overlays saved values on those defaults. It persists changes
through `save_config()`. Settings controls generally apply changes as they are
made and use callbacks to update the running engine or related services; values
that require a model reload take effect during that reload.

The Settings UI is split across `settings_dialog.py`, `settings_about.py`, and
`settings_engines.py`. Other UI responsibilities live in focused modules such
as `tray_indicator.py`, `dictation_overlay.py`, `transcription_history.py`,
`keyboard_shortcuts.py`, and `keyboard_backends/`.

## Services and optional integrations

`dbus_service.py` owns the `com.vocalinux.Vocalinux` session-bus name and
provides Toggle, Start, and Stop methods for external controls.
`gateway_embed/` manages the optional local VocaGateway container lifecycle,
status, pairing, and configuration. It is separate from the default
on-device whisper.cpp engine.
