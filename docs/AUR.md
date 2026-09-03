# AUR

## Users

```bash
yay -S vocalinux          # latest release tag
yay -S vocalinux-git      # community package, tracks main
```

`vocalinux` and `vocalinux-git` conflict. Install only one.

## Maintainers (one-time)

Release tags auto-push `packaging/aur/vocalinux/PKGBUILD` when these secrets exist:

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

## CI gate

Every PR that changes the Python source or `packaging/aur/**` builds the PKGBUILD on `archlinux:latest` — the `Build AUR package (gate)` job in `unified-pipeline.yml`. Run it locally with `just aur-gate` (needs docker).

The gate swaps the tag-archive `source=` for a `git archive` of the checkout, so it answers whether *this commit* builds on Arch — #757 reached users after the tag, when nothing could fail a build anymore (#736 reached Arch users too, but through `install.sh`; this package built fine). `python-pywhispercpp` (virtual, provided by the AUR backends) and `python-pynput` (AUR) cannot come from the repos, so the gate satisfies them with a stub for dependency resolution and pip-installs the pinned versions from `requirements/runtime.txt` for the import smoke. What AUR actually ships (python-pywhispercpp-cpu is still 1.4.x — see Troubleshooting) is a monitoring question, not the gate's.

## Troubleshooting

**`ERROR Missing dependencies: setuptools<82`**

The AUR package builds with `python -m build --wheel --no-isolation`, so it uses Arch extra `python-setuptools` (currently 84). Vocalinux 0.16.1 drops the `<82` cap in `pyproject.toml`. Rebuild 0.16.1 or later.

**`'_pywhispercpp.whisper_full_params' object has no attribute 'context_params'`**

AUR `python-pywhispercpp-cpu` / `-cuda` / `-rocm` are still 1.4.x. Those wheels accept `context_params` in Python and then crash in the native object. 0.16.1 skips that argument on pywhispercpp older than 1.5 and still loads the model (default GPU, no device picker). PyPI and `install.sh` already use 1.5.0.

There is no AUR `python-pywhispercpp-vulkan` package. GPU Vulkan 1.5 is the `install.sh` / AppImage path, not the AUR python backends.
