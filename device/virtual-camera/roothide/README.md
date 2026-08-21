# RootHide

This variant targets RootHide devices only.

- Runtime root: validated output from `/usr/bin/jbroot`
- Theos scheme: `roothide`
- Package architecture: `iphoneos-arm64e`
- Daemon ABI: `arm64e (caps: PAC00)`
- Artifact directory: `artifacts/virtual-camera/roothide/`

Rebuild `../shared/NativeDaemonRender.c` with the device-native RootHide
clang/ld64 toolchain, sign it, and place the result at
`prebuilt/IOSMaxVirtualCameraDaemon.dylib`. Then package the WhatsApp-side
tweak with the RootHide Theos fork:

```sh
export THEOS=/path/to/roothide-theos
make clean package FINALPACKAGE=1
```

The `preinst` script rejects devices without a valid dynamic RootHide root.
