# Custom Dictionary Support Design

## Scope

Custom dictionary support has two separate jobs:

1. **Custom terms** bias local Whisper, whisper.cpp, and Faster Whisper recognition
   toward names and jargon.
2. **Transcript corrections** deterministically replace a known misheard phrase
   after transcription.

They appear together on the **Custom Dictionary** Settings page, but are not
interchangeable. A correction replacement does not implicitly become a prompt
term. That coupling would make recognition bias depend on correction order and
would make the external terms contract surprising.

## File contracts

Both files live in VocaLinux's XDG-aware configuration directory:
`$XDG_CONFIG_HOME/vocalinux` (or `~/.config/vocalinux` when unset).

| File | Contract | Consumer |
| --- | --- | --- |
| `dictionary.txt` | UTF-8 (BOM accepted), one term per line. Blank lines and lines beginning with `#` are ignored. Terms are de-duplicated case-insensitively while retaining the first spelling. | VocaLinux and an external accessibility scanner. |
| `custom-dictionary-corrections.json` | UTF-8 JSON object: `{"version": 1, "corrections": [{"heard": "super base", "replacement": "Supabase"}]}`. | VocaLinux only. |

The terms file remains deliberately simple and scanner-friendly. Corrections
need two unambiguous fields, a version, and exact replacement casing, so JSON is
used rather than overloading the line file with an ambiguous delimiter grammar.
The UI writes either file by atomic replacement; a failed UI save preserves the
old file and reports an error.

The application reads both files for each completed transcript. An externally
edited file therefore takes effect on the next dictation segment without an app
restart. Missing, unreadable, malformed, or unsupported correction files are
ignored safely; dictation continues without their entries.

The terms file may contain any number of lines, but VocaLinux limits a single
prompt to the first 200 valid terms and 2,000 characters. This bounds decoding
work while leaving the scanner's complete line-file contract intact. The Custom
Dictionary page keeps both an add/remove editor and a validated file chooser
for the terms file.

## Processing and engine behavior

For every completed audio segment, VocaLinux applies this order:

1. The selected engine transcribes audio.
2. Live phrase corrections run against the raw transcript.
3. Voice-command interpretation runs on that corrected text.
4. Remaining text and actions are dispatched.

Corrections run before commands so a correction can prevent a command-like
misrecognition from being acted on. This also means users must not create a
replacement that deliberately creates a voice command unless that is intended.

Corrections match literal phrases case-insensitively, only where the adjacent
characters are not Unicode word characters (or common combining marks). Longer
phrases win over shorter overlaps; equal-length entries retain JSON order.
Replacement text is inserted exactly as written. Inputs are normalized to NFC
for matching, so composed/decomposed accents are handled consistently.

| Engine | Custom terms | Corrections |
| --- | --- | --- |
| OpenAI Whisper | `initial_prompt` | Yes |
| whisper.cpp | Advanced initial prompt followed by custom terms; explicit empty prompt clears reused native state | Yes |
| Faster Whisper | `initial_prompt` | Yes |
| VOSK | No prompt-bias API | Yes |
| Parakeet | No prompt-bias API | Yes |
| Remote API | No prompt is added to current request formats | Yes |

`--dictionary-file PATH` preserves the #767 session-only behavior: `PATH` is
used as the custom terms file, it enables terms for that session, and Settings
does not modify the saved terms file or enablement. Corrections remain loaded
from the standard JSON file. The previous experimental #768
`text_injection.custom_dictionary` config list is read only as a fallback until
the JSON corrections file exists; it is never silently deleted or migrated.

The #767 persisted configuration keys are retained unchanged:
`dictionary.enabled`, `dictionary.file_path` (default
`~/.config/vocalinux/dictionary.txt`), and `dictionary.max_words`. Existing
Peony settings therefore continue to select the scanner's `dictionary.txt`
file. New configured paths are accepted only when they can be expanded and are
either absent (so the UI can create them) or readable regular files; a failed
save leaves the prior setting in place. Invalid configured and `--dictionary-file`
paths are safely ignored and shown as unavailable rather than raising.

## Alternatives rejected

- **One mixed line file:** cannot express arbitrary phrases and replacements
  without reserving/escaping delimiters, which weakens the scanner contract.
- **Corrections in `config.json`:** makes a scanner compete with application
  settings writes and offers no durable external-file schema.
- **Post-command correction:** allows command-like transcription errors to be
  acted on before they can be fixed.
- **Automatically adding correction replacements to prompts:** rejected because
  replacements are not automatically included in the recognition prompt;
  corrections work post-transcription on every engine.

## Human test checklist

1. Add `VocaLinux`, `PyGObject`, and a non-ASCII term in **Custom terms**;
   confirm `dictionary.txt` is UTF-8, one line per term, and an external
   edit changes the next Whisper, whisper.cpp, and Faster Whisper dictation segment.
2. Add `super base` → `Supabase`; test lowercase, uppercase, punctuation, an
   overlapping short correction, `C++`, and non-ASCII text. Confirm replacement
   casing is exact and embedded text (for example `supersize`) is not replaced.
3. With voice commands enabled, add a correction that changes a command-like
   misrecognition into ordinary text. Confirm it is injected rather than acted
   on. Also verify an intentionally command-like replacement is avoided.
4. Edit each file externally while VocaLinux is running. Test an invalid JSON
   correction file and invalid UTF-8 terms file; confirm dictation continues and
   the Settings status/save feedback is clear.
5. Test the UI with keyboard only: Add buttons via Enter, empty validation,
   update/remove feedback, narrow window, long entries, and high-contrast theme.
6. Test all engines: Whisper, whisper.cpp, and Faster Whisper should use terms and
   corrections; VOSK, Parakeet, and remote API should use corrections only, with
   the VOSK terms warning.
7. Start with `--dictionary-file /path/to/terms.txt`; confirm the session uses
   that file, Settings disables terms editing, saved settings remain unchanged,
   and corrections still apply.
8. Start with an unresolved path such as `--dictionary-file ~missing-user/terms.txt`
   and configure an unreadable path through the file chooser. Confirm Settings
   reports the path safely, dictation continues without terms, and the prior
   saved `dictionary.file_path` remains intact.
