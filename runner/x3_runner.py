"""X3 Wine/Box64 supervisor. Runs inside the app's client rootfs under PRoot.

Adapted from trasc-server-android backend/client_runner.py (commit 99e8c86f). Kept: Xtigervnc
display on a private socket, relative-input helper, Turnip/DXVK preflight, Wine prefix
preparation, bounded Wine log capture, audio bridge setup, CPU-affinity repair, clean stop.
Removed: everything EverQuest-specific (dinput8, camera/loading adapters, eqclient.ini, spells).
Added: X3 program selection (game or any .exe/.bat in the game folder), PE checks (bitness,
Large Address Aware, Steam API import), 64-bit DXVK, Egosoft's 'dsp0' audio device, and saves kept
outside the prefix and runtime (Documents\\Egosoft -> /saves/Egosoft).

Interface with the Android app (unchanged contract from TRASC):
  /session/request.json   launch request written by GameRuntime.java
  /session/status.json    progress, errors and diagnostics, rewritten atomically
  /session/stop           created by the app to request a clean stop
  /session/display.sock   RFB display; /session/input.sock relative pointer; /session/audio.sock
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import struct
import subprocess
import threading
import time
from contextlib import contextmanager

import client_audio
import client_presentation
import client_vulkan
import pe_info
from client_metrics import LAUNCH_ENV, process_threads, allow_game_cpus, place_game_threads, fastest_cpus, fast_cpus
from client_xauthority import write_xauthority

HERE = Path(__file__).resolve().parent
SESSION = Path('/session')
GAME = Path('/game')
PREFIX = Path('/prefix')
SAVES = Path('/saves')
LOGS = Path('/logs')
BOX64 = '/usr/local/bin/box64'
WINE = '/opt/wine/bin/wine'
WINE_LOG_LIMIT = 8 * 1024 * 1024
RESOLUTIONS = ('800x600', '1024x768', '1280x720', '1366x768', '1600x900', '1920x1080')
PROGRAM_SUFFIXES = ('.exe', '.bat', '.cmd')
stop_requested = False
stop_reason = None


# Music and voices: warnings and fixmes of the DirectShow, ACM and winegstreamer channels name
# where a graph or conversion fails at a few lines per stream. amstream logs on the quartz channel;
# its traces (file names, formats) are heavy, so they come with "Sound diagnostics" only.
MEDIA_DEBUG = ','.join(level + '+' + channel for channel in
                       ('quartz', 'strmbase', 'winegstreamer', 'qasf', 'wmvcore', 'dmo',
                        'msacm', 'mpeg3', 'mp3dmod', 'mfplat') for level in ('warn', 'fixme'))
# Patch 0008's channel in the patched amstream and winegstreamer: files opened, state changes,
# seeks, segments, the first frames and updates after each, then counts. A few lines per comms
# call, so it is always on: the comms face problems never showed up in a run with diagnostics.
MEDIA_DEBUG += ',trace+x3media'


def wine_debug(verbose=False, sound=False):
    # +seh and per-frame traces flood PRoot; Wine's fps channel reports every 1.5 s per swapchain.
    normal = '-all,+timestamp,+pid,err+all,trace+loaddll,trace+fps,' + MEDIA_DEBUG
    return (normal + ',warn+dsound,warn+wave,warn+mmdevapi'
            + (',warn+all,fixme+all,trace+module' if verbose else '')
            + (',trace+msacm,trace+quartz,trace+strmbase' if sound else ''))


# Sound diagnostics: per-sample and reference-counting quartz traces carry nothing about why a
# file plays or not, and at 30 frames a second they fill a log segment in seconds.
SOUND_NOISE = re.compile(
    rb':trace:(?:quartz|strmbase):(?:\w*_(?:AddRef|Release)\b|StdMediaSample2_|BaseMemAllocator_|wg_sample_'
    rb'|quartz_sample_destroy|enum_(?:pins|media_types)_|pin_Query|pin_ConnectedTo|FM2_ReadFilterData'
    rb'|SystemClockImpl_GetTime|wg_transform_(?:read|push)_|wg_parser_(?:get_next_read_offset|push_data'
    rb'|stream_get_buffer|stream_copy_buffer|stream_release_buffer)|FileAsyncReader_|sync_read|filter_EnumPins'
    rb'|filter_inner_QueryInterface|Inner_QueryInterface|DllGetClassObject|DSCF_CreateInstance'
    rb'|filter_mapper_create|AMFilterData_|FilterMapper3_EnumMatchingFilters Considering)')


def archive_log(path, limit=WINE_LOG_LIMIT):
    from log_retention import rotate
    rotate(path, limit)


MEDIA_ADDON = Path('/etc/x3-media-addon.json')   # written by the app after it unpacks the add-on
GST_ROOT = '/usr/lib/aarch64-linux-gnu'


def dll_overrides(media_addon=False, controller_passthrough=False):
    """WINEDLLOVERRIDES for every Wine process of the session (prefix setup included).

    winegstreamer: X3 plays music, comms voices and movies through DirectShow, which in Wine 10
    decodes through winegstreamer. Without the media add-on there is no GStreamer, so its Unix side
    cannot load and it stays off. With the add-on Box64 maps it onto native arm64 GStreamer.
    ir50_32: Wine's Indeo 5 codec delay-loads winegstreamer_create_video_decoder when opened and
    Wine aborts the process if that fails; X3's DirectShow set-up opens every codec (first device
    run). It stays off either way: decoding Indeo needs gst-libav, which the add-on leaves out.
    winebus.sys: Wine finds the Thor's built-in pad (SDL2/udev) and X3 AP reads it through XInput
    on top of the app's key and mouse mappings: doubled actions, and the ship turning and
    accelerating on its own (fourth device run). Off unless the launcher asks for passthrough.
    """
    disabled = ['winemenubuilder', 'mscoree', 'mshtml', 'ir50_32']
    if not media_addon: disabled.append('winegstreamer')
    if not controller_passthrough: disabled.append('winebus.sys')
    return ','.join(disabled) + '='


def media_addon(path=MEDIA_ADDON):
    """The installed add-on's manifest, or None."""
    try:
        manifest = json.loads(path.read_text()) if path.is_file() and path.stat().st_size < 65536 else None
    except (OSError, ValueError):
        return None
    return manifest if isinstance(manifest, dict) and manifest.get('format') == 1 else None


def gstreamer_environment(prefix=PREFIX, diagnostic=False):
    """Native arm64 GStreamer as winegstreamer.so (x86-64, under Box64) sees it."""
    return {'GST_PLUGIN_SYSTEM_PATH_1_0': GST_ROOT + '/gstreamer-1.0',
            'GST_PLUGIN_SCANNER_1_0': GST_ROOT + '/gstreamer1.0/gstreamer-1.0/gst-plugin-scanner',
            'GST_REGISTRY_1_0': str(prefix / 'x3-cache' / 'gstreamer-registry.aarch64.bin'),
            'GST_DEBUG': '2' if diagnostic else '1', 'GST_DEBUG_NO_COLOR': '1'}
# Box64 dynarec settings for the game's process ([X3AP.exe] section of the session rc file; an rc
# section overrides the environment). The CPU-bound part of a load is X3's own code.
# Seventh Thor run (0.1.7): Box64's own "fast" profile (SAFEFLAGS=0 and DIRTY=1 on top of the
# settings below) hung X3 right after it created its D3D9 device. The main thread spun at 100 %
# user time with no system call, page fault or frame for two minutes. "fast" here keeps
# balanced's flag handling and code-change detection and only builds bigger blocks (BIGBLOCK=3 is
# the level that reaches PE code) with direct call/return. It stays an experiment until a Thor
# run confirms it.
CPU_PROFILES = {
    'balanced': {'BOX64_DYNAREC_BIGBLOCK': '2', 'BOX64_DYNAREC_SAFEFLAGS': '1', 'BOX64_DYNAREC_STRONGMEM': '1'},
    'fast': {'BOX64_DYNAREC_BIGBLOCK': '3', 'BOX64_DYNAREC_CALLRET': '1', 'BOX64_DYNAREC_FORWARD': '1024',
             'BOX64_DYNAREC_SAFEFLAGS': '1', 'BOX64_DYNAREC_STRONGMEM': '1'},
    'fastest': {'BOX64_DYNAREC_BIGBLOCK': '3', 'BOX64_DYNAREC_CALLRET': '1', 'BOX64_DYNAREC_FORWARD': '1024',
                'BOX64_DYNAREC_SAFEFLAGS': '1', 'BOX64_DYNAREC_STRONGMEM': '0'},
    'accurate': {'BOX64_DYNAREC_BIGBLOCK': '2', 'BOX64_DYNAREC_SAFEFLAGS': '1', 'BOX64_DYNAREC_STRONGMEM': '1'},
}
DEFAULT_CPU_PROFILE = 'fast'     # tenth Thor run: loads 146 s against 183 s, 32 fps against 24
PRESENT_PAUSE = 5.0        # seconds without a Vulkan present that count as a loading pause
SPIN_SAMPLES = 6           # 10 s samples of a busy game main thread with no kernel work: stuck


