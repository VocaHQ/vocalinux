{
  description = "Vocalinux — free, offline voice dictation for Linux";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
        in
        {
          vocalinux = pkgs.python3Packages.callPackage ./packaging/nix/package.nix {
            pywhispercpp = pkgs.python3Packages.callPackage ./packaging/nix/pywhispercpp.nix { };
            src = self;
          };
          default = self.packages.${system}.vocalinux;
        }
      );

      apps = forAllSystems (system: {
        vocalinux = {
          type = "app";
          program = "${self.packages.${system}.vocalinux}/bin/vocalinux";
        };
        default = self.apps.${system}.vocalinux;
      });

      overlays.default = final: prev: {
        vocalinux = self.packages.${prev.system}.vocalinux;
      };

      nixosModules.vocalinux =
        { pkgs, lib, ... }:
        {
          imports = [ ./packaging/nix/module.nix ];
          programs.vocalinux.package = lib.mkDefault self.packages.${pkgs.system}.vocalinux;
        };
      nixosModules.default = self.nixosModules.vocalinux;

      homeManagerModules.vocalinux =
        { pkgs, lib, ... }:
        {
          imports = [ ./packaging/nix/home-manager.nix ];
          programs.vocalinux.package = lib.mkDefault self.packages.${pkgs.system}.vocalinux;
        };
      homeManagerModules.default = self.homeManagerModules.vocalinux;
    };
}
