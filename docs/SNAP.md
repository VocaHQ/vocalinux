# Snap build inputs and verification

The supported Snap build is **amd64, core24 (Ubuntu 24.04 / Python 3.12),
strict confinement, GNOME extension**. whisper.cpp is built for the portable
CPU baseline, not Vulkan/CUDA. Optional local engines are not bundled.
User installation and interface connections are documented in
[INSTALL.md](INSTALL.md#snap-ubuntu-snap-store).

## Python inputs

`uv.lock` owns Python versions. The Snap reuses these generated exports:

- `requirements/installer-build.txt`: the complete hash-pinned build toolchain,
  installed wheel-only into a temporary, isolated build virtualenv;
- `requirements/runtime.txt`: the runtime pins, platform markers and SHA-256
  hashes, already excluding PyGObject.

`snap/local/build.py` replaces the Python plugin's implicit resolution. A distro
`ensurepip` seeds the build environment offline; its first network operation
installs the locked toolchain with `--require-hashes --no-deps`. Runtime
dependencies use the same flags plus `--no-build-isolation`. Native builds find
the locked CMake/Ninja on PATH. pywhispercpp always builds from its pinned sdist,
without a wheel cache, with the portable `GGML_*` CPU options in the recipe.

The project installs with `--no-deps --no-build-isolation --no-index`. Neither
`pyproject.toml` nor its dependency metadata is patched. PyGObject/GTK come from
the GNOME platform, not pip. The packaged virtualenv contains no pip or build
toolchain. Its launchers are relocatable and prioritize the locked Python
packages over incidental copies in the GNOME platform.

The build audits build-tool and installed runtime versions against the active
export pins and records expected runtime versions and both export digests in
`usr/share/vocalinux/python-inputs.json` inside the snap. Missing, extra,
duplicate or wrong-version Python distributions fail the build.

Regenerate exports with the repository's `just lock` workflow, not by editing
them or adding independent pins to `snapcraft.yaml`. `just export-check` checks
them against `uv.lock` in CI.

## Build and artifact gate

On a Linux machine with Snapcraft and LXD or Multipass:

```bash
snapcraft pack
```

On a **disposable Ubuntu host with snapd**, inspect the resulting artifact:

```bash
bash snap/local/smoke-test.sh ./vocalinux_0.18.5_amd64.snap
```

Substitute the version that was built. The script refuses to overwrite an
existing Vocalinux snap. It installs the supplied file with `--dangerous`,
runs the actual application launcher with `--version`, then enters the GNOME
command-chain environment to audit Python versions and import the native,
GTK, recognition and text-injection modules. It leaves the installation in
place for inspection; use a disposable host, not your normal Vocalinux install.

`unified-pipeline.yml` builds and runs this gate on relevant Python/Snap PRs and
main pushes, including recipe-only changes. `release.yml` runs it before the
snap artifact can be attached or sent to the Store. Both use the same pinned
builder action and Ubuntu 24.04 runner. PR checks need no Store credentials and
never publish. Historical-tag backfills retain the tagged recipe's behavior.

## Deliberate limits

- This pins Python downloads and build tools, **not every native input**.
  Ubuntu packages are controlled by the core24/Ubuntu archive policy; the
  GNOME SDK/platform, Snapcraft and base snaps follow their upstream channels.
  Their exact revisions and native package versions remain visible in the
  Snapcraft build records. They are not an immutable snapshot owned by our
  Python lock.
- This is not a claim of byte-for-byte reproducible `.snap` archives. There is
  no independent Snap rebuild comparison, and native inputs can change.
- The smoke imports real modules under confinement but does not download a
  model, run inference, capture audio, test shortcuts, or type into an app.
  Candidate desktop QA and promotion to stable remain separate operations;
  this gate does not trigger `snap-promote.yml`.