def box64_rc(game, profile=DEFAULT_CPU_PROFILE, extra=None):
    """Box64 rc text: real CPU count for Wine, the chosen profile for the game's process."""
    game = re.sub(r'[^A-Za-z0-9._-]', '', game) or 'X3AP.exe'
    settings = ''.join(f'{key}={value}\n' for key, value in {**CPU_PROFILES[profile], **(extra or {})}.items())
    return ('[wine]\nBOX64_MAXCPU=0\n[wine64]\nBOX64_MAXCPU=0\n'
            '[explorer.exe]\nBOX64_DYNAREC_BIGBLOCK=0\n'
            f'[{game}]\n{settings}')


class SpinWatch:
    """Notice a game main thread that only burns user time: no system time, no page faults.

    A real load reads files and grows its heap, so both move. In the 0.1.7 hang neither moved
    for 120 s while the thread used a full core.
    """
    def __init__(self, samples=SPIN_SAMPLES):
        self.samples, self.last, self.count = samples, None, 0

    def observe(self, thread, seconds):
        """thread: the main-thread entry of one sample. True once it has spun long enough."""
        now = (thread.get('user_ticks'), thread.get('system_ticks'), thread.get('minor_faults'))
        if None in now: return False
        if self.last and seconds > 0:
            busy = (now[0] - self.last[0]) / 100 / seconds >= 0.9
            self.count = self.count + 1 if busy and now[1:] == self.last[1:] else 0
        self.last = now
        return self.count >= self.samples


# Native arm64 numbers: Box64 makes the game's system calls itself. Only the ones a load or a
# frame plausibly spends time in; others are reported by number.
ARM64_SYSCALLS = {
    17: 'getcwd', 22: 'epoll_pwait', 23: 'dup', 25: 'fcntl', 29: 'ioctl', 35: 'unlinkat',
    43: 'statfs', 44: 'fstatfs', 48: 'faccessat', 56: 'openat', 57: 'close', 61: 'getdents64',
    62: 'lseek', 63: 'read', 64: 'write', 65: 'readv', 66: 'writev', 67: 'pread64', 68: 'pwrite64',
    73: 'ppoll', 78: 'readlinkat', 79: 'newfstatat', 80: 'fstat', 98: 'futex', 101: 'nanosleep',
    113: 'clock_gettime', 124: 'sched_yield', 129: 'kill', 131: 'tgkill', 134: 'rt_sigaction',
    135: 'rt_sigprocmask', 139: 'rt_sigreturn', 172: 'getpid', 178: 'gettid', 203: 'connect',
    207: 'recvfrom', 211: 'sendmsg', 212: 'recvmsg', 215: 'munmap', 222: 'mmap', 226: 'mprotect',
    233: 'madvise', 260: 'wait4', 278: 'getrandom', 291: 'statx', 439: 'faccessat2'}
THREAD_STATES = {'R': 'running', 'S': 'sleeping', 'D': 'disk', 't': 'traced', 'T': 'stopped'}


def dynacache_summary(folder=None):
    """X3 addition: Box64 0.4.4 caches translated code on disk by default ($HOME/.cache/box64), per
    binary and per dynarec settings, so a second load with the same CPU profile can skip
    translating. Whether X3's code lands there under WoW64 is not documented: count it."""
    folder = Path(folder or os.path.join(os.environ.get('XDG_CACHE_HOME') or os.path.join(os.environ.get('HOME', '/root'), '.cache'), 'box64'))
    found = {'folder': str(folder), 'files': 0, 'bytes': 0}
    try:
        entries = []
        for entry in os.scandir(folder):
            if entry.is_file(follow_symlinks=False):
                size = entry.stat(follow_symlinks=False).st_size
                found['files'] += 1; found['bytes'] += size
                entries.append((size, entry.name))
        found['largest'] = [{'name': name[-96:], 'bytes': size} for size, name in sorted(entries, reverse=True)[:8]]
    except FileNotFoundError: found['missing'] = True
    except OSError as error: found['error'] = error.strerror
    return found


def android_cpuset(proc=Path('/proc'), dev=Path('/dev/cpuset')):
    """X3 addition: which Android cpuset this launch runs in, and its CPUs when readable."""
    found = {}
    try:
        for line in (proc/'self'/'cgroup').read_text()[:4096].splitlines():
            parts = line.split(':', 2)
            if len(parts) == 3 and 'cpuset' in parts[1].split(','): found['group'] = parts[2]
    except OSError as error: found['error'] = error.strerror
    if 'group' in found:
        try: found['cpus'] = (dev / found['group'].lstrip('/') / 'cpus').read_text()[:64].strip()
        except OSError as error: found['cpus_error'] = error.strerror
    return found


class MainThreadProfile:
    """X3 addition: what the game's main thread is doing, 20 times a second, loading and playing apart.

    The 10 s thread samples showed the main thread 10-23 % in the kernel during the tenth Thor
    run's 146 s loads, sometimes stopped by PRoot (state t, wchan ptrace_stop). This says how much
    of a load goes to PRoot ('traced'), to waiting on wineserver ('sleeping' in read) and to the
    game's own work ('running'), and which system calls are behind each.

    0.1.13: 'below_cap' repeats the playing samples taken while Wine reported fewer frames than
    the frame cap, so time spent waiting at the cap does not hide what slows the rest.
    """
    def __init__(self, proc=Path('/proc')):
        self.proc, self.pid = proc, None
        self.lock = threading.Lock()
        self.states = {'loading': {}, 'playing': {}, 'below_cap': {}}
        self.calls = {'loading': {}, 'playing': {}, 'below_cap': {}}

    def sample(self, *phases):
        if self.pid is None: return
        task = self.proc / str(self.pid) / 'task' / str(self.pid)
        try:
            stat = (task / 'stat').read_text()
            state = THREAD_STATES.get(stat[stat.rindex(')') + 2], 'other')
        except (OSError, ValueError, IndexError): return
        try: call = (task / 'syscall').read_text().split(maxsplit=1)[0]
        except (OSError, IndexError): call = ''
        with self.lock:
            for phase in phases:
                states = self.states[phase]
                states[state] = states.get(state, 0) + 1
                if call.isdecimal():
                    key = state + ':' + ARM64_SYSCALLS.get(int(call), call)
                    self.calls[phase][key] = self.calls[phase].get(key, 0) + 1

    def report(self):
        """Shares of samples per phase: states, then the eight commonest state:syscall pairs."""
        out = {}
        with self.lock:
            for phase, states in self.states.items():
                total = sum(states.values())
                if not total: continue
                calls = sorted(self.calls[phase].items(), key=lambda item: -item[1])[:8]
                out[phase] = {'samples': total,
                              **{state: round(count / total, 3) for state, count in sorted(states.items(), key=lambda item: -item[1])},
                              'syscalls': {key: round(count / total, 3) for key, count in calls}}
        return out


def read_number(path, scale=1.0):
    """First number in a sysfs file (kgsl's '37 %' included), or None when it cannot be read."""
    try: match = re.match(r'\s*(\d+)', path.read_text())
    except OSError: return None
    return int(match[1]) * scale if match else None


