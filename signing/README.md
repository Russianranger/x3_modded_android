# Preview signing key

`x3-preview.keystore` signs every CI build so new APKs install **over** the previous one. That
keeps your imported game, Wine prefix, saves and controller profile. A per-build debug key would
force an uninstall, which deletes all of that.

- Store/key password: `android`, alias `x3preview` (PKCS12, RSA-3072).
- Certificate SHA-256: see `x3-preview.sha256`. CI checks every APK against it.

This key is public because it lives in this repository. Anyone could sign an APK that Android
accepts as an update to this app, so **only install APKs from this repository's Releases page**.
For wider distribution, switch to a private key stored as a GitHub Actions secret.
