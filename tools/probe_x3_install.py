#!/usr/bin/env python3
"""Read-only inventory of an X3 install (Windows or Linux build, vanilla or LxXRM).

Answers the Phase-0 questions in docs/01-plan.md without modifying anything:
  * which executables exist, their architecture, and whether X3AP.exe is Large Address Aware
  * the shared libraries the Linux ELF binaries need (DT_NEEDED), parsed directly (no readelf)
  * size and file count per top-level folder; loose script / text file counts (load-time cost)
  * cat/dat numbering in the root and addon/ (gaps break mod load order)
  * paths that differ only by case (a problem on Route A) and how many names contain capitals
  * audio/video file formats in soundtrack/, mov/, sfx/ (XRM's Linux patch swaps some of these)

Usage:  python3 -I tools/probe_x3_install.py "/path/to/X3 Terran Conflict" [--json report.json]
"""
import argparse
import collections
import json
import os
import struct
import sys

EXECUTABLES = ["X3AP.exe", "X3TC.exe", "X3FL.exe", "X3AP_main", "X3TC_main", "X3FL_main",
               "X3AP_config", "X3TC_config", "X3FL_config"]
MEDIA_DIRS = ["soundtrack", "mov", "sfx", "addon/soundtrack", "addon/mov", "addon/sfx"]
LOOSE_DIRS = ["scripts", "t", "director", "addon/scripts", "addon/t", "addon/director"]
ELF_MACHINES = {3: "i386", 62: "x86_64", 183: "aarch64", 40: "arm"}
PE_MACHINES = {0x14C: "i386", 0x8664: "x86_64", 0xAA64: "arm64"}


def find_case_insensitive(root, rel):
    """Resolve rel under root ignoring case; returns the real path or None."""
    current = root
    for part in rel.split("/"):
        try:
            names = os.listdir(current)
        except OSError:
            return None
        match = next((n for n in names if n.lower() == part.lower()), None)
        if match is None:
            return None
        current = os.path.join(current, match)
    return current


