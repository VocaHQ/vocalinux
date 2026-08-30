# Vocalinux Release Process

This document outlines the step-by-step process for creating a new release of Vocalinux.

## Overview

Vocalinux uses [Semantic Versioning](https://semver.org/) with pre-release suffixes:
- **Alpha**: Early testing phase (e.g., `0.4.1-alpha`)
- **Beta**: Feature-complete, testing phase (e.g., `0.5.0-beta`)
- **RC** (Release Candidate): Final testing before stable (e.g., `0.5.0-rc1`)
- **Stable**: Production-ready (e.g., `1.0.0`)

## Quick Release Checklist

Use this checklist for every release:

```markdown
## Version Bump Checklist for X.Y.Z-PHASE

### Core Version Files
- [ ] `src/vocalinux/version.py` - Update `__version__` and `__version_info__`
- [ ] `pyproject.toml` - Confirm `Development Status` classifier and `requires-python` are correct for this release phase

### Documentation
- [ ] `README.md` - Update release announcement and status references
- [ ] `docs/INSTALL.md` - Verify install examples use `main/install.sh` (not version-pinned raw URLs)
- [ ] `docs/UPDATE.md` - Add "What's New" section for new version
- [ ] `SECURITY.md` - Update supported versions table

### Website
- [ ] `web/src/app/page.tsx` - Update `softwareVersion` in schema
- [ ] `web/src/app/page.tsx` - Update version badge / live version surfaces if present
- [ ] `web/src/app/changelog/page.tsx` - Add new release entry to changelog
- [ ] `web/package.json` - Update version field
- [ ] `web/package-lock.json` - Keep top-level/version metadata aligned with `web/package.json`
- [ ] `web/PRODUCT.md` - Keep capabilities aligned with shipped features
- [ ] Confirm install docs/website mention **AppImage** when this release ships AppImages

### Testing & Verification
Install `just` from https://just.systems or the distro package `just`.
- [ ] Run `just test` - All tests pass
- [ ] Run `just lint` - No linting errors
- [ ] Run `just typecheck` - No type errors
- [ ] Run `just build` - Package builds successfully
- [ ] Run `npm run build` in `web/` - Website builds successfully

> Note: CI workflows also sync website version metadata from `src/vocalinux/version.py`, but source files should still be updated in-repo during release prep for review clarity.

### Git Operations
- [ ] Create release branch: `git checkout -b release/vX.Y.Z-PHASE`
- [ ] Commit all version changes
- [ ] Push branch and create PR
- [ ] After PR merge, create tag: `git tag -a vX.Y.Z-PHASE -m "Release X.Y.Z-PHASE"`
- [ ] Push tag: `git push origin vX.Y.Z-PHASE`
```

## Detailed Release Steps

### Step 1: Determine Version Number

Follow semantic versioning:

```
Given version MAJOR.MINOR.PATCH-PHASE:

MAJOR - Breaking changes (for 1.0.0: public API stable)
MINOR - New features, backwards compatible
PATCH - Bug fixes, backwards compatible
PHASE - alpha, beta, rc1, rc2, etc. (omit for stable releases)
```

**Examples:**
- Alpha → Beta: `0.4.1-alpha` → `0.5.0-beta` (new features, phase change)
- Beta → RC: `0.5.0-beta` → `0.5.0-rc1` (same features, testing phase)
- RC → Stable: `0.5.0-rc1` → `1.0.0` (first stable release)
- Stable patch: `1.0.0` → `1.0.1` (bug fixes only)
- Stable minor: `1.0.0` → `1.1.0` (new features)

### Step 2: Update Core Version Files

#### 2.1 Update `src/vocalinux/version.py`

```python
__version__ = "0.5.0-beta"
__version_info__ = (0, 5, 0, "beta")
```

#### 2.2 Update `pyproject.toml`

Change the Development Status classifier:

```toml
# For Alpha:
"Development Status :: 3 - Alpha",

# For Beta:
"Development Status :: 4 - Beta",

# For Stable:
"Development Status :: 5 - Production/Stable",
```

### Patch releases within a minor line (e.g. 0.14.x)

When shipping bug fixes only (PATCH bump, same MINOR):

- **README / `docs/UPDATE.md` "What's New"** keeps the **minor-series feature list** (everything introduced in that 0.Y line) and adds a short **Bug fixes in this patch** subsection for the delta only. Do not make the marketing highlight table look featureless because this tag only contains fixes.
- **Website changelog** (`web/src/app/changelog/page.tsx`) may list only the delta for the new entry; older entries stay historical.
- **AppStream** (`packaging/flatpak/com.vocalinux.Vocalinux.metainfo.xml`): add a short `<release>` note for the patch delta only; leave the long product feature `<ul>` as series/product-level.
- **SECURITY.md** supported versions table usually stays on the minor line (`0.14.x`) without a row per patch.
- **AUR PKGBUILD**: bump `pkgver` / `_tag`; leave `sha256sums=('SKIP')` until the tag tarball exists. The release workflow runs `updpkgsums` when publishing to the AUR.
- **Dates**: patch release dates must not predate the previous release in changelog / AppStream / version history.

### GitHub Release Notes Writing Rules

Use these rules for every GitHub Release body (and for the draft pasted into the release-prep PR). Website changelog entries stay shorter; see below.

#### Sources of truth

- Delta commits: `git log vPREV..HEAD` plus merged PR titles/bodies.
- Closed issues via PR `Fixes` / `Closes` references only — do not invent issue numbers.
- Do not invent benchmarks, user counts, testimonials, or features not in the tree.

#### Required structure

1. `# Vocalinux vX.Y.Z` title
2. One to three plain sentences: what this release is for (no hype)
3. `## Highlights` — markdown table, about 4–8 rows
4. `## New Features` — bullets with PR + author; include issue closes when real
5. `## Bug Fixes` — group by area (IBus, Installer, AUR, Text injection, …)
6. Optional: `## Improvements`, `## Docs`, `## Packaging`
7. `## Thanks` — external PR authors and issue reporters by `@handle`
8. `## Install / Upgrade` — `install.sh`, AUR, PyPI, **AppImage**, Flatpak status (honest)
9. Footer compare link: `https://github.com/VocaHQ/vocalinux/compare/vPREV...vX.Y.Z`

#### Include / exclude

- **Include:** user-visible features, install/packaging changes, desktop reliability fixes, docs that change user instructions.
- **Exclude or demote:** Dependabot-only bumps, CI matrix tweaks, agent-env docs, pure refactors — short “CI / maintenance” subsection at most.

#### Attribution and voice

- Feature/fix bullets: `(#N by @author; fixes #M reported by @reporter)` when known.
- Practical, specific, Linux-native. Name the symptom users hit.
- Avoid promotional filler (“seamless”, “pivotal”, “game-changer”, fake significance).

#### Website changelog vs GitHub Release

- **Website** (`web/src/app/changelog/page.tsx`): 3–10 concise user-facing bullets for the new entry.
- **GitHub Release**: fuller narrative + install block + thanks. Draft in the release-prep **PR body**; paste/edit onto the release after the tag workflow runs (workflow install stub + generated notes are a starting point only).

#### Minor vs patch (reminder)

- **Minor** (e.g. `0.15.0`): rewrite README / UPDATE “What’s New” for the new series; full website changelog entry; AppStream release note summarizes the series.
- **Patch** (e.g. `0.15.1`): keep series feature table; add “Bug fixes in this patch” only; website changelog lists delta only.

#### Draft delivery

- Release-prep PRs should include a `## Draft GitHub Release Notes` section in the PR description for review before tag.
- Do not tag from the prep branch alone; tag after merge to `main`.

### Step 3: Update Documentation

#### 3.1 Update `README.md`

**Status Badge (line ~6):**
```markdown
<!-- Alpha -->
[![Status: Alpha](https://img.shields.io/badge/Status-Alpha-orange)]

<!-- Beta -->
[![Status: Beta](https://img.shields.io/badge/Status-Beta-blue)]

<!-- Stable -->
[![Status: Stable](https://img.shields.io/badge/Status-Stable-brightgreen)]
```

**Install Commands:**
Keep install commands on `main/install.sh` (installer resolves latest release tag automatically):
```bash
curl -fsSL https://raw.githubusercontent.com/VocaHQ/vocalinux/main/install.sh | bash
```

**Release Announcement (lines ~31-34):**
```markdown
> 🎉 **Beta Release!**
>
> We're excited to share Vocalinux Beta with the community.
> This release is feature-complete and ready for broader testing.
```

#### 3.2 Update `docs/INSTALL.md`

Confirm install examples point to `main/install.sh` and not release-tag raw URLs.

#### 3.3 Update `docs/UPDATE.md`

Add a new "What's New" section at the top:

```markdown
## What's New in v0.5.0-beta

- Feature 1
- Feature 2
- Bug fix 1

See the [full changelog](https://github.com/VocaHQ/vocalinux/releases/tag/v0.5.0-beta).

---

## Previous Versions

### v0.4.1-alpha
...
```

#### 3.4 Update `SECURITY.md`

Update the supported versions table:

```markdown
| Version | Supported          |
| ------- | ------------------ |
| 0.5.x   | :white_check_mark: |
| 0.4.x   | :x:                |
| < 0.4   | :x:                |
```

### Step 4: Update Website

#### 4.1 Update `web/src/app/page.tsx`

Update the schema.org softwareVersion (around line 68):

```typescript
"softwareVersion": "vX.Y.Z-PHASE",
```

Update the version badge in the header (around line 293):

```tsx
vX.Y.Z Beta
```

#### 4.2 Update `web/src/app/changelog/page.tsx`

Add new release entry to the `releases` array at the top of the file.

#### 4.3 Update `web/package.json`

```json
{
  "name": "vocalinux-website",
  "version": "0.5.0"
}
```

Also align `web/package-lock.json` top-level `version` fields with `web/package.json`.

### Step 5: Verify Everything Works

Run the full verification suite. Install `just` from
https://just.systems or the distro package `just`.

```bash
# Run tests
just test

# Run linting
just lint

# Run type checking
just typecheck

# Build package
just build

# Website build
cd web && npm run build && cd ..

# Install script sanity checks (optional but recommended)
bash -n install.sh
./install.sh --help | grep -- --tag
```

### Step 6: Create Release Branch and PR

```bash
# Create branch
git checkout -b release/v0.5.0-beta

# Stage all changes
git add -A

# Commit with conventional commit format
git commit -m "chore(release): prepare v0.5.0-beta

- Update version from 0.4.1-alpha to 0.5.0-beta
- Update status badges from Alpha to Beta
- Update documentation version references
- Update website schema and badges
- Update pyproject.toml classifiers
- Update SECURITY.md supported versions table"

# Push branch
git push origin release/v0.5.0-beta

# Create PR (use GitHub CLI or web interface)
gh pr create --title "chore(release): prepare v0.5.0-beta" \
  --body "This PR prepares the repository for the v0.5.0-beta release.

## Changes
- Bumped version to 0.5.0-beta
- Updated status badges from Alpha to Beta
- Updated all documentation version references
- Updated website version info
- Updated SECURITY.md supported versions

## Checklist
- [x] All tests passing
- [x] Linting clean
- [x] Type checking clean
- [x] Package builds successfully"
```

### Step 7: Create and Push Tag (After PR Merge)

Once the PR is merged to main:

```bash
# Checkout main
git checkout main
git pull origin main

# Create annotated tag
git tag -a v0.5.0-beta -m "Vocalinux Beta Release 0.5.0

Key changes since 0.4.1-alpha:
- Feature 1
- Feature 2
- Bug fix 1

Full changelog: https://github.com/VocaHQ/vocalinux/releases"

# Push tag
git push origin v0.5.0-beta
```

### Step 8: Monitor Release

After pushing the tag, the GitHub Actions workflow will automatically:

1. Build the Python package (wheel and sdist)
2. Build and attach AppImages for x86_64 and aarch64
3. Create a GitHub Release with auto-generated notes
4. Publish to PyPI
5. Publish the AUR package (when the `AUR_SSH_PRIVATE_KEY` secret is configured)
6. Deploy the website to vocalinux.com
7. Mark as pre-release if version contains alpha/beta/rc

Monitor at: https://github.com/VocaHQ/vocalinux/actions

### Step 9: Post-Release Tasks

- [ ] Verify GitHub Release was created correctly
- [ ] Verify PyPI package was published (if applicable)
- [ ] Verify website was deployed (check vocalinux.com)
- [ ] Announce on social media/communities
- [ ] Update any pinned issues or discussions

## Emergency Hotfix Process

For critical bugs in a released version:

```bash
# Create hotfix branch from the tag
git checkout -b hotfix/v0.5.1-beta v0.5.0-beta

# Make fix, commit, push
git add -A
git commit -m "fix: critical bug description"
git push origin hotfix/v0.5.1-beta

# Create PR targeting main
# After merge, tag new version
git tag -a v0.5.1-beta -m "Hotfix release v0.5.1-beta"
git push origin v0.5.1-beta
```

## Version History

| Version | Date | Phase | Notes |
|---------|------|-------|-------|
| 0.2.0-alpha | 2024 | Alpha | Initial alpha |
| 0.3.0-alpha | 2024 | Alpha | - |
| 0.4.0-alpha | 2024 | Alpha | Multi-language support |
| 0.4.1-alpha | 2024 | Alpha | Language selector UI |
| 0.5.0-beta | 2025 | Beta | First beta release |
| 0.6.0-beta | 2026-02-11 | Beta | Web SEO, mobile responsiveness, improved Fedora support |
| 0.6.1-beta | 2026-02-12 | Beta | Device handling improvements |
| 0.6.2-beta | 2026-02-17 | Beta | Bug fixes |
| 0.6.3-beta | 2026-02-19 | Beta | GPU detection improvements |
| 0.7.0-beta | 2026 | Beta | Autostart, tabbed settings, Intel GPU support, single instance |
| 0.8.0-beta | 2026-03-01 | Beta | Push-to-talk mode, optional voice commands, input/audio compatibility fixes |
| 0.9.0-beta | 2026-03-14 | Beta | Left/right modifier keys, sound effects toggle, Wayland clipboard fallback, leading-space fix |
| 0.10.0-beta | 2026-03-25 | Beta | Keyboard/audio reliability hardening, IBus/tray stability fixes, CI + test coverage improvements |
| 0.10.1-beta | 2026-03-27 | Beta | Stability patch: tray resource bundling, engine-switch segfault prevention, settings close action, XKB layout preservation |
| 0.10.2-beta | 2026-04-08 | Beta | Non-ASCII text injection, IBus Wayland detection, Pop!_OS deps, code quality refactor |
| 0.11.0-beta | 2026-05-30 | Beta | Advanced Settings tab, IBus/recognition hardening, installer fixes, distro compatibility |
| 0.12.0-beta | 2026-06-07 | Beta | Remote API engine, Silero VAD, threading/IBus hardening, settings and installer fixes |
| 0.13.0-beta | 2026-06-30 | Beta | Guided whisper.cpp model variants, Wayland text-injection reliability, hotplug keyboard support, dictation spacing fix, website docs refresh |
| 0.14.0-beta | 2026-07-13 | Beta | Configurable modifier+key hotkeys, FunASR/SenseVoice remote-API support, GNOME/KDE Wayland IBus reliability fixes, audio crash fix, hybrid-CPU efficiency fix |
| 0.14.1 | 2026-07-17 | Stable | Flatpak packaging, AUR package, layout-aware hotkeys, installer/text-injection fixes |
| 0.14.2 | 2026-07-17 | Stable | IBus engine launch + FocusIn gate; settings tabs scroll to fit monitor |
| 0.15.0 | 2026-07-28 | Stable | Searchable settings + sidebar dictation footer, AppImage, expanded languages, dictation polish, auto-pause/keepalive, Vulkan device selection, ibus-wayland, Bluetooth mic + shortcut UI fixes |
| 0.16.0 | 2026-08-23 | Stable | Update checker + tray notify, Right Alt PTT default (new installs), searchable language list, delete unused models, Voca tone picker (family preview WAVs), About page, AGPL-3.0, family mic icons, installer/just/uv pinning, Test Dictation missing-model message, IBus/audio/clipboard/GPU/AppImage reliability, vocalinux.com family workbench restyle |
| 0.16.1 | 2026-08-30 | Stable | Patch: per-engine model at startup, leftover tray idle, terminal Ctrl+Shift+V paste, GNOME XWayland layout after IBus, Python 3.11 floor + verified downloads, AppImage glibc that boots on Debian 12, Settings/About polish |

## Questions?

If you're unsure about any step:
1. Check previous releases for examples
2. Review the GitHub Actions workflows in `.github/workflows/`
3. Ask in the project's discussions

---

**Note**: This document should be updated when the release process changes.
