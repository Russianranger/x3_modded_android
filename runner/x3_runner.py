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
from client_metrics import LAUNCH_ENV, process_threads, allow_game_cpus
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


def wine_debug(verbose=False, sound=False):
    # +seh and per-frame traces flood PRoot; Wine's fps channel reports every 1.5 s per swapchain.
    normal = '-all,+timestamp,+pid,err+all,trace+loaddll,trace+fps,' + MEDIA_DEBUG
    return (normal + ',warn+dsound,warn+wave,warn+mmdevapi'
            + (',warn+all,fixme+all,trace+module' if verbose else '')
            + (',trace+dsound,trace+dsound3d,trace+mmdevapi,trace+msacm,trace+quartz' if sound else ''))


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
    options.append('d3d9.maxFrameRate = %d' % request.get('display_fps', 60))   # nothing above the frame bridge rate is seen
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
    match = re.search(r'wine: could not load kernel32\.dll, status ([0-9a-f]+)', log, re.I)
    if match:
        return 'Wine could not start its Windows loader (kernel32.dll, ' + match[1] + '). Reinstall the runtime and export Logs.'
    if re.search(r'err:module:\w+ (?:Importing|Initializing).*failed, status', log):
        missing = re.findall(r'err:module:import_dll Library ([^\r\n]+)', log)
        if missing:
            return 'A required Windows library could not load: ' + missing[-1][:350] + '. Export Logs for details.'
        return 'Windows program initialization failed. Export Logs (x3-wine.log) for the failing module.'
    return None


class WineLog:
    """Drain Wine's output on a thread; parse before rotating so early evidence survives."""
    def __init__(self, path, limit=WINE_LOG_LIMIT, game=False):
        self.path, self.limit, self.game = path, limit, game
        self.lock = threading.Lock()
        self.fields = {'wine_log_bytes': 0, 'wine_log_rotations': 0, 'dsound_errors': 0}
        self.error = None
        self.pending = b''
        self.trace = ''
        self.fps_streams = set()

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
                if re.search(r'DXVK: v?2\.5\.3\b', line): self.fields['dxvk_loaded'] = '2.5.3'
                pin = re.search(r'x3pin: (\d+) of (\d+) DLLs pinned \(([^)]{0,40})\)', line)
                if pin: self.fields['crypto_pin'] = f'{pin[1]}/{pin[2]} ({pin[3]})'
                mode = re.search(r'Present mode: (VK_PRESENT_MODE_\w+)', line)
                if mode: self.fields['dxvk_present_mode'] = mode[1]
                if re.search(r'Loaded L".*\\+dsound\.dll".*: (builtin|native)\s*$', line, re.I):
                    self.fields['dsound_loaded'] = re.search(r': (builtin|native)\s*$', line)[1]
                if re.search(r':(err|warn):dsound', line): self.fields['dsound_errors'] += 1
                fps = re.search(r':([0-9a-f]+):[0-9a-f]+:trace:fps:\w+ ((?:0x)?[0-9a-f]+) @ approx ([0-9]+\.[0-9]+)fps', line, re.I)
                if fps:
                    stream = fps[1].lower() + ':' + fps[2].lower()
                    if stream in self.fps_streams and 0 <= float(fps[3]) <= 10000:
                        self.fields['wine_present'] = {'per_second': float(fps[3]), 'sampled_at': time.time()}
                    if len(self.fps_streams) < 64: self.fps_streams.add(stream)
            self.fields['wine_log_bytes'] += len(chunk)
            self.error = self.error or fatal_launch_error(self.trace, game=self.game)

    def snapshot(self):
        with self.lock: return dict(self.fields), self.error

    def pump(self, stream):
        output = None
        try:
            output = self.path.open('wb'); written = 0
            while chunk := stream.read1(min(64*1024, self.limit)):
                self.observe(chunk)
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
        except OSError as error:
            with self.lock: self.error = 'Could not capture Wine output: ' + str(error)
        finally:
            if output: output.close()
            stream.close()


