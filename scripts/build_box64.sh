#!/usr/bin/env bash
# Build the Box64 that the X3 app binds over the runtime's /usr/local/bin/box64.
#
# Same source and flags as TRASC's client runtime (client-runtime/Dockerfile: Box64 2f130fab on
# debian:bookworm-slim, -DARM_DYNAREC=ON -DBAD_SIGNAL=ON RelWithDebInfo), plus patches/box64/*.patch.
# Runs inside an arm64 debian:bookworm-slim container so the binary matches the runtime's glibc.
# Then runs tests/box64/smsw.S with the dynarec on and off, strips debug info, and writes
# OUT/box64 and OUT/box64-build.json.
#
# Usage (on an arm64 host): docker run --rm -v "$PWD:/repo:ro" -v "$PWD/box64-out:/out" \
#     debian:bookworm-slim bash /repo/scripts/build_box64.sh /out
set -euo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
out=${1:?usage: build_box64.sh OUTDIR}
commit=2f130fab1d6e1a4ee8a71dc60cfdfcc839ad192a
cmake_flags=(-DARM_DYNAREC=ON -DBAD_SIGNAL=ON -DCMAKE_BUILD_TYPE=RelWithDebInfo)

test "$(uname -m)" = aarch64 || { echo "build_box64.sh must run on arm64" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends ca-certificates git cmake build-essential python3 \
    binutils-x86-64-linux-gnu >/dev/null

src=$(mktemp -d)
git -C "$src" init -q
git -C "$src" fetch -q --depth 1 https://github.com/ptitSeb/box64.git "$commit"
git -C "$src" checkout -q FETCH_HEAD
test "$(git -C "$src" rev-parse HEAD)" = "$commit"
for patch in "$repo"/patches/box64/*.patch; do
    git -C "$src" apply --whitespace=nowarn "$patch"
    echo "applied $(basename "$patch")"
done
cmake -S "$src" -B "$src/build" "${cmake_flags[@]}" >/dev/null
cmake --build "$src/build" --parallel "$(nproc)" >/dev/null
box64="$src/build/box64"

# Regression tests: x86-64 static programs, no libraries needed.
work=$(mktemp -d)
for test in "$repo"/tests/box64/*.S; do
    name=$(basename "$test" .S)
    x86_64-linux-gnu-as --64 -o "$work/$name.o" "$test"
    x86_64-linux-gnu-ld -static -o "$work/$name" "$work/$name.o"
    for dynarec in 1 0; do
        if BOX64_DYNAREC=$dynarec BOX64_LOG=1 BOX64_NOBANNER=1 "$box64" "$work/$name"; then
            echo "pass $name (dynarec=$dynarec)"
        else
            echo "FAIL $name (dynarec=$dynarec): exit $?" >&2; exit 1
        fi
    done
done

mkdir -p "$out"
strip --strip-debug -o "$out/box64" "$box64"
"$out/box64" --version
python3 -I - "$out" "$commit" "$repo" "${cmake_flags[@]}" <<'PY'
import hashlib, json, pathlib, sys
out, commit, repo, flags = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3]), sys.argv[4:]
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
binary = out / "box64"
record = {
    "commit": commit, "cmake": flags, "built_in": "debian:bookworm-slim arm64",
    "patches": [{"name": p.name, "sha256": digest(p)} for p in sorted((repo / "patches" / "box64").glob("*.patch"))],
    "tests": sorted(p.stem for p in (repo / "tests" / "box64").glob("*.S")),
    "sha256": digest(binary), "bytes": binary.stat().st_size,
}
(out / "box64-build.json").write_text(json.dumps(record, indent=1) + "\n")
print(json.dumps(record))
PY
