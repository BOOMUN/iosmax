#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <CoreImage/CoreImage.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#import <objc/runtime.h>
#import <dlfcn.h>
#import <mach-o/dyld.h>
#import <pthread.h>
#import <unistd.h>
#import <stdint.h>
#import <string.h>
#import <stdbool.h>
#import <stdatomic.h>
#import <math.h>

@interface NSObject (IOSMaxBWCameraGraph)
- (id)output;
- (id)connection;
- (id)input;
- (id)node;
@end

static atomic_bool gHookInstalled = false;
static atomic_bool gEnabled = false;
static atomic_ullong gBuffersSeen = 0;
static atomic_ullong gFramesReplaced = 0;

static CIContext *gCIContext;
static CIImage *gSourceImage;
static NSMutableDictionary<NSString *, CIImage *> *gPreparedImages;
static CGColorSpaceRef gColorSpace;
static NSString *gSharedDirectory;
static NSString *gLastError;
static NSTimeInterval gLastControlModificationTime = -1;
static pid_t gTargetPID = 0;
static __thread BOOL gRendering = NO;
static pthread_mutex_t gStateMutex = PTHREAD_MUTEX_INITIALIZER;
static ptrdiff_t gReceiverPIDOffset = -1;

typedef void (*IOSMaxBWMRCOriginal)(id, SEL, CMSampleBufferRef, id);
static IOSMaxBWMRCOriginal gOriginalRenderSampleBuffer = NULL;

static NSString *IOSMaxDeriveJBRoot(void) {
    Dl_info info = {};
    if (dladdr((const void *)&IOSMaxDeriveJBRoot, &info) == 0 || info.dli_fname == NULL) {
        return nil;
    }
    const char *resolvedPath = info.dli_fname;
    uint32_t imageCount = _dyld_image_count();
    for (uint32_t index = 0; index < imageCount; ++index) {
        if ((const void *)_dyld_get_image_header(index) == info.dli_fbase) {
            const char *candidate = _dyld_get_image_name(index);
            if (candidate != NULL) resolvedPath = candidate;
            break;
        }
    }
    NSString *imagePath = [NSString stringWithUTF8String:resolvedPath];
    NSRange marker = [imagePath rangeOfString:@"/usr/lib/TweakInject/"];
    if (marker.location == NSNotFound) return nil;
    return [imagePath substringToIndex:marker.location];
}

static NSString *IOSMaxControlPath(void) {
    return [gSharedDirectory stringByAppendingPathComponent:@"control.plist"];
}

static NSString *IOSMaxStatusPath(void) {
    return [gSharedDirectory stringByAppendingPathComponent:@"daemon-status.plist"];
}

static void IOSMaxSetError(NSString *message) {
    pthread_mutex_lock(&gStateMutex);
    gLastError = [message copy];
    pthread_mutex_unlock(&gStateMutex);
}

static void IOSMaxWriteStatus(NSString *event, size_t width, size_t height, OSType pixelFormat) {
    if (gSharedDirectory.length == 0) return;
    NSString *error;
    pid_t targetPID;
    pthread_mutex_lock(&gStateMutex);
    error = [gLastError copy];
    targetPID = gTargetPID;
    pthread_mutex_unlock(&gStateMutex);
    NSMutableDictionary *status = [@{
        @"ProbeLoaded": @YES,
        @"HookInstalled": @(atomic_load_explicit(&gHookInstalled, memory_order_relaxed)),
        @"Enabled": @(atomic_load_explicit(&gEnabled, memory_order_relaxed)),
        @"Event": event ?: @"unknown",
        @"PID": @(getpid()),
        @"TargetPID": @(targetPID),
        @"BuffersSeen": @(atomic_load_explicit(&gBuffersSeen, memory_order_relaxed)),
        @"FramesReplaced": @(atomic_load_explicit(&gFramesReplaced, memory_order_relaxed)),
        @"Width": @(width),
        @"Height": @(height),
        @"PixelFormat": @((uint32_t)pixelFormat),
        @"UpdatedAt": [NSDate date],
    } mutableCopy];
    if (error.length > 0) status[@"LastError"] = error;
    [status writeToFile:IOSMaxStatusPath() atomically:YES];
}

