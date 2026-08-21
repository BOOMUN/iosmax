# Rootless (Dopamine)

This variant targets Dopamine-style rootless devices only.

- Bootstrap root: `/var/jb`
- Theos scheme: `rootless`
- Package architecture: `iphoneos-arm64`
- Artifact directory: `artifacts/virtual-camera/rootless/`

Build with standard rootless Theos:

```sh
export THEOS=/path/to/theos
make clean package FINALPACKAGE=1
```

The `preinst` script rejects a detected RootHide environment before unpacking.
