# Arch User Repository (AUR)

## Users

```bash
yay -S vocalinux          # canonical release sdist, built against Arch dependencies
yay -S vocalinux-git      # community package; tracks main
```

`vocalinux`, `vocalinux-bin` and `vocalinux-git` conflict; install only one.

`packaging/aur/vocalinux-bin/` builds a `-bin` variant that installs the
prebuilt AppImage from the release — no Python, engine, or GPU dependency
builds, since the bundle carries them (#817). The release workflow publishes
it alongside the source package: it first pins the per-arch AppImage digests
in the PKGBUILD, then pushes to AUR in the `Publish AUR -bin package` step.

## Maintainers (one-time setup)

Release tags prepare and test the source PKGBUILD from
`packaging/aur/vocalinux/PKGBUILD`, then auto-push the verified file when these
secrets exist:

| Secret | Value |
|--------|--------|
| `AUR_SSH_PRIVATE_KEY` | Private key whose public half is on your AUR account |
| `AUR_USERNAME` | AUR username (git author) |
| `AUR_EMAIL` | AUR account email |

```bash
# 1. AUR account + SSH pubkey: https://aur.archlinux.org/register
ssh-keygen -t ed25519 -C "vocalinux-aur" -f ./aur_ed25519 -N ""
# upload aur_ed25519.pub on AUR; put aur_ed25519 in AUR_SSH_PRIVATE_KEY

# 2. Create empty package once
git clone ssh://aur@aur.archlinux.org/vocalinux.git

# 3. Next v* tag runs Publish to AUR (skipped if secret missing)
```

Sources: `packaging/aur/vocalinux/PKGBUILD`. Community git package: https://aur.archlinux.org/packages/vocalinux-git

## Source archive and trust model

The source package consumes the **canonical sdist attached to the GitHub release**,
the same bytes published to PyPI, not GitHub's automatically generated tag archive.
The sdist is produced by the locked reproducible-wheel gate. Only wheels are
compared for reproducibility; sdists are built and validated, not compared.

`scripts/prepare_aur_source.py` verifies the downloaded sdist against the published
`SHA256SUMS` and runs `gh attestation verify`, requiring the VocaHQ/vocalinux
repository, `.github/workflows/release.yml` signer, exact tag ref, and expected
source commit. Missing hashes, mismatches, rejected provenance, or mismatched
tag/package versions stop preparation. It preserves the original archive bytes
and pins their digest in the prepared PKGBUILD. `_tag` retains the release tag;
`_version` is the PEP 440-normalized sdist version, including for prereleases.

This verification is a **maintainer publication gate**. An AUR user's `makepkg`
checks the pinned SHA-256; it does not independently verify GitHub provenance.
Arch still owns the dependency/toolchain versions: this does not claim that AUR
builds use our Python lock or reproduce the PyPI wheel byte-for-byte.

## CI gates

### PR and local source gate

Python/AUR changes and changes to the source manifest, README or license build the
canonical sdist from the current checkout's reproducible-wheel gate, then prepare
an explicitly `--local-unattested` fixture. The `Build AUR package (gate)` job in
`unified-pipeline.yml` builds and installs its PKGBUILD on `archlinux:latest`.
Run `just aur-gate` locally (needs uv and Docker); it includes the reproducible-wheel
build and uses a fresh temporary directory for the prepared fixture.

### Release gate

After the release checksum/provenance job succeeds, `aur-source-test` downloads
the **published** sdist and manifest, verifies them, and prepares the PKGBUILD.
The same Arch gate makes `makepkg` download the actual source URL afresh
(`AUR_FETCH_SOURCE=1`) and verify its checksum, runs `namcap` on the recipe and
package, installs the package, checks the installed distribution version, and
runs the import smoke. It does not rewrite the source URL or disable source
checksum checks. The tested recipe and downloaded archive must match the
prepared PKGBUILD and provenance-verified sdist byte-for-byte.

Only after this succeeds is `aur-source-pkgbuild` uploaded for `publish-aur`.
Publication downloads that exact file; there is no version rewrite or
`updpkgsums` afterwards. The gate runs even without AUR credentials; only the
final push is secret-gated. This intentionally makes source publication wait
for the release's checksums and attestations. `vocalinux-bin` keeps its existing
separate AppImage publication path; its PR smoke still uses a stub AppImage.

Both gates deliberately use rolling `archlinux:latest`: #757 was Arch's
setuptools moving underneath us. `python-pywhispercpp` (virtual, provided by the
AUR backends) and `python-pynput` (AUR) cannot come from the repos, so the gate
satisfies them with a stub for dependency resolution and pip-installs their
pinned versions from `requirements/runtime.txt` for the import smoke. It does
not test those AUR providers or prove dependency completeness in a minimal host.
What those providers actually ship remains a separate monitoring question.

## Troubleshooting

**`ERROR Missing dependencies: setuptools<82`**

The AUR package builds with `python -m build --wheel --no-isolation`, so it uses Arch extra `python-setuptools` (currently 84). Vocalinux 0.16.1 drops the `<82` cap in `pyproject.toml`. Rebuild 0.16.1 or later.

**`'_pywhispercpp.whisper_full_params' object has no attribute 'context_params'`**

AUR `python-pywhispercpp-cpu` / `-cuda` / `-rocm` are still 1.4.x. Those wheels accept `context_params` in Python and then crash in the native object. 0.16.1 skips that argument on pywhispercpp older than 1.5 and still loads the model (default GPU, no device picker). PyPI and `install.sh` already use 1.5.0.

There is no AUR `python-pywhispercpp-vulkan` package. GPU Vulkan 1.5 is the `install.sh` / AppImage path, not the AUR python backends.