static void IOSMaxReloadControl(void) {
    @autoreleasepool {
        NSString *controlPath = IOSMaxControlPath();
        NSDictionary *attributes = [[NSFileManager defaultManager]
            attributesOfItemAtPath:controlPath error:nil];
        NSDate *modificationDate = attributes[NSFileModificationDate];
        NSDictionary *control = [NSDictionary dictionaryWithContentsOfFile:controlPath];
        BOOL requested = [control[@"Enabled"] boolValue];
        pid_t targetPID = (pid_t)[control[@"TargetPID"] intValue];
        NSString *imageName = control[@"ImageName"];
        if (![imageName isKindOfClass:NSString.class] || imageName.length == 0 ||
            ![[imageName lastPathComponent] isEqualToString:imageName]) {
            imageName = @"frame.png";
        }
        NSString *imagePath = [gSharedDirectory stringByAppendingPathComponent:imageName];
        CIImage *image = requested && targetPID > 0
            ? [CIImage imageWithContentsOfURL:[NSURL fileURLWithPath:imagePath]]
            : nil;

        pthread_mutex_lock(&gStateMutex);
        gTargetPID = targetPID;
        gSourceImage = image;
        [gPreparedImages removeAllObjects];
        gLastControlModificationTime = modificationDate != nil
            ? modificationDate.timeIntervalSince1970
            : 0;
        if (requested && targetPID <= 0) {
            gLastError = @"TargetPID must identify the active WhatsApp process";
        } else if (requested && image == nil) {
            gLastError = [NSString stringWithFormat:@"Unable to load %@", imageName];
        } else {
            gLastError = nil;
        }
        pthread_mutex_unlock(&gStateMutex);
        atomic_store_explicit(
            &gEnabled, requested && targetPID > 0 && image != nil, memory_order_release);
        IOSMaxWriteStatus(@"control-reloaded", 0, 0, 0);
    }
}

static void IOSMaxReloadControlIfChanged(void) {
    NSDictionary *attributes = [[NSFileManager defaultManager]
        attributesOfItemAtPath:IOSMaxControlPath() error:nil];
    NSDate *modificationDate = attributes[NSFileModificationDate];
    NSTimeInterval current = modificationDate != nil ? modificationDate.timeIntervalSince1970 : 0;
    NSTimeInterval previous;
    pthread_mutex_lock(&gStateMutex);
    previous = gLastControlModificationTime;
    pthread_mutex_unlock(&gStateMutex);
    if (current != previous) IOSMaxReloadControl();
}

static BOOL IOSMaxRouteTargetsConfiguredProcess(id mrcNode) {
    id output = [mrcNode output];
    id connection = [output connection];
    id input = [connection input];
    id sink = [input node];
    if (sink == nil) return NO;
    if (gReceiverPIDOffset < 0) {
        Ivar receiverPID = class_getInstanceVariable(object_getClass(sink), "_receiverPID");
        if (receiverPID == NULL || strcmp(ivar_getTypeEncoding(receiverPID), "i") != 0) {
            return NO;
        }
        gReceiverPIDOffset = ivar_getOffset(receiverPID);
    }
    int receiverPID = *(const int *)((const uint8_t *)(__bridge const void *)sink +
        gReceiverPIDOffset);
    pthread_mutex_lock(&gStateMutex);
    pid_t targetPID = gTargetPID;
    pthread_mutex_unlock(&gStateMutex);
    return targetPID > 0 && receiverPID == targetPID;
}

static BOOL IOSMaxSupportedPixelFormat(OSType pixelFormat) {
    return pixelFormat == kCVPixelFormatType_32BGRA ||
        pixelFormat == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange ||
        pixelFormat == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
}

static CIImage *IOSMaxPreparedImage(size_t width, size_t height, OSType pixelFormat) {
    NSString *key = [NSString stringWithFormat:@"%zux%zu-%u", width, height, (uint32_t)pixelFormat];
    pthread_mutex_lock(&gStateMutex);
    CIImage *cached = gPreparedImages[key];
    if (cached != nil) {
        pthread_mutex_unlock(&gStateMutex);
        return cached;
    }
    if (gSourceImage == nil) {
        pthread_mutex_unlock(&gStateMutex);
        return nil;
    }

    CGRect extent = gSourceImage.extent;
    if (CGRectIsEmpty(extent) || !isfinite(extent.size.width) ||
        !isfinite(extent.size.height)) {
        gLastError = @"Source image has an invalid extent";
        pthread_mutex_unlock(&gStateMutex);
        return nil;
    }
    CGFloat target = MIN((CGFloat)width, (CGFloat)height) * 0.82;
    CGFloat scale = target / MAX(extent.size.width, extent.size.height);
    CGFloat scaledWidth = extent.size.width * scale;
    CGFloat scaledHeight = extent.size.height * scale;
    CGFloat translateX = ((CGFloat)width - scaledWidth) / 2.0 - extent.origin.x * scale;
    CGFloat translateY = ((CGFloat)height - scaledHeight) / 2.0 - extent.origin.y * scale;
    CGAffineTransform transform = CGAffineTransformMake(
        scale, 0, 0, scale, translateX, translateY);
    CIImage *foreground = [gSourceImage imageByApplyingTransform:transform];
    CIImage *background = [[CIImage imageWithColor:
        [CIColor colorWithRed:1 green:1 blue:1 alpha:1]]
        imageByCroppingToRect:CGRectMake(0, 0, width, height)];
    CIImage *prepared = [foreground imageByCompositingOverImage:background];
    gPreparedImages[key] = prepared;
    pthread_mutex_unlock(&gStateMutex);
    return prepared;
}