def elf_info(path):
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"\x7fELF":
        return None
    bits = 32 if data[4] == 1 else 64
    end = "<" if data[5] == 1 else ">"
    etype, machine = struct.unpack_from(end + "HH", data, 16)
    if bits == 32:
        shoff = struct.unpack_from(end + "I", data, 32)[0]
        shentsize, shnum = struct.unpack_from(end + "HH", data, 46)
    else:
        shoff = struct.unpack_from(end + "Q", data, 40)[0]
        shentsize, shnum = struct.unpack_from(end + "HH", data, 58)
    sections = []
    for i in range(shnum):
        off = shoff + i * shentsize
        if bits == 32:
            name, stype, flags, addr, offset, size, link = struct.unpack_from(end + "IIIIIII", data, off)
        else:
            name, stype = struct.unpack_from(end + "II", data, off)
            flags, addr, offset, size = struct.unpack_from(end + "QQQQ", data, off + 8)
            link = struct.unpack_from(end + "I", data, off + 40)[0]
        sections.append((stype, offset, size, link))
    needed = []
    for stype, offset, size, link in sections:
        if stype != 6 or link >= len(sections):   # SHT_DYNAMIC
            continue
        stroff = sections[link][1]
        entsize = 8 if bits == 32 else 16
        fmt = end + ("iI" if bits == 32 else "qQ")
        for j in range(size // entsize):
            tag, val = struct.unpack_from(fmt, data, offset + j * entsize)
            if tag == 0:
                break
            if tag == 1:   # DT_NEEDED
                stop = data.index(b"\0", stroff + val)
                needed.append(data[stroff + val:stop].decode("utf-8", "replace"))
    return {"format": "ELF%d" % bits, "machine": ELF_MACHINES.get(machine, str(machine)),
            "pie": etype == 3, "needed": needed}


def pe_info(path):
    with open(path, "rb") as f:
        head = f.read(4096)
    if head[:2] != b"MZ":
        return None
    pe = struct.unpack_from("<I", head, 0x3C)[0]
    if head[pe:pe + 4] != b"PE\0\0":
        return None
    machine, = struct.unpack_from("<H", head, pe + 4)
    characteristics, = struct.unpack_from("<H", head, pe + 22)
    return {"format": "PE", "machine": PE_MACHINES.get(machine, hex(machine)),
            "large_address_aware": bool(characteristics & 0x20)}


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            yield os.path.join(dirpath, name)


def catalogs(folder):
    if not folder or not os.path.isdir(folder):
        return None
    names = {n.lower() for n in os.listdir(folder)}
    numbers = sorted(int(n[:-4]) for n in names if n.endswith(".cat") and n[:-4].isdigit())
    missing_dat = [n for n in numbers if "%02d.dat" % n not in names and "%d.dat" % n not in names]
    gaps = [n for n in range(1, (numbers[-1] if numbers else 0) + 1) if n not in numbers]
    return {"cats": numbers, "gaps": gaps, "cat_without_dat": missing_dat}


def probe(root):
    root = os.path.abspath(root)
    report = {"root": root, "warnings": []}
    if root.startswith(("/sdcard", "/storage")):
        report["warnings"].append("Install is on Android shared storage (FUSE). Copy it into app-private "
                                  "storage before measuring load times.")
    exes = {}
    for name in EXECUTABLES:
        path = find_case_insensitive(root, name) or find_case_insensitive(root, "game/" + name)
        if path:
            exes[os.path.relpath(path, root)] = elf_info(path) or pe_info(path) or {"format": "unknown"}
    report["executables"] = exes
    if not exes:
        report["warnings"].append("No X3 executable found; point at the folder holding X3AP.exe or X3AP_main.")

    per_top = collections.defaultdict(lambda: [0, 0])
    lower_map = collections.defaultdict(list)
    upper_names = 0
    total_files = 0
    for path in walk(root):
        rel = os.path.relpath(path, root)
        top = rel.split(os.sep)[0] if os.sep in rel else "(root files)"
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        per_top[top][0] += 1
        per_top[top][1] += size
        total_files += 1
        lower_map[rel.lower()].append(rel)
        if any(c.isupper() for c in os.path.basename(rel)):
            upper_names += 1
    report["total_files"] = total_files
    report["total_mib"] = round(sum(v[1] for v in per_top.values()) / 2**20, 1)
    report["top_level"] = {k: {"files": v[0], "mib": round(v[1] / 2**20, 1)}
                           for k, v in sorted(per_top.items(), key=lambda kv: -kv[1][1])}
    collisions = [v for v in lower_map.values() if len(v) > 1]
    report["case"] = {"names_with_capitals": upper_names, "collisions": len(collisions),
                      "collision_examples": collisions[:10]}
    if collisions:
        report["warnings"].append("%d path(s) differ only by case: they work on Windows/Wine but will "
                                  "shadow each other if lowercased for the native build." % len(collisions))

    loose = {}
    for rel in LOOSE_DIRS:
        path = find_case_insensitive(root, rel)
        if path and os.path.isdir(path):
            loose[rel] = sum(1 for _ in walk(path))
    report["loose_files"] = loose
    if sum(loose.values()) > 2000:
        report["warnings"].append("%d loose script/text files: each costs path lookups at load (PRoot and "
                                  "Wine both add overhead per lookup)." % sum(loose.values()))

    report["catalogs"] = {"root": catalogs(root), "addon": catalogs(find_case_insensitive(root, "addon"))}
    for where, info in report["catalogs"].items():
        if info and info["gaps"]:
            report["warnings"].append("%s: cat numbering has gaps %s (X3 stops loading at the first gap)."
                                      % (where, info["gaps"]))

    media = {}
    for rel in MEDIA_DIRS:
        path = find_case_insensitive(root, rel)
        if path and os.path.isdir(path):
            counts = collections.Counter(os.path.splitext(p)[1].lower() or "(none)" for p in walk(path))
            media[rel] = dict(counts.most_common())
    report["media_formats"] = media
    return report


def print_report(r):
    print("X3 install probe: %s" % r["root"])
    print("\nExecutables:")
    for name, info in r["executables"].items() or [("(none)", {})]:
        extra = ""
        if info.get("format") == "PE":
            extra = " LAA=%s" % ("yes" if info["large_address_aware"] else "no")
        elif info.get("format", "").startswith("ELF"):
            extra = " PIE=%s needs: %s" % ("yes" if info["pie"] else "no", ", ".join(info["needed"]) or "-")
        print("  %-22s %s %s%s" % (name, info.get("format", "?"), info.get("machine", ""), extra))
    print("\nSize: %d files, %.1f MiB" % (r["total_files"], r["total_mib"]))
    for top, v in list(r["top_level"].items())[:15]:
        print("  %-24s %7d files %9.1f MiB" % (top, v["files"], v["mib"]))
    print("\nLoose script/text files:", r["loose_files"] or "none found")
    for where, info in r["catalogs"].items():
        if info:
            print("Catalogs in %-6s cats=%s gaps=%s cat-without-dat=%s"
                  % (where + ":", info["cats"], info["gaps"] or "none", info["cat_without_dat"] or "none"))
    c = r["case"]
    print("\nCase: %d file names contain capitals; %d case-only collisions" % (c["names_with_capitals"], c["collisions"]))
    for ex in c["collision_examples"]:
        print("  ", " <-> ".join(ex))
    print("\nMedia formats:")
    for rel, counts in r["media_formats"].items():
        print("  %-18s %s" % (rel, counts))
    if r["warnings"]:
        print("\nWarnings:")
        for w in r["warnings"]:
            print("  - " + w)


def main():
    ap = argparse.ArgumentParser(description="Read-only X3 install inventory")
    ap.add_argument("root")
    ap.add_argument("--json", help="also write the report as JSON to this path")
    args = ap.parse_args()
    if not os.path.isdir(args.root):
        print("not a directory: %s" % args.root, file=sys.stderr)
        sys.exit(2)
    report = probe(args.root)
    print_report(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)


if __name__ == "__main__":
    main()
