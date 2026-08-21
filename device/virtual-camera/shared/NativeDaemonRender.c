#include <CoreGraphics/CoreGraphics.h>
#include <CoreMedia/CoreMedia.h>
#include <CoreVideo/CoreVideo.h>
#include <mach-o/dyld.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

extern id objc_retain(id object);
extern void objc_release(id object);
extern void *objc_autoreleasePoolPush(void);
extern void objc_autoreleasePoolPop(void *context);

typedef void (*IOSMaxBWMRCOriginal)(id, SEL, CMSampleBufferRef, id);
typedef id (*IOSMaxMessageId0)(id, SEL);
typedef id (*IOSMaxMessageId1)(id, SEL, id);
typedef id (*IOSMaxMessageData)(id, SEL, const void *, unsigned long);
typedef id (*IOSMaxMessageColor)(id, SEL, double, double, double, double);
typedef id (*IOSMaxMessageTransform)(id, SEL, CGAffineTransform);
typedef id (*IOSMaxMessageRect)(id, SEL, CGRect);
typedef CGRect (*IOSMaxMessageCGRect)(id, SEL);
typedef void (*IOSMaxMessageRender)(id, SEL, id, CVPixelBufferRef, CGRect, CGColorSpaceRef);

static _Atomic(bool) gIOSMaxHookInstalled = false;
static _Atomic(bool) gIOSMaxEnabled = false;
static _Atomic(unsigned long long) gIOSMaxBuffersSeen = 0;
static _Atomic(unsigned long long) gIOSMaxFramesReplaced = 0;
static _Atomic(unsigned long long) gIOSMaxSessionFramesReplaced = 0;

static IOSMaxBWMRCOriginal gIOSMaxOriginalRender = 0;
static id gIOSMaxContext = 0;
static id gIOSMaxSourceImage = 0;
static id gIOSMaxPreparedImage = 0;
static CGColorSpaceRef gIOSMaxColorSpace = 0;
static size_t gIOSMaxPreparedWidth = 0;
static size_t gIOSMaxPreparedHeight = 0;
static OSType gIOSMaxPreparedPixelFormat = 0;
static pid_t gIOSMaxTargetPID = 0;
static struct timespec gIOSMaxControlModificationTime = { .tv_sec = -1, .tv_nsec = -1 };
static char gIOSMaxSharedDirectory[1024] = {0};
static char gIOSMaxControlPath[1200] = {0};
static char gIOSMaxFramePath[1200] = {0};
static char gIOSMaxStatusPath[1200] = {0};
static __thread bool gIOSMaxRendering = false;

static SEL IOSMaxSelector(const char *name) {
    return sel_registerName(name);
}

