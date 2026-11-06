# Native game and co-op client: `nix-shell shell.nix --run 'bash build.sh'`.
{ pkgs ? import <nixpkgs> {} }:
pkgs.mkShell {
  packages = with pkgs; [
    gcc gnumake cmake ninja pkg-config python3 binutils
    vulkan-headers vulkan-loader sdl3 jack2
    # GPU library (gpu/): shadPS4 video core dependencies
    ffmpeg-headless boost fmt magic-enum robin-map xxhash vulkan-memory-allocator glslang spirv-cross xbyak zydis spirv-headers miniz libx11 libxcb libxau xorgproto wayland alsa-lib
    # bbnet: shared co-op protocol, HTTPS and WebAPI client.
    protobuf nlohmann_json openssl zlib miniupnpc
  ];
}
