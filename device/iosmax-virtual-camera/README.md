# Legacy diagnostics and compatibility source

This directory no longer contains an authoritative package project.

- Shared native renderer: `../virtual-camera/shared/NativeDaemonRender.c`
- Rootless package: `../virtual-camera/rootless/`
- RootHide package: `../virtual-camera/roothide/`

The remaining Objective-C/Logos files are historical diagnostics. The
`NativeDaemonRender.c` file is only a compatibility include. Do not build or
publish a virtual-camera package from this directory.
