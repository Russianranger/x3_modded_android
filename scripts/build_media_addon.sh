#!/usr/bin/env bash
# Build the media add-on: native arm64 GStreamer for Wine's winegstreamer, so X3's music, comms
# voices and movies (DirectShow) can play. Everything else in the runtime stays as it is.
#
# Runs as root *inside* TRASC's pinned client runtime (client-runtime-v1, imported into Docker),
# so apt resolves dependencies against exactly what the app has. The add-on is the set of files
# that are new or changed after the install, as a GNU tar the app unpacks over its runtime.
#
# Then tests it: every required element exists, native decodes of WAV and MP3 work, and an
# x86-64 program under the runtime's Box64 decodes both through Box64's wrapped GStreamer with a
# callback into emulated code (tests/media/gst_box64_check.c), the path winegstreamer.so takes.
#
# Usage: docker run --rm -v "$PWD:/repo:ro" -v "$PWD/media-out:/out" x3-runtime:v1 \
#            bash /repo/scripts/build_media_addon.sh /out
set -euo pipefail
out=${1:?usage: build_media_addon.sh OUTDIR}
repo=$(cd "$(dirname "$0")/.." && pwd)
version=media-addon-v2
runtime_sha256=2f130c07683e50bc606af111d5c35c4f503c1427772c1f9b0f45e1e4b75c76c4
gst=/usr/lib/aarch64-linux-gnu/gstreamer-1.0
export DEBIAN_FRONTEND=noninteractive

test -f /etc/trasc-client-runtime.json || { echo "not the TRASC client runtime" >&2; exit 1; }
test "$(uname -m)" = aarch64

snapshot() {   # every file and symlink outside scratch areas: path, size, mtime, link target
    find / -xdev \( -path /proc -o -path /sys -o -path /dev -o -path /run -o -path /tmp -o -path /root \
        -o -path /var/cache -o -path /var/log -o -path /var/lib/apt/lists -o -path /out -o -path /repo \
        -o -path /etc/hostname -o -path /etc/hosts -o -path /etc/resolv.conf \) -prune \
        -o \( -type f -o -type l \) -printf '%P\t%s\t%T@\t%l\n' | LC_ALL=C sort
}
snapshot > /tmp/before.tsv
dpkg-query -W -f '${Package}:${Architecture}=${Version}\n' | LC_ALL=C sort > /tmp/packages-before.txt

