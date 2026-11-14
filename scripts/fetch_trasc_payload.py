#!/usr/bin/env python3
"""Assemble the APK's native payload from pinned, checksum-verified archives.

Downloads the archives named in payload/trasc-payload.lock.json, verifies each archive and every
extracted file by SHA-256, and writes payload/out/{assets,jniLibs}/ for Gradle. Nothing is
executed from the downloads. Re-running with a warm cache re-verifies without downloading.

Usage:  python3 -I scripts/fetch_trasc_payload.py [--cache DIR] [--sources DEST]
  --sources DEST   also fetch + verify TRASC's launcher-sources.tar.gz (for release publishing)
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "payload" / "trasc-payload.lock.json"
OUT = ROOT / "payload" / "out"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(url, expected, cache):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (expected[:16] + "-" + url.rsplit("/", 1)[1])
    if target.is_file() and sha256_file(target) == expected:
        return target
    fd, temporary = tempfile.mkstemp(dir=cache, prefix=".download-")
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url, timeout=120) as response:
            shutil.copyfileobj(response, out, 1 << 20)
        actual = sha256_file(temporary)
        if actual != expected:
            raise SystemExit("checksum mismatch for %s: %s" % (url, actual))
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target


def read_member(archive, member):
    if archive.suffix == ".apk":
        with zipfile.ZipFile(archive) as z:
            return z.read(member)
    with tarfile.open(archive, "r:gz") as t:
        info = t.getmember(member)
        if not info.isfile():
            raise SystemExit("%s is not a regular file in %s" % (member, archive.name))
        return t.extractfile(info).read()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache", default=str(ROOT / "payload" / "cache"))
    ap.add_argument("--sources", help="copy the verified TRASC launcher-sources.tar.gz here")
    args = ap.parse_args()
    lock = json.loads(LOCK.read_text())
    cache = Path(args.cache)
    archives = {}
    for name, source in lock["sources"].items():
        if name == "trasc_sources":
            continue
        archives[name] = fetch(source["url"], source["sha256"], cache)
    if OUT.exists():
        shutil.rmtree(OUT)
    written = {}
    for relative, entry in lock["files"].items():
        data = read_member(archives[entry["source"]], entry["member"])
        actual = hashlib.sha256(data).hexdigest()
        if actual != entry["sha256"]:
            raise SystemExit("payload file %s has sha256 %s, lock says %s" % (relative, actual, entry["sha256"]))
        target = OUT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written[relative] = actual
    for check in lock.get("cross_checks", []):
        data = read_member(archives[check["source"]], check["member"])
        if hashlib.sha256(data).hexdigest() != written[check["equals"]]:
            raise SystemExit("cross-check failed: %s != %s" % (check["member"], check["equals"]))
    provenance = {"format": 1, "lock_sha256": sha256_file(LOCK), "files": written,
                  "sources": {k: {"url": v["url"], "sha256": v["sha256"]} for k, v in lock["sources"].items()}}
    (OUT / "assets" / "payload" / "payload-provenance.json").write_text(json.dumps(provenance, indent=1) + "\n")
    print("payload ok: %d files verified into %s" % (len(written), OUT.relative_to(ROOT)))
    if args.sources:
        source = lock["sources"]["trasc_sources"]
        path = fetch(source["url"], source["sha256"], cache)
        shutil.copyfile(path, args.sources)
        print("sources ok: %s" % args.sources)


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, tarfile.TarError, zipfile.BadZipFile) as error:
        print("error: %s" % error, file=sys.stderr)
        sys.exit(1)
