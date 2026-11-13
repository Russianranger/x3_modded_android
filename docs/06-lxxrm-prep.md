# 6. Preparing the LxXRM game folder

LxXRM 3.1 ("Lucike XRM Resurrection Modding Package", last updated 6 Oct 2019) is a **package with an
installer, not a mod by itself**. Its `SETUP.bat` installs XRM, all of Lucike's scripts and his fake
patches, the missing English text files, optional TCAP-for-AP and Lost Colony, a compatibility "fix
mix", a full X3 Customizer tweak set, the CPP performance patch, Awesomefied Weapons, complex and
equipment-dock extras, and X3-Resurrection 3.0 with its XRM compatibility pack and patch 3.2.

## Route B (Windows build): assemble on a PC, then import

1. Install X3: Terran Conflict and X3: Albion Prelude (Steam or GOG) on a Windows PC.
2. Download `LxXRM31.zip`, unzip it, and put every archive the thread lists into
   `LxXRM/_DOWNLOADS` **without unpacking them**. For Steam copies, that includes Egosoft's
   NoSteam `X3AP.exe` (Egosoft's downloads page; it requires a registered game). Non-Steam copies
   just provide their normal `X3AP.exe`.
3. Run `LxXRM/SETUP.bat` and pick the options you want.
4. Optional: start the game once on the PC to confirm it works, and set EAX off in the launcher.
5. Zip the whole Terran Conflict folder (it contains `addon/` for AP), copy it to the device and
   import it in the app. The app copies it into private storage.
6. Saves: copy your `Documents\Egosoft\X3AP\save` folder too if you want to continue a game (path
   to be confirmed; see docs/01).

`tools/probe_x3_install.py` on the PC copy (with Python 3) records the baseline: executables, LAA
flag, sizes, file counts and catalog numbering.

## Route A (native Linux build): reuse the data, keep Linux binaries

1. Start from a **vanilla Linux** Terran War Pack (GOG Linux installer or Steam Linux depot,
   July 2021 or later). Run the probe on it and keep the report. It shows whether Egosoft's own
   data files are lowercase, which is the naming convention to match.
2. From the finished Windows LxXRM install, copy the **data** over the Linux install: numbered
   `cat`/`dat` files in the root and `addon/`, and the `scripts`, `t`, `director`, `types`, `maps`
   and other data folders. **Never** copy `.exe`, `.dll` or Windows-only tools.
3. XRM Part 3 sounds: the XRM guide says not to use Part 3 on Linux/macOS and to install the XRM
   **Linux patch** instead. Copy its `mov` folder into `addon/` and its `soundtrack` folder into the
   TC root (not `addon/`).
4. X3 Customizer output is portable. Its transforms edit game data (`L/x3story.obj`, scripts,
   director XML), not the executable. Both builds should be AP 3.3; confirm with the probe.
5. Case: compare both probe reports. If Phase-0 strace (docs/01) shows the native build failing on
   mixed-case names, run `tools/normalize_case.py <copy> --only addon` (dry run first). Watch
   language files like `7311-L044.xml`: match whatever case Egosoft's own Linux files use, don't
   guess. The tool refuses to run if two names would collide, and it writes a manifest for
   `--revert`.
6. Saves live in `~/.config/EgoSoft/X3AP/save` on the Linux build. Windows saves should load if both
   builds are 3.3, but test with a copy.

## Catalog sanity

X3 loads numbered catalogs in sequence. The probe flags gaps (e.g. `01 02 03 05`) and a `.cat`
without its `.dat`. LxXRM's installer handles numbering on Windows; recheck it after any manual
copying for Route A.
