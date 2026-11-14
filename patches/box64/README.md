# Box64 patches

The app swaps the runtime's own `/usr/local/bin/box64` for a build of the **same commit**: TRASC's
pinned Box64 `2f130fab` (0.4.4), built with the same flags as TRASC's `client-runtime/Dockerfile`,
plus the patches in this folder. `scripts/build_box64.sh` does the build on arm64 Debian Bookworm
inside CI and runs every program in `tests/box64` with the dynarec on and with it off. The runner
checks the binary's hash against `box64-build.json` before each launch.

| Patch | Why |
| --- | --- |
| `0001-interpreter-66-0f-01-smsw.patch` | `X3AP.exe` runs `smsw ax` (`66 0F 01 E0`) when it starts, then tests CR0.EM before probing for FXSAVE. Box64 decodes `0F 01 /4` (SMSW) but not with the `66` operand-size prefix, so Wine reported an illegal instruction at `0x4F9975` and X3 never opened a window (second run on the Thor, November 2026). The patch adds `66 0F 01 /4` to the interpreter, returning the same dummy machine status word as the unprefixed form: PE and ET set, EM clear. The dynarec already hands unknown opcodes to the interpreter. Upstream `main` (November 2026) still lacks this form. |

Box64 is MIT-licensed. Its source is upstream commit `2f130fab1d6e1a4ee8a71dc60cfdfcc839ad192a`
plus these patches.
