# 5. Loading times

LxXRM makes X3 load a lot more than vanilla: XRM's catalogs, all of Lucike's scripts as loose
files, extra text files, and large late-game universes. On Android every file lookup can be taxed
two or three times over. Below are the likely costs, ranked by expected payoff. Measure before and
after each change.

## Where the time goes

| Cost | Why it hurts here | Fix |
| --- | --- | --- |
| **Shared storage (FUSE)** | Running from `/sdcard` or `/storage/...` goes through Android's FUSE layer. Per Samsung's reply on Google's issue tracker, only *app-private directories on internal storage* bypass FUSE. Winlator and GameNative games often live on shared storage. | Import the game into app-private internal storage (TRASC's workspace model). Launch scripts warn if the path is under `/sdcard` or `/storage`. |
| **PRoot path syscalls** | PRoot intercepts every syscall that takes a path (open, stat, access) with ptrace. Thousands of loose script and text files means thousands of round trips. | TRASC's patched PRoot uses seccomp acceleration and logs when it is active; keep it on and check the log. |
| **Wine case-insensitive lookups** (Route B) | Windows names are case-insensitive. When a requested name doesn't exist with that exact case, Wine has to scan the directory to find a match. Mods with mixed-case names in big folders pay this repeatedly. | Route A avoids Wine. On Route B, keep the install in one place (no symlink farms) and measure before changing anything. |
| **Intro movies** | Fixed seconds on every launch | `-skipintro` (confirmed for the Linux binary by the x3ui project; test on the Windows exe). |
| **Straight to a save** | Menu round trips | `-faststart N` loads save slot N directly on the Linux binary (x3ui uses `-skipintro -faststart <slot>`). |
| **Box64 JIT warm-up** | Every launch re-translates the same x86 code | Box64's **DynaCache** stores translated blocks on disk; upstream enables it by default. Point `BOX64_DYNACACHE_FOLDER` at persistent app storage (the launch scripts do) and confirm your pinned Box64 has it. |
| **Little cores** | TRASC once caught a game's threads confined to CPU 0 | Reuse TRASC's "allow available cores" option and log the thread masks during loading. |
| **Many loose scripts** | Each is found, opened and parsed separately | Experiment only: X3 also reads scripts from catalogs (vanilla scripts ship inside cat/dat), so packing LxXRM's loose `addon/scripts` into a new catalog could cut lookups. Back up first; load order and overrides must stay identical. |

In-game slowdown is a separate problem. LxXRM already includes the CPP combat performance patch and
X3 Customizer fixes for it.

## Measurement protocol

Use the same save, resolution and route each time, and do three runs each, cold and warm. The app
should log:

1. Process start, then first frame, then main menu, then save loaded (first in-flight frame).
2. Game folder location (internal or shared), PRoot acceleration active, DynaCache size before and
   after, CPU affinity masks of the game threads, and storage free space.
3. File counts from `tools/probe_x3_install.py` (loose scripts and text, catalogs), so results
   can be compared across installs.

Record results in a table here. A useful first comparison: Winlator from `/sdcard` vs. this app from
internal storage, both on Route B with the same save.
