# WhatsApp is arm64-only. The mediaserverd renderer is built separately with
# the device-native RootHide toolchain so its slice uses the matching PAC00 ABI.
ARCHS = arm64
TARGET = iphone:clang:latest:15.0
THEOS_PACKAGE_SCHEME = roothide
INSTALL_TARGET_PROCESSES = WhatsApp mediaserverd

include $(THEOS)/makefiles/common.mk

TWEAK_NAME = IOSMaxVirtualCamera

IOSMaxVirtualCamera_FILES = Tweak.xm
IOSMaxVirtualCamera_CFLAGS = -fobjc-arc -Wall -Wextra -DIOSMAX_LOAD_PROBE=0
IOSMaxVirtualCamera_FRAMEWORKS = Foundation CoreGraphics CoreImage CoreMedia CoreVideo

include $(THEOS_MAKE_PATH)/tweak.mk

after-stage::
	$(ECHO_NOTHING)mkdir -p $(THEOS_STAGING_DIR)/Library/MobileSubstrate/DynamicLibraries$(ECHO_END)
	$(ECHO_NOTHING)cp prebuilt/IOSMaxVirtualCameraDaemon.dylib $(THEOS_STAGING_DIR)/Library/MobileSubstrate/DynamicLibraries/$(ECHO_END)
	$(ECHO_NOTHING)cp IOSMaxVirtualCameraDaemon.plist $(THEOS_STAGING_DIR)/Library/MobileSubstrate/DynamicLibraries/$(ECHO_END)