static void IOSMaxProcessSampleBuffer(id mrcNode, CMSampleBufferRef sampleBuffer) {
    if (sampleBuffer == NULL || gRendering) return;
    unsigned long long seen =
        atomic_fetch_add_explicit(&gBuffersSeen, 1, memory_order_relaxed) + 1;
    if (seen == 1 || seen % 8 == 0) IOSMaxReloadControlIfChanged();
    if (!atomic_load_explicit(&gEnabled, memory_order_acquire) ||
        !IOSMaxRouteTargetsConfiguredProcess(mrcNode)) return;

    CVImageBufferRef imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (imageBuffer == NULL) return;
    size_t width = CVPixelBufferGetWidth(imageBuffer);
    size_t height = CVPixelBufferGetHeight(imageBuffer);
    OSType pixelFormat = CVPixelBufferGetPixelFormatType(imageBuffer);
    if (!IOSMaxSupportedPixelFormat(pixelFormat)) {
        if (seen == 1 || seen % 120 == 0) {
            IOSMaxSetError([NSString stringWithFormat:@"Unsupported pixel format %u",
                (uint32_t)pixelFormat]);
            IOSMaxWriteStatus(@"buffer-skipped", width, height, pixelFormat);
        }
        return;
    }

    @autoreleasepool {
        CIImage *prepared = IOSMaxPreparedImage(width, height, pixelFormat);
        if (prepared == nil) return;
        gRendering = YES;
        [gCIContext render:prepared
           toCVPixelBuffer:(CVPixelBufferRef)imageBuffer
                     bounds:CGRectMake(0, 0, width, height)
                 colorSpace:gColorSpace];
        gRendering = NO;
        unsigned long long replaced =
            atomic_fetch_add_explicit(&gFramesReplaced, 1, memory_order_relaxed) + 1;
        if (replaced == 1 || replaced % 120 == 0) {
            IOSMaxSetError(nil);
            IOSMaxWriteStatus(@"frame-replaced", width, height, pixelFormat);
        }
    }
}

static void IOSMaxRenderSampleBuffer(id self, SEL command, CMSampleBufferRef sampleBuffer, id input) {
    @autoreleasepool {
        IOSMaxProcessSampleBuffer(self, sampleBuffer);
    }
    IOSMaxBWMRCOriginal original = gOriginalRenderSampleBuffer;
    if (original != NULL) original(self, command, sampleBuffer, input);
}

static BOOL IOSMaxTryInstallHook(void) {
    Class nodeClass = objc_getClass("BWMRCNode");
    if (nodeClass == Nil) return NO;
    SEL selector = sel_registerName("renderSampleBuffer:forInput:");
    Method method = class_getInstanceMethod(nodeClass, selector);
    if (method == NULL) return NO;
    IMP previous = method_setImplementation(method, (IMP)&IOSMaxRenderSampleBuffer);
    if (previous == NULL) return NO;
    gOriginalRenderSampleBuffer = (IOSMaxBWMRCOriginal)previous;
    atomic_store_explicit(&gHookInstalled, true, memory_order_release);
    IOSMaxWriteStatus(@"mrc-hook-installed-disabled", 0, 0, 0);
    return YES;
}

static void *IOSMaxHookInstallerThread(void *unused) {
    (void)unused;
    for (unsigned int attempt = 0; attempt < 600; ++attempt) {
        @autoreleasepool {
            if (IOSMaxTryInstallHook()) return NULL;
        }
        sleep(1);
    }
    @autoreleasepool {
        IOSMaxSetError(@"BWMRCNode did not become available");
        IOSMaxWriteStatus(@"hook-install-timeout", 0, 0, 0);
    }
    return NULL;
}

__attribute__((constructor))
static void IOSMaxNativeDaemonInitialize(void) {
    @autoreleasepool {
        gPreparedImages = [NSMutableDictionary new];
        NSString *jbRoot = IOSMaxDeriveJBRoot();
        if (jbRoot.length > 0) {
            gSharedDirectory = [jbRoot stringByAppendingPathComponent:
                @"var/mobile/Library/Caches/com.iosmax.virtualcamera"];
        }
        IOSMaxWriteStatus(@"native-daemon-path-ready", 0, 0, 0);
        gCIContext = [CIContext contextWithOptions:nil];
        gColorSpace = CGColorSpaceCreateDeviceRGB();
        IOSMaxReloadControl();
        IOSMaxWriteStatus(@"native-daemon-loaded-disabled", 0, 0, 0);

        if (IOSMaxTryInstallHook()) return;
        pthread_t thread;
        if (pthread_create(&thread, NULL, IOSMaxHookInstallerThread, NULL) == 0) {
            pthread_detach(thread);
        } else {
            IOSMaxSetError(@"Unable to start BWMRC hook installer thread");
            IOSMaxWriteStatus(@"hook-thread-failed", 0, 0, 0);
        }
    }
}