apt-get update -qq
# base: decodebin, audioconvert, audioresample; good: wavparse, avidemux, mpegaudioparse,
# mpg123audiodec; ugly: mpeg2dec, asfdemux; tools: gst-inspect-1.0 for on-device diagnostics.
# libav (v2): avdec_wmav2. X3's Betty and NPC voices are WMA 2 in ASF (mov/*.dat, sixth device
# run's media survey); Wine 10's WMA decoder and ASF reader decode through GStreamer, and only
# gst-libav has a WMA decoder in Debian. It also covers MPEG-1 video for the comms panel.
apt-get install -y -qq --no-install-recommends gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-ugly gstreamer1.0-libav gstreamer1.0-tools >/dev/null
# Two plugins from -bad (MPEG program streams for movies) without that package's ~150 MB of
# dependencies (GTK, OpenCV-adjacent, codecs X3 never uses). ldd below proves they resolve.
mkdir -p /tmp/bad && cd /tmp/bad
apt-get download -qq gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-0
for deb in ./*.deb; do dpkg-deb -x "$deb" /tmp/bad/root; done
cp -a /tmp/bad/root$gst/libgstmpegpsdemux.so /tmp/bad/root$gst/libgstvideoparsersbad.so "$gst/"
cp -a /tmp/bad/root/usr/lib/aarch64-linux-gnu/libgstcodecparsers-1.0.so.0* /usr/lib/aarch64-linux-gnu/
ldconfig
cd /
unresolved=$(for so in "$gst"/*.so; do ldd "$so" | sed -n "s|^\s*\(.*not found\)|$(basename "$so"): \1|p"; done)
if [ -n "$unresolved" ]; then echo "unresolved libraries:" >&2; echo "$unresolved" >&2; exit 1; fi
apt-get clean

dpkg-query -W -f '${Package}:${Architecture}=${Version}\n' | LC_ALL=C sort > /tmp/packages-after.txt
LC_ALL=C comm -13 /tmp/packages-before.txt /tmp/packages-after.txt > /etc/x3-media-addon.packages
printf '%s\n' "+ gstreamer1.0-plugins-bad: libgstmpegpsdemux.so libgstvideoparsersbad.so" \
    "+ libgstreamer-plugins-bad1.0-0: libgstcodecparsers-1.0" >> /etc/x3-media-addon.packages
snapshot > /tmp/after.tsv
LC_ALL=C comm -13 /tmp/before.tsv /tmp/after.tsv | cut -f1 > /tmp/addon-files.txt
echo "$(wc -l < /tmp/addon-files.txt) new or changed files; $(wc -l < /etc/x3-media-addon.packages) packages"
grep -c "^usr/lib/aarch64-linux-gnu/gstreamer-1.0/" /tmp/addon-files.txt | sed 's/^/plugins: /'

mkdir -p "$out"
tar --format=gnu --hard-dereference --numeric-owner --no-recursion -C / -czf "$out/media-addon-arm64.tar.gz" \
    --verbatim-files-from -T /tmp/addon-files.txt
if tar -tvzf "$out/media-addon-arm64.tar.gz" | grep -qv '^[-l]'; then echo "add-on must hold only files and symlinks" >&2; exit 1; fi

# --- tests: native GStreamer ---------------------------------------------------------------
for element in decodebin audioconvert audioresample wavparse avidemux mpegaudioparse mpg123audiodec \
               mpeg2dec mpegpsdemux mpegvideoparse asfdemux avdec_wmav2 avdec_mpeg1video \
               lamemp3enc wavenc audiotestsrc videotestsrc avenc_wmav2 avenc_mpeg1video; do
    gst-inspect-1.0 --exists "$element" || { echo "missing element $element" >&2; exit 1; }
done
work=$(mktemp -d)
gst-launch-1.0 -q audiotestsrc num-buffers=100 ! audioconvert ! wavenc ! filesink location="$work/tone.wav"
gst-launch-1.0 -q audiotestsrc num-buffers=100 ! audioconvert ! lamemp3enc ! filesink location="$work/tone.mp3"
# WMA-in-ASF (voices) and MPEG-1 program streams (comms videos) need muxers from -bad that the
# add-on leaves out: load just those two from the unpacked -bad package, for the test only.
mkdir -p "$work/muxers" && cp /tmp/bad/root$gst/libgstasfmux.so /tmp/bad/root$gst/libgstmpegpsmux.so "$work/muxers/"
GST_PLUGIN_PATH="$work/muxers" gst-launch-1.0 -q audiotestsrc num-buffers=100 ! audioconvert ! avenc_wmav2 ! asfmux \
    ! filesink location="$work/voice.wma"
GST_PLUGIN_PATH="$work/muxers" gst-launch-1.0 -q videotestsrc num-buffers=50 ! video/x-raw,width=320,height=240,framerate=25/1 \
    ! videoconvert ! avenc_mpeg1video ! mpegvideoparse ! mpegpsmux ! filesink location="$work/comms.mpg"
for file in "$work/tone.wav" "$work/tone.mp3" "$work/voice.wma"; do
    gst-launch-1.0 -q filesrc location="$file" ! decodebin ! audioconvert ! fakesink
    echo "native decode ok: $(basename "$file")"
done
gst-launch-1.0 -q filesrc location="$work/comms.mpg" ! decodebin ! videoconvert ! fakesink
echo "native decode ok: comms.mpg (MPEG-1 program stream)"

# --- tests: Box64-wrapped GStreamer from x86-64 code (not part of the add-on) -----------------
apt-get update -qq
apt-get install -y -qq --no-install-recommends gcc-x86-64-linux-gnu libc6-dev-amd64-cross >/dev/null
x86_64-linux-gnu-gcc -O2 -o "$work/gst_box64_check" "$repo/tests/media/gst_box64_check.c" -ldl
for file in "$work/tone.wav" "$work/tone.mp3" "$work/voice.wma"; do
    BOX64_LOG=1 BOX64_NOBANNER=1 BOX64_LD_LIBRARY_PATH=/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu \
        GST_REGISTRY_1_0="$work/registry.bin" /usr/local/bin/box64 "$work/gst_box64_check" "$file" 2>&1 \
        | tee "$work/box64.log" | grep -E "native\(wrapped\) libgst|EOS|Warning|Error" || true
    grep -q ": EOS, " "$work/box64.log" || { echo "Box64 GStreamer check failed for $file" >&2; cat "$work/box64.log" >&2; exit 1; }
done

python3 -I - "$out" "$version" "$runtime_sha256" <<'PY'
import hashlib, json, pathlib, sys
out, version, runtime = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]
archive = out / "media-addon-arm64.tar.gz"
manifest = {
    "format": 1, "version": version, "runtime_sha256": runtime,
    "url": f"https://github.com/Russianranger/x3_modded_android/releases/download/{version}/media-addon-arm64.tar.gz",
    "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "bytes": archive.stat().st_size,
    "files": sum(1 for _ in open("/tmp/addon-files.txt")),
    "packages": pathlib.Path("/etc/x3-media-addon.packages").read_text().split("\n")[:-1],
    "tests": ["gst-inspect elements", "native wav+mp3+wma(asf)+mpeg1-ps decode", "box64 wrapped gstreamer wav+mp3+wma decode with callback"],
}
(out / "media-addon.json").write_text(json.dumps(manifest, indent=1) + "\n")
print(json.dumps({k: manifest[k] for k in ("version", "sha256", "bytes", "files")}))
PY
