# Install reports

Phase 0 output goes here (docs/01-plan.md). Suggested names:

- `windows-lxxrm.json`: `python3 -I tools/probe_x3_install.py "<Windows TC folder with LxXRM>" --json reports/windows-lxxrm.json`
- `linux-vanilla.json`: same tool on a vanilla Linux Terran War Pack install
- `linux-openat.txt`: `strace -f -e trace=openat ./X3AP_main -skipintro 2>&1 | grep -i ENOENT` from an x86 Linux PC

The reports contain only file names, sizes and counts, no game data.
