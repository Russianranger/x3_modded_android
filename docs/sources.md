# Sources

Researched on 13 November 2026. The Egosoft forum sits behind a bot check that blocked direct
fetching, so LxXRM details come from search-engine copies of the thread and from posts that link to
it.

## Mod package
- [LxXRM 3.1 thread, page 2 (t=399184)](https://forum.egosoft.com/viewtopic.php?t=399184&start=15): installer steps, `_DOWNLOADS`, contents
- [X3 Customizer thread](https://forum.egosoft.com/viewtopic.php?p=4694928) and [source/docs](https://github.com/bvbohnen/X3_Customizer): designed for AP 3.3; transforms edit `L/x3story.obj`, scripts and director files
- [Post by the LxXRM author on using X3 Customizer in the package](https://forum.egosoft.com/viewtopic.php?p=4718445)
- [LxXRM forum report on installed size](https://forum.egosoft.com/viewtopic.php?p=4718623) (`addon` ≈ 2.55 GB, backup ≈ 709 MB)
- [GOG: installing XRM on all operating systems](https://gog.com/forum/x_series/howto_install_the_x3_rebalance_mod_xrm_all_operating_systems): skip Part 3 on Linux/macOS, use the Linux patch; AP loads TC's catalogs first

## Game builds
- [Egosoft: Linux version now available (Farnham's Legacy, TC/AP updates)](https://forum.egosoft.com/viewtopic.php?p=5069696)
- [GamingOnLinux on the July 2021 update](https://www.gamingonlinux.com/2021/07/x3-farnhams-legacy-now-available-for-linux-with-linux-fixes-for-other-games-live/)
- [Egosoft wiki: X3 Albion Prelude, latest version 3.3 (2017)](https://egosoft.com:8444/confluence/x/JoCKAg)
- [x3ui: LD_PRELOAD overlay for X3AP_main](https://github.com/FabricSoul/x3ui): 32-bit non-PIE i386 ELF, SDL2 + GL, `-skipintro -faststart`, `~/.config/EgoSoft/X3AP`
- [Steam: X3AP Linux zlib/libpng issue](https://steamcommunity.com/app/201310/discussions/0/1480982971167475463/)
- [ProtonDB: X3: Albion Prelude](https://www.protondb.com/app/201310): native music-missing report, Proton notes
- [Phoronix forum: NoSteam executable](https://www.phoronix.com/forums/forum/software/linux-gaming/35857-x3-albion-prelude-released-for-linux-gamers?p=436859)
- [Steam news: AP 3.0 adds controller support](https://store.steampowered.com/news/10612)

## Audio
- [Egosoft X3 wiki: Unable to initialize audio (Linux, ALSA dmix / dsp0)](https://wiki.egosoft.com/X3%20Wiki/Troubleshooting/NoAudio)
- [GOG: X3 TC uses EAX on DirectSound3D](https://gog.com/forum/x_series/several_technical_problems_with_x3_terran_conflict)
- [GOG: Linux/Wine installation of the Terran War Pack](https://gog.com/forum/x_series/linuxwine_installation_x3_terran_war_pack): GStreamer + winetricks media components, music-loop bug 51126
- [WineHQ bug 39369 (EAX in wine-staging)](https://list.winehq.org/mailman3/hyperkitty/list/wine-bugs@winehq.org/thread/DWHK4TE4JGIV6EBZGBAWUR7SKO4AD52A) and [EAX crash fixed by a staging patch](https://list.winehq.org/mailman3/hyperkitty/list/wine-bugs@winehq.org/thread/WDX3P5WPGJOKEX6UB5ZC3HMY5GBBN5RZ)
- [Winlator container audio driver options](https://mintlify.wiki/brunodev85/winlator/containers/settings) and [troubleshooting](https://mintlify.wiki/brunodev85/winlator/advanced/troubleshooting)
- [GameNative audio path (Wine -> PulseAudio -> AAudio)](https://aospbooks.github.io/aosp-internal-book/64-windows-games/)

## Controls
- [X3: Reunion manual (Steam), default key profile](https://steamcdn-a.akamaihd.net/steam/apps/2810/manuals/X3_Reunion_Manual_Steam_English.pdf)
- [X3: Albion Prelude Survival Guide](https://www.egosoft.com/download/x3ap/files/X3AP_SurvivalGuide_EN.pdf)
- [Egosoft: controller support for X3TC/X3AP](https://forum.egosoft.com/viewtopic.php?p=3993030)

## Translation layers
- [Box64 wiki](https://github.com/ptitSeb/box64/wiki): Box32 experimental
- [Box64 v0.4.2 release (April 2026)](https://sourceforge.net/projects/box64.mirror/files/v0.4.2/)
- [box86.org on Box64 0.3.2 / Box32](https://box86.org/2024/12/new-version-of-box64-v0-3-2-and-box86-v0-3-8/) and [box86.org](https://box86.org/): Box86 needs a 32-bit OS
- Box64 source (checked 13 Nov 2026, commit `6441fcfa`): `src/wrapped32/` wrapped-library list; `docs/USAGE.md` for DynaCache, BIGBLOCK, STRONGMEM; `CMakeLists.txt` options `BOX32`, `SD8G2`
- [FEX-Emu](https://fex-emu.com), [FEX ARM64EC/WOW64 wiki](https://wiki.fex-emu.com/index.php/Development:ARM64EC), [FEX-2501 release (WoW64/ARM64EC package)](https://www.linuxcompatible.org/story/fex2501-released)
- [Winlator Ludashi Plus (Arm64EC containers with FEXCore)](https://github.com/TripleJ160/winlator-ludashi-plus)

## Android storage
- [Google issue tracker 179412245: FUSE bypass only for app-private internal directories](https://issuetracker.google.com/issues/179412245)

## Your code
- [trasc-server-android](https://github.com/Russianranger/trasc-server-android): `ControllerInput.java`, `ControllerManager.java`, `AudioBridge.java`, `native/pcm_trasc.c`, `backend/client_audio.py`, `client-runtime/Dockerfile`, docs/controller-layers-0413.md, docs/client-performance.md
