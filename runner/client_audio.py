# Adapted from trasc-server-android backend/client_audio.py (commit 99e8c86f).
# X3 changes: EverQuest PFS/WAV inspectors removed; 'dsp0' added because Egosoft's own Linux X3
# audio fix uses that ALSA device name (see docs/03-audio.md). Protocol and plugin are unchanged.
"""Configure the APK's ALSA endpoint without changing the installed rootfs."""
import hashlib
import json
import struct


def configure_environment(env, session):
    env.update(ALSA_CONFIG_PATH=str(session/'asound.conf'), TRASC_AUDIO_SOCKET=str(session/'audio.sock'))
    # No PulseAudio server exists in the rootfs: force winealsa.drv for this session only.
    env['WINEDLLOVERRIDES'] += ';winepulse.drv=d'


def asound_conf(library):
    plug = '{ type plug slave { pcm "trasc" format S16_LE rate 48000 channels 2 } }'
    return ('</usr/share/alsa/alsa.conf>\n'
            f'pcm_type.trasc {{ lib "{library}" }}\n'
            'pcm.trasc { type trasc }\n'
            f'pcm.!default {plug}\n'
            f'pcm.dsp0 {plug}\n')


def prepare(folder, session):
    library = folder/'libasound_module_pcm_trasc.so'
    data = library.read_bytes()
    manifest = json.loads((folder/'audio-bundle.json').read_text())
    if (manifest.get('protocol'), manifest.get('architecture')) != (1, 'arm64-glibc'):
        raise RuntimeError('Unsupported audio bridge bundle')
    if library.is_symlink() or hashlib.sha256(data).hexdigest() != manifest.get('sha256'):
        raise RuntimeError('Audio bridge checksum failed')
    if data[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', data, 18)[0] != 183:
        raise RuntimeError('Audio bridge is not ARM64')
    if not (session/'audio.sock').is_socket():
        raise RuntimeError('Android audio bridge is not listening')
    # ALSA's plug converts rate, channels and sample format. No capture device is offered.
    (session/'asound.conf').write_text(asound_conf(library))
    return {'backend': 'alsa-audiotrack', 'protocol': 1, 'rate': 48000, 'channels': 2,
            'devices': ['default', 'dsp0'], 'sha256': manifest['sha256']}