static void IOSMaxWriteStatus(
    const char *event,
    size_t width,
    size_t height,
    OSType pixelFormat,
    int errorCode
) {
    if (gIOSMaxStatusPath[0] == '\0') return;
    char buffer[1024];
    int length = snprintf(
        buffer,
        sizeof(buffer),
        "event=%s\n"
        "pid=%d\n"
        "target_pid=%d\n"
        "hook_installed=%d\n"
        "enabled=%d\n"
        "buffers_seen=%llu\n"
        "frames_replaced=%llu\n"
        "session_frames_replaced=%llu\n"
        "width=%zu\n"
        "height=%zu\n"
        "pixel_format=%u\n"
        "error_code=%d\n",
        event != 0 ? event : "unknown",
        getpid(),
        gIOSMaxTargetPID,
        atomic_load_explicit(&gIOSMaxHookInstalled, memory_order_relaxed) ? 1 : 0,
        atomic_load_explicit(&gIOSMaxEnabled, memory_order_relaxed) ? 1 : 0,
        atomic_load_explicit(&gIOSMaxBuffersSeen, memory_order_relaxed),
        atomic_load_explicit(&gIOSMaxFramesReplaced, memory_order_relaxed),
        atomic_load_explicit(&gIOSMaxSessionFramesReplaced, memory_order_relaxed),
        width,
        height,
        (unsigned int)pixelFormat,
        errorCode
    );
    if (length <= 0) return;
    if ((size_t)length >= sizeof(buffer)) length = (int)sizeof(buffer) - 1;
    int fd = open(gIOSMaxStatusPath, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return;
    (void)write(fd, buffer, (size_t)length);
    (void)close(fd);
}

static void IOSMaxInitializePaths(void) {
    // Dopamine exposes its bootstrap through /var/jb, but dyld may report the
    // canonical /private/preboot/.../procursus path for a loaded tweak. Start
    // with the Dopamine shared path and override it only for a RootHide image.
    snprintf(gIOSMaxSharedDirectory, sizeof(gIOSMaxSharedDirectory),
        "%s", "/var/jb/var/mobile/Library/Caches/com.iosmax.virtualcamera");
    uint32_t count = _dyld_image_count();
    for (uint32_t index = 0; index < count; ++index) {
        const char *path = _dyld_get_image_name(index);
        if (path == 0) continue;
        const char *marker = strstr(path, "/usr/lib/TweakInject/");
        if (strstr(path, "/.jbroot-") != 0 && marker != 0) {
            size_t rootLength = (size_t)(marker - path);
            if (rootLength == 0 || rootLength >= sizeof(gIOSMaxSharedDirectory) - 80) continue;
            memcpy(gIOSMaxSharedDirectory, path, rootLength);
            gIOSMaxSharedDirectory[rootLength] = '\0';
            strlcat(gIOSMaxSharedDirectory,
                "/var/mobile/Library/Caches/com.iosmax.virtualcamera",
                sizeof(gIOSMaxSharedDirectory));
            break;
        } else if (strncmp(path, "/var/jb/usr/lib/TweakInject/",
            strlen("/var/jb/usr/lib/TweakInject/")) == 0 ||
            strstr(path, "/procursus/usr/lib/TweakInject/") != 0) {
            break;
        } else {
            continue;
        }
    }
    snprintf(gIOSMaxControlPath, sizeof(gIOSMaxControlPath),
        "%s/daemon-control.txt", gIOSMaxSharedDirectory);
    snprintf(gIOSMaxFramePath, sizeof(gIOSMaxFramePath),
        "%s/frame.png", gIOSMaxSharedDirectory);
    snprintf(gIOSMaxStatusPath, sizeof(gIOSMaxStatusPath),
        "%s/daemon-status.txt", gIOSMaxSharedDirectory);
}

static void IOSMaxClearImages(void) {
    atomic_store_explicit(&gIOSMaxEnabled, false, memory_order_release);
    if (gIOSMaxPreparedImage != 0) {
        objc_release(gIOSMaxPreparedImage);
        gIOSMaxPreparedImage = 0;
    }
    if (gIOSMaxSourceImage != 0) {
        objc_release(gIOSMaxSourceImage);
        gIOSMaxSourceImage = 0;
    }
    gIOSMaxPreparedWidth = 0;
    gIOSMaxPreparedHeight = 0;
    gIOSMaxPreparedPixelFormat = 0;
}

static bool IOSMaxReadFile(const char *path, void **bytesOut, size_t *sizeOut) {
    *bytesOut = 0;
    *sizeOut = 0;
    int fd = open(path, O_RDONLY);
    if (fd < 0) return false;
    struct stat attributes;
    if (fstat(fd, &attributes) != 0 || attributes.st_size <= 0 ||
        attributes.st_size > 16 * 1024 * 1024) {
        close(fd);
        return false;
    }
    size_t size = (size_t)attributes.st_size;
    void *bytes = malloc(size + 1);
    if (bytes == 0) {
        close(fd);
        return false;
    }
    size_t offset = 0;
    while (offset < size) {
        ssize_t received = read(fd, (uint8_t *)bytes + offset, size - offset);
        if (received <= 0) break;
        offset += (size_t)received;
    }
    close(fd);
    if (offset != size) {
        free(bytes);
        return false;
    }
    ((uint8_t *)bytes)[size] = 0;
    *bytesOut = bytes;
    *sizeOut = size;
    return true;
}

static bool IOSMaxEnsureContext(void) {
    if (gIOSMaxContext != 0) return true;
    Class contextClass = objc_getClass("CIContext");
    if (contextClass == Nil) return false;
    id context = ((IOSMaxMessageId1)(void *)objc_msgSend)(
        (id)contextClass, IOSMaxSelector("contextWithOptions:"), 0);
    if (context == 0) return false;
    gIOSMaxContext = objc_retain(context);
    gIOSMaxColorSpace = CGColorSpaceCreateDeviceRGB();
    return gIOSMaxColorSpace != 0;
}

static bool IOSMaxLoadSourceImage(void) {
    void *bytes = 0;
    size_t size = 0;
    if (!IOSMaxReadFile(gIOSMaxFramePath, &bytes, &size)) return false;
    Class dataClass = objc_getClass("NSData");
    Class imageClass = objc_getClass("CIImage");
    if (dataClass == Nil || imageClass == Nil) {
        free(bytes);
        return false;
    }
    id data = ((IOSMaxMessageData)(void *)objc_msgSend)(
        (id)dataClass, IOSMaxSelector("dataWithBytes:length:"), bytes, (unsigned long)size);
    free(bytes);
    if (data == 0) return false;
    id image = ((IOSMaxMessageId1)(void *)objc_msgSend)(
        (id)imageClass, IOSMaxSelector("imageWithData:"), data);
    if (image == 0) return false;
    gIOSMaxSourceImage = objc_retain(image);
    return true;
}

static void IOSMaxReloadControlIfChanged(bool force) {
    if (gIOSMaxControlPath[0] == '\0') return;
    struct stat attributes;
    if (stat(gIOSMaxControlPath, &attributes) != 0) {
        if (gIOSMaxControlModificationTime.tv_sec != 0 ||
            gIOSMaxControlModificationTime.tv_nsec != 0) {
            IOSMaxClearImages();
            gIOSMaxTargetPID = 0;
            gIOSMaxControlModificationTime = (struct timespec){0, 0};
            IOSMaxWriteStatus("control-missing-disabled", 0, 0, 0, 0);
        }
        return;
    }
    struct timespec current = attributes.st_mtimespec;
    if (!force && current.tv_sec == gIOSMaxControlModificationTime.tv_sec &&
        current.tv_nsec == gIOSMaxControlModificationTime.tv_nsec) return;
    gIOSMaxControlModificationTime = current;

    void *bytes = 0;
    size_t size = 0;
    int requested = 0;
    int targetPID = 0;
    if (!IOSMaxReadFile(gIOSMaxControlPath, &bytes, &size) ||
        sscanf((const char *)bytes, "enabled=%d\ntarget_pid=%d", &requested, &targetPID) != 2) {
        free(bytes);
        IOSMaxClearImages();
        gIOSMaxTargetPID = 0;
        IOSMaxWriteStatus("control-invalid-disabled", 0, 0, 0, 1);
        return;
    }
    free(bytes);
    IOSMaxClearImages();
    gIOSMaxTargetPID = targetPID;
    if (!requested || targetPID <= 0) {
        IOSMaxWriteStatus("control-disabled", 0, 0, 0, 0);
        return;
    }

    void *pool = objc_autoreleasePoolPush();
    bool ready = IOSMaxEnsureContext() && IOSMaxLoadSourceImage();
    if (ready) {
        atomic_store_explicit(&gIOSMaxSessionFramesReplaced, 0, memory_order_relaxed);
        atomic_store_explicit(&gIOSMaxEnabled, true, memory_order_release);
    }
    IOSMaxWriteStatus(ready ? "control-enabled" : "image-load-failed-disabled", 0, 0, 0,
        ready ? 0 : 2);
    objc_autoreleasePoolPop(pool);
}

static bool IOSMaxRouteTargetsConfiguredProcess(id mrcNode) {
    id output = ((IOSMaxMessageId0)(void *)objc_msgSend)(
        mrcNode, IOSMaxSelector("output"));
    id connection = ((IOSMaxMessageId0)(void *)objc_msgSend)(
        output, IOSMaxSelector("connection"));
    id input = ((IOSMaxMessageId0)(void *)objc_msgSend)(
        connection, IOSMaxSelector("input"));
    id sink = ((IOSMaxMessageId0)(void *)objc_msgSend)(
        input, IOSMaxSelector("node"));
    if (sink == 0) return false;
    Ivar receiverPIDVariable = class_getInstanceVariable(
        object_getClass(sink), "_receiverPID");
    if (receiverPIDVariable == 0 ||
        strcmp(ivar_getTypeEncoding(receiverPIDVariable), "i") != 0) {
        return false;
    }
    int receiverPID = *(const int *)((const uint8_t *)(const void *)sink +
        ivar_getOffset(receiverPIDVariable));
    return gIOSMaxTargetPID > 0 && receiverPID == gIOSMaxTargetPID;
}

static bool IOSMaxPrepareImage(size_t width, size_t height, OSType pixelFormat) {
    if (gIOSMaxPreparedImage != 0 && gIOSMaxPreparedWidth == width &&
        gIOSMaxPreparedHeight == height && gIOSMaxPreparedPixelFormat == pixelFormat) return true;
    if (gIOSMaxPreparedImage != 0) {
        objc_release(gIOSMaxPreparedImage);
        gIOSMaxPreparedImage = 0;
    }
    if (gIOSMaxSourceImage == 0) return false;

    CGRect extent = ((IOSMaxMessageCGRect)(void *)objc_msgSend)(
        gIOSMaxSourceImage, IOSMaxSelector("extent"));
    if (CGRectIsEmpty(extent) || !isfinite(extent.size.width) ||
        !isfinite(extent.size.height)) return false;
    CGFloat target = (CGFloat)(width < height ? width : height) * 0.82;
    CGFloat scale = target / (extent.size.width > extent.size.height
        ? extent.size.width : extent.size.height);
    CGFloat scaledWidth = extent.size.width * scale;
    CGFloat scaledHeight = extent.size.height * scale;
    CGFloat translateX = ((CGFloat)width - scaledWidth) / 2.0 - extent.origin.x * scale;
    CGFloat translateY = ((CGFloat)height - scaledHeight) / 2.0 - extent.origin.y * scale;
    CGAffineTransform transform = CGAffineTransformMake(
        scale, 0, 0, scale, translateX, translateY);
    id foreground = ((IOSMaxMessageTransform)(void *)objc_msgSend)(
        gIOSMaxSourceImage, IOSMaxSelector("imageByApplyingTransform:"), transform);

    Class colorClass = objc_getClass("CIColor");
    Class imageClass = objc_getClass("CIImage");
    if (foreground == 0 || colorClass == Nil || imageClass == Nil) return false;
    id white = ((IOSMaxMessageColor)(void *)objc_msgSend)(
        (id)colorClass, IOSMaxSelector("colorWithRed:green:blue:alpha:"), 1, 1, 1, 1);
    id infiniteBackground = ((IOSMaxMessageId1)(void *)objc_msgSend)(
        (id)imageClass, IOSMaxSelector("imageWithColor:"), white);
    id background = ((IOSMaxMessageRect)(void *)objc_msgSend)(
        infiniteBackground, IOSMaxSelector("imageByCroppingToRect:"),
        CGRectMake(0, 0, width, height));
    id prepared = ((IOSMaxMessageId1)(void *)objc_msgSend)(
        foreground, IOSMaxSelector("imageByCompositingOverImage:"), background);
    if (prepared == 0) return false;
    gIOSMaxPreparedImage = objc_retain(prepared);
    gIOSMaxPreparedWidth = width;
    gIOSMaxPreparedHeight = height;
    gIOSMaxPreparedPixelFormat = pixelFormat;
    return true;
}

static bool IOSMaxSupportedPixelFormat(OSType pixelFormat) {
    return pixelFormat == kCVPixelFormatType_32BGRA ||
        pixelFormat == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange ||
        pixelFormat == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
}

static void IOSMaxProcessSampleBuffer(id mrcNode, CMSampleBufferRef sampleBuffer) {
    if (sampleBuffer == 0 || gIOSMaxRendering) return;
    unsigned long long seen =
        atomic_fetch_add_explicit(&gIOSMaxBuffersSeen, 1, memory_order_relaxed) + 1;
    if (seen == 1 || seen % 8 == 0) IOSMaxReloadControlIfChanged(false);
    if (!atomic_load_explicit(&gIOSMaxEnabled, memory_order_acquire) ||
        !IOSMaxRouteTargetsConfiguredProcess(mrcNode)) return;

    CVImageBufferRef imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (imageBuffer == 0) return;
    size_t width = CVPixelBufferGetWidth(imageBuffer);
    size_t height = CVPixelBufferGetHeight(imageBuffer);
    OSType pixelFormat = CVPixelBufferGetPixelFormatType(imageBuffer);
    if (!IOSMaxSupportedPixelFormat(pixelFormat)) {
        IOSMaxWriteStatus("pixel-format-unsupported-disabled", width, height, pixelFormat, 3);
        atomic_store_explicit(&gIOSMaxEnabled, false, memory_order_release);
        return;
    }

    void *pool = objc_autoreleasePoolPush();
    if (IOSMaxPrepareImage(width, height, pixelFormat)) {
        gIOSMaxRendering = true;
        ((IOSMaxMessageRender)(void *)objc_msgSend)(
            gIOSMaxContext,
            IOSMaxSelector("render:toCVPixelBuffer:bounds:colorSpace:"),
            gIOSMaxPreparedImage,
            (CVPixelBufferRef)imageBuffer,
            CGRectMake(0, 0, width, height),
            gIOSMaxColorSpace
        );
        gIOSMaxRendering = false;
        atomic_fetch_add_explicit(&gIOSMaxFramesReplaced, 1, memory_order_relaxed);
        unsigned long long sessionReplaced = atomic_fetch_add_explicit(
            &gIOSMaxSessionFramesReplaced, 1, memory_order_relaxed) + 1;
        if (sessionReplaced == 1 || sessionReplaced % 120 == 0) {
            IOSMaxWriteStatus("frame-replaced", width, height, pixelFormat, 0);
        }
    }
    objc_autoreleasePoolPop(pool);
}

static void IOSMaxRenderSampleBuffer(
    id self,
    SEL command,
    CMSampleBufferRef sampleBuffer,
    id input
) {
    IOSMaxProcessSampleBuffer(self, sampleBuffer);
    IOSMaxBWMRCOriginal original = gIOSMaxOriginalRender;
    if (original != 0) original(self, command, sampleBuffer, input);
}

static bool IOSMaxTryInstallHook(void) {
    if (atomic_load_explicit(&gIOSMaxHookInstalled, memory_order_acquire)) return true;
    Class nodeClass = objc_getClass("BWMRCNode");
    if (nodeClass == Nil) return false;
    SEL selector = IOSMaxSelector("renderSampleBuffer:forInput:");
    Method method = class_getInstanceMethod(nodeClass, selector);
    if (method == 0) return false;
    IMP previous = method_setImplementation(method, (IMP)&IOSMaxRenderSampleBuffer);
    if (previous == 0) return false;
    gIOSMaxOriginalRender = (IOSMaxBWMRCOriginal)previous;
    atomic_store_explicit(&gIOSMaxHookInstalled, true, memory_order_release);
    IOSMaxWriteStatus("mrc-hook-installed-disabled", 0, 0, 0, 0);
    return true;
}

static void *IOSMaxHookInstallerThread(void *unused) {
    (void)unused;
    for (unsigned int attempt = 0; attempt < 600; ++attempt) {
        if (IOSMaxTryInstallHook()) return 0;
        sleep(1);
    }
    IOSMaxWriteStatus("hook-install-timeout", 0, 0, 0, 4);
    return 0;
}

__attribute__((constructor))
static void IOSMaxNativeDaemonInitialize(void) {
    IOSMaxInitializePaths();
    IOSMaxReloadControlIfChanged(true);
    IOSMaxWriteStatus("native-daemon-loaded-disabled", 0, 0, 0, 0);
    if (IOSMaxTryInstallHook()) return;
    pthread_t thread;
    if (pthread_create(&thread, 0, IOSMaxHookInstallerThread, 0) == 0) {
        pthread_detach(thread);
    }
}
