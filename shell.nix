# The same client environment as bbport/shell.nix, plus the dedicated server.
# Use a nixpkgs with Qt >= 6.8 (including Qt HttpServer), e.g. nixpkgs-unstable.
{ pkgs ? import <nixpkgs> {} }:
assert pkgs.lib.versionAtLeast pkgs.qt6.qtbase.version "6.8";
let
  client = import ./bbport/shell.nix { inherit pkgs; };
in
pkgs.mkShell {
  inputsFrom = [ client ];
  packages = with pkgs; [ qt6.qtbase qt6.qthttpserver ];
}
