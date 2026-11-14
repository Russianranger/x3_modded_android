# Copied from trasc-server-android backend/client_metrics.py (commit 99e8c86f). Keep changes minimal and marked.
"""Bounded, read-only observations of this launch's Linux process tree."""
import os
from pathlib import Path
import re
import time
from itertools import islice

# X3: TRASC's marker is TRASC_CLIENT_LAUNCH; the X3 runner sets this name (x3_runner imports it).
LAUNCH_ENV = 'X3_LAUNCH'


def blocked_in(task):
    """X3 addition: kernel wait channel and syscall number of a sleeping thread, when readable.

    After the third Thor run (all X3 threads asleep, no log line saying why) this is what tells a
    futex wait from a blocked pipe write or a poll on the X server. Optional: Android may hide both.
    """
    found = {}
    try:
        wchan = (task/'wchan').read_text()[:64].strip()
        if wchan and wchan != '0': found['wchan'] = wchan
    except OSError: pass
    try:
        number = (task/'syscall').read_text()[:256].split(maxsplit=1)[0]
        if number.lstrip('-').isdecimal(): found['syscall'] = int(number)
    except (OSError, IndexError): pass
    return found


def process_threads(root_pid, proc=Path('/proc'), launch_token=None, game_name='x3ap.exe'):
    """Never scan unrelated processes or log command lines / environments.

    Mesa 22.3 names its GL command worker <process>:gl0 (util/u_queue.c).
    A requested environment option is not proof that this thread exists.
    Wine can reparent processes away from its original launcher. An ephemeral
    inherited marker finds those processes too. Only same-UID environments are
    inspected for that exact marker; no environment contents are returned.
    Linux children lists are a fallback for callers without a launch marker.
    Android may deny some proc files: report incomplete evidence, not failure.
    """
    pending = [int(root_pid)]
    visited, workers, threads = set(), [], []
    incomplete = False
    if launch_token:
        pending = []
        marker = (LAUNCH_ENV+'='+launch_token).encode()  # X3: shared name
        try:
            uid = (proc/'self').stat().st_uid
            entries = list(islice(proc.iterdir(), 2049))
            if len(entries) > 2048: incomplete = True
            for path in entries[:2048]:
                if not path.name.isdecimal(): continue
                try:
                    if path.stat().st_uid != uid: continue
                    with (path/'environ').open('rb') as source: environment = source.read(65537)
                    if len(environment) > 65536:
                        incomplete = True
                        continue
                    if marker in environment.split(b'\0'): pending.append(int(path.name))
                except OSError: continue # Exited, hidden or not readable by this app.
        except OSError: incomplete = True
    while pending and len(visited) < 32 and len(threads) < 256:
        pid = pending.pop()
        if pid in visited: continue
        visited.add(pid)
        try: tasks = list(islice((proc/str(pid)/'task').iterdir(), 257))
        except OSError:
            incomplete = True
            continue
        for task in tasks[:256-len(threads)]:
            if not task.name.isdecimal(): continue
            try:
                # stat field 2 may contain spaces and parentheses.
                stat = (task/'stat').read_text()[:4096]
                end = stat.rfind(')')
                fields = stat[end+2:].split()
                name = stat[stat.find('(')+1:end]
                entry = {'pid': pid, 'tid': int(task.name), 'name': name, 'state': fields[0],
                         'start_ticks': int(fields[19]),
                         'cpu_ticks': int(fields[11])+int(fields[12]),
                         'last_cpu': int(fields[36])}
                if len(threads) < 32 or re.search(r'(?:^|:)gl\d+$', name):
                    status = (task/'status').read_text()[:16384]
                    mask = re.search(r'^Cpus_allowed_list:\s*(.+)$', status, re.M)
                    if mask: entry['allowed_cpus'] = mask[1].strip()
                if fields[0] in ('S', 'D'): entry.update(blocked_in(task))  # X3: where a hung thread waits
                threads.append(entry)
                if re.search(r'(?:^|:)gl\d+$', name): workers.append(entry)
                if not launch_token:
                    children = (task/'children').read_text()[:4096]
                    pending.extend(int(p) for p in children.split()[:32] if p.isdecimal() and int(p) not in visited)
            except (OSError, ValueError, IndexError): incomplete = True
    if pending or len(threads) >= 256: incomplete = True
    return {'sampled_at': time.time(), 'clock_ticks_per_second': os.sysconf('SC_CLK_TCK'),
            'scope': 'launch_marker' if launch_token else 'launcher_descendants', 'incomplete': incomplete,
            'game_running': any(t['pid'] == t['tid'] and t['name'].lower() == game_name[:15].lower() and t['state'] not in ('Z', 'X') for t in threads),
            'processes': len(visited), 'threads': threads[:256], 'mesa_gl_workers': workers[:16]}


def allow_game_cpus(sample, launch_token, proc=Path('/proc'), game_name='x3ap.exe'):
    """Undo the game's CPU-0 restriction within this app's current allowed mask.

    Match the launch marker, process owner and thread start time again before
    changing a mask. Never change server/helper processes or Android policy.
    """
    allowed = os.sched_getaffinity(0)
    result = {'available_cpus': sorted(allowed), 'changed_threads': 0, 'errors': 0}
    game_pids = {t['pid'] for t in sample['threads'] if t['tid'] == t['pid'] and t['name'].lower() == game_name[:15].lower()}  # X3: parameterised
    marker = (LAUNCH_ENV+'='+launch_token).encode()  # X3: shared name
    for pid in game_pids:
        parent = proc/str(pid)
        try:
            if parent.stat().st_uid != (proc/'self').stat().st_uid: continue
            with (parent/'environ').open('rb') as source: environment = source.read(65537)
            if len(environment)>65536 or marker not in environment.split(b'\0'): continue
        except OSError: continue
        for t in sample['threads']:
            if t['pid'] != pid: continue
            try:
                raw = (parent/'task'/str(t['tid'])/'stat').read_text()[:4096]
                if int(raw[raw.rfind(')')+2:].split()[19]) != t.get('start_ticks'): continue
                if os.sched_getaffinity(t['tid']) != allowed:
                    os.sched_setaffinity(t['tid'], allowed)
                    result['changed_threads'] += 1
            except (OSError, ValueError, IndexError): result['errors'] += 1
    return result
