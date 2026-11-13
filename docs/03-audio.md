# 3. Audio

## How X3 produces sound

| Build | Path | Evidence |
| --- | --- | --- |
| Windows (`X3AP.exe`) | DirectSound, with an optional **EAX** mode (DirectSound3D property sets). Some media may also go through DirectShow. | The TC manual's launcher section lists an "EAX" option. A GOG forum answer describes X3's 3D sound as EAX on DirectSound3D and calls EAX "skittish". A Wine install guide for the Terran War Pack adds GStreamer and DirectShow components. |
| Linux (`X3AP_main`) | ALSA. Egosoft's own fix for "Unable to initialize audio" is an `~/.asoundrc` that defines `pcm.dsp0` (plug -> dmix) and `ctl.mixer0`, the device names ALSA's OSS emulation uses. | Egosoft X3 wiki, Troubleshooting/NoAudio |

Known problems reported by others:

- **Music restarting about every 20 s** with Wine Staging after 6.7 (WineHQ bug 51126, reported in
  the GOG Wine guide).
- **Native Linux: music missing** in at least one ProtonDB report.
- **Older GOG Linux builds missing voices**: fixed by Egosoft's July 2021 Linux update.
- **XRM Part 3 sound files** don't work on Linux/macOS. The XRM install guide says to skip Part 3
  there and use the XRM **Linux patch** (`mov` + `soundtrack`). This matters for Route A.

## Why Winlator/GameNative were silent: what to try right now

These are hypotheses, ranked by likelihood, and each takes a minute to test in Winlator or
GameNative:

1. **EAX enabled.** EAX support in Wine has historically existed only as wine-staging patches
   (WineHQ bugs 39369 and the F.E.A.R. EAX crash), so a stock build may fail or mute DirectSound3D
   buffers that use EAX. Untick EAX in X3's launcher window and check the in-game sound options.
2. **Audio driver.** Winlator offers `alsa` or `pulseaudio` per container; its docs say to switch
   between them on crackling or silence. GameNative pipes Wine's audio into an in-app PulseAudio
   server that outputs through AAudio. Try the other one.
3. **DirectSound component.** Winlator's *Wine Components -> DirectSound* toggles Microsoft's
   native `dsound` versus Wine's builtin. With EAX off, builtin is the safer default.
4. **Only music or movies missing.** That points at DirectShow/codecs, not the audio driver (see
   the GStreamer note in docs/02).
5. **Volume sliders at 0** in X3's own sound menu. TRASC's ROF2 notes caught music set to 0 in one
   session, so it is worth a look.

## The audio stack for this app

One path serves both routes and needs no `/dev/snd`, root, PulseAudio or network:

```text
Route B: X3AP.exe -> dsound (builtin) -> mmdevapi -> winealsa.drv ┐
Route A: X3AP_main -> SDL2 or libasound (wrapped to native arm64) ┤
                                                                  ▼
                 ALSA 'plug' (any rate/format -> 48 kHz S16 stereo)
                                                                  ▼
          pcm_trasc ioplug plugin  --Unix socket (app-private)-->  AudioBridge (Java)
                                                                  ▼
                                                    AudioTrack (USAGE_GAME)
```

- `runtime/asound.conf.template` is TRASC's config plus `pcm.dsp0` for Egosoft's Linux device
  name. The launcher fills in the plugin path and exports `ALSA_CONFIG_PATH` and
  `TRASC_AUDIO_SOCKET`, the same contract as TRASC's `backend/client_audio.py`.
- Route B: `WINEDLLOVERRIDES=...;winepulse.drv=d` forces Wine onto `winealsa.drv` for the session,
  exactly as TRASC does. No registry edit is needed.
- Route A: `SDL_AUDIODRIVER=alsa`. Box32 wraps `libasound`, so the native arm64 `libasound` loads
  the arm64 `pcm_trasc` plugin directly.
- **Mixer control (only if needed).** Egosoft's fix also defines `ctl.mixer0` as hardware card 0,
  which doesn't exist inside PRoot. If the native build logs a mixer/ctl open failure, add a tiny
  ALSA `ctl_ext` plugin (one "Master" volume, built in the same Dockerfile as `pcm_trasc`) and
  enable the commented `ctl.mixer0` lines in the template.

## Tests, in order

1. Inside the rootfs: `speaker-test -D default -c 2 -t sine -l 1`. This proves ALSA -> bridge ->
   speaker with the game out of the picture.
2. Route B: X3 launcher with EAX off -> main-menu music -> SFX in flight -> comms voice -> a movie.
3. Route A: the same, plus `-D dsp0` in step 1.
4. Export logs. TRASC's AudioBridge log already counts submitted/played frames and underruns; its
   ROF2 runs showed a few early underruns that then stabilised. Use that as the baseline.

Later improvement: move AudioBridge from AudioTrack to AAudio (via Oboe) in low-latency mode if
weapon sounds feel late.