class ClockProfile:
    """X3 addition: CPU and GPU clocks once a second while playing, at the frame cap and below it.

    The twelfth Thor run held 60 fps most of the time but fell to 42-48 with the main thread busy
    85-94 %. This tells a slow core (clocked down: thermal limit or power mode) from a busy one, and
    a GPU at its limit from an idle one. Android may hide kgsl's files from apps; then the GPU
    fields stay empty and 'gpu_readable' says so.
    """
    KGSL = Path('/sys/class/kgsl/kgsl-3d0')

    def __init__(self, cpu, cpus=Path('/sys/devices/system/cpu'), kgsl=None):
        self.cpu = cpus / ('cpu%d' % cpu) / 'cpufreq' if cpu is not None else None
        self.kgsl = kgsl or self.KGSL
        self.lock = threading.Lock()
        self.bands = {}
        self.gpu_readable = None
        self.cpu_max = read_number(self.cpu / 'cpuinfo_max_freq') if self.cpu else None

    def sample(self, band):
        values = {}
        if self.cpu:
            values['cpu_mhz'] = read_number(self.cpu / 'scaling_cur_freq', 1e-3)
            values['cpu_limit_mhz'] = read_number(self.cpu / 'scaling_max_freq', 1e-3)
        values['gpu_busy_percent'] = read_number(self.kgsl / 'gpu_busy_percentage')
        values['gpu_mhz'] = read_number(self.kgsl / 'devfreq' / 'cur_freq', 1e-6) or read_number(self.kgsl / 'gpuclk', 1e-6)
        if not self.gpu_readable: self.gpu_readable = values['gpu_busy_percent'] is not None
        with self.lock:
            totals = self.bands.setdefault(band, {'samples': 0})
            totals['samples'] += 1
            for key, value in values.items():
                if value is None: continue
                entry = totals.setdefault(key, [0, 0.0, value, value])   # count, sum, min, max
                entry[0] += 1; entry[1] += value; entry[2] = min(entry[2], value); entry[3] = max(entry[3], value)

    def report(self):
        out = {'cpu': self.cpu.parent.name if self.cpu else None,
               'cpu_max_mhz': round(self.cpu_max / 1000) if self.cpu_max else None, 'gpu_readable': self.gpu_readable}
        with self.lock:
            for band, totals in self.bands.items():
                out[band] = {'samples': totals['samples'],
                             **{key: {'mean': round(v[1] / v[0]), 'min': round(v[2]), 'max': round(v[3])}
                                for key, v in totals.items() if key != 'samples'}}
        return out


GAME_START_GRACE = 150     # seconds after launch before a missing game process is reported
GAME_EXIT_SAMPLES = 2      # consecutive 10 s samples without the game after it was running
WINE_PROCESS = re.compile(r'(?:^wineserver$|\.exe$)', re.I)


def dxvk_configuration(request):
    """DXVK_CONFIG for X3. Without vsync, DXVK presents IMMEDIATE and the frame cap paces the game.

    Third Thor run (0.1.3): X3 requests vsync, so DXVK 2.5.3 switches to FIFO. In FIFO it waits for
    every frame with vkWaitForPresentKHR(..., UINT64_MAX), and on this path (Wine X11 surface ->
    Mesa sw WSI -> Xtigervnc) that wait never returns. After the first frames the game blocks for
    good: a black screen with every X3 and DXVK thread asleep. DXVK skips that wait for IMMEDIATE.
    TRASC's vulkan-probe passed because it never waits for a present.
    """
    options = [] if request.get('vsync', False) else ['d3d9.presentInterval = 0']
    # Nothing above the frame bridge rate is seen. DXVK 3 reads dxvk.maxFrameRate first and
    # falls back to d3d9.maxFrameRate; 2.5.3 only knows the d3d9 one.
    key = 'd3d9' if request.get('dxvk_version', client_vulkan.DEFAULT_DXVK) == '2.5.3' else 'dxvk'
    options.append('%s.maxFrameRate = %d' % (key, request.get('display_fps', 60)))
    return '; '.join(options)


def fatal_launch_error(log, game=False):
    missing = re.search(r'^wine: Call from \S+ to unimplemented function ([\w.]+?)\.(\w+), aborting', log, re.M)
    if missing:
        module, function = missing[1], missing[2]
        disabled = re.search(r'DelayLoadFailureHook failed to delay load ' + re.escape(module), log, re.I)
        return (f'The program stopped: it called {module} {function}, which this Wine runtime does not provide'
                + (' (the DLL is disabled or could not load)' if disabled else '') + '. Export Logs and attach x3-wine.log.')
    if game:
        # Any kind Wine reports: page fault, exception, illegal/privileged instruction, stack overflow...
        crash = re.search(r'^wine: Unhandled ((?:page fault|exception|[a-z]+ instruction|stack overflow|division by zero|[a-z]+))\b'
                          r'([^\r\n]{0,240})starting debugger', log, re.I | re.M)
        if crash:
            address = re.search(r'\bat address ((?:0x)?[0-9a-f]{1,16})\b', crash[2], re.I)
            location = ' at ' + (address[1] if address[1].lower().startswith('0x') else '0x' + address[1]) if address else ''
            detail = ''
            # Box64 names the x86 instruction it could not translate just before Wine reports it.
            opcode = re.findall(r'Unimplemented (?:32bits )?Opcode \([0-9A-F ]+\) ((?:[0-9A-F]{2} ){1,6})', log)
            if opcode and crash[1].lower() == 'illegal instruction':
                detail = ': Box64 cannot run the x86 instruction ' + opcode[-1].strip()
            return ('The game crashed (unhandled ' + crash[1].lower() + location + detail + '). '
                    'Export Logs and check x3-wine.log.')
    pipeline = re.search(r'err:msvcrt:_wassert \(L"!status && \\?"(vk\w+)\\?""', log)
    if pipeline:
        return ('The Vulkan driver crashed in ' + pipeline[1] + ' (DXVK ' + (re.findall(r'DXVK: v(\d+\.\d+(?:\.\d+)?)', log) or ['?'])[-1]
                + '). Choose DXVK 2.5.3 and launch again; export Logs to report it.')
    dxvk = re.search(r"Device does not support required feature '(\w+)'|DXVK: No adapters found", log)
    if dxvk:
        return ('DXVK could not use the Vulkan driver' + (' (it lacks ' + dxvk[1] + ')' if dxvk[1] else '')
                + '. Choose DXVK 2.5.3, or Turnip 26.0.0, and launch again.')
    match = re.search(r'wine: could not load kernel32\.dll, status ([0-9a-f]+)', log, re.I)
    if match:
        return 'Wine could not start its Windows loader (kernel32.dll, ' + match[1] + '). Reinstall the runtime and export Logs.'
    if re.search(r'err:module:\w+ (?:Importing|Initializing).*failed, status', log):
        missing = re.findall(r'err:module:import_dll Library ([^\r\n]+)', log)
        if missing:
            return 'A required Windows library could not load: ' + missing[-1][:350] + '. Export Logs for details.'
        return 'Windows program initialization failed. Export Logs (x3-wine.log) for the failing module.'
    return None


def clock_hint(report):
    """A line for the status when the prime core runs held below its top clock.

    Fourteenth Thor run: CPU 7 was limited to 2477 of its 3187 MHz for the whole run, the kind of
    cap a power mode sets. AYN's handhelds have Standard, Performance and High Performance modes
    in their quick settings."""
    top = report.get('cpu_max_mhz')
    limits = [band['cpu_limit_mhz']['max'] for name, band in report.items()
              if isinstance(band, dict) and 'cpu_limit_mhz' in band]
    if not top or not limits or max(limits) >= 0.92 * top: return None
    return ('%s is held at %d of its %d MHz (power mode or heat). On the Thor, High Performance mode '
            'in the quick settings lifts it.' % (report.get('cpu') or 'The fastest core', max(limits), top))


def frame_band(wine_log, cap, now=None):
    """'at_cap' or 'below_cap' from Wine's latest fps report (every 1.5 s while presenting), else 'unknown'."""
    with wine_log.lock: present = dict(wine_log.fields.get('wine_present') or {})
    if not present or (now or time.time()) - present.get('sampled_at', 0) >= 4: return 'unknown'
    return 'below_cap' if present['per_second'] < cap - 3 else 'at_cap'


