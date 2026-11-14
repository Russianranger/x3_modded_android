Rolling preview of **X3 Modded** for ARM64 Android handhelds (built for the AYN Thor). It runs your
own Windows X3: Albion Prelude, with or without LxXRM, through Wine 10 WoW64, Box64, DXVK and Turnip.
Sound goes through Android AudioTrack.

Every push to `main` replaces the APK. The APK is signed with the repository's public preview key,
so each new build installs over the previous one and keeps your imported game, prefix, saves and
controls.

**First run**

1. Install `x3-modded-android-preview.apk`.
2. On the **Runtime** card, choose **Download runtime**. This is TRASC's client runtime: about 340 MB,
   checked against its SHA-256.
3. On the **Game files** card, choose **Import X3 folder**. Pick the folder that contains `X3AP.exe`,
   or its parent folder. The files are copied into app storage, which keeps them off slow shared
   storage. LxXRM's `_DOWNLOADS` installer archives are left out by default. The card then shows
   whether `X3AP.exe` is the NoSteam build.
4. Choose **Launch**. In X3's own settings, turn **EAX off**. Saves and settings are kept in app
   storage, outside the Wine prefix, so **Reset Wine prefix** and updates don't touch them.

**Controls**

- Hold **Select** to see the help overlay. **Select + Start** keeps it on screen.
- Use **Select + D-pad** to switch between the Flight, Navigate, Menus and Command layers.
- Hold **L2** for the Combat layer.
- The gear menu has the keyboard, the controller mapping editor and **Stop game**.

`build-info.json` lists the commit, the APK's SHA-256 and the pinned payload sources.
`launcher-sources.tar.gz` holds the corresponding sources for the bundled GPL and LGPL binaries.
See `THIRD_PARTY_NOTICES.md`.

Only install APKs from this page: the preview signing key is public.
