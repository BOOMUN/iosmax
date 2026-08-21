# IOSMax Virtual Camera Variants

This directory is the authoritative source for virtual-camera packaging.
The two jailbreak environments are intentionally separate and must never
share an install artifact.

| Variant | Project | Package scheme | Architecture | Runtime root |
| --- | --- | --- | --- | --- |
| rootless (Dopamine) | `rootless/` | `rootless` | `iphoneos-arm64` | `/var/jb` |
| RootHide | `roothide/` | `roothide` | `iphoneos-arm64e` (PAC00) | `/usr/bin/jbroot` output |

Shared renderer source lives in `shared/NativeDaemonRender.c`. RootHide still
requires its device-native toolchain to rebuild the PAC00 daemon slice; the
signed result belongs in `roothide/prebuilt/`.

Build and publish artifacts into matching directories only:

```text
artifacts/virtual-camera/rootless/
artifacts/virtual-camera/roothide/
```

Both packages keep the same package identifier because they are alternative
implementations of the same device capability. Their version suffix,
architecture, custom control field, pre-install guard, artifact directory, and
device `jailbreak_type` distinguish them. The backend refuses injection when
the configured and detected variants differ.
