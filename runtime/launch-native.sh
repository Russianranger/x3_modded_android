#!/usr/bin/env bash
# Route A: Egosoft's native Linux X3: Albion Prelude (X3AP_main, 32-bit i386 ELF, SDL2 + OpenGL)
# through Box64 with BOX32. Only the game's own code is emulated: SDL2, libGL, libasound, OpenAL
# and X11 are wrapped to the rootfs's native arm64 libraries.
# EXPERIMENTAL: Box64 documents BOX32 as experimental. See docs/01-plan.md, Phase 4.
set -euo pipefail

: "${X3_GAME_DIR:?folder containing X3AP_main and lib/ (Linux Terran War Pack)}"
: "${ALSA_CONFIG_PATH:?asound.conf generated from runtime/asound.conf.template}"
: "${TRASC_AUDIO_SOCKET:?AudioBridge socket path}"
: "${DISPLAY:?X display}"

BOX64="${BOX64:-box64}"          # must be built with -DBOX32=ON (and -DSD8G2=ON for the Thor)
X3_BIN="${X3_BIN:-./X3AP_main}"
X3_ARGS="${X3_ARGS:--skipintro}"  # add '-faststart N' to load save slot N straight away

case "$X3_GAME_DIR" in
  /sdcard/*|/storage/*) echo "warning: game is on shared storage (FUSE); expect slow loading" >&2 ;;
esac

# Video: SDL2 on X11; OpenGL via Mesa Zink on Turnip (Vulkan/KGSL). MESA_VK_WSI_DEBUG=sw is the
# CPU-image present path TRASC already uses to get Turnip frames into its X server.
export SDL_VIDEODRIVER="${SDL_VIDEODRIVER:-x11}"
export MESA_LOADER_DRIVER_OVERRIDE="${MESA_LOADER_DRIVER_OVERRIDE:-zink}"
export GALLIUM_DRIVER="${GALLIUM_DRIVER:-zink}"
export MESA_VK_WSI_DEBUG="${MESA_VK_WSI_DEBUG:-sw}"
# Audio: native libasound -> pcm_trasc -> AudioBridge.
export SDL_AUDIODRIVER="${SDL_AUDIODRIVER:-alsa}"
# The game ships some i386 libs in lib/ (e.g. libpng/zlib); Box64 emulates those.
export BOX64_LD_LIBRARY_PATH="$X3_GAME_DIR/lib${BOX64_LD_LIBRARY_PATH:+:$BOX64_LD_LIBRARY_PATH}"
export BOX64_DYNACACHE_FOLDER="${BOX64_DYNACACHE_FOLDER:-$HOME/.cache/box64}"
mkdir -p "$BOX64_DYNACACHE_FOLDER"

# Keep the simulation running when an Android overlay or the IME takes focus (the x3ui project
# writes this same file for the Linux build).
mkdir -p "$HOME/.config/EgoSoft/X3AP"
[ -f "$HOME/.config/EgoSoft/X3AP/RunInBackground" ] || printf '1' > "$HOME/.config/EgoSoft/X3AP/RunInBackground"

cd "$X3_GAME_DIR"
# shellcheck disable=SC2086  # X3_ARGS is intentionally word-split
exec "$BOX64" "$X3_BIN" $X3_ARGS