class WineLog:
    """Drain Wine's output on a thread; parse before rotating so early evidence survives."""
    def __init__(self, path, limit=WINE_LOG_LIMIT, game=False, drop=None):
        self.path, self.limit, self.game, self.drop = path, limit, game, drop
        self.unwritten = b''
        self.lock = threading.Lock()
        self.fields = {'wine_log_bytes': 0, 'wine_log_rotations': 0, 'dsound_errors': 0}
        self.error = None
        self.pending = b''
        self.trace = ''
        self.fps_streams = set()
        self.last_present = None
        self.last_present_seen = None   # time.monotonic() when the last present line arrived

    def observe(self, chunk):
        self.pending += chunk
        end = self.pending.rfind(b'\n') + 1
        text = self.pending[:end].decode(errors='replace')
        self.pending = self.pending[end:][-128*1024:]
        self.trace = (self.trace + text)[-128*1024:]
        with self.lock:
            for line in text.splitlines():
                if re.search(r'Loaded L".*\\+d3d9\.dll".*: native\s*$', line, re.I):
                    self.fields['native_d3d9_loaded'] = True
                loaded = re.search(r'DXVK: v?(\d+\.\d+(?:\.\d+)?)\b', line)
                if loaded: self.fields['dxvk_loaded'] = loaded[1]
                binding = re.search(r'Binding model: ([\w ]{1,40})', line)
                if binding: self.fields['dxvk_binding_model'] = binding[1].strip()
                pin = X3PIN_SUMMARY.search(line)
                if pin: self.fields['crypto_pin'] = f'{pin[1]}/{pin[2]} ({pin[3]})'
                mode = re.search(r'Present mode: (VK_PRESENT_MODE_\w+)', line)
                if mode: self.fields['dxvk_present_mode'] = mode[1]
                if re.search(r'Loaded L".*\\+dsound\.dll".*: (builtin|native)\s*$', line, re.I):
                    self.fields['dsound_loaded'] = re.search(r': (builtin|native)\s*$', line)[1]
                if re.search(r':(err|warn):dsound', line): self.fields['dsound_errors'] += 1
                fps = re.search(r':([0-9a-f]+):[0-9a-f]+:trace:fps:\w+ ((?:0x)?[0-9a-f]+) @ approx ([0-9]+\.[0-9]+)fps', line, re.I)
                stamp = re.match(r'(\d+\.\d+):', line) if fps else None
                if stamp:
                    # Wine prints this at the first present 1.5 s after its last print, so the
                    # distance between two prints is a pause in presenting: a loading screen.
                    now = float(stamp[1])
                    if self.last_present is not None and now - self.last_present >= PRESENT_PAUSE:
                        pauses = self.fields.setdefault('present_pauses_seconds', [])
                        pauses.append(round(now - self.last_present, 1))
                        del pauses[:-12]
                        self.fields['longest_present_pause_seconds'] = max(pauses + [self.fields.get('longest_present_pause_seconds', 0)])
                    self.last_present = now
                    self.last_present_seen = time.monotonic()
                if fps:
                    stream = fps[1].lower() + ':' + fps[2].lower()
                    if stream in self.fps_streams and 0 <= float(fps[3]) <= 10000:
                        self.fields['wine_present'] = {'per_second': float(fps[3]), 'sampled_at': time.time()}
                    if len(self.fps_streams) < 64: self.fps_streams.add(stream)
            self.fields['wine_log_bytes'] += len(chunk)
            self.error = self.error or fatal_launch_error(self.trace, game=self.game)

    def snapshot(self):
        with self.lock: return dict(self.fields), self.error

    def kept(self, chunk, final=False):
        """What of chunk goes to the file: everything, or whole lines not matching self.drop."""
        if not self.drop: return chunk
        data = self.unwritten + chunk
        end = len(data) if final else data.rfind(b'\n') + 1
        self.unwritten = data[end:][-128*1024:]
        lines = data[:end].splitlines(keepends=True)
        kept = [line for line in lines if not self.drop.search(line)]
        with self.lock: self.fields['wine_log_dropped_lines'] = self.fields.get('wine_log_dropped_lines', 0) + len(lines) - len(kept)
        return b''.join(kept)

    def pump(self, stream):
        output = None
        try:
            output = self.path.open('wb'); written = 0
            while chunk := stream.read1(min(64*1024, self.limit)):
                self.observe(chunk)
                chunk = self.kept(chunk)
                if written + len(chunk) > self.limit:
                    output.close()
                    with self.lock: first = self.fields['wine_log_rotations'] == 0
                    # The first segment holds start-up (DLL loads, stream set-up): keep it.
                    os.replace(self.path, self.path.with_suffix('.start.log' if first else '.overflow.log'))
                    output = self.path.open('wb'); written = 0
                    with self.lock: self.fields['wine_log_rotations'] += 1
                output.write(chunk); output.flush(); written += len(chunk)
            if self.pending:
                self.observe(b'\n')
                with self.lock: self.fields['wine_log_bytes'] -= 1
            if self.unwritten: output.write(self.kept(b'', final=True))
        except OSError as error:
            with self.lock: self.error = 'Could not capture Wine output: ' + str(error)
        finally:
            if output: output.close()
            stream.close()


class StopRequested(Exception):
    pass


# The GStreamer splitter's entry under the DirectShow filter category, in the 32-bit registry view.
GSTREAMER_SPLITTER_KEY = (r'wow6432node\\clsid\\{083863f1-70de-11d0-bd40-00a0c911ce86}'
                          r'\\instance\\{f9d8d64e-a144-47dc-8ee0-f53498372c29}')


def gstreamer_filters_registered(prefix=PREFIX):
    """Whether winegstreamer's DllRegisterServer() has run for 32-bit programs in this prefix.

    Eighth Thor run (0.1.8): the prefix was made before the media add-on existed, with winegstreamer
    disabled. wineboot still wrote its COM classes and its catch-all media type (they come from
    resources), but not its filter entries, which DllRegisterServer() writes through the filter
    mapper. So DirectShow knew no GStreamer splitter: ASF speech and the 48 kHz menu track could
    not be rendered, while MPEG files still played through the MPEG-1 splitter.
    """
    try: text = (prefix / 'system.reg').read_text(errors='replace').lower()
    except OSError: return False
    return GSTREAMER_SPLITTER_KEY in text


def prefix_diagnostics(prefix=PREFIX, wine=Path('/opt/wine')):
    report = {'files': {}, 'runtime_ready': True, 'prefix_ready': True}
    for scope, parent in (('runtime', wine / 'lib/wine/i386-windows'), ('prefix', prefix / 'drive_c/windows/syswow64')):
        for name in ('ntdll.dll', 'kernel32.dll', 'kernelbase.dll', 'cmd.exe'):
            path = parent / name
            entry = {'present': path.is_file()}
            if path.is_file():
                try: entry['machine'] = pe_info.inspect(path)['machine']
                except (OSError, ValueError) as error: entry['error'] = str(error)
            report['files'][scope + '/' + name] = entry
            report[scope + '_ready'] &= entry.get('machine') == 'i386'
    return report


def persist_documents(prefix=PREFIX, saves=SAVES):
    """Point each Wine user's Documents\\Egosoft at /saves/Egosoft and return what was done.

    X3 keeps saves and settings in Documents\\Egosoft\\X3AP. Wine may link Documents to
    $HOME/Documents, which is inside the replaceable runtime image, and "Reset Wine prefix" moves the
    whole prefix aside. Linking only the Egosoft entry to app storage keeps saves through both.
    An existing real Egosoft folder is moved, never deleted: into /saves/Egosoft when that is empty,
    otherwise beside it as Egosoft-from-<user>-<time>.
    """
    target = saves / 'Egosoft'
    target.mkdir(parents=True, exist_ok=True)
    report = {'target': str(target), 'users': [], 'migrated': []}
    users = prefix / 'drive_c' / 'users'
    if not users.is_dir():
        return report
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for user in sorted(users.iterdir()):
        if user.name.lower() == 'public' or user.is_symlink() or not user.is_dir():
            continue
        documents = user / 'Documents'
        if documents.is_symlink() and not documents.exists():
            documents.resolve().mkdir(parents=True, exist_ok=True)   # dangling link into $HOME
        elif not documents.exists():
            documents.mkdir()
        entry = documents / 'Egosoft'
        if entry.is_symlink():
            if os.readlink(entry) == str(target):
                report['users'].append(user.name)
                continue
            entry.unlink()
        elif entry.is_dir():
            if any(target.iterdir()):
                destination = saves / f'Egosoft-from-{user.name}-{stamp}'
                shutil.move(str(entry), str(destination))
            else:
                destination = target
                for child in list(entry.iterdir()):
                    shutil.move(str(child), str(target / child.name))
                entry.rmdir()
            report['migrated'].append({'user': user.name, 'to': str(destination)})
        elif entry.exists():
            entry.rename(entry.with_name(f'Egosoft.moved-{stamp}'))
        entry.symlink_to(target)
        report['users'].append(user.name)
    return report


