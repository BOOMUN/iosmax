# Jailbreak kit packaging

This directory defines the reproducible Windows installation kit used for the
validated Dopamine rootless deployment. Third-party binaries are intentionally
excluded from Git and are read from the operator's local `Downloads` directory.

Build the offline archive from the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\packaging\jailbreak-kit\build-jailbreak-kit.ps1
```

The default output is written under `artifacts/jailbreak-kit/`, which is ignored
by Git. The build fails unless file names, byte lengths, and SHA-256 values match
`manifest.json` exactly.

The pinned Dopamine 3.0.7 IPA reproduces the version validated on the managed
devices. It must not be silently replaced by a newer release. Sideloadly 0.60.0
is obtained from its official website, but its Windows installer is not
Authenticode-signed and the publisher does not publish a checksum. Do not upload
or publicly redistribute that installer without confirming redistribution
permission from its publisher.

Dopamine intentionally contains jailbreak exploit implementations, and
Microsoft Defender can classify components in the official IPA as
`Exploit:MacOS/*`. Treat the kit as security-sensitive: verify the pinned hash,
use it only on an owned or explicitly authorized device, and do not disable
endpoint protection permanently. The tested Sideloadly installer produced no
Defender detection, but its unsigned status still requires exact hash checking.
