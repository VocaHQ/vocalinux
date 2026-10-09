# NixOS module for Vocalinux.
#
# The flake wraps this file and injects the flake-built package as the
# default (programs.vocalinux.package), so importing the module through
# nixosModules.vocalinux needs no extra wiring. Imported on its own, set
# programs.vocalinux.package to a vocalinux derivation.
#
# What it cannot do for you: membership in the "input" group is per-user,
# so the module documents it and each user opts in:
#
#   users.users.<name>.extraGroups = [ "input" "uinput" ];
#
# "input" grants read access to every keyboard and pointer device — the
# evdev global-shortcut backend needs it on Wayland. X11 sessions need none
# of this. See docs/INSTALL.md for the same notes the deb/rpm carry.
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
    environment.systemPackages = [ cfg.package ];

    # /dev/uinput is what ydotool (native Wayland typing) and the evdev
    # backend's keyboard clone open. The option loads the module, creates
    # the "uinput" group and installs the matching udev rule.
    hardware.uinput.enable = true;
  };
}