ASF_HEADER = bytes.fromhex('3026b2758e66cf11a6d900aa0062ce6c')
ASF_STREAM_PROPERTIES = bytes.fromhex('9107dcb7b7a9cf118ee600c00c205365')
ASF_AUDIO = bytes.fromhex('409e69f84d5bcf11a8fd00805f5c442b')
AUDIO_TAGS = {0x0001: 'pcm', 0x0002: 'adpcm', 0x0011: 'ima-adpcm', 0x000a: 'wma-voice (WMSP)', 0x0050: 'mpeg-audio',
              0x0055: 'mp3', 0x0160: 'wma1', 0x0161: 'wma2', 0x0162: 'wma-pro', 0x0163: 'wma-lossless'}


def sniff_media(head):
    """Container and audio codec of a file from its first bytes (no decoding)."""
    if head[:4] == b'RIFF' and head[8:12] == b'WAVE':
        at = head.find(b'fmt ', 12)
        tag = struct.unpack_from('<H', head, at + 8)[0] if 0 <= at <= len(head) - 10 else None
        return 'wav/' + AUDIO_TAGS.get(tag, hex(tag) if tag is not None else '?')
    if head[:16] == ASF_HEADER:
        codecs, at = [], 30
        while at + 24 <= len(head):
            guid, size = head[at:at + 16], struct.unpack_from('<Q', head, at + 16)[0]
            if size < 24: break
            if guid == ASF_STREAM_PROPERTIES and head[at + 24:at + 40] == ASF_AUDIO and at + 80 <= len(head):
                codecs.append(AUDIO_TAGS.get(struct.unpack_from('<H', head, at + 78)[0], '?'))
            at += size
        return 'asf/' + ('+'.join(sorted(set(codecs))) if codecs else '?')
    if head[:3] == b'ID3' or (len(head) > 1 and head[0] == 0xff and head[1] & 0xe0 == 0xe0):
        return 'mpeg-audio'
    if head[:4] == b'OggS': return 'ogg'
    if head[:4] == b'\x00\x00\x01\xba': return 'mpeg-ps' + ('2' if len(head) > 4 and head[4] & 0xc0 == 0x40 else '1')
    if head[:4] == b'\x00\x00\x01\xb3': return 'mpeg-video-es'
    if head[:2] == b'\x1f\x8b': return 'gzip'
    return 'other'


def media_survey(game=GAME, sniff_per_folder=60):
    """What X3's music, speech and movie folders hold: counts per extension and container/codec."""
    survey = {}
    for top in [game, *(child for child in game.iterdir() if child.name.lower() == 'addon' and child.is_dir())] if game.is_dir() else []:
        for folder in (child for child in top.iterdir() if child.is_dir() and child.name.lower() in ('soundtrack', 'mov', 's')):
            kinds, sniffed = {}, 0
            for entry in sorted(folder.iterdir()):
                if not entry.is_file() or entry.is_symlink(): continue
                kind = entry.suffix.lower() or '(none)'
                if sniffed < sniff_per_folder and entry.suffix.lower() in ('.mp3', '.dat', '.wav', '.wma', '.ogg', '.mpg', ''):
                    try:
                        with entry.open('rb') as handle: kind += ':' + sniff_media(handle.read(65536))
                        sniffed += 1
                    except OSError: kind += ':unreadable'
                kinds[kind] = kinds.get(kind, 0) + 1
            survey[str(folder.relative_to(game))] = kinds
    return survey


def program_path(relative, game=GAME):
    """Resolve a program inside the imported game folder; reject anything that could escape it."""
    if not isinstance(relative, str) or not relative or '\\' in relative or '\0' in relative or len(relative) > 512:
        raise ValueError('Invalid program path')
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in ('', '.', '..') for part in pure.parts):
        raise ValueError('Program must be inside the game folder')
    if pure.suffix.lower() not in PROGRAM_SUFFIXES:
        raise ValueError('Choose a .exe, .bat or .cmd program')
    path = game.joinpath(*pure.parts)
    current = game
    for part in pure.parts:
        current = current / part
        if current.is_symlink(): raise ValueError('Program path cannot contain links')
    if not path.is_file(): raise ValueError('Program not found in the imported game folder: ' + relative)
    return path


def validate_request(request, game=GAME):
    if request.get('mode') not in ('game', 'program'): raise ValueError('Choose game or program mode')
    if request.get('resolution') not in RESOLUTIONS: raise ValueError('Unsupported resolution')
    if request.get('renderer', 'turnip') not in ('turnip', 'software'): raise ValueError('Unsupported graphics option')
    client_vulkan.driver_file(request.get('turnip_driver', client_vulkan.DEFAULT_DRIVER))
    client_vulkan.dxvk_files(request.get('dxvk_version', client_vulkan.DEFAULT_DXVK))
    if request.get('cpu_profile', DEFAULT_CPU_PROFILE) not in CPU_PROFILES: raise ValueError('Unsupported CPU profile')
    if request.get('cpu_affinity', 'prime') not in ('prime', 'available', 'game'): raise ValueError('Unsupported CPU affinity')
    if request.get('runtime_mode', 'auto') not in ('auto', 'compatibility'): raise ValueError('Unsupported runtime mode')
    client_presentation.options(request)
    for key in ('audio', 'dxvk_hud', 'diagnostic_logging', 'sound_diagnostics', 'vsync', 'controller_passthrough'):
        if not isinstance(request.get(key, False), bool): raise ValueError('Invalid option: ' + key)
    arguments = request.get('arguments', [])
    if (not isinstance(arguments, list) or len(arguments) > 32
            or any(not isinstance(a, str) or len(a) > 512 or '\0' in a for a in arguments)):
        raise ValueError('Invalid program arguments')
    path = program_path(request.get('program', ''), game)
    info = {'program': request['program'], 'kind': path.suffix.lower()[1:]}
    if info['kind'] == 'exe':
        try: details = pe_info.inspect(path)
        except (OSError, ValueError) as error: raise ValueError('Not a valid Windows program: ' + str(error))
        if details['machine'] not in ('i386', 'x86_64'): raise ValueError('Unsupported Windows program architecture: ' + details['machine'])
        info.update(machine=details['machine'], large_address_aware=details['large_address_aware'],
                    steam_api=details['steam_api'], gui=details['gui'], imports=details['imports'][:64])
    return info


def windows_path(relative):
    return 'D:\\' + relative.replace('/', '\\')


X3PIN = HERE / 'x3pin.exe'      # native/x3pin: keeps the CryptoAPI DLLs loaded in the game
X3PIN_WINDOWS = 'Z:' + str(X3PIN).replace('/', '\\')
X3PIN_LOG = SESSION / 'x3pin.log'   # x3pin's report (its console stderr is not ours to read)
X3PIN_SUMMARY = re.compile(r'x3pin: (\d+) of (\d+) DLLs pinned \(([^)]{0,40})\)')


def build_command(request, info, pin=None):
    """Wine command line and Unix working directory (the program's own folder becomes its cwd).

    X3AP.exe starts through x3pin.exe when it is bundled: 1,467 CryptoAPI open/close cycles made a
    LxXRM new game take 208 s to load on the Thor, each cycle reloading rsaenh/crypt32/bcrypt and
    their emulated Unix libraries. x3pin holds one reference to each for the life of the game.
    """
    relative = request['program']
    desktop = ['explorer', '/desktop=X3,' + request['resolution']]
    if pin is None: pin = X3PIN.is_file()
    if info['kind'] == 'exe':
        program = [windows_path(relative)]
        if pin and request.get('mode') == 'game': program = [X3PIN_WINDOWS] + program
    else:
        # Batch installers (e.g. LxXRM's SETUP.bat) need a console; /k keeps it open for reading.
        program = ['cmd.exe', '/k', windows_path(relative)]
    cwd = GAME.joinpath(*PurePosixPath(relative).parent.parts) if '/' in relative else GAME
    return [BOX64, WINE] + desktop + program + list(request.get('arguments', [])), cwd


