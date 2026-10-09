# Home Manager module for Vocalinux.
#
# Installs the package into the user profile; device permissions are a
# system concern, so pair it with the NixOS module (or the manual group
# steps in docs/INSTALL.md) for Wayland/evdev shortcuts and ydotool typing.
{ config, lib, pkgs, ... }:

let
  cfg = config.programs.vocalinux;
in
{
  options.programs.vocalinux = {
    enable = lib.mkEnableOption "Vocalinux voice dictation";

    package = lib.mkOption {
      type = lib.types.package;
      defaultText = "the package built by the vocalinux flake";
      description = "The vocalinux package to install.";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];
  };
}
