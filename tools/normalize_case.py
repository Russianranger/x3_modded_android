#!/usr/bin/env python3
"""Lowercase mod/game DATA paths for the native Linux build (Route A), reversibly.

Windows and Wine ignore case; Egosoft's Linux binary runs on a case-sensitive filesystem, so a mod
that ships 'Scripts/plugin.Lucike.Foo.xml' may not be found. Only use this after the probe or a
file-not-found log shows it is needed, and only on a COPY of the game folder.

Safety
  * dry run by default; --apply to rename
  * refuses to run if two paths would collapse into one (case-only collisions), listing them
  * never touches executables, lib/, shared objects or Windows binaries (see EXCLUDE)
  * writes a manifest so --revert MANIFEST restores the original names

Usage
  python3 -I tools/normalize_case.py "/path/to/game" [--only addon --only scripts] [--apply]
  python3 -I tools/normalize_case.py "/path/to/game" --revert case-manifest.json
"""
import argparse
import fnmatch
import json
import os
import sys

EXCLUDE = ["lib", "lib64", "*.so", "*.so.*", "X3*_main", "X3*_config", "*.exe", "*.dll", "*.sh"]
MANIFEST = "case-manifest.json"


def excluded(rel):
    parts = rel.split(os.sep)
    return any(fnmatch.fnmatch(p, pat) for p in parts for pat in EXCLUDE)


def plan(root, only):
    starts = [os.path.join(root, o) for o in only] if only else [root]
    renames, seen = [], {}
    for start in starts:
        if not os.path.isdir(start):
            raise SystemExit("not a directory: %s" % start)
        if start != root and os.path.basename(start) != os.path.basename(start).lower():
            renames.append(os.path.relpath(start, root))
        for dirpath, dirnames, filenames in os.walk(start, topdown=False):
            for name in filenames + dirnames:
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                if excluded(rel):
                    continue
                key = rel.lower()
                seen.setdefault(key, []).append(rel)
                if name != name.lower():
                    renames.append(rel)
    collisions = [v for v in seen.values() if len(v) > 1]
    # deepest first so parents are renamed after their children
    renames = sorted(set(renames), key=lambda r: (-r.count(os.sep), r))
    # a lowercase sibling that already exists (possibly outside --only) would be overwritten
    for rel in renames:
        head, name = os.path.split(rel)
        target = os.path.join(root, head, name.lower())
        if os.path.lexists(target) and not os.path.samefile(target, os.path.join(root, rel)):
            collisions.append([rel, os.path.join(head, name.lower())])
    unique = {tuple(sorted(c)): c for c in collisions}
    return renames, list(unique.values())


def apply(root, renames):
    done = []
    for rel in renames:
        head, name = os.path.split(rel)
        src = os.path.join(root, head, name)
        dst = os.path.join(root, head, name.lower())
        os.rename(src, dst)
        done.append([os.path.join(head, name.lower()), rel])
    return done


def revert(root, manifest):
    with open(manifest, encoding="utf-8") as f:
        pairs = json.load(f)["renamed"]
    for lowered, original in reversed(pairs):
        os.rename(os.path.join(root, lowered), os.path.join(root, original))
    print("restored %d names" % len(pairs))


def main():
    ap = argparse.ArgumentParser(description="Reversible lowercase normalisation of X3 data paths")
    ap.add_argument("root")
    ap.add_argument("--only", action="append", default=[], help="limit to this subfolder (repeatable)")
    ap.add_argument("--apply", action="store_true", help="actually rename (default is a dry run)")
    ap.add_argument("--revert", metavar="MANIFEST", help="undo a previous run")
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    if args.revert:
        revert(root, args.revert)
        return
    renames, collisions = plan(root, args.only)
    if collisions:
        print("refusing: %d case-only collision(s); resolve these first:" % len(collisions), file=sys.stderr)
        for c in collisions[:50]:
            print("  " + " <-> ".join(c), file=sys.stderr)
        sys.exit(1)
    print("%d path(s) to lowercase%s" % (len(renames), "" if args.apply else " (dry run)"))
    for rel in renames[:40]:
        print("  %s -> %s" % (rel, os.path.join(os.path.dirname(rel), os.path.basename(rel).lower())))
    if len(renames) > 40:
        print("  ...")
    if args.apply and renames:
        manifest = os.path.join(root, MANIFEST)
        if os.path.exists(manifest):
            sys.exit("%s exists; revert or move it before running again" % manifest)
        done = apply(root, renames)
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump({"root": root, "renamed": done}, f, indent=1)
        print("renamed %d; manifest: %s" % (len(done), manifest))


if __name__ == "__main__":
    main()