class StopRequested(Exception):
    pass


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
    if head[:4] in (b'\x00\x00\x01\xba', b'\x00\x00\x01\xb3'): return 'mpeg-video'
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
    if request.get('cpu_profile', 'balanced') not in ('balanced', 'accurate'): raise ValueError('Unsupported CPU profile')
    if request.get('cpu_affinity', 'available') not in ('available', 'game'): raise ValueError('Unsupported CPU affinity')
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
        self.launch_token = secrets.token_hex(16)
        self.started_monotonic = time.monotonic()
        self.game_name = PurePosixPath(request.get('program', 'X3AP.exe')).name
        self.status = {'phase': 'starting', 'mode': request.get('mode'), 'program': request.get('program'),
                       'resolution': request.get('resolution'), 'display_target_fps': request.get('display_fps', 60),
                       'renderer': 'Checking graphics driver', 'graphics_backend': request.get('renderer', 'turnip'),
                       'started_at': time.time(), 'timings_seconds': {},
                       'cpu_profile': request.get('cpu_profile', 'balanced'),
                       'runtime_acceleration': request.get('runtime_acceleration', 'unspecified')}
        self.env = dict(os.environ, DISPLAY=':7', XAUTHORITY=str(SESSION / 'Xauthority'),
                        WINEPREFIX=str(PREFIX), WINEARCH='win64', WINEDEBUG=wine_debug(),
                        WINEDLLOVERRIDES=dll_overrides(media_addon() is not None, request.get('controller_passthrough', False)),
                        BOX64_DYNAREC_STRONGMEM='1', BOX64_DYNAREC_BIGBLOCK='2', BOX64_DYNAREC_SAFEFLAGS='1',
                        BOX64_MAXCPU='0', BOX64_RCFILE=str(SESSION / 'box64.rc'),
                        BOX64_LOG='1', BOX64_NOBANNER='0', BOX64_PATH='/opt/wine/bin',
                        BOX64_LD_LIBRARY_PATH='/usr/lib/x86_64-linux-gnu:/lib/x86_64-linux-gnu:/opt/wine/lib/wine/x86_64-unix',
                        LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe', LP_NUM_THREADS='4',
                        WINE_D3D_CONFIG='csmt=1', **{LAUNCH_ENV: self.launch_token})
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
            client_vulkan.configure_environment(self.env, HERE, SESSION, PREFIX, version)
            self.env['DXVK_HUD'] = 'devinfo,fps,compiler' if request.get('dxvk_hud', True) else '0'
            self.env['DXVK_CONFIG'] = self.status['dxvk_configuration'] = dxvk_configuration(request)
        else:
            self.env['WINEDLLOVERRIDES'] += ';d3d9=b'
        if request.get('audio', True): client_audio.configure_environment(self.env, SESSION)
        else: self.env['WINEDLLOVERRIDES'] += ';winepulse.drv=d;winealsa.drv=d'

    def configure_cpu(self):
        # Box64's stock [wine] section forces 64 CPUs; a private rc file keeps the real count.
        game = re.sub(r'[^A-Za-z0-9._-]', '', self.game_name) or 'X3AP.exe'
        (SESSION / 'box64.rc').write_text(
            '[wine]\nBOX64_MAXCPU=0\n[wine64]\nBOX64_MAXCPU=0\n'
            '[explorer.exe]\nBOX64_DYNAREC_BIGBLOCK=0\n'
            f'[{game}]\nBOX64_DYNAREC_BIGBLOCK=2\nBOX64_DYNAREC_SAFEFLAGS=1\nBOX64_DYNAREC_STRONGMEM=1\n')
        try: affinity = sorted(os.sched_getaffinity(0))
        except (AttributeError, OSError): affinity = []
        self.update(cpu_settings={k: v for k, v in self.env.items() if k.startswith('BOX64_')}, available_cpu_ids=affinity)

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
            self.wine_log = WineLog(LOGS / log, game=self.request.get('mode') == 'game')
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
        temporary = marker.with_suffix('.new')
        temporary.write_text(json.dumps(signature)); os.replace(temporary, marker)

    def check_graphics(self):
        self.update('checking_graphics')
        if self.request.get('renderer', 'turnip') == 'turnip':
            version = self.request.get('turnip_driver', client_vulkan.DEFAULT_DRIVER)
            manifest, command = client_vulkan.prepare_probe(HERE, SESSION, PREFIX, self.env, version)
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
            self.update(dxvk_d3d9_sha256=client_vulkan.install_d3d9(HERE, PREFIX, GAME))
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
        while not self.stopping():
            if xserver.poll() is not None: raise RuntimeError('Display exited; see x3-display.log')
            observed, fatal = self.wine_log.snapshot()
            if fatal: raise RuntimeError(fatal)
            if time.monotonic() - self.last_thread_sample >= 10:
                self.last_thread_sample = time.monotonic()
                sample = self.sample_threads(launcher.pid)
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

    def sample_threads(self, pid):
        before = time.monotonic()
        sample = process_threads(pid, launch_token=self.launch_token, game_name=self.game_name)
        if self.request.get('cpu_affinity', 'available') == 'available':
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
