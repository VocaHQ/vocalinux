# Threat model

Vocalinux is a desktop voice-dictation app for Linux (X11 and Wayland). It records the
microphone, runs speech recognition, and types the result into whichever window has focus.
It runs as the logged-in user, never as root, and has no server of its own. Python
sources are under `src/vocalinux/`; the tests are under `tests/`.

## What this project does and where untrusted input enters

The user, their microphone, and their own config files are trusted. The local desktop
session is trusted to the extent that any process running as the same user already
has the user's privileges. Input from these places is untrusted:

1. **Downloaded models and archives.** whisper.cpp ggml files, VOSK zips, Parakeet and
   faster-whisper files come from Hugging Face, alphacephei.com and
   openaipublic.azureedge.net (`speech_recognition/recognition_manager.py`,
   `utils/*_model_info.py`). Every file must match the sha256 pinned in
   `utils/model_checksums.txt` before it is used or handed to native code
   (`utils/model_checksums.py`). Verification must fail closed. Look for ways around
   that rule: TOCTOU between verify and load, models "found on disk" and not
   re-hashed, path traversal in names, and zip-slip in `_unpack_vosk_model`.
2. **Update checks.** `utils/update_checker.py` and `utils/update_monitor.py` parse GitHub
   release JSON. Only URLs on this project's GitHub pages may be shown or opened
   (`is_trusted_release_url`).
3. **Remote transcription servers.** With the Remote API engine
   (`docs/HTTP_REMOTE.md`), audio goes to a user-configured OpenAI-compatible or
   whisper.cpp HTTP endpoint, and the JSON response is parsed and *typed into the
   focused window*. Treat the server as hostile. It may return oversized, malformed,
   or control-character-laden responses, try to make Vocalinux type key sequences,
   shell commands or terminal escapes, or redirect requests elsewhere.
4. **Local VocaGateway embed** (`gateway_embed/`). Vocalinux can start a
   [VocaGateway](https://github.com/VocaHQ/vocagateway) container via podman or docker
   compose. It writes the compose `.env` (`runner.py`, with `_IMAGE_RE` guarding image
   refs) and fetches pairing JSON and QR SVG from the gateway over HTTP (`pairing.py`,
   which has size caps). With "Allow LAN" on, the gateway publishes on `0.0.0.0:8765`, so
   other machines on the LAN can reach it. Values written into `.env` and compose
   arguments must not allow injection. Pairing responses must not lead to SSRF,
   unbounded reads, or a token leak.
5. **Local IPC.**
   - IBus text-injection socket in `text_injection/ibus_engine.py`: a unix socket in a
     0700 directory, socket mode 0600, peer UID checked with SO_PEERCRED.
   - Session D-Bus service in `dbus_service.py`.
   - Single-instance lock in `single_instance.py`.
   Another *local user* must not be able to inject text, drive the app, or read
   dictated text. A process running as the same user is not a security boundary.
6. **Recognised text.** The transcript is attacker-influenced, since someone can speak
   near the mic and audio can come from a video or call. It flows through
   `speech_recognition/command_processor.py`, `custom_dictionary.py` and
   `post_processor.py` into `text_injection/text_injector.py`. That module shells out
   to xdotool, ydotool, wtype, wl-copy, xclip and similar tools, and also uses the
   RemoteDesktop portal. Recognised text must only ever become typed characters. It
   must never become program arguments interpreted as options, a shell command, or
   key chords beyond the documented voice commands.
7. **Proxy settings** (`utils/proxy.py`): requests must honour them and must not leak
   credentials to other hosts.
8. **`install.sh` / `install.d/`**: these run once as the user, under curl-pipe-bash. They
   matter for supply chain: checksums of what they download, quoting, and temp-file
   handling.

## Components that matter most / least
- Most: text injection (`text_injection/`), model download, verification and unpacking
  (`speech_recognition/recognition_manager.py`, `utils/model_checksums.py`), the remote
  API client, `gateway_embed/`, IBus socket and D-Bus IPC, update checker.
- Less: GTK UI code under `ui/` (settings dialog, overlay, tray), except where it
  passes user or remote data into subprocesses or URLs.
- Out of scope: `web/` (the marketing website), `docs/`, `packaging/` (AppImage,
  Flatpak, AUR, Snap recipes), `snap/`, `.github/` workflows, and bugs that live
  in third-party engines (whisper.cpp, VOSK, sherpa-onnx, onnxruntime, torch)
  themselves. Report those upstream, unless Vocalinux calls them unsafely.

## How to exercise it
- `python -m pytest -q tests/` runs the full suite offline. Hardware and display tests
  are mocked. `tests/test_model_checksums.py`, `tests/test_gateway_embed.py`,
  `tests/test_update_checker*.py` and the `test_text_injector*` / `test_ibus_*` files are
  good starting points.
- `scripts/test_remote_server.py` is a small fake remote-transcription server for the
  Remote API engine.
- There is no microphone, display, or IBus daemon in the scan image, so drive the
  modules directly from Python with mocks, as the existing tests do. No speech model
  is preinstalled.
- The image runs as root. Two tests rely on chmod making a directory unwritable, which
  root ignores, so they fail there and nowhere else:
  `test_appimage_native_cache.py::test_publish_keeps_the_previous_cache_when_a_copy_fails`
  and `test_autostart_manager_ext.py::TestAutostartManagerExtra::test_enable_autostart_permission_error`.
  The rest of the suite (about 4,250 tests) passes offline.

## How you rate severity
- **Critical:** code execution as the user, or arbitrary keystroke or command injection
  into the focused window, from a remote party with no user action beyond normal use.
  Examples: a malicious remote-transcription server, update feed, model mirror or LAN
  peer of the gateway. Also critical: bypassing sha256 model verification so that
  attacker bytes reach whisper.cpp or another native loader.
- **High:** the same outcomes, but needing a non-default setting (a Remote API endpoint
  or Allow LAN), or a local *other user*. Also high: arbitrary file write outside the
  model, cache and config directories (for example zip-slip), and leaking dictated text,
  gateway tokens or proxy credentials to another host.
- **Medium:** SSRF limited to GET, unbounded memory or CPU use from remote data (DoS
  of the app), and symlink or temp-file races that need same-host timing.
- **Low / not a vulnerability:** anything that needs the attacker to already run code
  as the same user, or to edit the user's own config file. Crashes from malformed
  local config. Spoken words producing the documented voice commands.

## Anything to leave alone
- Do not report that spoken audio can contain arbitrary words that get typed. That is
  the product. Only escapes from "typed as literal text" count.
- Do not report that a same-UID process can talk to the D-Bus service or IBus socket.
- Model downloads use HTTPS to fixed hosts by design. Missing certificate pinning is not
  a finding.
