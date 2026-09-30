# Self-hosted Flatpak remote

Vocalinux publishes a signed OSTree Flatpak remote on every stable `v*` tag —
the Homebrew-tap analogue to `VocaHQ/homebrew-vocamac`
([issue #785](https://github.com/VocaHQ/vocalinux/issues/785)). The remote
lives in the dedicated repo `VocaHQ/vocalinux-flatpak`, served by GitHub
Pages:

```bash
flatpak install https://vocahq.github.io/vocalinux-flatpak/com.vocalinux.Vocalinux.flatpakref
flatpak update   # picks up each new release
```

The `.flatpakref` adds the `vocahq` remote (via `SuggestRemoteName=`) and lets
flatpak resolve `org.gnome.Platform//50` through its `RuntimeRepo=` pointer to
Flathub — one command, no separate Flathub setup. The equivalent manual
steps:

```bash
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-add --if-not-exists vocahq https://vocahq.github.io/vocalinux-flatpak/vocahq.flatpakrepo
flatpak install vocahq com.vocalinux.Vocalinux
```

Only the app is ours; the GNOME runtime still comes from Flathub —
`RuntimeRepo=` is a `.flatpakref` key (it is ignored on `.flatpakrepo`, which
is why the app ref carries it, not the remote descriptor). GitHub Release
`.flatpak` bundles ([#784](https://github.com/VocaHQ/vocalinux/issues/784))
remain as a no-auto-update fallback, and are the only Flatpak path for
prerelease tags, which never reach the remote.

## Maintainer setup (one time)

1. **Repo** — create `VocaHQ/vocalinux-flatpak` (public).
2. **Pages** — Settings → Pages → "Deploy from a branch" → branch `gh-pages`,
   folder `/ (root)`. The first publish creates the branch, so Pages can be
   pointed at it afterwards; creating an empty `gh-pages` upfront works too.
3. **Signing key** — OSTree remotes sign the summary and commits with GPG:

   ```bash
   gpg --quick-gen-key "Vocalinux Flatpak <flatpak@vocahq.com>" ed25519 sign never
   gpg --list-secret-keys                          # note the KEYID
   gpg --export-secret-keys --armor KEYID          # -> FLATPAK_GPG_PRIVATE_KEY
   gpg --gen-revoke KEYID > flatpak-remote-revoke.asc   # store it somewhere safe
   ```

   A passphrase-less key keeps CI simplest — libostree signs through
   gpg-agent, which has no `--passphrase-fd` to reach for. A passphrase works
   too: set `FLATPAK_GPG_PASSPHRASE` and the workflow presets it onto the
   keygrip via `gpg-preset-passphrase`.
4. **Secrets on `VocaHQ/vocalinux`** (Settings → Secrets and variables →
   Actions):
   - `FLATPAK_GPG_PRIVATE_KEY` — the armored private key
   - `FLATPAK_GPG_PASSPHRASE` — optional
   - `FLATPAK_REPO_TOKEN` — fine-grained PAT scoped to
     `VocaHQ/vocalinux-flatpak` with Contents: read and write
5. **Variables (optional)** — same settings page, Variables tab:
   - `FLATPAK_REMOTE_REPO` — publish target (default
     `VocaHQ/vocalinux-flatpak`)
   - `FLATPAK_REMOTE_URL` — remote URL baked into the `.flatpakrepo`
     (default `https://vocahq.github.io/vocalinux-flatpak/repo`; set
     e.g. `https://flatpak.vocalinux.com/repo` for a custom domain)
   - `FLATPAKREPO_URL` — where users fetch `vocahq.flatpakrepo` (default
     `https://vocahq.github.io/vocalinux-flatpak/vocahq.flatpakrepo`)
   - `FLATPAKREF_URL` — where users fetch the app `.flatpakref` (default
     `https://vocahq.github.io/vocalinux-flatpak/com.vocalinux.Vocalinux.flatpakref`)
6. **Trigger** — push a stable `v*` tag (alpha/beta/rc tags do not publish to
   the remote), or re-run `publish-flatpak-remote` on an existing release run
   after configuring the secrets.

Without the secrets the job skips itself (same pattern as `publish-aur`), so
an unconfigured remote never fails a release.

## How a publish works

`release.yml → publish-flatpak-remote` runs on stable tags only, after the
GitHub Release exists and the two arch builds finish:

1. Downloads `Vocalinux-<version>-{x86_64,aarch64}.flatpak` from the build
   jobs.
2. Probes the remote repo for an existing `gh-pages` branch; only a confirmed
   first publish may skip the history checkout — a transient failure aborts
   instead of seeding an empty repo over the live remote. It then checks out
   `gh-pages` and copies `repo/` over, so existing objects and deltas
   survive — clients pull an incremental delta each release, not the whole
   app.
3. `flatpak build-import-bundle --gpg-sign` imports each bundle under the
   signing key.
4. `flatpak build-update-repo --generate-static-deltas --gpg-sign
   --gpg-import` rebuilds the summary, signs it, and generates static deltas.
5. Regenerates `vocahq.flatpakrepo` (URL + base64 public key),
   `com.vocalinux.Vocalinux.flatpakref` (the one-command app ref carrying the
   `RuntimeRepo=` pointer to Flathub), `vocahq.gpg` (the bare public key, for
   the key-rotation path below), and the index page from
   `packaging/flatpak/index.html`.
6. Publishes the directory back to `gh-pages` via
   `peaceiris/actions-gh-pages`.

## Verifying a publish

```bash
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak remote-add --if-not-exists vocahq https://vocahq.github.io/vocalinux-flatpak/vocahq.flatpakrepo
flatpak remote-info vocahq com.vocalinux.Vocalinux   # signed commit, both arches
flatpak install vocahq com.vocalinux.Vocalinux
flatpak run com.vocalinux.Vocalinux
# after the next tag: flatpak update pulls the delta
```

## Key rotation and loss

Generate a fresh key, replace `FLATPAK_GPG_PRIVATE_KEY` (and
`FLATPAK_GPG_PASSPHRASE` if used), then re-run `publish-flatpak-remote`. The
published `.flatpakrepo`/`.flatpakref` then carry the new `GPGKey=`, so new
installs trust it immediately.

Existing installs must import the new key into the remote's trusted keyring —
re-running `remote-add` does **not** replace it (with `--if-not-exists` it
does nothing at all), and `flatpak update` fails verification until the key
is updated. Point users at the public key published beside the repo:

```bash
curl -fsSL https://vocahq.github.io/vocalinux-flatpak/vocahq.gpg -o /tmp/vocahq.gpg
flatpak remote-modify --gpg-import=/tmp/vocahq.gpg vocahq
flatpak update
```

`remote-modify --gpg-import` adds the key — the old one stays trusted, which
is what makes a routine rotation seamless. To *revoke* a leaked key, drop the
remote's keyring instead: delete and re-add the remote (installed apps keep
their `vocahq` origin and update normally afterwards):

```bash
flatpak remote-delete --force vocahq   # --force: the remote is still in use
flatpak remote-add vocahq https://vocahq.github.io/vocalinux-flatpak/vocahq.flatpakrepo
flatpak update
```

Either way is worth a line in that release's notes. The revoke certificate is
for the day the key leaks, not for routine rotation.
