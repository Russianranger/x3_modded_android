#!/usr/bin/env bash
# Validate the compiled X3 profile against TRASC's real ControllerInput.java.
# Usage: tools/trasc_check/run.sh /path/to/trasc-server-android
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$here/../.." && pwd)"
trasc="${1:?path to a trasc-server-android checkout}"
src="$trasc/app/src/main/java/io/github/russianranger/trasc/ControllerInput.java"
[ -f "$src" ] || { echo "ControllerInput.java not found under $trasc" >&2; exit 2; }

python3 -I "$repo_root/tools/build_controls.py" --check
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
pkg="$work/io/github/russianranger/trasc"
mkdir -p "$pkg" "$work/out"
cp "$src" "$pkg/"
cp "$here/TrascProfileCheck.java" "$pkg/"
javac -d "$work/out" "$pkg/ControllerInput.java" "$pkg/TrascProfileCheck.java"
java -cp "$work/out" io.github.russianranger.trasc.TrascProfileCheck "$repo_root/controls/generated/trasc-layers.tsv"
