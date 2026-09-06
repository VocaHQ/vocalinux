# Vocalinux Snap packaging

Snap packaging for Ubuntu and other snap-enabled distros (issue
[#48](https://github.com/VocaHQ/vocalinux/issues/48)).

Recipe: [`snap/snapcraft.yaml`](../../snap/snapcraft.yaml)
GUI assets: [`snap/gui/`](../../snap/gui/)

## Status

| Item | State |
|------|--------|
| Snapcraft recipe in-repo | Yes (`snap/snapcraft.yaml`) |
| Published on Snap Store | **Yes** — [snapcraft.io/vocalinux](https://snapcraft.io/vocalinux) (publisher `jatinkrmalik`). Current public channel: `latest/edge` @ 0.14.0-beta (rev 6). Refresh via upload; **do not** `snapcraft register`. |
| Intended first channel | `edge`, then promote to `stable` after validation |
| Confinement | `strict` (first ship) |
| Default engine | whisper.cpp (`pywhispercpp`); VOSK may install via project deps; OpenAI Whisper/torch **not** bundled |

Listing already exists. Install the testing channel today; promote a new
0.16.2 build through `candidate` → `stable` after QA:

```bash
# Current public testing channel (refresh after upload)
sudo snap install vocalinux --edge
# After candidate/stable promotion:
# sudo snap install vocalinux --candidate
# sudo snap install vocalinux

# Microphone / hotkeys if not auto-connected
sudo snap connect vocalinux:audio-record
sudo snap connect vocalinux:raw-input   # global shortcuts
```

## Strategy (how we publish)

### Agent / repo work (done in this packaging)

1. Ship a current `snap/snapcraft.yaml` (version from `src/vocalinux/version.py`, not the stale 0.2.0 draft on #48).
2. Align plugs and staged tools with real runtime needs and Flatpak lessons.
3. Document build, install, limitations, and human-only store steps.
4. Keep secrets out of git (no Snapcraft credentials in CI until a dedicated store token is added later).

### Human-only Snap Store steps (maintainer)

Name **`vocalinux` is already registered** and the listing is live
([snapcraft.io/vocalinux/listing](https://snapcraft.io/vocalinux/listing)).
Do **not** run `snapcraft register vocalinux`.

1. `snapcraft login` as publisher `jatinkrmalik` (Ubuntu One).
2. From a clean checkout of this branch/tag: `snapcraft pack`
   (produces `vocalinux_0.16.2_amd64.snap` when `version.py` is 0.16.2).
3. Upload without releasing, then release deliberately:
   ```bash
   snapcraft upload vocalinux_*.snap          # prints revision N
   snapcraft release vocalinux N edge        # replace stale 0.14.0-beta edge
   snapcraft release vocalinux N candidate   # QA gate
   # after desktop QA:
   snapcraft release vocalinux N stable
   ```
   Or one-shot edge: `snapcraft upload --release=edge vocalinux_*.snap`.
4. Update Store listing metadata to match this recipe: **AGPL-3.0** license,
   VocaHQ links (`https://github.com/VocaHQ/vocalinux`), screenshots, summary.
5. Desktop QA on Ubuntu: tray, mic, model download, type into gedit/browser;
   optional `sudo snap connect vocalinux:raw-input` for hotkeys.
6. Flip README/INSTALL copy from “edge-only / not on stable yet” once `stable`
   has the 0.16.2 revision; add the Snap Store badge if missing.
7. Optional later: CI with a Snap Store export token for continuous `edge`
   publishes (token stays out of git).

### Channel path

```
local pack  →  upload to edge  →  manual QA  →  candidate (optional)  →  stable
```

Use `grade: devel` while shipping beta builds to non-stable channels. Set
`grade: stable` in the recipe before promoting a build intended for the
`stable` channel (store policy).

## Confinement and interfaces

**Decision: `strict` first**, not `classic`.

Reasons:

- Matches the security story users expect from the Snap Store.
- Mirrors Flatpak’s sandboxed first ship (X11 injection + mic + network, no `/dev/input`).
- Classic requires a manual store review and is harder to justify for a v1 listing.

| Need | Interface / mechanism | Notes |
|------|----------------------|--------|
| GTK tray / desktop | `gnome` extension (`desktop`, `desktop-legacy`, `unity7`, …) | AppIndicator/GTK from gnome-42 platform (do not stage a second GLib) |
| Display | `x11`, `wayland` (from extension) | Injection prefers X11/XWayland + xdotool; IBus D-Bus when available |
| Microphone | `audio-record` (+ `pulseaudio` legacy) | May need `snap connect` |
| Feedback sounds | `audio-playback` | Short UI tones |
| Model download | `network` | First-run / Settings downloads |
| Remote API engine | `network` / `network-bind` | Optional; not the primary path |
| GPU / Vulkan | `opengl` (extension) | whisper.cpp acceleration when available |
| Config / models | snap-private `HOME` (`~/snap/vocalinux/…`) | Same code paths (`~/.config`, `~/.local/share`) remap automatically |
| Global hotkeys | `raw-input` (manual connect) | `sudo snap connect vocalinux:raw-input` then restart; tray works without it |

If strict confinement blocks text injection or required desktop integration after
real-device testing, escalate deliberately:

1. Document the failure with compositor + interface list.
2. Consider extra interfaces or a reduced feature set.
3. Only then evaluate `classic` / store review (last resort).

## What is not in this snap (v1)

- OpenAI Whisper + PyTorch/CUDA (optional extra; huge).
- Auto-connected global hotkeys (evdev needs a one-time `sudo snap connect vocalinux:raw-input`; tray works without it).
- Guaranteed native Wayland injection on every compositor (same class of limits as Flatpak; XWayland/xdotool, staged `wtype`, and IBus paths are the supported sandboxed routes).
- Automatic Snap Store upload from CI (needs a human-provisioned token).
- ydotool / uinput injection (not staged; host classic installs may use ydotool separately).

## Local build

Helper (pack / upload-edge / promote revision) once `snapcraft` is logged in:

```bash
./scripts/snap-store-refresh.sh              # pack only
./scripts/snap-store-refresh.sh upload-edge  # pack + upload + release edge
./scripts/snap-store-refresh.sh promote N    # release rev N to candidate
```


Requirements:

- `snapcraft` (classic): `sudo snap install snapcraft --classic`
- A build provider: LXD **or** Multipass (snapcraft will prompt to set one up)

From the repository root:

```bash
snapcraft pack
# produces vocalinux_<version>_<arch>.snap

# Optional local install (dangerous on a daily driver — prefer a VM)
sudo snap install --dangerous ./vocalinux_*.snap
sudo snap connect vocalinux:audio-record
vocalinux --debug
```

Clean rebuild:

```bash
snapcraft clean
snapcraft pack
```

### If snapcraft / LXD / Multipass cannot run

Validate the recipe structure with the unit test:

```bash
pytest tests/test_snap_packaging.py -v
```

That test loads `snap/snapcraft.yaml` and asserts name, version source policy,
plugs, and staged injection helpers. It does **not** replace a real `snapcraft pack`.

## Relation to Flatpak

| Topic | Flatpak (`packaging/flatpak`) | Snap (this tree) |
|-------|-------------------------------|------------------|
| Engine scope | whisper.cpp first | whisper.cpp first (+ VOSK dep possible) |
| Mic | `pulseaudio` socket | `audio-record` / pulse |
| Injection | x11 + xdotool/xsel | stage xdotool/xsel/xclip; x11 via gnome extension |
| Hotkeys | no `/dev/input` | `raw-input` plug (manual connect) |
| Models | network + app data dir | network + `~/snap/vocalinux/` |
| Store | Flathub (separate track) | Snap Store |

## Maintainer checklist (refresh existing listing)

- [ ] `snapcraft login` as `jatinkrmalik` (listing already owned — no register)
- [ ] Version in `src/vocalinux/version.py` is the release you intend (0.16.2)
- [ ] `snapcraft pack` succeeds on amd64 (arm64 optional later)
- [ ] `snapcraft upload` → `release … edge` (replace rev 6 / 0.14.0-beta)
- [ ] `snapcraft release … candidate` and install `--candidate` for QA
- [ ] Verify: tray, mic, model download, type into gedit/browser; raw-input if testing hotkeys
- [ ] Listing metadata: AGPL-3.0, VocaHQ URLs, screenshots current
- [ ] `snapcraft release … stable` when candidate QA passes
- [ ] README/INSTALL: document `snap install vocalinux` once stable is current

## Ordered Snap Store deploy steps (human + in-repo)

**Already automated / in-repo:**

1. `snap/snapcraft.yaml` (strict, gnome extension, plugs, ALSA→Pulse, version from `version.py` = 0.16.2 + AGPL metadata)
2. GUI assets under `snap/gui/` + ALSA conf under `snap/local/`
3. Structural CI coverage via `tests/test_snap_packaging.py`
4. Runtime helpers: `raw-input` hints, evdev `/proc` fallback, staged `wtype` + `paplay`
5. Docs that point at the live listing and the edge→candidate→stable refresh path

**Jatin must do on a machine with Snapcraft auth (box browser login OK):**

1. `snapcraft login` (publisher already owns `vocalinux` — **skip register**)
2. `git checkout` this PR branch / release tag; `snapcraft pack`
3. `snapcraft upload vocalinux_0.16.2_*.snap` → note revision **N**
4. `snapcraft release vocalinux N edge` (supersede store 0.14.0-beta rev 6)
5. `snapcraft release vocalinux N candidate` → `sudo snap install vocalinux --candidate` QA
6. Update listing at https://snapcraft.io/vocalinux/listing (AGPL-3.0, screenshots, links)
7. `snapcraft release vocalinux N stable` after QA
8. Optional: export token for CI edge publishes later

**Channel policy:** keep `grade: devel` while only on `edge`/`candidate`; set
`grade: stable` in the recipe before a build intended primarily for `stable`
(store policy). First refresh can stay `devel` on edge/candidate, then a
follow-up pack with `grade: stable` for the stable promotion if required.

