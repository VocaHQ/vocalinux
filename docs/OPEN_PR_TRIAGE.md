# Open pull request triage

Snapshot of all **21 open PRs** on VocaHQ/vocalinux, reviewed 13 Aug 2026 against `main` @ `36b2d92`.

**Do not merge this document into main.** It is a working triage board.

None of the 21 are safe to squash-merge as they sit. Four are one rebase or CI fix away. Five should be closed.

A print-friendly HTML dashboard ships next to this file: `docs/open-pr-triage.html` (open in a browser, or Print → Save as PDF).

## Do first

| PR | Verdict | Action |
|---|---|---|
| [#635](https://github.com/VocaHQ/vocalinux/pull/635) fix(installer): gate util-linux-extra to Ubuntu 24.04+ | Rebase first | Rebase onto main keeping current DNF/PACMAN Ayatana names, re-apply the apt-cache util-linux-extra probe, approve/re-run CI, then merge. |
| [#649](https://github.com/VocaHQ/vocalinux/pull/649) feat(text-injection): let config.json pin the injection backend | Fix, then merge | Approve first-time-contributor workflows and re-run CI. Optional: fix the leftover VOCALINUX_FORCE_BACKEND success logs. Prefer this over #402. Squash-merge once CI is green. |
| [#667](https://github.com/VocaHQ/vocalinux/pull/667) fix(tray): reuse open Settings/Logs dialog instead of duplicating it | Fix, then merge | Request the test isolation wrap (patch.object, matching test_settings_callback). Re-run CI. Ignore AppImage 503s. Squash-merge when Python 3.9/3.10 pass. |
| [#575](https://github.com/VocaHQ/vocalinux/pull/575) feat(security): pin and verify every model download with secured UX | Fix, then merge | Request changes. Do not merge until the false-success dialog and installer symlink check are fixed; decide fail-open vs STRICT-by-default in the same pass. |

## Close

| PR | Why |
|---|---|---|
| [#556](https://github.com/VocaHQ/vocalinux/pull/556) feat(text-injection): opt-in "Preserve Clipboard" for the Wayland paste fallback 🤖🤖🤖 | Clipboard restore already landed on main as always-on (#588/#646); this opt-in branch would regress that and still conflicts. |
| [#402](https://github.com/VocaHQ/vocalinux/pull/402) feat(injection): add selectable text injection backends | Stale 9-file backend picker; superseded by VOCALINUX_FORCE_BACKEND on main and the narrower config pin in #649. Lint red, conflicts, runtime reload does not rewire dictation. |
| [#425](https://github.com/VocaHQ/vocalinux/pull/425) fix: paste into Firefox through clipboard fallback | Draft Firefox+xdotool special case; #665 did not fix silent IBus drops, but this heuristic is wrong and main's clipboard-paste/backend-pin work supersedes it. |
| [#353](https://github.com/VocaHQ/vocalinux/pull/353) Add double-tap Super key shortcut and --settings CLI option (fixes from PR #332) 🤖🤖🤖 | suspend_handler.py and tray resume logic already live on main; super+super was later deprecated; double-tap Super fights GNOME Activities; --settings is the only leftover and belongs in a tiny new PR. |
| [#291](https://github.com/VocaHQ/vocalinux/pull/291) feat(shortcuts): custom keyboard shortcut capture widget | Custom shortcuts plus a Record/capture UI already shipped on main in #493; the parse_keys vs parse_shortcut single-key contract bug was never fixed and a rebase would collide with parse_shortcut_spec. |

## Keep, don’t merge yet

| PR | Verdict | One-liner |
|---|---|---|
| [#662](https://github.com/VocaHQ/vocalinux/pull/662) chore(deps): bump the npm_and_yarn group across 1 directory with 3 updates | Needs changes | Dependabot's 'postcss' group PR also major-bumps Next.js 15.5.21 → 16.3.0; the website build dies on default Turbopack plus a webpack-only next.config.js. |
| [#642](https://github.com/VocaHQ/vocalinux/pull/642) feat(commands): localize punctuation voice commands (#640) | Keep draft | Real #640 fix (language-aware punctuation aliases) that is still missing on main, but it is a draft with a PRODUCT.md conflict and no live dictation check. |
| [#634](https://github.com/VocaHQ/vocalinux/pull/634) docs: improve project documentation for a clearer public surface | Keep draft | Useful docs split (CoC/SUPPORT/CHANGELOG/INSTALL_MANUAL still absent on main) but 10 days stale: a naive merge would republish GPL and Toggle-as-default. |
| [#568](https://github.com/VocaHQ/vocalinux/pull/568) feat: opt-in D-Bus activation for compositor global shortcuts | Rebase first | Useful opt-in D-Bus activation, but the branch is still DIRTY vs current main; the claimed rebase stopped at cc69c7e. |
| [#543](https://github.com/VocaHQ/vocalinux/pull/543) feat(speech_recognition): add faster-whisper engine backend | Keep draft | Useful optional faster-whisper extra, but draft+conflicting, Engine registry unused, and install.sh claims CUDA while installing CPU PyTorch. |
| [#519](https://github.com/VocaHQ/vocalinux/pull/519) feat(snap): Snap packaging recipe and Snap Store publish strategy | Needs changes | In-repo snap recipe can land without a Snap Store account, but it is conflicting, codecov-red, ships a 315KB duplicate SVG, and requests network-bind + home it does not need. |
| [#516](https://github.com/VocaHQ/vocalinux/pull/516) feat(ui): floating glowing dictation overlay | Needs changes | Overlay work is real (optional GtkLayerShell, no present(), opacity instead of hide/show) but default-on plus a full-width always-mapped 30fps strip is the wrong first ship on GNOME Wayland. |
| [#487](https://github.com/VocaHQ/vocalinux/pull/487) feat(tray): add recent dictation snippets history menu 🤖🤖🤖 | Needs changes | Useful tray recovery feature with a sound in-memory store, but it is conflicting, defaults history on, and "delete that" does not actually purge the dictated text. |
| [#479](https://github.com/VocaHQ/vocalinux/pull/479) Pipe transcriptions through an optional postprocessing script | Needs changes | Clean stdin/stdout hook with timeout and no shell=True, but Jatin already put it on hold for the settings refactor (now landed) and example scripts, and the executable path needs hardening. |
| [#424](https://github.com/VocaHQ/vocalinux/pull/424) feat: add configurable Whisper language candidates | Keep draft | Useful whisper.cpp auto-detect constraint, not on main, but needs a rewrite against resolve_whisper_language and must not force a language at 0% confidence. |
| [#387](https://github.com/VocaHQ/vocalinux/pull/387) feat: experimental real-time streaming transcription (fixes #320) | Keep draft | Default-off is correct, but Whisper streaming is not real streaming, LA-2 is wrong in places, live injection is a stub, and the branch is stale/conflicting with 3.13 CI red — keep draft until redesigned. |
| [#503](https://github.com/VocaHQ/vocalinux/pull/503) refactor: mega-cleanup of dead bloat | Keep draft | Still a useful cleanup thesis, but this branch is too stale to merge: it deletes APIs and files that current main now uses, and conflicts with the settings/IBus/About rewrite. |

## Per-PR notes and paste-ready comments

### [#635](https://github.com/VocaHQ/vocalinux/pull/635) fix(installer): gate util-linux-extra to Ubuntu 24.04+

- **Verdict:** Rebase first (confidence high)
- **Author:** @flesler · ready · CONFLICTING · updated 2026-08-06
- **Size:** +25 / −2, 2 files
- **One-liner:** Correct apt-cache gate for #526; main still hardcodes util-linux-extra on Ubuntu, but install.sh conflicts with the later Ayatana package-list change.
- **Do this:** Rebase onto main keeping current DNF/PACMAN Ayatana names, re-apply the apt-cache util-linux-extra probe, approve/re-run CI, then merge.

Findings:

- **major** Main has not gated util-linux-extra; the PR still needs a rebase, not a close — origin/main install.sh still has util-linux-extra in APT_PACKAGES_UBUNTU (unconditional) and APT_PACKAGES_DEBIAN_13_PLUS. Introduced in 48a4dd6 for sg on Ubuntu 26.04/Debian 13 (#524). Ubuntu 22.04 / Mint 21 still fail with 'Unable to locate package util-linux-extra'. Issue #526 is closed (reporter closed it 2026-07-16, before this PR) but the installer bug is live. Do not treat the closed issue as 'already fixed'. (`install.sh`)
- **minor** Conflict is mechanical; keep main's Ayatana package names — merge-tree conflicts only in install.sh. PR head still has 'libappindicator-gtk3' on DNF_PACKAGES and PACMAN_PACKAGES; main removed those in afc4b37 (#621). Rebase must take main's DNF/PACMAN lines and re-apply only: drop util-linux-extra from the two APT base strings, then append via apt-cache show after Ubuntu/Debian list selection. Tests file has no conflict. (`install.sh`)
- **nit** Regression test is a source grep, not a probe execution — test_ubuntu_22_package_list_omits_util_linux_extra asserts the Ubuntu/Debian-13 lines omit the package and that 'apt-cache show util-linux-extra' plus the append assignment exist. Same style as test_installer_includes_xsel_for_wayland_clipboard_fallback. Adequate for this change; does not execute the probe. (`tests/test_installer_cuda_diagnostics.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review

Still needed. `main` has **not** gated `util-linux-extra`:

```text
APT_PACKAGES_UBUNTU=... wl-clipboard util-linux-extra $PYWHISPERCPP_BUILD_DEPS
APT_PACKAGES_DEBIAN_13_PLUS=... gir1.2-ayatanaappindicator3-0.1 util-linux-extra
```

That is exactly the jammy/Mint 21.3 failure in #526 (`E: Unable to locate package util-linux-extra`). #526 is closed by the reporter, not because this landed.

Head `49730ef` is the right design: drop it from both base lists, then

```bash
if apt-cache show util-linux-extra &>/dev/null 2>&1; then
    APT_PACKAGES="$APT_PACKAGES util-linux-extra"
fi
```

after Ubuntu vs Debian list selection. That matches the existing `glslc` / `libgirepository-2.0-dev` probes and is why Mint/Zorin `VERSION_ID` is not used (the first commit’s `UBUNTU_MAJOR -ge 24` gate would skip the package on Mint 22, which is noble-based). Maintainer already approved that follow-up; author verified `./install.sh --auto` deps on Ubuntu 22.04.

Wrappers still have `command -v sg` fallback from #524, so skipping the package on 22.04 is safe.

### Blockers

- **Rebase `install.sh`.** Conflict is the #621 Ayatana hunk sitting next to this edit. Keep main’s Fedora/Arch package lines (no `libappindicator-gtk3`); re-apply only the util-linux-extra probe.
- **Re-run CI on the rebased head.** Fork PRs often only get the labeler check until workflows are approved.

No other code issues. After rebase + green CI this is mergeable.
```

</details>

### [#649](https://github.com/VocaHQ/vocalinux/pull/649) feat(text-injection): let config.json pin the injection backend

- **Verdict:** Fix, then merge (confidence high)
- **Author:** @HashimAbdulaziz · ready · MERGEABLE · updated 2026-08-06
- **Size:** +217 / −4, 5 files
- **One-liner:** Narrow, correct config.json pin for #476; main still only has VOCALINUX_FORCE_BACKEND. CI never ran (first-time contributor cancel), not a code defect.
- **Do this:** Approve first-time-contributor workflows and re-run CI. Optional: fix the leftover VOCALINUX_FORCE_BACKEND success logs. Prefer this over #402. Squash-merge once CI is green.

Findings:

- **minor** Later selection logs still claim VOCALINUX_FORCE_BACKEND when the pin came from config — _check_dependencies is updated to log source as VOCALINUX_FORCE_BACKEND vs text_injection.backend, but the Wayland branch on current main still hardcodes `VOCALINUX_FORCE_BACKEND=wtype: using wtype...` / `...ydotool...` (text_injector.py:579 and :583 on main). After merge, a config-only pin will log the new source line then a contradictory env-var line. Update those two messages to use the same `source` variable. Pre-existing wording, made wrong by this PR. (`src/vocalinux/text_injection/text_injector.py:548`)
- **nit** No Settings UI; overlaps #402 but is the right slice — #402 (CONFLICTING, 9 files) adds a GTK combo, xdotool as a value, and runtime injector rebuild. This PR is additive auto-default, reads config the same way as _should_copy_to_clipboard, and leaves _forced_backend() env-only. Current main has no text_injection.backend key and USER_GUIDE.md has no injection-backend section — #476 is not already solved. Prefer this PR; park/close #402 rather than merging both. (`src/vocalinux/ui/config_manager.py:83`)
- **nit** Pinning wtype on X11 silently selects xdotool — documented, still easy to misread — Accepted values stay ibus/wtype/ydotool/auto to match the env enum. USER_GUIDE.md correctly says X11's real choice is ibus vs anything else. No code bug. A debug log when environment is X11 and preference is wtype/ydotool ('using xdotool') would save a support thread. (`docs/USER_GUIDE.md`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review (@HashimAbdulaziz)

This is the right shape for #476. Current `main` still only honors `VOCALINUX_FORCE_BACKEND`; there is no `text_injection.backend` default, no disk reader, and no user-guide section. Autodetect stays byte-for-byte when the key is missing/`auto`.

Resolution order (env, then config, else auto), unknown-value warning, and corrupt-JSON fallback match `_forced_backend()` / `_should_copy_to_clipboard()`. Tests cover the preference matrix, including invalid env falling through to a valid saved setting. Staying off `ConfigManager` in this package is consistent with the clipboard helper.

CI red Xes are not a test failure: both `Vocalinux CI` and `Flatpak` were cancelled at `steps=0` (first-time-contributor `pull_request` approval). Labeler on `pull_request_target` ran. I am treating that as workflow gating, not a defect in this diff.

Versus #402: please keep this PR. #402 is conflicting, rebuilds the injector at runtime, and adds Settings/tray UI across 9 files. This change is the persistent pin the issue asked for. Settings toggle can be a follow-up.

One follow-up in the same file after rebase: `_check_dependencies` now logs `text_injection.backend=wtype`, but the Wayland success path on main still logs `VOCALINUX_FORCE_BACKEND=wtype: using wtype for Wayland injection`. Please thread the `source` name into those two lines so `--debug` is not lying.

Approve workflows, confirm `tests/test_text_injector.py` + `tests/test_text_injector_ext.py`, then squash-merge. GitHub reports MERGEABLE against main (including the later ibus XKB work); no rebase required unless you want that log tweak in the same commit.
```

</details>

### [#667](https://github.com/VocaHQ/vocalinux/pull/667) fix(tray): reuse open Settings/Logs dialog instead of duplicating it

- **Verdict:** Fix, then merge (confidence high)
- **Author:** @AmirF194 · ready · MERGEABLE · updated 2026-08-12
- **Size:** +85 / −0, 2 files
- **One-liner:** Production reuse logic is sound, but the new tests ignore the file's own patch.object pattern and fail Python 3.9/3.10 in the full suite.
- **Do this:** Request the test isolation wrap (patch.object, matching test_settings_callback). Re-run CI. Ignore AppImage 503s. Squash-merge when Python 3.9/3.10 pass.

Findings:

- **blocker** New reuse tests fail in the full 3.9/3.10 suite — CI run 31631035019: test_about_reuses_open_settings_dialog (SettingsDialog called 0 times), test_settings_dialog_reused_on_repeated_click and test_settings_dialog_destroy_allows_a_fresh_one (StopIteration; SettingsDialog is a MagicMock spec='str' with an exhausted tuple side_effect, and config_manager is a real ConfigManager). test_settings_callback already documents the fix: 'Use patch.object to patch SettingsDialog on the actual module object / This ensures the patch applies to the reference that _on_settings_clicked uses.' The new tests call self.mock_settings_dialog_class from setUp and skip that wrap, so they pass in isolation / on 3.11+ and fail in the 3.9/3.10 full run. Wrap each new test the same way as test_settings_callback. (`tests/test_tray_indicator.py:267`)
- **minor** Settings click while About is showing does not navigate off About — _show_settings_page(None) reuses with `if page_name:` so a falsy page_name only present()s. About and Settings share one dialog; opening About then clicking Settings leaves the user on the About page. First-open Settings uses initial_page=None and selects sidebar row 0. Either navigate to the default page when page_name is None, or document that a second Settings click only raises. (`src/vocalinux/ui/tray_indicator.py:573`)
- **nit** Destroy handlers should identity-check before clearing — _on_settings_dialog_destroy / _on_logging_dialog_destroy unconditionally set the slot to None. If destroy is delivered after a replacement instance is stored, the live dialog becomes untracked and the next click duplicates again. Use `if self._settings_dialog is dialog:`. Unlikely with the current single-instance path, but it is the usual GTK pattern. (`src/vocalinux/ui/tray_indicator.py:596`)
- **nit** AppImage x86_64/aarch64 failures are unrelated 503s — x86_64: curl 503 fetching AppImage tooling. aarch64: appimagetool 'Failed to download runtime: server returned status code 503' from AppImage/type2-runtime. Not caused by this diff. Website, lint, Flatpak, and Python 3.11/3.13 are green.

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review (@AmirF194)

The tray change itself is the right fix for duplicate Settings/Logs windows. Tracking one instance, connecting `destroy` to drop it, and `present()` / `navigate_to_page()` on a repeat click matches how this GTK dialog should work. `navigate_to_page` exists on `SettingsDialog` (settings_dialog.py:1353). Current `main` still constructs a new dialog every click in `_show_settings_page` / `_on_logs_clicked` — this is not already landed.

**Required before merge:** the three new tests fail Python 3.9 and 3.10 in the full CI suite (run `31631035019`).

- `test_about_reuses_open_settings_dialog` — `SettingsDialog` called 0 times
- `test_settings_dialog_reused_on_repeated_click` / `test_settings_dialog_destroy_allows_a_fresh_one` — `StopIteration` from a polluted `SettingsDialog` mock (`spec='str'`, tuple iterator side_effect). The `config_manager` passed in is a real `ConfigManager`, so setUp's patches are not the object `_show_settings_page` is calling.

`test_settings_callback` already explains this and uses `patch.object` on the imported module:

```python
import vocalinux.ui.tray_indicator as tray_module
with patch.object(tray_module, "SettingsDialog", mock_dialog_class):
    ...
```

Please wrap the new Settings tests the same way (and keep the logs tests' `patch.dict(sys.modules, ...)` style, which did stay green). Author-reported local green was against a subset; CI's 3.9/3.10 jobs run the whole `tests/` tree.

AppImage x86_64/aarch64 red Xes are GitHub 503s downloading linuxdeploy/type2-runtime, not this diff.

**Optional:** `_show_settings_page` reuse does `if page_name:` so Settings (page_name=None) while About is open only raises the window and leaves the About page selected. If that is unintended, navigate to the default page when `page_name` is None. Also consider `if self._settings_dialog is dialog:` in the destroy handlers.

Happy to merge once 3.9/3.10 are green.
```

</details>

### [#575](https://github.com/VocaHQ/vocalinux/pull/575) feat(security): pin and verify every model download with secured UX

- **Verdict:** Fix, then merge (confidence high)
- **Author:** @jatinkrmalik · ready · MERGEABLE · updated 2026-08-03
- **Size:** +1897 / −90, 16 files
- **One-liner:** Solid hash pinning and zip-slip work, but Bugbot's high-severity false-success dialog is still open and the installer/runtime checks are fail-open by default.
- **Do this:** Request changes. Do not merge until the false-success dialog and installer symlink check are fixed; decide fail-open vs STRICT-by-default in the same pass.

Findings:

- **blocker** Failed integrity/apply still shows SHA256 success — download_and_apply always GLib.idle_add(download_dialog.set_complete, True) after _apply_settings_internal(settings) without checking the bool. _apply_settings_internal catches ModelIntegrityError (and any reconfigure failure), shows an error dialog, and returns False. The exception never reaches download_and_apply's except, so the secured dialog still flips to success. If the hash already matched, set_complete sees _integrity_verified True and paints 'SHA256 verified · Model ready to use' for a model that was discarded / settings that were not applied. Same pattern at both call sites. Bugbot flagged this as High on e96e6ba; still unfixed. (`src/vocalinux/ui/settings_dialog.py:4493-4495`)
- **major** Installer zip check skips symlinks that runtime refuses — verify_zip_members_safe only greps unzip -Z1 names for absolute paths and '..' segments, then install.sh still unzip -d. It never inspects member type. Runtime safe_extract_zip rejects Unix symlink entries via external_attr 0xA000. SECURITY.md says VOSK archives with symlink members are refused. The installer path does not honor that. Bugbot Medium, still open. (`install.sh:3345-3357`)
- **major** Verification is fail-open unless VOCALINUX_STRICT_MODEL_VERIFICATION is set — load_registry() returns {} on OSError/JSONDecodeError, so a missing or corrupt model_hashes.json silently disables every pin. verify_downloaded_model then warns and returns if get_pinned_digest is None (strict=False, the default). install.sh verify_model_sha256 returns 0 when the registry/python3 lookup fails or sha256sum is missing. Tests explicitly assert this degradation. For a change titled 'pin and verify every model download', the shipped default still installs unverified bytes whenever the pin lookup fails. STRICT exists but is opt-in and not used by install.sh at all. (`src/vocalinux/utils/model_integrity.py:77-147`)
- **major** Cancel is ignored during SHA256 and VOSK extract — _download_cancelled is only observed in _interruptible_pause and the streaming loops. After the last byte, _verify_download_with_status hashes the whole file and the VOSK path then safe_extract_zip + rename without re-reading the flag. A Cancel click while the dialog says 'Verifying SHA256 checksum…' still installs the model and later hits set_complete(True). Bugbot Medium, still open. Large VOSK/whisper.cpp files make this a multi-second window. (`src/vocalinux/speech_recognition/recognition_manager.py:1909-1935`)
- **minor** Hash refresh script KeyError on missing Content-Length — collect_whisper does int(response.headers['content-length']) after HEAD. OpenAI's CDN can omit that header; the whole Whisper pin refresh then aborts. Bugbot Low, still open. Use headers.get and skip/size-from-GET. (`scripts/update_model_hashes.py:100-105`)
- **minor** Pins are only checked at download time, not at load — A file already in the models dir, or replaced after a successful verify+rename, is loaded with no digest check. The tmp-file verify-then-os.rename path is fine against network tampering; it is not a load-time TOCTOU control. Out of the stated download scope, but the lock-badge copy implies ongoing integrity. (`src/vocalinux/speech_recognition/recognition_manager.py:2054-2058`)
- **nit** Hash supply chain is the upstream API, reviewed only as a JSON diff — collect_whispercpp copies Hugging Face LFS sha256 from the repo API; collect_vosk hashes live zips and cross-checks Alphacephei's MD5. SECURITY.md already says pinning is integrity not authenticity. Treat model_hashes.json diffs as security-sensitive in review; a compromised HF/Alphacephei response would produce a matching pin PR. (`scripts/update_model_hashes.py:68-77`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review @jatinkrmalik

The pinning, HTTPS/host checks, HTTP-downgrade guard, and runtime `safe_extract_zip` are the right shape. Registry coverage tests and the packaging fix (`pyproject.toml` + `MANIFEST.in`) close the earlier Bugbot holes (placeholder VOSK hash, JSON omitted from the wheel, false "hash matches" on unpinned files).

I am not merging this while two unresolved Bugbot findings still hold on `e96e6ba`.

### Blocker: success UI after a failed apply

`download_and_apply` does this in both places (`settings_dialog.py:4493-4495` and `:4783-4785`):

```python
self._apply_settings_internal(settings)
GLib.idle_add(download_dialog.set_complete, True, "")
```

`_apply_settings_internal` (`:4809-4839`) swallows `ModelIntegrityError`, shows an error dialog, and returns `False`. That exception never reaches the `except Exception` in `download_and_apply`, so the secured dialog still calls `set_complete(True)`. If the digest already matched, `_integrity_verified` is set (`:1235-1236`) and the user sees **SHA256 verified · Model ready to use** for a download that was discarded.

Honor the return value (or let integrity errors propagate). Do not paint success unless `reconfigure` actually succeeded.

### Still open from Bugbot

- **Installer zip-slip vs runtime** (`install.sh:3345-3357`): `verify_zip_members_safe` greps names only. `unzip` will still create symlink members. `safe_extract_zip` (`model_integrity.py:210-213`) refuses them. `SECURITY.md` says they are refused. Make the installer check `unzip -Z` / `file_type` (or skip `unzip` and share the Python helper).
- **Cancel during verify** (`recognition_manager.py:1909-1935`, VOSK `:2235-2243`): after the stream ends, SHA256 + extract/rename never read `_download_cancelled`. Check it after `verify_downloaded_model` and before `os.rename` / `safe_extract_zip`, and delete the temp file.
- **`collect_whisper` KeyError** (`scripts/update_model_hashes.py:104`): `response.headers["content-length"]` will abort the whole Whisper refresh if the HEAD has no length. `.get()` and skip.

### Fail-open (not a merge blocker if you document it as the product choice, but it fights the PR title)

`load_registry()` returns `{}` on a missing/corrupt JSON (`model_integrity.py:77-85`). Unpinned files then download with a warning (`:139-147`). `install.sh` `verify_model_sha256` returns 0 when the pin lookup or `sha256sum` is missing (`:3319-3327`). Tests lock that in. Default-off `VOCALINUX_STRICT_MODEL_VERIFICATION` is the only fail-closed switch, and the installer never reads it.

If the claim is "every model download is verified", a missing registry should refuse the download, not warn. Otherwise say plainly in SECURITY.md that verification is best-effort unless STRICT is set, including on `install.sh`.

### What I am not blocking on

- Zip-slip in the Python path looks correct: absolute names, `resolve()` escape check, symlink attr, 8 GiB cap, then `extractall` on the same `ZipFile`.
- Runtime flow is verify-the-tmp-file then `os.rename`; that is the right TOCTOU story for the network attacker.
- Whisper pins matching the OpenAI URL digest is tested. VOSK `TODO_DOWNLOAD_AND_COMPUTE` is gone (`vosk-model-small-en-us-0.15.zip` has a real sha256).
- Portuguese medium/large ID change to `vosk-model-pt-fb-v0.1.1-20220516_2113` is required for the coverage test; fine as part of this PR.
- No equivalent of this exists on `main`.

CI is green and GitHub reports MERGEABLE (install.sh overlap with later util-linux-extra commits looks auto-mergeable). Fix the false-success dialog and the installer symlink gap, then this is mergeable.
```

</details>

### [#662](https://github.com/VocaHQ/vocalinux/pull/662) chore(deps): bump the npm_and_yarn group across 1 directory with 3 updates

- **Verdict:** Needs changes (confidence high)
- **Author:** @app/dependabot · ready · MERGEABLE · updated 2026-08-08
- **Size:** +310 / −191, 2 files
- **One-liner:** Dependabot's 'postcss' group PR also major-bumps Next.js 15.5.21 → 16.3.0; the website build dies on default Turbopack plus a webpack-only next.config.js.
- **Do this:** Close or refuse merge. Recreate a postcss/nanoid-only bump; keep Next 15 until there is a dedicated Next 16 migration PR. Do not squash-merge.

Findings:

- **blocker** Unadvertised Next.js 16 major bump breaks the site build — PR body lists postcss 8.5.19→8.5.26, nanoid 3.3.16→3.3.18, sharp 0.34.5→0.35.3. The actual package.json diff also changes next ^15.5.21 → ^16.3.0 (and the lockfile root + node_modules/next follow). CI run 31276436442: `▲ Next.js 16.3.0 (Turbopack)` then `ERROR: This build is using Turbopack, with a webpack config and no turbopack config`. Secondary: tsc `next.config.js:23` — `eslint` is not in NextConfig (Next 16 removed that key). This is a framework migration, not a postcss patch. Main is still Next 15.5.21 (confirmed in /workspace web/package.json and lockfile). (`web/package.json:32`)
- **major** sharp 0.34.5 → 0.35.3 rides along as a 0.x breaking bump — Lockfile replaces @img/sharp-* 0.34.5 with 0.35.3 (engines node >=20.9.0, libvips 1.3.2). Fine only as a Next 16 companion; not an independent, reviewable postcss fix. nanoid 3.3.18 (zero-size loop) is a real patch and can come back in a postcss-only PR. (`web/package-lock.json`)
- **minor** Intended postcss bump is still missing on main — Main lockfile still resolves postcss 8.5.19 (package.json ^8.5.12). 8.5.23's 'do not load source map without opts.from' is the actual security-ish reason to want this group. Recreate without touching next. (`web/package.json:55`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review (Dependabot)

Do not merge. The title says postcss, but `web/package.json` also does:

```diff
-    "next": "^15.5.21",
+    "next": "^16.3.0",
```

CI `Build Website` (run `31276436442`) installs Next 16.3.0, enables Turbopack by default, and fails:

```
ERROR: This build is using Turbopack, with a `webpack` config and no `turbopack` config.
```

`npm run test:types` also errors on `eslint` in `next.config.js` (removed in Next 16). Current `main` still pins Next 15.5.21 and the website job is green there.

postcss 8.5.26 / nanoid 3.3.18 are still worth taking. Next 16 is a separate migration (Turbopack or `--webpack`, drop the `eslint` config key, re-verify static export).

Please close this PR and open a postcss-only bump (`@dependabot ignore next major version` on this group, then recreate), or replace this branch with a lockfile that leaves `next` at 15.5.x.
```

</details>

### [#642](https://github.com/VocaHQ/vocalinux/pull/642) feat(commands): localize punctuation voice commands (#640)

- **Verdict:** Keep draft (confidence high)
- **Author:** @jatinkrmalik · draft · CONFLICTING · updated 2026-08-04
- **Size:** +355 / −52, 8 files
- **One-liner:** Real #640 fix (language-aware punctuation aliases) that is still missing on main, but it is a draft with a PRODUCT.md conflict and no live dictation check.
- **Do this:** Rebase onto main, resolve PRODUCT.md by keeping AGPL + Right-Alt PTT default and only updating the voice-command bullet, run a live Italian dictation check, then undraft.

Findings:

- **major** Cannot merge until PRODUCT.md is rebased against current main — git merge-tree vs origin/main conflicts only in web/PRODUCT.md. Main now says 'Shortcut modes: push-to-talk default (hold Right Alt / Option)' and 'AGPL-3.0'; the PR still has 'toggle and push-to-talk' and 'GPL-3.0'. A careless resolve would revert #648 and #660 in the product-truth file. command_processor.py itself has not changed on main since merge-base 45acb10, so the feature hunks should apply cleanly. (`web/PRODUCT.md`)
- **minor** auto language keeps English-only aliases by design — normalize_command_language('auto') returns 'en', and test_auto_language_keeps_english_only_aliases asserts 'virgola' is not loaded. That matches the PR body, but #640's reporter may have been dictating Italian under Auto-detect. Whisper's detected language is never fed into CommandProcessor. Documented; not a code bug, but it is the gap most likely to make the issue look unfixed. (`src/vocalinux/speech_recognition/command_phrases.py`)
- **nit** NL/PL/RU alias maps are untested — Tests cover IT/FR/DE/ES/PT plus English 'dot', auto, and set_language. Dutch/Polish/Russian tables (including Cyrillic) have no process_text cases. Codecov reported 4 uncovered lines in command_phrases.py. Not a merge blocker. (`tests/test_command_processor.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review (draft / do not merge yet)

This is the right fix for #640. Current `main` still constructs `CommandProcessor()` with no language (`recognition_manager.py` ~927) and the English-only `text_commands` map. Spoken Italian/French punctuation is still injected as words.

The implementation is small and coherent:
- `command_phrases.py` keyed by Whisper ISO codes (`it`/`fr`/`de`/`es`/`pt`/`nl`/`pl`/`ru`), English extras always merged (`dot` → `.`)
- `CommandProcessor(language=…)` / `set_language()` rebuild aliases and sort longest-first so `punto interrogativo` does not collapse to `.` + leftover `interrogativo`
- attach-left spacing keyed by replacement char (`.,?;:`) so locale phrases get the same `ciao,mondo` behavior as English `comma`
- `SpeechRecognitionManager` passes language on init and on `reconfigure` when it actually changes

CI on the head commit is green (Python 3.9–3.13, Bugbot). I did not invent issues in the alias tables; longest-first + `re.IGNORECASE` is the correct matcher for these phrases.

### Blockers

1. **Draft + unchecked manual test.** The Italian “ciao virgola mondo punto” live check in the test plan is still open. Unit tests cannot catch ASR tokenization (`point d'interrogation` vs `point d interrogation` is already aliased; curly apostrophes are not).
2. **Conflict in `web/PRODUCT.md` only.** Rebase and keep main’s PTT-default + AGPL-3.0 lines; only swap the English-only voice-command bullet. Do not take the PR’s `GPL-3.0` / old shortcut wording.

### After rebase

- Mark ready once one real Italian (or French) dictation pass works with voice commands on.
- Optional: one NL/PL/RU `process_text` case; optional note in USER_GUIDE that Auto-detect does not load locale punctuation aliases.

Out of scope as stated (action/format phrases stay English) is fine for this PR.
```

</details>

### [#634](https://github.com/VocaHQ/vocalinux/pull/634) docs: improve project documentation for a clearer public surface

- **Verdict:** Keep draft (confidence high)
- **Author:** @jatinkrmalik · draft · CONFLICTING · updated 2026-08-03
- **Size:** +1379 / −1919, 20 files
- **One-liner:** Useful docs split (CoC/SUPPORT/CHANGELOG/INSTALL_MANUAL still absent on main) but 10 days stale: a naive merge would republish GPL and Toggle-as-default.
- **Do this:** Keep draft. Rebase onto main and explicitly restore AGPL, Right-Alt PTT default, Ayatana Fedora/Arch packages, and the CUDA device-0 note before considering undraft.

Findings:

- **major** Would regress the public license to GPL-3.0 — PR README badge is still 'License: GPL v3' linking gnu.org/licenses/gpl-3.0. Main is AGPL-3.0 after #660 (badge, intro, license section). PRODUCT.md on main also says AGPL-3.0. Merging the rewrite without that update puts the wrong license on the repo front door. (`README.md`)
- **major** USER_GUIDE still documents Toggle + Ctrl as the default shortcut — PR USER_GUIDE: 'Toggle (default) | Double-tap the shortcut key (Ctrl by default)' and 'Start dictation with the tray menu or your keyboard shortcut'. Main after #648: 'Hold Right Alt (Option) by default' and 'Push-to-talk mode (default)'. Rebasing USER_GUIDE by taking the PR side would undo that user-facing change. (`docs/USER_GUIDE.md`)
- **major** INSTALL_MANUAL Fedora/Arch package lists predate the Ayatana switch — PR new docs/INSTALL_MANUAL.md still has 'python3-gobject gtk3 libappindicator-gtk3' (Fedora) and 'libappindicator-gtk3' (Arch). Main docs/INSTALL.md after #638 uses libayatana-appindicator-gtk3 / libayatana-appindicator. Splitting INSTALL without carrying #638 recreates the wrong tray packages in the manual path. (`docs/INSTALL_MANUAL.md`)
- **minor** Main USER_GUIDE CUDA device-0 note is missing from the PR — #644 added the pywhispercpp CUDA device 0 / hybrid-GPU warning to docs/USER_GUIDE.md on main. The PR rewrite of that file does not include it. Easy to drop in a conflict resolve. (`docs/USER_GUIDE.md`)
- **nit** Structural docs work is still not on main — do not close — main still has no CHANGELOG.md, CODE_OF_CONDUCT.md, SUPPORT.md, docs/INSTALL_MANUAL.md, docs/TROUBLESHOOTING.md, or docs/README.md. README is still 510 lines with three badge rows and a full v0.15 highlight table; INSTALL.md is still 715 lines including pipe-to-bash. The split and calmer templates remain worth landing after a careful rebase. (`README.md`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review (keep draft)

Docs-only, and the *shape* is still worth it: main has no CoC / SUPPORT / CHANGELOG / INSTALL_MANUAL / TROUBLESHOOTING / docs index. README on main is still badge-heavy (510 lines) and INSTALL.md is still a 715-line grab bag with `curl … | bash`.

Do **not** merge this tree as-is. It diverged from main on purpose-user facts, not just wording.

### Must carry forward on rebase

| Landed on main | PR still has |
|---|---|
| AGPL-3.0 badge + copy (#660) | GPL v3 badge |
| Push-to-talk / hold Right Alt default (#648) | Toggle default, Ctrl double-tap in USER_GUIDE |
| Fedora/Arch Ayatana package names (#638) | `libappindicator-gtk3` in the new INSTALL_MANUAL lists |
| CUDA device 0 hybrid-GPU note (#644) | absent from rewritten USER_GUIDE |

Conflicts: `CONTRIBUTING.md`, `README.md`, `docs/INSTALL.md`, `docs/UPDATE.md`, `docs/USER_GUIDE.md`. Auto-merge will not save the license or shortcut default — those are content choices in the rewrite.

`CODE_OF_CONDUCT.md` (Contributor Covenant), root `SUPPORT.md` / `CHANGELOG.md` (pointers, not a dump), and download-then-run install snippets are fine. No application code in the diff.

Rebase, re-read README + USER_GUIDE + INSTALL_MANUAL against current main, then undraft.
```

</details>

### [#568](https://github.com/VocaHQ/vocalinux/pull/568) feat: opt-in D-Bus activation for compositor global shortcuts

- **Verdict:** Rebase first (confidence high)
- **Author:** @webenefits · ready · CONFLICTING · updated 2026-07-29
- **Size:** +842 / −7, 9 files
- **One-liner:** Useful opt-in D-Bus activation, but the branch is still DIRTY vs current main; the claimed rebase stopped at cc69c7e.
- **Do this:** Do not merge. Ask author to rebase onto current main (not cc69c7e) and update USER_GUIDE; re-review after GitHub reports MERGEABLE.

Findings:

- **blocker** Still conflicting; rebase claim is stale — Maintainer asked for a rebase (CHANGES_REQUESTED). Author replied that the branch is linear on cc69c7e with no merge commits. GitHub still reports DIRTY. Current main is not that commit: tray_indicator.py now prefers Ayatana AppIndicator (#621), default shortcut is hold Right Alt PTT (#648), and USER_GUIDE/settings/tray have all moved. The PR body still says 'double-tap Ctrl still works out of the box', which is no longer true on main. A rebase is required before any code review of the conflicted files can be trusted. (`src/vocalinux/ui/tray_indicator.py`)
- **major** Session D-Bus Toggle/Start/Stop is always registered, not gated on the opt-in — TrayIndicator.__init__ always constructs VocalinuxDBusService. shortcuts.disable_internal_hotkey only skips the evdev/pynput listener. Any same-user process on the session bus can call com.vocalinux.Vocalinux.Toggle/Start/Stop and start the microphone, even when the user never enabled 'external activation'. That is normal for an unauthenticated session-bus API and is probably how vocalinux --toggle is meant to work without extra config, but it is new attack surface vs main (where only the hotkey listener / tray can start recognition). Document it; consider Restricting to the same uid is already implied by the session bus, so this is mostly a product note, not a Polkit request. Do not silently leave it undocumented in USER_GUIDE. (`src/vocalinux/ui/tray_indicator.py:165-176`)
- **minor** D-Bus method returns success before the handler runs — _handle_method_call GLib.idle_add(self._invoke, callback) then invocation.return_value(None). send_command / vocalinux --toggle therefore exits 0 even if _toggle_recognition later throws. Fine as fire-and-forget if documented; the CLI cannot report 'started'. (`src/vocalinux/dbus_service.py:131-134`)
- **nit** No equivalent on main — main.py has no --toggle/--start/--stop, no dbus_service.py, and no disable_internal_hotkey. The feature is still unique. Keep it; just rebase. Bus name com.vocalinux.Vocalinux matches the Flatpak id, which is the right name if you later export it from the manifest. (`src/vocalinux/dbus_service.py:19-21`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review @webenefits

The design is still the one I want: compositor shortcut runs `vocalinux --toggle`, CLI talks to the running instance **before** the single-instance lock, and `disable_internal_hotkey` actually `stop()`s the shortcut manager before returning (`tray_indicator.py:177-194`). Tests for CLI dispatch and the config gate look real.

I cannot review-to-merge a DIRTY branch.

You wrote that this was rebased onto current main through `cc69c7e`. GitHub still has **mergeable=CONFLICTING** / **DIRTY**, and `main` has moved since that commit (Ayatana-first tray, default hold-Right-Alt PTT in #648, update checker, AGPL, clipboard restore, …). Conflicts are in `settings_dialog.py`, `tray_indicator.py`, `config_manager.py`, `docs/USER_GUIDE.md`, and `tests/test_settings_shortcuts.py`. Please rebase onto **current** `main` and push; the PR body still says double-tap Ctrl is the default, which is no longer true.

Until that exists I am not treating the conflicted files as reviewable. Two notes to handle in the rebase, not as reasons to abandon the PR:

1. `VocalinuxDBusService` is constructed unconditionally (`tray_indicator.py` init). The opt-in only drops `/dev/input`. That is probably what you want so `vocalinux --toggle` works without flipping a setting, but USER_GUIDE should say any same-user session-bus client can Start/Stop the mic. This API does not exist on `main` today.
2. `_handle_method_call` acks the D-Bus call before `_invoke` runs (`dbus_service.py:131-134`). `--toggle` can exit 0 and then the handler can fail. Acceptable if the docs call it fire-and-forget.

No equivalent feature on `main`; this should not be closed. Rebase, fix the USER_GUIDE default-shortcut text, then ping for re-review.
```

</details>

### [#543](https://github.com/VocaHQ/vocalinux/pull/543) feat(speech_recognition): add faster-whisper engine backend

- **Verdict:** Keep draft (confidence high)
- **Author:** @jatinkrmalik · draft · CONFLICTING · updated 2026-07-18
- **Size:** +1108 / −14, 13 files
- **One-liner:** Useful optional faster-whisper extra, but draft+conflicting, Engine registry unused, and install.sh claims CUDA while installing CPU PyTorch.
- **Do this:** Keep draft. Rebase onto current main. Fix install.sh CUDA lie (CPU torch URL). Either wire SpeechRecognitionManager through ENGINES or delete the unused Protocol/registry. Extend settings model/download paths after rebase.

Findings:

- **blocker** Installer CUDA claim is false — In the HAS_NVIDIA_GPU==yes branch the installer says it is installing PyTorch with CUDA support and may download ~2GB of CUDA runtime, then immediately runs `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu`. That is the CPU wheel index. faster-whisper inference is CTranslate2, not torch; this PR never installs a CUDA ctranslate2 build either. `_has_torch_cuda()` will therefore stay false after a 'GPU' install, `get_compute_type` will pick int8/CPU, and the menu copy 'Best performance on NVIDIA GPUs (CUDA)' is advertising a path the installer does not create. INT8-on-CPU (`get_compute_type('cpu') == 'int8'`) is the one claim that matches the code. (`install.sh`)
- **major** Engine Protocol / engines/ registry is dead code — `src/vocalinux/speech_recognition/engines/` does NOT exist on main — this is new, not a duplicate. But it is also not wired up. ENGINES is only populated for FasterWhisperEngine (bare `except Exception: pass`), and SpeechRecognitionManager never reads ENGINES: it still uses engine == 'vosk'|'whisper'|'whisper_cpp'|'remote_api'|'faster_whisper' if/elif in __init__, _process_audio_buffer, reconfigure, and reinitialize_after_resume. Existing engines do not implement the Protocol. For one optional backend this is a premature abstraction; either route the manager through ENGINES or drop the Protocol/registry until a second backend actually uses it. (`src/vocalinux/speech_recognition/engines/__init__.py`)
- **major** Must rebase; settings/manager surfaces have moved on — Default engine is correctly still whisper_cpp (DEFAULT_CONFIG, --auto, CLI help). Optional extra `faster_whisper = [faster-whisper>=1.0.0]` in pyproject.toml is the right dep shape. After rebase the manager still needs faster_whisper arms in reconfigure/reinitialize_after_resume (main now also has auto-pause / idle-unload reinit). settings_dialog.py on main has ENGINE_MODELS, variant picker, and _auto_apply_settings download branches only for whisper/whisper_cpp/vosk — the PR's 36-line _populate_model_options patch will not apply cleanly and does not teach the download/info cards about HF-cached faster-whisper models. (`src/vocalinux/ui/settings_dialog.py`)
- **minor** Settings model list and MODEL_INFO disagree — FASTER_WHISPER_MODEL_INFO includes tiny.en/base.en/large-v1/large-v2, but ENGINE_MODELS['faster_whisper'] only lists tiny/base/small/medium/large-v3. Harmless if intentional, but the UI cannot select the .en variants the metadata describes. (`src/vocalinux/ui/settings_dialog.py`)
- **nit** Registry swallows all exceptions — `try: from .faster_whisper_engine import FasterWhisperEngine except Exception: pass` hides packaging/syntax errors, not just a missing optional extra. Limit to ImportError. (`src/vocalinux/speech_recognition/engines/__init__.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review (adversarial) — keep draft, do not mark ready

`src/vocalinux/speech_recognition/engines/` does **not** exist on current `main`. This is new work, not a duplicate of an already-landed engine package. Default engine is still `whisper_cpp`. The `[faster_whisper]` extra is optional. Those three are fine.

This still should not leave draft, and it cannot merge as-is.

### Blocker: installer CUDA copy is false

```bash
print_info "NVIDIA GPU detected - installing PyTorch with CUDA support..."
print_info "Note: This may download ~2GB of CUDA runtime packages"
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
```

That index is CPU wheels. faster-whisper runs on **CTranslate2**, and this PR never installs a CUDA CT2 build. After this "GPU" path, `_has_torch_cuda()` stays false and `get_compute_type` selects `int8` on CPU. The interactive menu's "Fast on CPU with INT8 quantization" is accurate; "Best performance on NVIDIA GPUs (CUDA)" is not something the installer delivers.

The existing OpenAI Whisper branch already installs CPU torch without pretending it is CUDA. Do not copy that pattern and then label it CUDA.

### Major: Engine Protocol is unused

`ENGINES` is populated only for `FasterWhisperEngine` (and `except Exception: pass` will hide real import bugs). `SpeechRecognitionManager` never consults the registry — it hardcodes another `elif engine == "faster_whisper"` next to vosk/whisper/whisper_cpp/remote_api, and the other engines do not implement `Engine`. For one optional backend, drop the Protocol/registry or actually dispatch through it.

### Rebase is mandatory

Head is `0184b8ec` vs a July 18 base. `install.sh`, `recognition_manager.py` (auto-pause / idle unload reinit), and `settings_dialog.py` (variant picker, `_auto_apply_settings` download only for whisper/whisper_cpp/vosk) have all moved. A naive remount of the 36-line settings patch will miss download/info-card paths.

**Action:** keep draft. Rebase. Either use `ENGINES` or delete it. Fix the installer so NVIDIA/CUDA text matches what pip actually installs (CPU INT8 is enough for v1). Then re-request review.
```

</details>

### [#519](https://github.com/VocaHQ/vocalinux/pull/519) feat(snap): Snap packaging recipe and Snap Store publish strategy

- **Verdict:** Needs changes (confidence high)
- **Author:** @jatinkrmalik · ready · CONFLICTING · updated 2026-07-15
- **Size:** +6588 / −45, 15 files
- **One-liner:** In-repo snap recipe can land without a Snap Store account, but it is conflicting, codecov-red, ships a 315KB duplicate SVG, and requests network-bind + home it does not need.
- **Do this:** Rebase onto main. Drop network-bind and home unless justified. Remove duplicate 315KB snap/gui SVG. Add tests for evdev list_devices fallback and snap permission hints so codecov/patch passes. Store account is not a merge requirement.

Findings:

- **major** network-bind is unnecessary privilege — apps.vocalinux.plugs includes network-bind 'optional remote_api engine'. Remote API is an outbound HTTP client; `network` is sufficient to connect to a whisper.cpp/OpenAI-compatible server. network-bind lets the snap listen on ports. packaging/snap/README.md repeats the same justification. Drop network-bind unless there is a concrete in-snap server this recipe actually starts (there is not). (`snap/snapcraft.yaml`)
- **major** home plug is broader than snap-private config — The recipe already documents that config/models live under ~/snap/vocalinux/ via snap-private HOME remapping of ~/.config and ~/.local/share. The extra `home` plug grants the confined app the user's real home directory. Flatpak finish-args on main do not use --filesystem=home. A dictation app that also has network + audio-record (+ optional raw-input) does not need to read ~/Documents to function. Drop `home` or document a specific file the host home is required for. (`snap/snapcraft.yaml`)
- **major** Codecov patch gate is failing — codecov/patch 51.13% (43 lines missing), codecov/project FAILURE. Almost all of that is src/vocalinux/ui/keyboard_backends/evdev_backend.py (25 missing + 4 partials) plus keyboard_shortcuts.py and audio_feedback.py. tests/test_snap_packaging.py only YAML-asserts the recipe; _find_keyboard_devices_from_evdev() and the SNAP/raw-input permission-hint branches are largely untested. This will stay red after rebase unless those paths get tests or codecov is explicitly waived for packaging. (`src/vocalinux/ui/keyboard_backends/evdev_backend.py`)
- **minor** snap/gui/vocalinux.svg is a 315KB duplicate — The added snap/gui/vocalinux.svg is 5873 lines / ~315KB of traced paths — the same blob as resources/icons/scalable/vocalinux.svg already in the tree. snapcraft.yaml override-build already installs the resources icon into usr/share/icons and meta/gui/icon.svg. Keep one copy (symlink or just the resources file). tests/test_snap_packaging.py asserting SNAP_ICON exists is what forces the duplicate. (`snap/gui/vocalinux.svg`)
- **minor** raw-input is the right interface, but it is a sandbox escalation — Strict confinement + documented `sudo snap connect vocalinux:raw-input` is honest. raw-input is not auto-connected, tray still works without it, and the evdev fallback via evdev.list_devices() is a real fix because snap raw-input grants /dev/input/event* but often still denies /proc/bus/input/devices. That fallback is also useful on non-snap hosts where /proc is unreadable. Do not treat raw-input as a silent auto-connect later. (`src/vocalinux/ui/keyboard_backends/evdev_backend.py`)
- **nit** Stale fallback version and DISTRO_COMPATIBILITY conflict — snapcraft.yaml fallback version is 0.14.0-beta; main is 0.15.0 (adopt-info from version.py still wins). docs/DISTRO_COMPATIBILITY.md on main already marks Phase 7 Flatpak complete; this PR still patches a 'Phase 7 Planned' table. Rebase carefully or Phase 7 status regresses. (`docs/DISTRO_COMPATIBILITY.md`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review (adversarial) — needs changes, not mergeable now

**Snap Store account is not required to merge this.** The PR is a recipe + docs + a couple of runtime fallbacks. `snapcraft pack` and `snap install --dangerous` work without registering `vocalinux`. Store login is only for `snapcraft register` / `upload`. The PR already says that; do not close it for lacking a store listing.

It is also not mergeable today: `CONFLICTING`, codecov/patch **51%** (gate 80%), and the plug set is wider than the app needs.

### Sandbox

`snap/snapcraft.yaml` is `confinement: strict` (good, matches the Flatpak-first-ship story). Plugs that are justified:

- `audio-record` — microphone; documented as maybe-manual-connect
- `audio-playback` — UI tones
- `network` — model download / remote client
- `raw-input` — evdev hotkeys; **not** auto-connected; tray remains the fallback

Plugs that are not justified by this recipe:

- **`network-bind`** — Remote API is outbound HTTP. Nothing in this snap listens. `network` is enough.
- **`home`** — snap-private HOME already remaps `~/.config` / `~/.local/share` to `~/snap/vocalinux/`. The `home` interface is the user's real `$HOME`. Flatpak on main does not grant `--filesystem=home`. Drop it unless you can name a host path this app must read.

`raw-input` is super-privileged (keylogger-class). Keeping it manual-connect is the right call; do not auto-connect it in a follow-up "to make hotkeys work."

### evdev changes

The `/proc/bus/input/devices` → `evdev.list_devices()` fallback is the actually useful code in this PR. Snap `raw-input` often grants `/dev/input/event*` and still denies `/proc/bus/input`. `get_permission_hint()` printing `sudo snap connect vocalinux:raw-input` is correct. Cover `_find_keyboard_devices_from_evdev` and the snap hint branches so codecov is not 51%.

### Huge SVG

`snap/gui/vocalinux.svg` is a 5873-line / ~315KB duplicate of `resources/icons/scalable/vocalinux.svg`. `override-build` already copies the resources icon into the snap. Delete the gui copy or point the test at the existing icon.

### Rebase

README / INSTALL / DISTRO_COMPATIBILITY / evdev / audio_feedback / keyboard_shortcuts all moved. Main already completed Phase 7 Flatpak — do not revert that row to "Planned" while flipping Phase 8.

**Action:** rebase, drop `network-bind` and `home` (or justify them with a real path), delete the duplicate SVG, add evdev fallback tests until codecov/patch is green. Store publish stays a human follow-up.
```

</details>

### [#516](https://github.com/VocaHQ/vocalinux/pull/516) feat(ui): floating glowing dictation overlay

- **Verdict:** Needs changes (confidence high)
- **Author:** @jatinkrmalik · ready · CONFLICTING · updated 2026-07-15
- **Size:** +1485 / −0, 9 files
- **One-liner:** Overlay work is real (optional GtkLayerShell, no present(), opacity instead of hide/show) but default-on plus a full-width always-mapped 30fps strip is the wrong first ship on GNOME Wayland.
- **Do this:** Rebase onto current settings/tray APIs. Default show_overlay to false. Avoid keeping a full-width mapped idle window; clip or shrink the 30fps cairo redraw to the orb. Re-verify GNOME Wayland focus and IBus inject before ready-for-review.

Findings:

- **major** Default-on is too aggressive given Wayland residual risk — DEFAULT_CONFIG ui.show_overlay is True and Settings loads show_overlay default True. The PR itself needed a follow-up commit because hide()/show() re-activated the window on Wayland and broke IBus inject. GtkLayerShell is correctly optional and only used when is_supported(); GNOME/Mutter typically will not take that path. Default-on therefore ships the fallback TOPLEVEL (keep_above, NOTIFICATION hint, show_all, never present()) to the majority Ubuntu Wayland audience. Default this False until X11 + GNOME Wayland + a wlroots compositor have been checked; the switch already exists. (`src/vocalinux/ui/config_manager.py`)
- **major** Idle overlay stays mapped as a full-width strip — To avoid focus theft, _sync_window() maps once via show_all() then set_opacity(0.0) on IDLE instead of hide(). After the first LISTENING, a Gtk.WindowType.TOPLEVEL full-monitor-width × 120px surface remains mapped for the rest of the process. Click-through is cairo.Region() + input_shape_combine_region (and shape_combine_region(None)). That works on X11; on Wayland it is compositor-specific. If the empty input region is ignored, the bottom 120px plus _BOTTOM_MARGIN (48px) becomes a dead click zone after the first dictation — including over the GNOME dock / XFCE panel. Either hide() on X11, or keep a ~96px orb window instead of a full-width strip, or unmap when idle on compositors that do not steal focus. (`src/vocalinux/ui/dictation_overlay.py`)
- **major** Glow animation redraws the entire strip at ~30fps — _ANIMATION_TICK_MS = 33, _on_anim_tick always queue_draw()s the DrawingArea. _on_draw does OPERATOR_SOURCE paint of the full allocation (monitor width × 120) then several cairo arcs. On 1080p that is ~230k pixels/frame; on 4K ~460k, 30 times a second, typically in software cairo, concurrently with whisper.cpp on the same CPU. Animation does stop when not visible (good). Clip the draw to the orb (~96px) or lower the tick rate; do not SOURCE-clear a full-width strip every frame. (`src/vocalinux/ui/dictation_overlay.py`)
- **minor** GtkLayerShell optional path is done correctly — _try_import_layer_shell() catches Exception and returns None. KeyboardMode.NONE / set_keyboard_interactivity(False), exclusive_zone 0, OVERLAY layer, bottom+left+right anchors. Tests cover missing GI, is_supported() false, setup failure fallback, and both keyboard APIs. No new hard dependency. This part is fine. (`src/vocalinux/ui/dictation_overlay.py`)
- **minor** Focus-stealing was actually worked — residual is first map — set_accept_focus/can_focus/focus_on_map False, skip taskbar/pager, never present() (tests assert this), opacity instead of hide/show. That is the right GTK3 approach. Remaining hole is the first show_all() on the GNOME-without-layer-shell path, which is still enough to yank focus from the editor and break IBus/wtype — the bug they already hit. Do not treat the opacity trick as a GNOME Wayland fix without a session test. (`src/vocalinux/ui/dictation_overlay.py`)
- **nit** Rebase vs current Settings/tray API — SettingsDialog.__init__ on main now takes initial_page, pending_update, update_status_callback; tray opens settings via _show_settings_page(). Overlay's extra overlay_enabled_callback and the _build_general_section insert next to copy_to_clipboard (which has moved off the General page) will not apply cleanly. 886 lines of overlay tests vs 422 lines of implementation is coverage-gate padding; keep the controller/focus tests, drop the string-grep style once already removed in the ponytail pass. (`src/vocalinux/ui/tray_indicator.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review (adversarial) — needs changes

This is a real overlay, not a stub. Controller is testable without GTK. GtkLayerShell is a soft import (`_try_import_layer_shell` → None). Keyboard is explicitly not grabbed. `present()` is avoided (tests assert that). hide()/show() was replaced with opacity because it stole focus and broke IBus — that diagnosis is correct.

It still should not merge as drafted.

### Default on

`ui.show_overlay: True`. The majority Ubuntu session is GNOME Wayland, which typically **does not** get GtkLayerShell. Those users get the fallback `TOPLEVEL` + `set_keep_above(True)` + `show_all()`. You already needed a follow-up because mapping this window yanked editor focus. Default the switch **off** until that path is checked on GNOME Wayland and at least one wlroots compositor. The Settings row is enough for people who want SuperWhisper-style glow.

### Click-through vs idle mapped strip

After the first LISTENING, the window stays mapped at opacity 0 as a **full-width × 120px** surface (`_STRIP_HEIGHT`, left+right anchors / `resize(geom.width, 120)`). Click-through is an empty `cairo.Region` + `input_shape_combine_region`. If a compositor ignores that, the bottom of the screen (panel/dock included) stops receiving clicks for the rest of the process. Prefer a ~96px orb, or unmap when idle on compositors that do not refocus on map.

### Glow cost

`timeout_add(33ms)` → `queue_draw()` of the whole strip, `OPERATOR_SOURCE` clear of monitor-width × 120, then glow rings. That runs for the entire LISTENING/PROCESSING interval, on the same machine that is transcribing. Clip to the orb or tick slower. Stopping the source when hidden is already correct.

### Rebase

`SettingsDialog` gained `initial_page` / update kwargs; tray uses `_show_settings_page`; General no longer hosts copy-to-clipboard. The overlay callback has to land on the current constructor.

**Action:** rebase. Default `show_overlay` to false. Do not leave a full-width mapped window idle. Re-test GNOME Wayland focus + IBus inject before marking ready.
```

</details>

### [#487](https://github.com/VocaHQ/vocalinux/pull/487) feat(tray): add recent dictation snippets history menu 🤖🤖🤖

- **Verdict:** Needs changes (confidence high)
- **Author:** @LuigiKraken · ready · CONFLICTING · updated 2026-07-01
- **Size:** +494 / −4, 8 files
- **One-liner:** Useful tray recovery feature with a sound in-memory store, but it is conflicting, defaults history on, and "delete that" does not actually purge the dictated text.
- **Do this:** Ask LuigiKraken to rebase onto current main, default history off, purge undone text on delete_last, drop clipboard.store() (or document it), import Gdk, and attach the settings group to the Application sidebar page with live apply.

Findings:

- **major** History is on by default — DEFAULT_CONFIG sets history.enabled True. Vocalinux sees passwords, messages, 2FA phrases. copy_to_clipboard already defaults False for the same reason. Make history opt-in. The in-memory deque (nothing on disk, clears on quit) is the right persistence model; the default is not. (`src/vocalinux/ui/config_manager.py`)
- **major** delete that does not exclude the undone text — Action commands take a separate callback, so the phrase "delete that" is not stored as its own snippet. The preceding segment is still appended to session_segments in text_callback_wrapper and committed on IDLE. Dictating a secret then saying "delete that" in the same session still lands in Recent Snippets. Pop the last segment on delete_last, or skip commit of undone text. There is no test for this path in main.py. (`src/vocalinux/main.py`)
- **major** clipboard.store() can persist snippets to disk — _on_history_item_clicked calls Gtk.Clipboard.store(), which hands the text to the X clipboard manager (Klipper, CopyQ, clipman). That can write dictation to disk, contradicting the PR claim that nothing is written to disk. Use set_text without store(), or document the clipboard-manager caveat. Current tray_indicator.py also does not import Gdk; Gdk.SELECTION_CLIPBOARD will NameError until Gdk is added to the gi import. (`src/vocalinux/ui/tray_indicator.py`)
- **minor** Settings toggle requires restart; live API already exists — The UI copy says changes take effect after restart. TranscriptionHistory already has set_enabled/set_max_items and a change callback. Other settings apply immediately. After rebase, general_tab is the Application sidebar page alias (searchable sidebar landed in #601/#618), so the group can go there; do not invent a notebook tab. Wire the switches to the live store. (`src/vocalinux/ui/settings_dialog.py`)
- **nit** No maintainer review comments yet — Issue/review comments are codecov only. No jatinkrmalik review. Rebase will also have to record snippets before trailing-space / auto-capitalize (#608/#554) so history is the user's words, not the inject payload. (`src/vocalinux/main.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
@LuigiKraken The in-memory store is the right privacy model (deque, process lifetime, no file). The feature is still worth landing after a rebase, but not with history on by default and not with the current "delete that" behavior.

Conflicts: `tray_indicator.py`, `settings_dialog.py`, and `main.py` have all moved (update checker, auto-pause, searchable sidebar, trailing space, auto-capitalize). Rebase first.

Must-fix:

1. Default `history.enabled` to `false`, same posture as `copy_to_clipboard`. A dictation tool should not keep recent utterances unless the user asks.

2. "delete that" exclusion is incomplete. The command itself is not recorded (action callback). The text it undoes stays in `session_segments` and is committed on IDLE. Pop the last segment on `delete_last`, or do not commit undone text. Add a test around the callback wrapper.

3. Drop `clipboard.store()` or document that clicking a snippet can persist via the clipboard manager (Klipper/CopyQ/clipman). `set_text` is enough for an immediate paste. Also import `Gdk`; current `tray_indicator.py` only imports `GdkPixbuf`, so `Gdk.SELECTION_CLIPBOARD` will NameError.

4. Settings: `general_tab` is now the Application sidebar page. Put the group there. `TranscriptionHistory.set_enabled` / `set_max_items` already exist, so the restart-required note should go away.

Happy to re-review on a rebased branch with history off by default.
```

</details>

### [#479](https://github.com/VocaHQ/vocalinux/pull/479) Pipe transcriptions through an optional postprocessing script

- **Verdict:** Needs changes (confidence high)
- **Author:** @karottenreibe · ready · CONFLICTING · updated 2026-07-01
- **Size:** +256 / −0, 8 files
- **One-liner:** Clean stdin/stdout hook with timeout and no shell=True, but Jatin already put it on hold for the settings refactor (now landed) and example scripts, and the executable path needs hardening.
- **Do this:** Do not merge. Ask karottenreibe to rebase onto the sidebar settings UI, add the example scripts Jatin requested, require an absolute executable path, and stop logging transcription stdout. Keep the PR open per maintainer; do not close.

Findings:

- **major** Settings placement: maintainer hold still applies, target UI has changed — jatinkrmalik (2026-07-01): hesitant to slot a toggle into today's cramped dialog; wants a dedicated injection/post-processing home after a settings refactor; also wants example scripts (strip fillers, capitalization) and noted the #408 local-LLM/Ollama angle. Searchable sidebar settings landed in #601/#618. This PR still notebook.append_page('Post-Processing') on the old tab UI. Rebase as a SettingsPage (or under Application). Do not merge the tab as-is. Example scripts are still absent. (`src/vocalinux/ui/settings_dialog.py`)
- **major** Arbitrary executable from config with no path checks — PostProcessor.process runs subprocess.run([self.script_path], input=text, capture_output=True, text=True, timeout=10). No shell=True (good). Timeout 10s (good). Fallback on non-zero/timeout/OSError (good). Runs as the Vocalinux user (expected). Missing: absolute-path requirement (a value like curl or bash is looked up on PATH), exists+executable check, and any UI warning that this binary receives every transcription on stdin. Config.json is user-writable; a bad script_path is local RCE with dictation on stdin. Require an absolute path to an executable file before spawn. (`src/vocalinux/post_processor.py`)
- **major** Logs transcription stdout at INFO — logger.info('Post-processor returned: %r', result.stdout[:100]) writes up to 100 chars of the transformed (or original-shaped) dictation into the log file. Vocalinux logs are a tray menu item. Do not log payload text. Log script_path, returncode, duration, and byte length only. (`src/vocalinux/post_processor.py`)
- **minor** Empty stdout skips injection; timeout blocks the recognition thread — apply_post_processing maps empty script output to None, and main.py returns without injecting. A script that prints nothing silently drops the utterance; fallback-to-original would match the failure path. The 10s timeout runs inside text_callback_wrapper on the recognition thread, so a slow script stalls dictation. Document that. chsa-admin asked for a separate hotkey; Jatin hearted that as phase II, fine to defer. On rebase, run the hook after command processing and before trailing-space / auto-capitalize, or the script will see injected padding. (`src/vocalinux/post_processor.py`)
- **nit** save_config vs dialog convention — The changed handler calls save_config(), which is the non-deprecated API. Current settings_dialog.py still uses save_settings() everywhere. Either is functionally fine (save_settings warns and delegates). Match neighbors on rebase. File chooser does not restrict to executables. (`src/vocalinux/ui/settings_dialog.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
@karottenreibe Incorporating @jatinkrmalik's 1 July comment, plus a pass on the process helper.

Jatin liked the hook shape and explicitly kept the PR open: do not merge a Post-Processing notebook tab into the old dialog; wait for the settings refactor; add a couple of example scripts (strip fillers, fix capitalization); #408/Ollama can ride this later. That refactor has landed (#601/#618 searchable sidebar). Rebase and add a sidebar page (or put it under Application / a future injection page). The tab as written will not apply.

The runner itself is close: `subprocess.run([script_path], input=text, capture_output=True, text=True, timeout=10)` with no `shell=True`, fallback on non-zero/timeout, same user as Vocalinux. Keep that.

Please also:

1. Require an absolute path to an existing executable. `curl` / `bash` as `script_path` should not PATH-lookup. This is a user-configured hook, but config.json is enough to feed every transcription to whatever binary is named there.

2. Stop logging `result.stdout[:100]` at INFO. That is dictation text in `~/.local/share/vocalinux` logs (View Logs in the tray). Log path, returncode, duration, size.

3. Empty stdout currently becomes `None` and skips injection. Either treat empty as "use original" (same as failure) or document "empty means drop this utterance".

4. Ship the example scripts Jatin asked for. A hotkey to run post-processing only sometimes (chsa-admin) can wait.

Happy to re-review once this sits on the sidebar and the path/logging issues are tightened.
```

</details>

### [#424](https://github.com/VocaHQ/vocalinux/pull/424) feat: add configurable Whisper language candidates

- **Verdict:** Keep draft (confidence high)
- **Author:** @juanfradb · draft · MERGEABLE · updated 2026-05-08
- **Size:** +168 / −1, 7 files
- **One-liner:** Useful whisper.cpp auto-detect constraint, not on main, but needs a rewrite against resolve_whisper_language and must not force a language at 0% confidence.
- **Do this:** Keep draft. If revived: rebase onto resolve_whisper_language + current Advanced tab, add a probability floor, honor whispercpp_n_threads, hide the control unless engine is whisper_cpp.

Findings:

- **major** Forces a candidate even when all probabilities are zero — lang = max(candidate_probs, key=candidate_probs.get) always picks a code. If the user listed en,es and the audio is German, or the codes are typos, both probs are 0.0 and the first candidate is forced into transcribe(). Unrestricted auto-detect would have been better. Need a floor: if max(candidate_probs) is ~0, leave lang=None. (`src/vocalinux/speech_recognition/recognition_manager.py`)
- **major** Bypasses resolve_whisper_language on current main — Main maps catalog ids via resolve_whisper_language() (en-us/en-in → en, auto → None, SUPPORTED_LANGUAGES['whisper'] field). Candidate normalization does code.split('-', 1)[0] instead. That happens to work for en-US but will diverge from the catalog (and from the Language combo) the moment a code is not a simple region suffix. Reuse resolve_whisper_language; validate against Model.available_languages(). (`src/vocalinux/speech_recognition/recognition_manager.py`)
- **major** Ignores whispercpp_n_threads; extra detect pass mutates the ctx — auto_detect_language(..., n_threads=min(4, cpu_count or 1)) ignores the existing whispercpp_n_threads setting used to build the Model. auto_detect_language() runs whisper_pcm_to_mel on the shared ctx, then transcribe() does it again. pywhispercpp still exposes auto_detect_language (verified on the current venv Model), so the API is valid, but the extra pass is paid on every utterance whenever candidates are set. Use the model's n_threads, and if max candidate prob is below a floor skip detect and leave language=None. (`src/vocalinux/speech_recognition/recognition_manager.py`)
- **minor** Only wired for whisper.cpp, not OpenAI Whisper — _transcribe_with_whisper still calls transcribe(language=resolve_whisper_language(...)) with no candidate filter. A setting named Language Candidates in Advanced will surprise users on the Whisper engine. Either hide the row unless engine is whisper_cpp, or apply the same restrict on both. (`src/vocalinux/speech_recognition/recognition_manager.py`)
- **minor** Settings insertion targets a layout that no longer exists — PR inserts a Gtk.Entry before Initial Prompt in _build_advanced_section. Current Advanced tab is behind a power-user Revealer, Initial Prompt is multiline in a ScrolledWindow, and get_current_settings() builds a different dict (gpu_device, remote API). The hunks may still apply in places, but this needs to be re-done against the current dialog, not merged by git. (`src/vocalinux/ui/settings_dialog.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
@juanfradb Leaving this as draft. The idea is still missing from main: constrain whisper.cpp auto-detect to a user-supplied set (`en,es`). `pywhispercpp.Model.auto_detect_language` still exists, so the API choice is fine. The patch is not mergeable as current code.

Main now has `resolve_whisper_language()` (`en-us` → `en`, `auto` → `None`, catalog `whisper` field). Candidate normalization should go through that, not `split("-", 1)[0]`.

Do not merge until these are fixed:

- `max(candidate_probs)` with all zeros still **forces** the first candidate. German audio with candidates `en,es` becomes English or Spanish. If the best candidate prob is ~0, leave `lang=None` and let unrestricted auto-detect run.
- `n_threads=min(4, cpu_count)` ignores `whispercpp_n_threads` used to construct the Model.
- Extra `auto_detect_language` (it calls `whisper_pcm_to_mel` on the ctx) on every utterance, then `transcribe` does it again. Acceptable if gated on candidates being set, but use the model's thread count.
- OpenAI Whisper `_transcribe_with_whisper` is unchanged. Hide the row unless the engine is whisper.cpp, or apply the same restrict there.
- Advanced Settings was rebuilt (Unlock Advanced Settings + Revealer). Re-add the entry there; do not rely on GitHub's stale MERGEABLE bit.

Tests for the happy path (`en` vs `es` probs) are good. Add a case where every candidate is 0.0 / missing from `lang_probs`.

Not closing: this is a real power-user knob and nothing on main replaced it. Needs a rewrite, not a click-merge.
```

</details>

### [#387](https://github.com/VocaHQ/vocalinux/pull/387) feat: experimental real-time streaming transcription (fixes #320)

- **Verdict:** Keep draft (confidence high)
- **Author:** @jatinkrmalik · ready · CONFLICTING · updated 2026-06-07
- **Size:** +1710 / −118, 14 files
- **One-liner:** Default-off is correct, but Whisper streaming is not real streaming, LA-2 is wrong in places, live injection is a stub, and the branch is stale/conflicting with 3.13 CI red — keep draft until redesigned.
- **Do this:** Convert #387 to draft (or leave closed if the stale bot already did). Do not rebase for merge. If streaming comes back, open a new Vosk-only PR with a real partial UI and a streaming-aware stop/PTT path; leave Whisper out until there is a real streaming decoder.

Findings:

- **blocker** Live 'show text as you speak' is not implemented — PR body claims TrayIndicator injects streaming text. The only new tray hook is `_on_streaming_update` which discards both arguments. Partials never reach any injector. Finals only land via `_emit_text` on Vosk Result()/Whisper flush(), so this is incremental utterance commit, not live hypotheses. If someone later wires the callback to inject, `_emit_text` already fires on the same finals → double injection. (`src/vocalinux/ui/tray_indicator.py`)
- **blocker** Stop/PTT path not streaming-aware — tail double-inject or drop — Streaming only enqueues from inside the record loop. After `should_record` flips, existing `_record_audio` still `_enqueue_audio_segment()`s leftover `audio_buffer` as a normal segment. Whisper leftover is often just the 200ms overlap window, transcribed independently of TranscriptBuffer (duplicate last words or garbage). Pending LA-2 words are never `flush_all()`'d unless a streaming `is_final` segment is processed. Streaming silence also ignores push-to-talk and calls `is_final=True` mid-hold, which for Vosk runs FinalResult() and resets the recognizer. (`src/vocalinux/speech_recognition/recognition_manager.py`)
- **major** LA-2 implementation is not LA-2, and committed-tail overlap takes the shortest match — `confidence_threshold` and `_MIN_COMMIT_LENGTH` are dead. Prefix agreement across two passes is LA-2-ish, but on divergence `insert()` immediately commits the entire previous pending hypothesis (tests encode this: 'hello world' then 'goodbye moon' flushes 'hello world'). That is sequential-chunk dumping, which the author noted can also hold everything until stop if done strictly. Worse: the committed-tail strip loop uses `for i in range(1, max_check+1)` (first/shortest hit) while `_find_tail_head_overlap` correctly searches longest-first. Repeated boundary tokens (Whisper's `are… are`) under-strip and re-emit. `_strip_terminal_ellipsis` only handles a literal '...' suffix, not Whisper's other stall tokens. (`src/vocalinux/speech_recognition/transcript_buffer.py`)
- **major** Overlap math ignores real capture chunk size; callback list is racy — `_enqueue_streaming_segment` hardcodes `chunk_duration_s = 1024/16000` instead of CHUNK and `_capture_sample_rate`. Current main already resamples non-16kHz captures. `_streaming_callbacks` is a plain list mutated from GTK (`add/remove`) and iterated from the recognition thread. `experimental_streaming` / chunk duration are read on the audio thread and written from `reconfigure()` with no lock. `_signal_recognition_stop` no longer forces the None sentinel through a full queue. (`src/vocalinux/speech_recognition/recognition_manager.py`)
- **minor** Default-off is done right; UI still oversells it — `experimental_streaming: False` in DEFAULT_CONFIG and constructor kwargs default False. Settings switch starts inactive. That part is correct. The toggle subtitle is still 'Show text as you speak' with no engine caveat, and overlap_ms is not exposed. Voice-commands handler is rewritten to only `_auto_apply_settings()` (drops the immediate reconfigure current main still has) — unrelated drive-by. (`src/vocalinux/ui/config_manager.py`)
- **nit** Stale vs main: this is a rewrite, not a rebase — recognition_manager.py on main now has remote_api, silero VAD, model keepalive, download buffering. The PR deletes `is_model_downloaded` from the whispercpp import. Settings/tray/main constructor tests will not apply cleanly. 23+785 new tests mock `sys.modules['tempfile'|'numpy'|'zipfile']` globally — a likely 3.13 isolation landmine even after rebase. (`src/vocalinux/speech_recognition/recognition_manager.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Verdict: keep as draft — do not merge, do not rebase-to-land

@jatinkrmalik this matches the note you already left on 2026-05-07: Vosk has a real incremental API; Whisper does not. The branch should stay draft until that split is designed on purpose. Current main has moved far enough (remote_api, silero, keepalive) that a rebase would be a rewrite anyway. Python 3.13 CI is red.

### What is actually correct
Default-off is real: `experimental_streaming: False` in `DEFAULT_CONFIG`, constructor, and the settings switch. That is the only reason this is not a `close`.

### Blockers

**1. Advertised UX is a stub.** Tray registers `_on_streaming_update` and then does `_ = (text, is_final)`. Partials never inject. Finals only land through `_emit_text`. The PR description's `TrayIndicator → inject_text` pipeline is not in the diff. Wiring that callback later without removing `_emit_text` on the same finals will double-inject.

**2. Stop path is not streaming-aware.** After `should_record` goes false, leftover `audio_buffer` still goes through `_enqueue_audio_segment()` → `_process_audio_buffer()` (no TranscriptBuffer). For Whisper that leftover is often the overlap window, so the tail can duplicate or the unconfirmed pending words can vanish because `flush_all()` only runs on a streaming `is_final` segment. Streaming silence also skips the PTT deferral and calls `FinalResult()` mid-hold on Vosk.

**3. `TranscriptBuffer` is not LA-2.** `confidence_threshold` / `_MIN_COMMIT_LENGTH` are unused. Divergence commits the previous pending hypothesis in one shot (see `test_diverging_text_resets_buffer`). The committed-tail overlap loop takes the **shortest** match (`range(1, max_check+1)`); `_find_tail_head_overlap` correctly searches longest-first. Repeated boundary words (`are… are`) will under-strip.

### If this is ever revived
Ship Vosk `PartialResult()` as the only streaming engine, with a real partial-replacement story (or overlay, not raw injection). Treat Whisper/whisper.cpp as out of scope until there is a proper streaming backend, not overlapping `transcribe()` windows. Do not land this on main as-is.
```

</details>

### [#503](https://github.com/VocaHQ/vocalinux/pull/503) refactor: mega-cleanup of dead bloat

- **Verdict:** Keep draft (confidence high)
- **Author:** @jatinkrmalik · draft · CONFLICTING · updated 2026-07-11
- **Size:** +656 / −6386, 50 files
- **One-liner:** Still a useful cleanup thesis, but this branch is too stale to merge: it deletes APIs and files that current main now uses, and conflicts with the settings/IBus/About rewrite.
- **Do this:** Keep draft. Do not merge. Slice the still-valid cleanup (unused Python/npm deps, dead web modules, command-processor rewrite, download helper) into new PRs against current main. Do not replay deletions of shortcut display helpers, show_notifications, about_dialog.py, or the Flatpak resource path.

Findings:

- **blocker** Deletes shortcut display helpers that settings now call — The diff removes SHORTCUT_MODE_DISPLAY_NAMES and get_shortcut_display_name from keyboard_backends. On current main those are imported by settings_dialog.py (shortcut rows) and keyboard_shortcuts.py. This was dead at PR time; it is not dead now. Merging would break the shortcuts UI. (`src/vocalinux/ui/keyboard_backends/base.py`)
- **blocker** Edits about_dialog.py, which main already deleted — PR trims an unused custom AboutDialog class and keeps show_about_dialog() / Gtk.AboutDialog. #631 deleted src/vocalinux/ui/about_dialog.py entirely and moved About into Settings (tray _on_about_clicked -> _show_settings_page('about')). There is no AboutDialog class on main. This hunk cannot apply. (`src/vocalinux/ui/about_dialog.py`)
- **blocker** Drops ui.show_notifications default that tray now reads — config_manager DEFAULT_CONFIG loses ui.show_notifications. tray_indicator.py currently gates update notifications with get_bool('ui', 'show_notifications', True) from #631. Removing the key is no longer dead-config cleanup. (`src/vocalinux/ui/config_manager.py`)
- **major** ResourceManager rewrite drops the Flatpak path — Current _find_resources_dir still lists /app/share/vocalinux/resources plus lib/lib64 candidates. The PR requires a complete icon+sound set (good vs #330) but drops the Flatpak candidate. Flatpak packaging landed in #484 and is on main. Do not replay this hunk as-is. (`src/vocalinux/utils/resource_manager.py`)
- **major** command_processor rewrite must keep capitalize_sentences — Replacing the fixture if text.lower() == ... chain with a left-to-right matcher is still the right fix; that chain is still on main. #554 added capitalize_sentences() used from main.py for Vosk. Any replay of this file has to keep that helper and its tests. (`src/vocalinux/speech_recognition/command_processor.py`)
- **minor** Unused-deps claim is still true on main — pydub, tqdm, and python-xlib remain in pyproject.toml and packaging/flatpak/python3-dependencies.yaml. Grep of src/ finds no imports. tqdm is only mocked in tests (likely a pywhispercpp transitive). Sphinx docs extra is still unused. Dead web modules still unused: code-block.tsx, logo.tsx, ui/button.tsx, lib/api/util.ts, lib/utils.ts (only pulled by those dead components). dictation-overlay.tsx and use-double-press.ts are already gone from main. Salvage these as a small follow-up PR, not this 50-file branch. (`pyproject.toml`)
- **nit** _process_final_buffer is still test-only — Production recognition_manager never calls _process_final_buffer; only tests do. Deleting it is still valid. Just do not delete overlapping recognition tests without checking unique contracts against the files that grew after this PR. (`src/vocalinux/speech_recognition/recognition_manager.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
@jatinkrmalik Keep this draft. Do not merge this branch onto current main.

The cleanup thesis is still right in places. On today's main, `src/` still does not import `pydub`, `tqdm`, or `python-xlib`; the Sphinx extra is still unused; `_process_final_buffer` is still only called from tests; and the command processor is still the fixture `if text.lower() == ...` chain. The web leftovers (`code-block.tsx`, `logo.tsx`, `ui/button.tsx`, `lib/api/util.ts`) still have no app-page imports. `dictation-overlay.tsx` / `use-double-press.ts` are already gone.

What changed since 11 July is that several "dead" deletions are now live:

1. `get_shortcut_display_name` / `SHORTCUT_MODE_DISPLAY_NAMES` are used by `settings_dialog.py` and `keyboard_shortcuts.py`. Deleting them breaks the shortcuts UI.
2. `src/vocalinux/ui/about_dialog.py` was removed in #631. About lives in Settings; tray `About` calls `_show_settings_page("about")`. This PR still edits the deleted file.
3. `ui.show_notifications` is read by `tray_indicator.py` (#631). Dropping it from `DEFAULT_CONFIG` is not dead-config cleanup anymore.
4. `ResourceManager` still needs `/app/share/vocalinux/resources` for Flatpak (#484). The rewrite drops that candidate.
5. `command_processor.py` gained `capitalize_sentences` (#554). A wholesale replace has to keep it.
6. `recognition_manager.py` grew auto-pause, GPU, language mapping, and audio-device filters. The download DRY helper is still worth doing, but not by replaying this hunk.

Please abandon this tip and cut smaller cleanups against current main (deps / web dead files / command-processor algorithm / download helper). Resolving 50-file conflicts here will re-delete things main now depends on.
```

</details>

### [#556](https://github.com/VocaHQ/vocalinux/pull/556) feat(text-injection): opt-in "Preserve Clipboard" for the Wayland paste fallback 🤖🤖🤖

- **Verdict:** Close (confidence high)
- **Author:** @Nosion · ready · CONFLICTING · updated 2026-08-04
- **Size:** +483 / −10, 4 files
- **One-liner:** Clipboard restore already landed on main as always-on (#588/#646); this opt-in branch would regress that and still conflicts.
- **Do this:** Close as superseded by #588/#646. Invite a tiny follow-up for wl-copy --sensitive only. Do not merge; a rebase of the current branch would regress always-on restore.

Findings:

- **blocker** Restore is already on main, and this PR's default would regress it — On current main, _inject_via_clipboard_paste always saves the previous clipboard and restores it after 300ms unless copy_to_clipboard is on (text_injector.py:1311-1403). It also handles overlapping pastes via _clipboard_restore_generation / _clipboard_restore_target, skips restore if the user copied something else, and can clear an empty clipboard. #556 adds text_injection.restore_clipboard_after_paste default False plus a Settings toggle, and a simpler save/restore with a 150ms sleep and no generation counter. Merging or naively rebasing that on top of #588/#646 would make restore opt-in again. (`src/vocalinux/text_injection/text_injector.py`)
- **major** Still conflicting after the author claimed a sync — Maintainer requested conflict fixes (2026-07-28). Author said they synced to latest main on 2026-08-04. GitHub is still DIRTY. The conflicts are exactly the files #588/#646 rewrote (text_injector.py, config_manager.py, settings_dialog.py). A rebase now is a rewrite of the injector hunks, not a textual merge. (`src/vocalinux/text_injection/text_injector.py`)
- **minor** Only unique leftover is wl-copy --sensitive (Klipper history) — main never passes --sensitive, so dictation still lands in Klipper/etc. history. #556 probes wl-copy --help, caches the result, and marks the transient dictation copy sensitive while restoring with a plain copy. That part is still useful. It is ~40 lines on current _run_clipboard_command, not a 483-line PR. Do not drag the Settings toggle or the opt-in default along with it; restore is already the default. (`src/vocalinux/text_injection/text_injector.py:680-720`)
- **nit** #425 is a different clipboard-paste bug — #425 (juanfradb, still CONFLICTING) pastes into Firefox via clipboard when IBus commit is ignored on X11. It shares the paste fallback, not clipboard preservation. Closing #556 does not resolve #425. (`src/vocalinux/text_injection/text_injector.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Review @Nosion

Thank you for the KDE live testing and for addressing the earlier nits (`--no-newline` is the byte-faithful `wl-paste` read; coverage on the helpers).

I am going to close this rather than ask for another rebase.

Clipboard restore after the ydotool paste fallback is already on `main`, and it is stricter than this branch:

- #588 (`a15baa8`) restores after paste by default (no Settings toggle).
- #646 (`4a1d3ed`) adds overlapping-paste generation counters, text-only reads, and skip-if-the-user-copied-something-else.

This PR still adds `restore_clipboard_after_paste: false` and a Preserve Clipboard switch. Merging that on current `main` would make restore opt-in again. GitHub is also still **DIRTY** on `text_injector.py` / `config_manager.py` / `settings_dialog.py`, which are exactly the files those two commits rewrote.

The one piece `main` does not have is `wl-copy --sensitive` so Klipper does not keep the transient dictation copy. That is a small, feature-probed change on `_run_clipboard_command`. If Klipper history still bothers you, please open a new PR against current `main` with only that flag (gated so Copy to Clipboard stays a normal, non-sensitive offer). No toggle, no second restore path.

#425 is a different bug (Firefox IBus commit on X11) and is not a substitute for either this PR or #588.
```

</details>

### [#402](https://github.com/VocaHQ/vocalinux/pull/402) feat(injection): add selectable text injection backends

- **Verdict:** Close (confidence high)
- **Author:** @sabbari · ready · CONFLICTING · updated 2026-06-07
- **Size:** +302 / −71, 9 files
- **One-liner:** Stale 9-file backend picker; superseded by VOCALINUX_FORCE_BACKEND on main and the narrower config pin in #649. Lint red, conflicts, runtime reload does not rewire dictation.
- **Do this:** Close as superseded by VOCALINUX_FORCE_BACKEND + #649. If xdotool pinning is still wanted, add that value on #649 instead of reviving this rewrite.

Findings:

- **blocker** Superseded by FORCE_BACKEND on main and #649 — Main already pins backend via VOCALINUX_FORCE_BACKEND (ibus/wtype/ydotool/auto) inside TextInjector._forced_backend(). #649 (OPEN, MERGEABLE, updated 2026-08-06) adds the persistent config.json setting the issue asked for, with env overriding config and default auto unchanged. #649's own writeup is explicit: 'Deliberately narrower than #402, which also rebuilt the injector at runtime and added Settings/tray UI across 9 files.' Close this; take #649. (`src/vocalinux/text_injection/text_injector.py`)
- **blocker** Runtime reload does not update the injector that actually dictates — tray_indicator.update_text_injection_backend() constructs a new TextInjector and assigns self.text_injector. main() holds text_system and ActionHandler(text_system); the dictation callback calls text_system.inject_text(). Changing the setting in the dialog therefore saves config and rebuilds the tray's copy, while dictation and voice-command shortcuts keep using the old backend until restart. That is the feature this PR adds on top of #649, and it does not work. (`src/vocalinux/ui/tray_indicator.py`)
- **major** Reverts scoped IBus and ignores current selection logic — _configure_ibus() constructs IBusTextInjector(auto_activate=True). Main uses auto_activate=False plus per-inject engine switch, compositor denylist, ibus-wayland bridge, KDE VirtualKeyboard (#574), and VOCALINUX_FORCE_BACKEND. A rebase that keeps this helper would undo that. _configure_wayland_tool also prefers ydotool then wtype with no denylist and no ydotoold auto-start from main. (`src/vocalinux/text_injection/text_injector.py`)
- **major** Lint failed; tests grep source and stole a TestMainFunction method — CI Lint Python failed 2026-04-16 (black; at least the ydotoold RuntimeError line is 104 cols vs 100). Tests never ran (matrix skipped after lint). test_settings_dialog and test_main_args_deps assert that source files contain strings. Inserting class TestTrayIndicatorBackendReload in the middle of TestMainFunction moved test_main_initialization_error onto the new class. (`tests/test_main_args_deps.py`)
- **minor** xdotool as a pinable value is the one gap #649 left — VOCALINUX_FORCE_BACKEND and #649 accept ibus/wtype/ydotool/auto only. #649 says xdotool was omitted to avoid touching X11 selection. That is the actual remaining ask from #476's X11 reporter (and from #425's Firefox case). Add xdotool on #649 if wanted. Do not keep this PR alive for that one enum value. (`src/vocalinux/ui/config_manager.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
@sabbari Closing in favor of what landed and of #649.

I asked for a rebase on 7 May so this could make the next release. There has been no update. The PR is conflicting, tagged stale, and lint has been red since 16 April (black; the test matrix never ran).

Main already has `VOCALINUX_FORCE_BACKEND` (`ibus` / `wtype` / `ydotool` / `auto`) in `TextInjector._forced_backend()`. #649 is the persistent `text_injection.backend` setting, env-overrides-config, default `auto` byte-identical. That PR is explicit that it is the narrow version of this one (no Settings combo, no runtime rebuild, 9 files vs a contained config read).

The extra work here is also broken:

- `update_text_injection_backend` replaces `tray.text_injector` only. `main()`'s `text_system` and `ActionHandler` still hold the old instance, so dictation does not switch until restart.
- `_configure_ibus()` uses `IBusTextInjector(auto_activate=True)`. Current main is scoped injection (`auto_activate=False`) plus compositor denylist / `ibus-wayland` / KDE VirtualKeyboard. This helper cannot be rebased without rewriting it against that.
- Tests grep source. Inserting `TestTrayIndicatorBackendReload` in the middle of `TestMainFunction` moved `test_main_initialization_error` onto the new class.

The one thing #649 left out on purpose is pinning `xdotool`. If that is still needed (X11 #476, Firefox IBus), add it on #649. Please do not rebase this branch.
```

</details>

### [#425](https://github.com/VocaHQ/vocalinux/pull/425) fix: paste into Firefox through clipboard fallback

- **Verdict:** Close (confidence high)
- **Author:** @juanfradb · draft · CONFLICTING · updated 2026-05-08
- **Size:** +135 / −0, 2 files
- **One-liner:** Draft Firefox+xdotool special case; #665 did not fix silent IBus drops, but this heuristic is wrong and main's clipboard-paste/backend-pin work supersedes it.
- **Do this:** Close as superseded. Remaining Firefox-on-X11 IBus gap belongs as an xdotool value on VOCALINUX_FORCE_BACKEND/#649, or a WM_CLASS denylist that reuses _inject_via_clipboard_paste.

Findings:

- **blocker** Firefox IBus drop is not fixed by #665, and this PR does not fix it either — #665 (merged 2026-08-10) restores the XKB layout after scoped IBus injection. That is a different bug (#664, Brazilian ABNT2 flipping to US). IBusTextInjector.inject_text() still returns True whenever commit_text() does not throw (ibus_engine.py), so main's _switch_to_non_ibus_backend() never runs when Firefox swallows the commit. The underlying failure mode can still exist. This PR papers over it with an app heuristic instead of making IBus failure detectable or letting the user pin xdotool. (`src/vocalinux/text_injection/ibus_engine.py`)
- **blocker** App detection uses window title, so any title containing 'firefox' triggers paste — _get_current_x11_app_id() concatenates getwindowclassname, getwindowname (page title), /proc/pid/comm, and cmdline, then checks if 'firefox' is in the joined string. A Chrome/VS Code/terminal window whose title mentions Firefox (docs, GH issue, man page) takes the clipboard path and skips IBus. Match WM_CLASS/comm only (firefox, Navigator), never getwindowname. (`src/vocalinux/text_injection/text_injector.py`)
- **major** WAYLAND_IBUS also uses xdotool ctrl+v — The Firefox branch runs whenever environment is X11_IBUS or WAYLAND_IBUS. Native Wayland Firefox is not an X11 window; xdotool key ctrl+v either hits the wrong XWayland window or does nothing. Main already has _inject_via_clipboard_paste() for ydotool on Wayland, with clipboard save/restore. (`src/vocalinux/text_injection/text_injector.py`)
- **major** Duplicates paste and clobbers the clipboard — _inject_via_x11_clipboard_paste copies text and sends xdotool ctrl+v with no restore. Main's _inject_via_clipboard_paste already does copy+Ctrl+V and restores the previous clipboard (generation counter, delayed restore). #556 is the opt-in Preserve Clipboard/wl-copy --sensitive follow-up; it is still OPEN, but the restore itself is already on main. A new helper that skips restore is a regression against current behavior. (`src/vocalinux/text_injection/text_injector.py`)
- **minor** Pays four xdotool subprocesses plus /proc reads on every IBus injection — target_app is resolved for every X11_IBUS/WAYLAND_IBUS inject_text call, not only Firefox. That is extra latency on the dictation hot path. Main already logs window info via _log_x11_window_info(); this reimplements it for a boolean. (`src/vocalinux/text_injection/text_injector.py`)
- **nit** codecov/patch was red at 65% — _get_current_x11_app_id itself is untested; tests only mock it. 16 new lines uncovered. (`src/vocalinux/text_injection/text_injector.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
@juanfradb Closing this. Thanks for the Firefox report, but the patch should not land.

**#665 did not fix Firefox ignoring IBus.** That PR restores the XKB layout after scoped injection (#664). `IBusTextInjector.inject_text()` still returns `True` as soon as `commit_text()` succeeds at the IBus layer, so main's `_switch_to_non_ibus_backend()` never runs when Firefox drops the text. That failure mode can still be real. This is not the fix.

What is wrong here:

1. `"firefox" in target_app` after joining **window title** + class + `/proc/cmdline`. Any focused window whose title mentions Firefox (Chrome, VS Code, a terminal) skips IBus and pastes. Detect `WM_CLASS`/`comm` only.
2. The same branch runs on `WAYLAND_IBUS` and then calls `xdotool key ctrl+v`, which does not inject into native Wayland Firefox.
3. `_inject_via_x11_clipboard_paste` reimplements paste and **overwrites the clipboard with no restore**. Main already has `_inject_via_clipboard_paste` (restore + generation counter). #556 is the Klipper/`--sensitive` follow-up; do not add a third paste path.
4. Conflicts with current `inject_text()` (state lock, IBus runtime fallback). Draft, untouched since 8 May.

If Firefox-on-X11 still silently drops IBus commits, the right knobs are already in flight: pin a non-IBus backend (`VOCALINUX_FORCE_BACKEND` on main; config pin in #649). Neither accepts `xdotool` today — that is the actual X11 gap. Add `xdotool` there, or denylist WM_CLASS `firefox`/`Navigator` and reuse `_inject_via_clipboard_paste`. Do not special-case by window title.
```

</details>

### [#353](https://github.com/VocaHQ/vocalinux/pull/353) Add double-tap Super key shortcut and --settings CLI option (fixes from PR #332) 🤖🤖🤖

- **Verdict:** Close (confidence high)
- **Author:** @farconada · ready · CONFLICTING · updated 2026-05-07
- **Size:** +829 / −80, 13 files
- **One-liner:** suspend_handler.py and tray resume logic already live on main; super+super was later deprecated; double-tap Super fights GNOME Activities; --settings is the only leftover and belongs in a tiny new PR.
- **Do this:** Close #353 as superseded/conflicting. If --settings is still wanted, file a new small PR against current main (CLI flag + get_running_pid/SIGUSR1 or D-Bus) that calls TrayIndicator._show_settings_page(). Do not revive Super-as-preset or a second KeyboardShortcutManager.

Findings:

- **blocker** suspend_handler.py is a duplicate of code already on main — PR adds a new 126-line suspend_handler.py and wires SuspendHandler plus a large post-resume Gio.Settings input-source monitor into tray_indicator.py. Current main already has src/vocalinux/suspend_handler.py, tests/test_suspend_handler.py, and TrayIndicator constructing SuspendHandler(on_suspend=..., on_resume=...). The PR's getattr(handler, 'start', None) dance does not match main's constructor-connects-immediately API. Merging would conflict and likely regress AutoPauseMonitor / keepalive / update-monitor shutdown in _quit. (`src/vocalinux/suspend_handler.py`)
- **blocker** super+super is deprecated on main; this PR makes it a product feature — ConfigManager._migrate_shortcuts_config() on main rewrites toggle_recognition == 'super+super' to 'ctrl+ctrl'. SUPPORTED_SHORTCUTS has no Super presets. This PR adds super+super / left_super+left_super / right_super+right_super to the dropdown and starts a second KeyboardShortcutManager(shortcut='super+super') for Settings. That fights a later product decision and needs left_super in MODIFIER_NAMES (not present on main). (`src/vocalinux/ui/keyboard_backends/base.py`)
- **major** Double-tap Super vs GNOME Activities is still unsolved — Reviewer asked for a startup log; the PR added one. GNOME still uses Super (and Super double-tap / hold) for Overview. A second global listener does not prevent the shell from seeing the same key. There is no UI warning, no opt-in, no setting to disable it. Conflict detection only covers Vocalinux's own recognition shortcut, not the DE. Two KeyboardShortcutManager instances also mean two pynput/evdev listeners. (`src/vocalinux/ui/tray_indicator.py`)
- **major** --settings CLI is the only unique piece, and it is not on main — parse_arguments() on main has no --settings. get_running_pid() does not exist in single_instance.py. SIGUSR1 is a reasonable IPC hack (lock file already stores PID) but Python signal.signal(SIGUSR1) in the tray is another handler next to SIGINT/SIGTERM, and the second-instance path still shows the 'already running' error notification if kill() fails. This is salvageable as a ~40-line follow-up that calls current _show_settings_page(), not as this 829-line conflicting PR. (`src/vocalinux/main.py`)
- **minor** PR would drop remote_api from --engine choices and is agent-duplicated — Diff still has choices=['vosk','whisper','whisper_cpp'] while main includes remote_api. Title/body repeat 'Created by Maestro' twice. No CI. engine-choice / tray / test_main patches will not apply. (`src/vocalinux/main.py`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Verdict: close

@farconada thanks for the #332 follow-up, but this branch has been overtaken by main.

**Already on main (do not re-add):**
- `src/vocalinux/suspend_handler.py` and tray suspend/resume — current `TrayIndicator` already constructs `SuspendHandler` and shuts it down in `_quit`
- Super as a *modifier in combos* (`super+space`) via `parse_shortcut_spec` / #493

**Contradicted by main:**
- `super+super` is explicitly migrated to `ctrl+ctrl` in `ConfigManager._migrate_shortcuts_config()`. This PR puts Super presets back in the dropdown and starts a second `KeyboardShortcutManager(shortcut="super+super")` for Settings.

**Still a GNOME footgun:**
Double-tap Super is Overview/Activities. A log line does not fix that. Conflict detection only looks at Vocalinux's own recognition shortcut.

**Still missing, worth a new tiny PR:**
`--settings` + `get_running_pid()` / SIGUSR1 (or better, a D-Bus/GLib action) to open the *current* `_show_settings_page()`. Do not rebase this 829-line patch to get that.

Please close #353. If you still want `--settings`, open a new PR against current main with just CLI + single-instance signaling.
```

</details>

### [#291](https://github.com/VocaHQ/vocalinux/pull/291) feat(shortcuts): custom keyboard shortcut capture widget

- **Verdict:** Close (confidence high)
- **Author:** @matz-man · ready · CONFLICTING · updated 2026-06-07
- **Size:** +1155 / −142, 13 files
- **One-liner:** Custom shortcuts plus a Record/capture UI already shipped on main in #493; the parse_keys vs parse_shortcut single-key contract bug was never fixed and a rebase would collide with parse_shortcut_spec.
- **Do this:** Close #291 as superseded by #493/#509. Do not rebase. If a richer chord-capture widget is still desired, new PR against current parse_shortcut_spec only — no parallel parse_keys().

Findings:

- **blocker** Custom shortcut capture already exists on main — Current settings_dialog.py has custom_shortcut_entry, record_shortcut_button, _gdk_event_to_shortcut, _on_shortcut_key_press, and tests/test_shortcut_capture.py. base.py has ShortcutSpec / parse_shortcut_spec / is_valid_shortcut, and backends map Super + F-keys + named keys. docs/UPDATE.md credits #493. Landing this PR would duplicate that stack with a parallel parse_keys()/PRESET_SHORTCUTS/ShortcutCaptureWidget design. (`src/vocalinux/ui/settings_dialog.py`)
- **blocker** parse_keys vs parse_shortcut contract still broken (maintainer bug, unfixed) — parse_keys() accepts 'f5' and 'ctrl'. parse_shortcut() then requires len(keys)>=2 for non-presets. ShortcutCaptureWidget._finalize_capture() also requires 2+ keys. KeyboardShortcutManager.set_shortcut() / restart_with_shortcut() only validate via parse_keys(), so config `f5` or README-claimed F-keys pass the manager and blow up in backend setup. Maintainer asked to pick one canonical rule on 2026-03-14; this diff still has both. Main's parse_shortcut_spec solved this differently: require at least one modifier, reject bare 'ctrl', allow 'alt+f5' not 'f5'. (`src/vocalinux/ui/keyboard_backends/base.py`)
- **major** meta mapping still backend-dependent; capture widget focus/grab is fragile — Maintainer already noted `meta` is accepted in the parser/pynput but not evdev. ShortcutCaptureWidget uses grab_focus() without gtk_grab_add / a modal grab, so key-presses can miss the widget; main's capture listens on the dialog itself (`self.connect('key-press-event', ...)`), which is the more reliable GTK3 pattern. is_combo_shortcut() is `not is_double_tap_shortcut()`, so a one-key 'f5' is classified as a combo. (`src/vocalinux/ui/settings_dialog.py`)
- **minor** Preset UI copy and changelog file are leftover debt — Maintainer: info text can show 'Ctrl + Ctrl' instead of 'Double-tap Ctrl' because format_shortcut_display() is used instead of get_shortcut_display_name(). PR also ADDs CHANGELOG.md at repo root; this project documents releases in docs/UPDATE.md and has no CHANGELOG.md on main. (`CHANGELOG.md`)

<details>
<summary>Paste-ready review comment</summary>

```markdown
## Verdict: close — superseded by main

@matz-man the capture-widget idea was right, and it already landed in a different shape.

On current `main`:
- Settings → Custom Shortcut with **Record** / **Set** (`_on_record_shortcut_clicked`, `_gdk_event_to_shortcut`)
- Canonical parser is `parse_shortcut_spec()` / `ShortcutSpec`, not `parse_keys()`
- Combos like `alt+r`, `ctrl+shift+v`, `super+space` are documented in #493 / #509

Please do **not** rebase this branch onto that. You would be merging a second parser (`parse_keys` vs `parse_shortcut`, min-2-keys vs F5-in-README) into code that already picked a contract: at least one modifier, no bare `ctrl`, no single-key `f5`.

The 2026-03-14 blocking comment still applies to *this* diff: `set_shortcut()` validates with `parse_keys()` (allows `f5`) while `parse_shortcut()` and the capture widget reject <2 keys. That never got a canonical rule.

Close #291. If anything from ShortcutCaptureWidget is still nicer than the Record button (press-and-release chord UI), cherry-pick that widget onto current `parse_shortcut_spec` in a new PR — do not revive this file-level rewrite.
```

</details>
