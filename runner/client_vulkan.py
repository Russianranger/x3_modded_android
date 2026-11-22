# Adapted from trasc-server-android backend/client_vulkan.py (commit 99e8c86f).
# X3 changes: EverQuest asset/NPC helpers removed; 64-bit DXVK install added (verified against
# payload-provenance.json) for the case where X3AP.exe is a 64-bit build, and a choice of DXVK
# version (2.5.3 from TRASC's bundle, or upstream 3.1.1 pinned in the X3 payload lock).
"""Pinned, APK-owned Turnip/DXVK selection, with explicit device verification."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct

DEFAULT_DRIVER = '24.3.4'
DRIVERS = {'24.3.4': 'turnip.so', '26.0.0': 'turnip-26.0.0.so'}
FILES = (*DRIVERS.values(), 'vulkan-probe', 'dxvk-d3d9.dll')
X64_DLL = 'dxvk-d3d9-x64.dll'
# DXVK version -> (32-bit d3d9.dll, 64-bit d3d9.dll) in the payload. 2.5.3's 32-bit DLL is TRASC's
# bundled one (checked against vulkan-bundle.json); every other file is checked against
# payload-provenance.json, which the build wrote after verifying the upstream release tarball.
DXVK_VERSIONS = {'2.5.3': ('dxvk-d3d9.dll', X64_DLL), '3.1.1': ('dxvk-3.1.1-d3d9.dll', 'dxvk-3.1.1-d3d9-x64.dll')}
DEFAULT_DXVK = '3.1.1'


def dxvk_files(version):
    if not isinstance(version, str) or version not in DXVK_VERSIONS:
        raise ValueError('Unsupported DXVK version; choose ' + ' or '.join(DXVK_VERSIONS))
    return DXVK_VERSIONS[version]


def driver_file(version):
    if not isinstance(version, str) or version not in DRIVERS:
        raise ValueError('Unsupported Turnip driver; choose 24.3.4 or 26.0.0')
    return DRIVERS[version]


def cache_paths(prefix, version, dxvk='2.5.3'):
    """DXVK and Mesa shader caches per driver, and for DXVK per version (2.5.3 keeps its old folder)."""
    driver_file(version); dxvk_files(dxvk)
    suffix = '' if version == DEFAULT_DRIVER else '-turnip-' + version
    mesa_suffix = '' if version == DEFAULT_DRIVER else '-' + version
    dxvk_name = 'dxvk' + ('' if dxvk == '2.5.3' else '-' + dxvk) + suffix
    return prefix/'x3-cache'/dxvk_name, prefix/'x3-cache'/('mesa-turnip'+mesa_suffix)


def verify_bundle(folder):
    manifest = json.loads((folder/'vulkan-bundle.json').read_text())
    if (manifest.get('format'), manifest.get('mesa'), manifest.get('dxvk'), manifest.get('architecture'), manifest.get('kmd')) != (2, DEFAULT_DRIVER, '2.5.3', 'arm64-glibc', 'kgsl') or manifest.get('drivers') != DRIVERS:
        raise RuntimeError('Unsupported bundled Turnip/DXVK version; reinstall the APK')
    if set(manifest.get('files', {})) != set(FILES): raise RuntimeError('Vulkan bundle file list is incomplete')
    for name in FILES:
        p = folder/name
        if not p.is_file() or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest() != manifest['files'][name]:
            raise RuntimeError('Vulkan bundle checksum failed: '+name)
        header = p.read_bytes()[:64]
        if name != 'dxvk-d3d9.dll' and (len(header) < 64 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H',header,18)[0] != 183):
            raise RuntimeError('Vulkan native component is not ARM64: '+name)
    return manifest


def verify_payload_file(folder, name):
    """Check a file the X3 build adds to TRASC's payload against the build-time provenance."""
    provenance = json.loads((folder/'payload-provenance.json').read_text())
    expected = provenance['files'].get('assets/payload/'+name)
    path = folder/name
    if not expected or not path.is_file() or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError('Payload checksum failed: '+name+'; reinstall the APK')
    return expected


