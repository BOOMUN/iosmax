ARCHS = arm64
TARGET = iphone:clang:latest:15.0
THEOS_PACKAGE_SCHEME = rootless
INSTALL_TARGET_PROCESSES = mediaserverd

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = IOSMaxVirtualCameraDaemon

IOSMaxVirtualCameraDaemon_FILES = ../shared/NativeDaemonRender.c
IOSMaxVirtualCameraDaemon_CFLAGS = -std=gnu11 -Wall -Wextra -fvisibility=hidden
IOSMaxVirtualCameraDaemon_FRAMEWORKS = CoreGraphics CoreImage CoreMedia CoreVideo
IOSMaxVirtualCameraDaemon_LIBRARIES = objc

include $(THEOS_MAKE_PATH)/tweak.mk