class Supervisor:
    def __init__(self, request):
        self.request = request
        self.children = []
        self.wine_log = None
        self.log_thread = None
        self.last_thread_sample = 0
        self.spin = SpinWatch()
        self.profile = MainThreadProfile()
        self.launch_token = secrets.token_hex(16)
        self.started_monotonic = time.monotonic()
        self.game_name = PurePosixPath(request.get('program', 'X3AP.exe')).name
        self.status = {'phase': 'starting', 'mode': request.get('mode'), 'program': request.get('program'),
                       'resolution': request.get('resolution'), 'display_target_fps': request.get('display_fps', 60),
                       'renderer': 'Checking graphics driver', 'graphics_backend': request.get('renderer', 'turnip'),
                       'started_at': time.time(), 'timings_seconds': {},
                       'cpu_profile': request.get('cpu_profile', DEFAULT_CPU_PROFILE),
                       'runtime_acceleration': request.get('runtime_acceleration', 'unspecified')}
        self.env = dict(os.environ, DISPLAY=':7', XAUTHORITY=str(SESSION / 'Xauthority'),
                        WINEPREFIX=str(PREFIX), WINEARCH='win64', WINEDEBUG=wine_debug(),
                        WINEDLLOVERRIDES=dll_overrides(media_addon() is not None, request.get('controller_passthrough', False)),
                        BOX64_DYNAREC_STRONGMEM='1', BOX64_DYNAREC_BIGBLOCK='2', BOX64_DYNAREC_SAFEFLAGS='1',
                        BOX64_MAXCPU='0', BOX64_RCFILE=str(SESSION / 'box64.rc'),
                        BOX64_LOG='1', BOX64_NOBANNER='0', BOX64_PATH='/opt/wine/bin',
                        BOX64_LD_LIBRARY_PATH='/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/opt/wine/lib/wine/x86_64-unix',
                        LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe', LP_NUM_THREADS='4',
                        WINE_D3D_CONFIG='csmt=1', X3PIN_LOG='Z:' + str(X3PIN_LOG).replace('/', '\\'),
                        **{LAUNCH_ENV: self.launch_token})
        self.status['controller_passthrough'] = request.get('controller_passthrough', False)
        addon = media_addon()
        self.status['media_addon'] = {k: addon.get(k) for k in ('version', 'sha256')} if addon else None
        if addon:
            self.env.update(gstreamer_environment(diagnostic=request.get('diagnostic_logging', False)))
        if (HERE / 'wineserver-patch.json').is_file():
            # Wine 10 prefers its adjacent binary; the app binds the verified helper over it.
            self.env['WINESERVER'] = '/opt/wine/bin/wineserver'
        if request.get('cpu_profile') == 'accurate':
            self.env.update(BOX64_DYNAREC_X87DOUBLE='1', BOX64_DYNAREC_FASTNAN='0',
                            BOX64_DYNAREC_FASTROUND='0', BOX64_SYNC_ROUNDING='1')
        if request.get('renderer', 'turnip') == 'turnip':
            version = request.get('turnip_driver', client_vulkan.DEFAULT_DRIVER)
            self.status['turnip_driver_requested'] = version
            dxvk = request.get('dxvk_version', client_vulkan.DEFAULT_DXVK)
            self.status['dxvk_requested'] = dxvk
            client_vulkan.configure_environment(self.env, HERE, SESSION, PREFIX, version, dxvk)
            self.env['DXVK_HUD'] = 'devinfo,fps,compiler' if request.get('dxvk_hud', True) else '0'
            self.env['DXVK_CONFIG'] = self.status['dxvk_configuration'] = dxvk_configuration(request)
        else:
            self.env['WINEDLLOVERRIDES'] += ';d3d9=b'
        if request.get('audio', True): client_audio.configure_environment(self.env, SESSION)
        else: self.env['WINEDLLOVERRIDES'] += ';winepulse.drv=d;winealsa.drv=d'

    def configure_cpu(self):
        # Box64's stock [wine] section forces 64 CPUs; a private rc file keeps the real count.
        profile = self.request.get('cpu_profile', DEFAULT_CPU_PROFILE)
        # DXVK 3.1.1 crashed the fourteenth Thor run inside vkCreateGraphicsPipelines, with no
        # trace of where. While it is chosen, Box64 reports the fault and both backtraces.
        extra = ({'BOX64_SHOWSEGV': '1', 'BOX64_SHOWBT': '1'}
                 if self.request.get('renderer', 'turnip') == 'turnip'
                 and self.request.get('dxvk_version', client_vulkan.DEFAULT_DXVK) != '2.5.3' else {})
        (SESSION / 'box64.rc').write_text(box64_rc(self.game_name, profile, extra))
        self.status['game_box64'] = {**CPU_PROFILES[profile], **extra}
        try: affinity = sorted(os.sched_getaffinity(0))
        except (AttributeError, OSError): affinity = []
        self.update(cpu_settings={k: v for k, v in self.env.items() if k.startswith('BOX64_')}, available_cpu_ids=affinity,
                    android_cpuset=android_cpuset(), prime_cpus=sorted(fastest_cpus()), big_cpus=sorted(fast_cpus()),
                    dynacache_at_launch=dynacache_summary())

    @contextmanager
    def timed(self, name):
        started = time.monotonic()
        try: yield
        finally:
            elapsed = round(time.monotonic() - started, 3)
            self.status['timings_seconds'][name] = elapsed
            self.update()
            print(f'X3 timing: {name}={elapsed}s', flush=True)

    def update(self, phase=None, **fields):
        if phase: self.status['phase'] = phase
        self.status.update(fields)
        for path in (SESSION / 'status.json', LOGS / 'x3-state.json'):
            temporary = path.with_suffix('.new')
            temporary.write_text(json.dumps(self.status, indent=2)); os.replace(temporary, path)

    def stopping(self):
        if stop_requested or (SESSION / 'stop').exists():
            self.status['stop_reason'] = stop_reason or 'stop_request'
            return True
        return False

    def spawn(self, args, log, env=None, cwd=None):
        cwd = cwd or GAME
        if log == 'x3-wine.log':
            self.wine_log = WineLog(LOGS / log, game=self.request.get('mode') == 'game',
                                    drop=SOUND_NOISE if self.request.get('sound_diagnostics') else None)
            process = subprocess.Popen(args, env=env or self.env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, start_new_session=True, cwd=cwd)
            self.log_thread = threading.Thread(target=self.wine_log.pump, args=(process.stdout,), daemon=True)
            self.log_thread.start()
            self.children.append(process)
            return process
        with (LOGS / log).open('ab') as out:
            process = subprocess.Popen(args, env=env or self.env, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                                       start_new_session=True, cwd=cwd)
        self.children.append(process)
        return process

    def run(self, args, timeout=180, label='Wine setup'):
        process = self.spawn(args, 'x3-prefix.log')
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if self.stopping(): raise StopRequested()
            if time.monotonic() > deadline: raise RuntimeError(label + ' timed out; export Logs (x3-prefix.log)')
            time.sleep(.2)
        if process.returncode:
            trace = (LOGS / 'x3-prefix.log').read_text(errors='replace')[-128*1024:]
            raise RuntimeError(f'{label} exited with code {process.returncode}. ' + (fatal_launch_error(trace) or 'See x3-prefix.log.'))

    def prefix_signature(self):
        paths = [Path('/etc/trasc-client-runtime.json'), Path('/opt/wine/share/wine/wine.inf'),
                 Path('/opt/wine/lib/wine/i386-windows/ntdll.dll')]
        return {'format': 1, 'runtime': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}}

    def prepare_prefix(self):
        marker = PREFIX / '.x3-prefix-ready.json'
        signature = self.prefix_signature()
        try: previous = json.loads(marker.read_text())
        except (OSError, ValueError): previous = None
        ready = previous == signature and prefix_diagnostics()['prefix_ready']
        marker.unlink(missing_ok=True)
        self.update('preparing_prefix', prefix_update='reuse' if ready else 'update')
        with self.timed('wine_prefix'):
            self.run([BOX64, WINE, 'wineboot', '-i' if ready else '-u'])
        report = prefix_diagnostics()
        (LOGS / 'x3-prefix.json').write_text(json.dumps(report, indent=2))
        if not report['runtime_ready']:
            raise RuntimeError('The runtime is missing 32-bit Windows system files. Reinstall the runtime; your game files are kept.')
        if not report['prefix_ready']:
            raise RuntimeError('The Wine prefix is incomplete. Use "Reset Wine prefix" in the launcher; your game files and saves are kept separately.')
        with self.timed('wine32_check'):
            self.run([BOX64, WINE, r'C:\windows\syswow64\cmd.exe', '/d', '/c', 'exit', '0'], timeout=60, label='32-bit Wine check')
        self.register_media_filters()
        temporary = marker.with_suffix('.new')
        temporary.write_text(json.dumps(signature)); os.replace(temporary, marker)

    def register_media_filters(self):
        """With the media add-on in place, make sure the prefix has winegstreamer's DirectShow filters."""
        if media_addon() is None:
            self.update(gstreamer_filters='no media add-on'); return
        if gstreamer_filters_registered():
            self.update(gstreamer_filters='registered'); return
        try:
            with self.timed('gstreamer_filters'):
                for regsvr32 in (r'C:\windows\syswow64\regsvr32.exe', 'regsvr32'):
                    self.run([BOX64, WINE, regsvr32, '/s', 'winegstreamer.dll'], timeout=180, label='Registering GStreamer filters')
            self.update(gstreamer_filters='registered now')
        except RuntimeError as error:
            # Sound effects and MPEG media still work without it; carry on and say so.
            self.update(gstreamer_filters='registration failed', warning=str(error))

    def check_graphics(self):
        self.update('checking_graphics')
        if self.request.get('renderer', 'turnip') == 'turnip':
            version = self.request.get('turnip_driver', client_vulkan.DEFAULT_DRIVER)
            manifest, command = client_vulkan.prepare_probe(HERE, SESSION, PREFIX, self.env, version,
                                                            self.request.get('dxvk_version', client_vulkan.DEFAULT_DXVK))
            process = self.spawn(command, 'x3-vulkan.log')
            deadline = time.monotonic() + 30
            while process.poll() is None:
                if self.stopping(): raise StopRequested()
                if time.monotonic() > deadline: raise RuntimeError('Turnip ' + version + ' check timed out. Try the other Turnip version or Software graphics.')
                time.sleep(.1)
            if process.returncode: raise RuntimeError('Turnip ' + version + ' device check failed. See x3-vulkan.log; try Software graphics.')
            report = client_vulkan.parse_probe((LOGS / 'x3-vulkan.log').read_text(errors='replace'), expected_mesa=version)
            self.update(renderer='DXVK / ' + report['driver'] + ' (' + report['device'] + ')', vulkan=report,
                        graphics_acceleration='host_gpu')
            return
        process = self.spawn(['glxinfo', '-B'], 'x3-graphics.log')
        deadline = time.monotonic() + 30
        while process.poll() is None:
            if self.stopping(): raise StopRequested()
            if time.monotonic() > deadline: raise RuntimeError('OpenGL check timed out')
            time.sleep(.1)
        text = (LOGS / 'x3-graphics.log').read_text(errors='replace')
        match = re.search(r'^OpenGL renderer string:\s*(.+)$', text, re.M)
        self.update(renderer='WineD3D / ' + (match[1].strip() if match else 'unknown'), graphics_acceleration='software')

    def start(self):
        for p in (SESSION, PREFIX, LOGS, SAVES, PREFIX / 'x3-cache'): p.mkdir(parents=True, exist_ok=True)
        info = validate_request(self.request)
        self.update(program_info=info)
        if info.get('steam_api'):
            self.update(warning='This executable imports steam_api.dll. If it exits immediately, use the '
                                'NoSteam X3AP.exe that LxXRM installs, or Egosoft\'s NoSteam executable.')
        print(f"X3 session started at {self.status['started_at']}: {self.request.get('program')}", flush=True)
        self.configure_cpu()
        self.update(audio=client_audio.prepare(HERE, SESSION) if self.request.get('audio', True) else {'backend': 'disabled'})
        if 'WINESERVER' in self.env:
            patch = json.loads((HERE / 'wineserver-patch.json').read_text())
            binary = Path(self.env['WINESERVER'])
            if binary.is_symlink() or not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest() != patch['sha256']:
                raise RuntimeError('Bundled Wine server failed verification; reinstall the APK')
            self.update(wineserver_patch=patch['patch'])
        if (HERE / 'box64-build.json').is_file():
            build = json.loads((HERE / 'box64-build.json').read_text())
            binary = Path(BOX64)
            if not binary.is_file() or hashlib.sha256(binary.read_bytes()).hexdigest() != build['sha256']:
                raise RuntimeError('Bundled Box64 failed verification; reinstall the APK')
            self.update(box64_build={'commit': build['commit'], 'patches': [p['name'] for p in build['patches']]})
        if (HERE / 'wine-dlls.json').is_file():
            build = json.loads((HERE / 'wine-dlls.json').read_text())
            for name, expected in build['dlls'].items():
                installed = Path('/opt/wine/lib/wine/i386-windows') / name
                if not installed.is_file() or hashlib.sha256(installed.read_bytes()).hexdigest() != expected['sha256']:
                    raise RuntimeError(f'Patched Wine {name} failed verification; reinstall the APK')
            self.update(wine_patches=[p['name'] for p in build['patches']])
        native_log = LOGS / 'x3-proot.log'
        observed = False
        if native_log.is_file():
            with native_log.open('rb') as source:
                observed = b'TRASC PRoot: seccomp acceleration observed' in source.read(4096)
        self.update(runtime_acceleration_observed=observed)
        if self.request.get('runtime_acceleration') == 'seccomp' and not observed:
            raise RuntimeError('Runtime acceleration was not confirmed. Choose Compatibility runtime mode and export Logs.')
        for name in ('x3-wine.log', 'x3-prefix.log', 'x3-display.log', 'x3-graphics.log', 'x3-threads.log',
                     'x3-vulkan.log', 'client-input.log', 'client-frame-bridge.log'):
            archive_log(LOGS / name)
        (LOGS / 'x3-wine.overflow.log').unlink(missing_ok=True)
        X3PIN_LOG.unlink(missing_ok=True)
        write_xauthority(self.env['XAUTHORITY'], 7)
        xserver = self.spawn(['Xtigervnc', ':7', '-geometry', self.request['resolution'], '-depth', '24',
                              '-rfbport', '-1', '-rfbunixpath', str(SESSION / 'display.sock'), '-rfbunixmode', '0600',
                              '-SecurityTypes', 'None', '-nolisten', 'tcp', '-nolock', '-auth', self.env['XAUTHORITY'],
                              '-AlwaysShared', '-FrameRate', str(client_presentation.options(self.request)[1]),
                              '-desktop', 'X3'], 'x3-display.log')
        for _ in range(150):
            if self.stopping(): raise StopRequested()
            if xserver.poll() is not None: raise RuntimeError('Display failed to start; see x3-display.log')
            if (SESSION / 'display.sock').exists(): break
            time.sleep(.1)
        else: raise RuntimeError('Display did not become ready')
        self.update(**client_presentation.start(self))
        self.update(**client_presentation.start_input(self))
        self.update(display_ready=True)
        with self.timed('graphics_check'): self.check_graphics()
        self.prepare_prefix()
        self.update(saves=persist_documents())
        if self.request.get('mode') == 'game':
            try: self.update(media_files=media_survey())
            except OSError as error: self.update(media_files={'error': str(error)})
        if self.request.get('renderer', 'turnip') == 'turnip':
            self.update(dxvk_d3d9_sha256=client_vulkan.install_d3d9(
                HERE, PREFIX, GAME, self.request.get('dxvk_version', client_vulkan.DEFAULT_DXVK)))
        devices = PREFIX / 'dosdevices'; devices.mkdir(exist_ok=True)
        drive = devices / 'd:'
        if drive.is_symlink(): drive.unlink()
        if drive.exists(): raise RuntimeError('Wine D: drive is already occupied')
        drive.symlink_to(GAME)
        args, cwd = build_command(self.request, info)
        env = dict(self.env)
        env['WINEDEBUG'] = wine_debug(self.request.get('diagnostic_logging', False), self.request.get('sound_diagnostics', False))
        launcher = self.spawn(args, 'x3-wine.log', env, cwd=cwd)
        self.status['timings_seconds']['until_launch_requested'] = round(time.monotonic() - self.started_monotonic, 3)
        self.update('launch_requested', launcher_pid=launcher.pid, command=args[2:])
        launched, absent = time.monotonic(), 0
        watch_game = self.request.get('mode') == 'game' or PurePosixPath(self.game_name).suffix.lower() == '.exe'
        threading.Thread(target=self.profile_main_thread, daemon=True).start()
        while not self.stopping():
            if xserver.poll() is not None: raise RuntimeError('Display exited; see x3-display.log')
            observed, fatal = self.wine_log.snapshot()
            if fatal: raise RuntimeError(fatal)
            if time.monotonic() - self.last_thread_sample >= 10:
                interval = time.monotonic() - self.last_thread_sample
                self.last_thread_sample = time.monotonic()
                sample = self.sample_threads(launcher.pid)
                self.read_pin_report()
                self.watch_spin(sample, interval)
                profile = self.profile.report()
                if profile: self.status['main_thread_profile'] = profile
                if time.monotonic() - getattr(self, 'last_dynacache', 0) >= 60:
                    self.last_dynacache = time.monotonic()
                    self.status['dynacache'] = dynacache_summary()
                self.status['thread_sample'] = {k: v for k, v in sample.items() if k != 'threads'}
                self.status['thread_sample']['thread_count'] = len(sample['threads'])
                if sample.get('game_running'):
                    self.status['game_running'], absent = True, 0
                    self.status.pop('warning', None)
                elif watch_game and not sample.get('incomplete'):
                    if self.status.get('game_running'):
                        absent += 1
                        if absent >= GAME_EXIT_SAMPLES:
                            # The game quit (or died without a recognisable error): end the session
                            # instead of leaving an empty black Wine desktop.
                            self.status['stop_reason'] = 'game_exited'
                            self.update(launcher_exit=launcher.poll(), **observed)
                            return
                    elif not any(WINE_PROCESS.search(t['name']) for t in sample['threads']) and launcher.poll() is not None:
                        # Every Wine process is gone (second Thor run: X3 died, wineserver followed
                        # 10 s later) and no recognised error was logged.
                        absent += 1
                        if absent >= GAME_EXIT_SAMPLES:
                            raise RuntimeError(f'Wine closed before {self.game_name} opened a window. '
                                               'Export Logs and check x3-wine.log.')
                    elif time.monotonic() - launched > GAME_START_GRACE and 'warning' not in self.status:
                        self.status['warning'] = (f'{self.game_name} is not running {GAME_START_GRACE / 60:g} minutes after launch. '
                                                  'Stop the game and export logs (x3-wine.log shows why).')
                path = LOGS / 'x3-threads.log'
                if path.exists() and path.stat().st_size > WINE_LOG_LIMIT:
                    os.replace(path, path.with_suffix('.overflow.log'))
                with path.open('a') as output:
                    output.write(json.dumps(sample) + '\n')
            self.update(launcher_exit=launcher.poll(), **observed)
            time.sleep(1)

    def read_pin_report(self):
        try:
            with X3PIN_LOG.open(errors='replace') as source: text = source.read(16384)
        except OSError: return
        summary = X3PIN_SUMMARY.findall(text)
        if summary: self.status['crypto_pin'] = '%s/%s (%s)' % summary[-1]

    def profile_main_thread(self):
        """Sample the game's main thread at 20 Hz; a load is any time Wine has not presented for 4 s.

        With prime placement, also put the main thread back on the fastest core once a second:
        a change of Android's cpuset resets every mask in it, and that happened every few seconds.
        """
        prime = fastest_cpus() if self.request.get('cpu_affinity', 'prime') == 'prime' else set()
        if len(prime) >= (os.cpu_count() or 1) - 1: prime = set()
        big = fast_cpus() or set(range(os.cpu_count() or 1))
        fallbacks = 0
        fastest = sorted(fastest_cpus())
        clocks = ClockProfile(fastest[0] if fastest else None)
        cap = self.request.get('display_fps', 60)
        ticks = repins = 0
        while not self.stopping():
            seen = self.wine_log.last_present_seen if self.wine_log else None
            if seen is not None and time.monotonic() - seen < 4:
                band = frame_band(self.wine_log, cap)
                self.profile.sample(*(('playing', 'below_cap') if band == 'below_cap' else ('playing',)))
                if not ticks % 20:
                    clocks.sample(band)
                    self.status['clock_profile'] = report = clocks.report()
                    hint = clock_hint(report)
                    if hint: self.status['performance_hint'] = hint
            else:
                self.profile.sample('loading')
            ticks += 1
            if prime and self.profile.pid and not ticks % 20:
                try:
                    current = set(os.sched_getaffinity(self.profile.pid))
                    if current != prime:
                        try:
                            os.sched_setaffinity(self.profile.pid, prime)
                            repins += 1
                            self.status['main_thread_repins'] = repins
                        except OSError:
                            # The prime core is not in Android's CPUs now: the other big cores,
                            # not the little ones (the kernel trims the mask to what is allowed).
                            if not current <= big:
                                os.sched_setaffinity(self.profile.pid, big)
                                fallbacks += 1
                                self.status['main_thread_big_core_fallbacks'] = fallbacks
                except OSError: pass   # gone
            time.sleep(0.05)

    def watch_spin(self, sample, seconds):
        main = [t for t in sample['threads']
                if t['tid'] == t['pid'] and t['name'].lower() == self.game_name[:15].lower()]
        if main: self.profile.pid = main[0]['pid']
        if main and self.spin.observe(main[0], seconds) and 'warning' not in self.status:
            profile = self.request.get('cpu_profile', DEFAULT_CPU_PROFILE)
            self.status['main_thread_spinning'] = True
            self.status['warning'] = (
                f'{self.game_name} seems stuck: its main thread has used a full core for '
                f'{SPIN_SAMPLES * 10} s without any system call or page fault.'
                + (f' The {profile} CPU profile can do that: stop the game and choose balanced.'
                   if profile in ('fast', 'fastest') else ' Stop the game and export logs.'))

    def sample_threads(self, pid):
        before = time.monotonic()
        sample = process_threads(pid, launch_token=self.launch_token, game_name=self.game_name)
        affinity = self.request.get('cpu_affinity', 'prime')
        if affinity == 'prime':
            sample['affinity_update'] = place_game_threads(sample, self.launch_token, game_name=self.game_name)
            sample['affinity_update']['supervisor_cpus'] = sorted(os.sched_getaffinity(0))
        elif affinity == 'available':
            sample['affinity_update'] = allow_game_cpus(sample, self.launch_token, game_name=self.game_name)
        sample['collection_seconds'] = round(time.monotonic() - before, 4)
        return sample

    def stop(self):
        try:
            subprocess.run([BOX64, self.env.get('WINESERVER', '/opt/wine/bin/wineserver'), '-k'], env=self.env,
                           timeout=10, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired): pass
        for child in reversed(self.children):
            if child.poll() is None:
                try: os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        deadline = time.monotonic() + 5
        for child in self.children:
            try: child.wait(timeout=max(.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try: os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                child.wait()
        if self.log_thread:
            self.log_thread.join(timeout=2)
            self.status.update(self.wine_log.snapshot()[0])
        (SESSION / 'display.sock').unlink(missing_ok=True)
        self.update(display_ready=False)


def main():
    global stop_requested, stop_reason
    def stop(signum, _frame):
        global stop_requested, stop_reason
        stop_requested = True
        stop_reason = signal.Signals(signum).name
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    supervisor = None
    try:
        request = json.loads((SESSION / 'request.json').read_text())
        supervisor = Supervisor(request); supervisor.start()
    except StopRequested:
        if supervisor: supervisor.update('stopped')
    except Exception as error:
        if supervisor: supervisor.update('error', error=str(error))
        else:
            (SESSION / 'status.json').write_text(json.dumps({'phase': 'error', 'error': str(error)}))
        print(f'X3 runtime failed: {error}', flush=True)
        raise
    finally:
        if supervisor:
            supervisor.stop()
            if supervisor.status.get('phase') != 'error': supervisor.update('stopped', display_ready=False)
            print(f"X3 session ended at {time.time()}: {supervisor.status.get('error') or supervisor.status.get('stop_reason', 'completed')}", flush=True)


if __name__ == '__main__': main()
