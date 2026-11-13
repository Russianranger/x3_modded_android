#!/usr/bin/env bash
# Route B: Windows X3: Albion Prelude (+ LxXRM) through Wine WoW64 under Box64.
# Runs INSIDE the app's Debian arm64 rootfs (PRoot), the same way TRASC launches eqgame.exe.
# The Android side has already started the X server (DISPLAY) and the AudioBridge socket.
set -euo pipefail

: "${X3_GAME_DIR:?folder containing X3AP.exe (the Terran Conflict root, with addon/)}"
: "${WINEPREFIX:?app-private Wine prefix}"
: "${ALSA_CONFIG_PATH:?asound.conf generated from runtime/asound.conf.template}"
: "${TRASC_AUDIO_SOCKET:?AudioBridge socket path}"
: "${DISPLAY:?X display}"

BOX64="${BOX64:-box64}"
WINE="${WINE:-/opt/wine/bin/wine}"
X3_EXE="${X3_EXE:-X3AP.exe}"
X3_ARGS="${X3_ARGS:-}"          # try -skipintro (works on the Linux build; unverified on Windows)

case "$X3_GAME_DIR" in
  /sdcard/*|/storage/*) echo "warning: game is on shared storage (FUSE); expect slow loading" >&2 ;;
esac

export WINEDEBUG="${WINEDEBUG:--all}"
# DXVK's 32-bit d3d9.dll lives in the prefix's syswow64 (as in TRASC); prefer it over wined3d.
# winepulse.drv=d: no PulseAudio server exists, so Wine must pick winealsa.drv -> ALSA default
# -> pcm_trasc. Same session-only override TRASC uses (backend/client_audio.py); no registry edit.
export WINEDLLOVERRIDES="d3d9=n,b;winepulse.drv=d${WINEDLLOVERRIDES:+;$WINEDLLOVERRIDES}"
# Keep Box64's DynaCache (translated code) in persistent app storage so the 2nd launch is faster.
export BOX64_DYNACACHE_FOLDER="${BOX64_DYNACACHE_FOLDER:-$HOME/.cache/box64}"
mkdir -p "$BOX64_DYNACACHE_FOLDER"

cd "$X3_GAME_DIR"
# shellcheck disable=SC2086  # X3_ARGS is intentionally word-split
exec "$BOX64" "$WINE" "$X3_EXE" $X3_ARGS
