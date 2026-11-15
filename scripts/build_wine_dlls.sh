#!/usr/bin/env bash
# Build patched Wine 10.0 DLLs (32-bit PE) for the runtime's Kron4ek Wine 10.0 WoW64 build,
# plus their Wine conformance tests, from the wine-10.0 tag + patches/wine/*.patch, and the
# x3media test program (tests/wine/x3media.c).
# Only PE sides are built: winegstreamer.dll keeps talking to the runtime's own winegstreamer.so,
# which is the same 10.0 source, so the unix-call table matches.
# Needs: i686- and x86_64-w64-mingw32-gcc, gcc, flex, bison, make, GStreamer development files
# (configure leaves winegstreamer out without them). Usage: build_wine_dlls.sh OUTDIR
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
out=$(mkdir -p "${1:?usage: build_wine_dlls.sh OUTDIR}" && cd "$1" && pwd)
tag=wine-10.0
dlls=(amstream winegstreamer)   # patched by patches/wine; tests/wine/run_dll_tests.py knows their suites
work=$(mktemp -d)
git -C "$work" init -q src
git -C "$work/src" fetch -q --depth 1 https://github.com/wine-mirror/wine.git "refs/tags/$tag:refs/tags/$tag"
git -C "$work/src" checkout -q "$tag"
for patch in "$repo"/patches/wine/*.patch; do git -C "$work/src" apply "$patch"; echo "applied $(basename "$patch")"; done
mkdir "$work/build" && cd "$work/build"
"$work/src/configure" -q --enable-archs=i386,x86_64 --without-x --without-freetype --with-gstreamer \
    --without-alsa --without-pulse --without-oss --without-vulkan --without-opengl --without-gnutls \
    --without-krb5 --without-sane --without-usb --without-v4l2 --without-wayland --without-cups \
    --without-dbus --without-fontconfig --without-gphoto --without-netapi --without-pcap --without-pcsclite \
    --without-sdl --without-udev --without-unwind --without-capi --without-inotify --without-xcomposite >/dev/null
grep -q "^enable_winegstreamer *= *no" Makefile 2>/dev/null && { echo "configure left winegstreamer out (GStreamer development files missing?)" >&2; exit 1; }
targets=(dlls/amstream/tests/i386-windows/amstream_test.exe dlls/quartz/tests/i386-windows/quartz_test.exe)
for dll in "${dlls[@]}"; do targets+=("dlls/$dll/i386-windows/$dll.dll"); done
make -s -j"$(nproc)" "${targets[@]}"
for dll in "${dlls[@]}"; do cp "dlls/$dll/i386-windows/$dll.dll" "$out/"; done
cp dlls/amstream/tests/i386-windows/amstream_test.exe dlls/quartz/tests/i386-windows/quartz_test.exe "$out/"
i686-w64-mingw32-gcc -municode -O2 -Wall -o "$out/x3media.exe" "$repo/tests/wine/x3media.c" -lole32 -luuid -lstrmiids -lddraw
python3 -I - "$out" "$tag" "$repo" "${dlls[@]}" <<'PY'
import hashlib, json, pathlib, sys
out, tag, repo, dlls = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3]), sys.argv[4:]
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
record = {"wine": tag, "target": "Kron4ek wine-10.0-amd64-wow64, lib/wine/i386-windows",
          "patches": [{"name": p.name, "sha256": digest(p)} for p in sorted((repo / "patches" / "wine").glob("*.patch"))],
          "dlls": {f"{d}.dll": {"sha256": digest(out / f"{d}.dll"), "bytes": (out / f"{d}.dll").stat().st_size} for d in dlls}}
(out / "wine-dlls.json").write_text(json.dumps(record, indent=1) + "\n")
print(json.dumps(record))
PY
