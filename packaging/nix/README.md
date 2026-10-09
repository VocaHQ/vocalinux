# Vocalinux for Nix

A flake that builds Vocalinux against nixpkgs: GTK 3, PyGObject and the
AppIndicator typelib come from nixpkgs, and `pywhispercpp` — which nixpkgs
does not package — is built from its PyPI sdist (it vendors whisper.cpp and
pybind11). Every host tool the app probes for (`xdotool`, `wtype`, `ydotool`,
`wl-clipboard`, `xclip`, `xsel`, `xprop`, `setxkbmap`, `ibus`, `gdbus`,
`notify-send`, `paplay`, `aplay`) is wired onto PATH, so the wrapped binary
behaves like a deb/rpm install with Recommends present.

## Try it

```bash
nix run github:VocaHQ/vocalinux
```

or install into a profile:

```bash
nix profile install github:VocaHQ/vocalinux
```

## NixOS

```nix
{
  inputs.vocalinux.url = "github:VocaHQ/vocalinux";

  outputs = { nixpkgs, vocalinux, ... }: {
    nixosConfigurations.host = nixpkgs.lib.nixosSystem {
      modules = [
        vocalinux.nixosModules.vocalinux
        {
          programs.vocalinux.enable = true;
          users.users.you.extraGroups = [ "input" "uinput" ];
        }
      ];
    };
  };
}
```

`hardware.uinput` (enabled by the module) covers `/dev/uinput`, which ydotool
and the evdev backend's keyboard clone need. `input` group membership is a
per-user decision — it grants read access to every keyboard and pointer
device, the same trade-off `install.sh` documents. X11 sessions need neither
and can skip the group lines entirely.

## Home Manager

```nix
{
  inputs.vocalinux.url = "github:VocaHQ/vocalinux";

  outputs = { home-manager, vocalinux, ... }: {
    homeConfigurations.you = home-manager.lib.homeManagerConfiguration {
      modules = [
        vocalinux.homeManagerModules.vocalinux
        { programs.vocalinux.enable = true; }
      ];
    };
  };
}
```

Home Manager on NixOS still needs the system-side pieces above (the NixOS
module handles `hardware.uinput`; group membership stays per-user). On a
non-NixOS host, `nix profile install` plus the equivalent udev rule and group
membership from your distro does the same job — see docs/INSTALL.md.

## Scope

- Default engine whisper.cpp plus the `[vad]` extra (ONNX Runtime) are built
  in. The `vosk`, `whisper`, `parakeet` and `faster_whisper` extras are not
  packaged (PyTorch footprint / not in nixpkgs).
- `pywhispercpp` is built with `GGML_NATIVE=OFF` — a portable baseline rather
  than `-march=native`, so binaries can move between machines.