def configure_environment(env, folder, session, prefix, version=DEFAULT_DRIVER, dxvk='2.5.3'):
    # MESA_VK_WSI_DEBUG=sw selects CPU-copy X11 presentation, NOT a software GPU driver.
    # DXVK 2.5.3 keeps a pipeline state cache (DXVK_STATE_CACHE_PATH); 3.x replaced it with a
    # shader cache (DXVK_SHADER_CACHE_PATH). Both go to the same per-version folder.
    dxvk_cache, mesa_cache = cache_paths(prefix, version, dxvk)
    env.update(VK_ICD_FILENAMES=str(session/'turnip-icd.json'),
               VK_DRIVER_FILES=str(session/'turnip-icd.json'), MESA_VK_WSI_DEBUG='sw',
               DXVK_LOG_LEVEL='info', DXVK_LOG_PATH='/logs', DXVK_HUD='devinfo,fps,compiler',
               DXVK_STATE_CACHE_PATH=str(dxvk_cache), DXVK_SHADER_CACHE_PATH=str(dxvk_cache),
               MESA_SHADER_CACHE_DIR=str(mesa_cache), mesa_glthread='false')
    env['WINEDLLOVERRIDES'] += ';d3d9=n'


def prepare_probe(folder, session, prefix, env, version=DEFAULT_DRIVER, dxvk='2.5.3'):
    filename = driver_file(version)
    manifest = verify_bundle(folder)
    (session/'turnip-icd.json').write_text(json.dumps({'file_format_version':'1.0.0', 'ICD':{
        'library_path':str(folder/filename), 'api_version':'1.3.0'}}))
    for path in cache_paths(prefix, version, dxvk): path.mkdir(parents=True, exist_ok=True)
    return manifest, [str(folder/'vulkan-probe')]


def parse_probe(text, expected_mesa=None):
    reports = []
    for line in text.splitlines():
        try: reports.append(json.loads(line))
        except ValueError: pass
    if not reports: raise RuntimeError('Vulkan probe returned no device/presentation report')
    report = reports[-1]
    if report.get('presentation_frames') != 3: raise RuntimeError('Vulkan presentation was not verified')
    if report.get('api_version', 0) < (1<<22 | 3<<12): raise RuntimeError('DXVK requires Vulkan 1.3')
    if report.get('driver_id') != 18 or report.get('vendor_id') != 0x5143 or report.get('software') is not False:
        raise RuntimeError('Turnip/Qualcomm hardware was not verified; software fallback rejected')
    if expected_mesa is not None:
        driver_file(expected_mesa)
        major, minor, patch = map(int, expected_mesa.split('.'))
        if report.get('driver_version') != (major<<22 | minor<<12 | patch):
            raise RuntimeError('The loaded Turnip version does not match the selected driver; stop and export Logs')
    return report


def _install(source, expected, target, backup):
    if not target.parent.is_dir(): raise RuntimeError('Prepare the Wine prefix before DXVK')
    if target.is_file() and not target.is_symlink() and hashlib.sha256(target.read_bytes()).hexdigest() == expected:
        return expected
    backup.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and not backup.exists(): shutil.copyfile(target, backup)
    temporary = target.with_name('d3d9.x3-new')
    shutil.copyfile(source, temporary); os.replace(temporary, target)
    return expected


def install_d3d9(folder, prefix, game, dxvk='2.5.3'):
    """Install DXVK's d3d9 for 32-bit (syswow64) and, when shipped, 64-bit (system32) programs.

    The chosen version replaces whatever DXVK the prefix had; Wine's own d3d9 is kept once in
    x3-renderers for the Software graphics option."""
    x86, x64 = dxvk_files(dxvk)
    # A d3d9.dll beside the game would shadow ours (Windows loads the application folder first).
    if any(p.name.lower() == 'd3d9.dll' for p in game.iterdir()):
        raise RuntimeError('The game folder contains d3d9.dll, which would override bundled DXVK. Remove it or choose Software graphics.')
    manifest = verify_bundle(folder)
    expected = manifest['files'][x86] if x86 in manifest['files'] else verify_payload_file(folder, x86)
    result = {'version': dxvk,
              'x86': _install(folder/x86, expected, prefix/'drive_c/windows/syswow64/d3d9.dll', prefix/'x3-renderers/wine-d3d9-x86.dll')}
    if (folder/x64).exists():
        result['x86_64'] = _install(folder/x64, verify_payload_file(folder, x64),
                                    prefix/'drive_c/windows/system32/d3d9.dll', prefix/'x3-renderers/wine-d3d9-x64.dll')
    return result
