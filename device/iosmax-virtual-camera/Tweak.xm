#import <Foundation/Foundation.h>
#import <CoreImage/CoreImage.h>
#import <CoreMedia/CoreMedia.h>
#import <CoreVideo/CoreVideo.h>
#import <substrate.h>
#import <dlfcn.h>
#import <math.h>
#import <atomic>

static NSString *const kIOSMaxDirectoryName = @"com.iosmax.virtualcamera";
static NSString *const kIOSMaxReloadNotification = @"com.iosmax.virtualcamera.reload";

#if IOSMAX_LOAD_PROBE

%ctor {
    @autoreleasepool {
        if (![NSBundle.mainBundle.bundleIdentifier isEqualToString:@"net.whatsapp.WhatsApp"]) return;

        NSString *directory = [NSHomeDirectory() stringByAppendingPathComponent:
            [@"Library/Caches" stringByAppendingPathComponent:kIOSMaxDirectoryName]];
        NSError *directoryError = nil;
        BOOL directoryReady = [[NSFileManager defaultManager]
            createDirectoryAtPath:directory
            withIntermediateDirectories:YES
            attributes:nil
            error:&directoryError];
        NSMutableDictionary *status = [@{
            @"ProbeLoaded": @YES,
            @"HookInstalled": @NO,
            @"Enabled": @NO,
            @"Event": @"load-probe",
            @"UpdatedAt": [NSDate date],
            @"Process": NSProcessInfo.processInfo.processName ?: @"",
        } mutableCopy];
        if (!directoryReady && directoryError != nil) {
            status[@"LastError"] = directoryError.localizedDescription ?: @"Unable to create status directory";
        }
        [status writeToFile:[directory stringByAppendingPathComponent:@"status.plist"] atomically:YES];
    }
}

#else

static std::atomic_bool gHookInstalled(false);
static std::atomic_bool gCaptureManagerHookInstalled(false);
static std::atomic_bool gEnabled(false);
static std::atomic_bool gTargetScannerVisible(false);
static std::atomic_ullong gBuffersSeen(0);
static std::atomic_ullong gFramesReplaced(0);
static std::atomic_ullong gLastReloadCheck(0);

static NSObject *gStateLock;
static CIContext *gCIContext;
static CIImage *gSourceImage;
static NSMutableDictionary<NSString *, CIImage *> *gPreparedImages;
static dispatch_queue_t gStatusQueue;
static CGColorSpaceRef gColorSpace;
static NSUInteger gMinimumWidth = 320;
static NSUInteger gMinimumHeight = 240;
static NSString *gLastError;
static NSTimeInterval gLastControlModificationTime = -1;
static __thread BOOL gRendering = NO;

static NSString *IOSMaxDirectory(void) {
    return [NSHomeDirectory() stringByAppendingPathComponent:
        [@"Library/Caches" stringByAppendingPathComponent:kIOSMaxDirectoryName]];
}

static NSString *IOSMaxControlPath(void) {
    return [IOSMaxDirectory() stringByAppendingPathComponent:@"control.plist"];
}

static NSString *IOSMaxStatusPath(void) {
    return [IOSMaxDirectory() stringByAppendingPathComponent:@"status.plist"];
}

static void IOSMaxWriteStatus(NSString *event, size_t width, size_t height, OSType pixelFormat) {
    const unsigned long long seen = gBuffersSeen.load(std::memory_order_relaxed);
    const unsigned long long replaced = gFramesReplaced.load(std::memory_order_relaxed);
    const BOOL enabled = gEnabled.load(std::memory_order_relaxed);
    const BOOL scannerVisible = gTargetScannerVisible.load(std::memory_order_relaxed);
    NSString *error;
    @synchronized (gStateLock) {
        error = gLastError;
    }
    dispatch_async(gStatusQueue, ^{
        @autoreleasepool {
            NSMutableDictionary *status = [@{
                @"HookInstalled": @(gHookInstalled.load(std::memory_order_relaxed)),
                @"CaptureManagerHookInstalled": @(gCaptureManagerHookInstalled.load(std::memory_order_relaxed)),
                @"Enabled": @(enabled),
                @"TargetScannerVisible": @(scannerVisible),
                @"Event": event ?: @"unknown",
                @"BuffersSeen": @(seen),
                @"FramesReplaced": @(replaced),
                @"Width": @(width),
                @"Height": @(height),
                @"PixelFormat": @((uint32_t)pixelFormat),
                @"UpdatedAt": [NSDate date],
                @"Process": NSProcessInfo.processInfo.processName ?: @"",
            } mutableCopy];
            if (error.length > 0) status[@"LastError"] = error;
            [status writeToFile:IOSMaxStatusPath() atomically:YES];
        }
    });
}

static void IOSMaxSetError(NSString *message) {
    @synchronized (gStateLock) {
        gLastError = [message copy];
    }
}

static void IOSMaxReloadControl(void) {
    @autoreleasepool {
        NSString *controlPath = IOSMaxControlPath();
        NSDictionary *attributes = [[NSFileManager defaultManager]
            attributesOfItemAtPath:controlPath error:nil];
        NSDate *modificationDate = attributes[NSFileModificationDate];
        NSDictionary *control = [NSDictionary dictionaryWithContentsOfFile:controlPath];
        const BOOL enabled = [control[@"Enabled"] boolValue];
        const NSUInteger minimumWidth = MAX((NSUInteger)64, [control[@"MinimumWidth"] unsignedIntegerValue]);
        const NSUInteger minimumHeight = MAX((NSUInteger)64, [control[@"MinimumHeight"] unsignedIntegerValue]);
        NSString *imageName = control[@"ImageName"];
        if (![imageName isKindOfClass:NSString.class] || imageName.length == 0 ||
            [imageName containsString:@"/"]) {
            imageName = @"frame.png";
        }
        NSString *imagePath = [IOSMaxDirectory() stringByAppendingPathComponent:imageName];
        CIImage *image = enabled ? [CIImage imageWithContentsOfURL:[NSURL fileURLWithPath:imagePath]] : nil;

        @synchronized (gStateLock) {
            gMinimumWidth = minimumWidth;
            gMinimumHeight = minimumHeight;
            gSourceImage = image;
            [gPreparedImages removeAllObjects];
            if (enabled && image == nil) {
                gLastError = [NSString stringWithFormat:@"Unable to load %@", imageName];
            } else {
                gLastError = nil;
            }
            gLastControlModificationTime = modificationDate != nil
                ? modificationDate.timeIntervalSince1970
                : 0;
        }
        gEnabled.store(enabled && image != nil, std::memory_order_release);
        IOSMaxWriteStatus(@"control-reloaded", 0, 0, 0);
    }
}

static void IOSMaxReloadControlIfChanged(void) {
    @autoreleasepool {
        NSDictionary *attributes = [[NSFileManager defaultManager]
            attributesOfItemAtPath:IOSMaxControlPath() error:nil];
        NSDate *modificationDate = attributes[NSFileModificationDate];
        NSTimeInterval current = modificationDate != nil
            ? modificationDate.timeIntervalSince1970
            : 0;
        NSTimeInterval previous;
        @synchronized (gStateLock) {
            previous = gLastControlModificationTime;
        }
        if (current != previous) IOSMaxReloadControl();
    }
}

static CIImage *IOSMaxPreparedImage(size_t width, size_t height, OSType pixelFormat) {
    NSString *key = [NSString stringWithFormat:@"%zux%zu-%u", width, height, (uint32_t)pixelFormat];
    @synchronized (gStateLock) {
        CIImage *cached = gPreparedImages[key];
        if (cached != nil) return cached;
        if (gSourceImage == nil) return nil;

        CGRect extent = gSourceImage.extent;
        if (CGRectIsEmpty(extent) || !isfinite(extent.size.width) || !isfinite(extent.size.height)) {
            gLastError = @"Source image has an invalid extent";
            return nil;
        }
        CGFloat target = MIN((CGFloat)width, (CGFloat)height) * 0.82;
        CGFloat scale = target / MAX(extent.size.width, extent.size.height);
        CGFloat scaledWidth = extent.size.width * scale;
        CGFloat scaledHeight = extent.size.height * scale;
        CGFloat translateX = ((CGFloat)width - scaledWidth) / 2.0 - extent.origin.x * scale;
        CGFloat translateY = ((CGFloat)height - scaledHeight) / 2.0 - extent.origin.y * scale;
        CGAffineTransform transform = CGAffineTransformMake(scale, 0, 0, scale, translateX, translateY);
        CIImage *foreground = [gSourceImage imageByApplyingTransform:transform];
        CIImage *background = [[CIImage imageWithColor:[CIColor colorWithRed:1 green:1 blue:1 alpha:1]]
            imageByCroppingToRect:CGRectMake(0, 0, width, height)];
        CIImage *prepared = [foreground imageByCompositingOverImage:background];
        gPreparedImages[key] = prepared;
        return prepared;
    }
}

static BOOL IOSMaxSupportedPixelFormat(OSType pixelFormat) {
    return pixelFormat == kCVPixelFormatType_32BGRA ||
        pixelFormat == kCVPixelFormatType_420YpCbCr8BiPlanarFullRange ||
        pixelFormat == kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange;
}

static void IOSMaxProcessSampleBuffer(CMSampleBufferRef sampleBuffer) {
    if (sampleBuffer == nullptr || gRendering ||
        !gTargetScannerVisible.load(std::memory_order_acquire)) return;
    CVImageBufferRef imageBuffer = CMSampleBufferGetImageBuffer(sampleBuffer);
    if (imageBuffer == nullptr) return;

    const unsigned long long seen = gBuffersSeen.fetch_add(1, std::memory_order_relaxed) + 1;
    // Check for a changed control file about once every 120 image-buffer accesses.
    // This also lets the controller disable replacement without restarting WhatsApp.
    unsigned long long lastCheck = gLastReloadCheck.load(std::memory_order_relaxed);
    if (seen - lastCheck >= 120 &&
        gLastReloadCheck.compare_exchange_strong(lastCheck, seen, std::memory_order_relaxed)) {
        IOSMaxReloadControlIfChanged();
    }
    if (!gEnabled.load(std::memory_order_acquire)) return;

    const size_t width = CVPixelBufferGetWidth(imageBuffer);
    const size_t height = CVPixelBufferGetHeight(imageBuffer);
    const OSType pixelFormat = CVPixelBufferGetPixelFormatType(imageBuffer);
    NSUInteger minimumWidth;
    NSUInteger minimumHeight;
    @synchronized (gStateLock) {
        minimumWidth = gMinimumWidth;
        minimumHeight = gMinimumHeight;
    }
    if (width < minimumWidth || height < minimumHeight || !IOSMaxSupportedPixelFormat(pixelFormat)) {
        if (seen == 1 || seen % 240 == 0) {
            IOSMaxSetError([NSString stringWithFormat:@"Skipped pixel format %u or dimensions %zux%zu",
                (uint32_t)pixelFormat, width, height]);
            IOSMaxWriteStatus(@"buffer-skipped", width, height, pixelFormat);
        }
        return;
    }

    @autoreleasepool {
        CIImage *prepared = IOSMaxPreparedImage(width, height, pixelFormat);
        if (prepared == nil) return;
        @try {
            gRendering = YES;
            [gCIContext render:prepared
               toCVPixelBuffer:(CVPixelBufferRef)imageBuffer
                         bounds:CGRectMake(0, 0, width, height)
                     colorSpace:gColorSpace];
            gRendering = NO;
            const unsigned long long replaced =
                gFramesReplaced.fetch_add(1, std::memory_order_relaxed) + 1;
            if (replaced == 1 || replaced % 120 == 0) {
                IOSMaxSetError(nil);
                IOSMaxWriteStatus(@"frame-replaced", width, height, pixelFormat);
            }
        } @catch (NSException *exception) {
            gRendering = NO;
            gEnabled.store(false, std::memory_order_release);
            IOSMaxSetError([NSString stringWithFormat:@"Render exception: %@", exception.reason]);
            IOSMaxWriteStatus(@"fail-open", width, height, pixelFormat);
        }
    }
}

static void IOSMaxReloadNotification(
    CFNotificationCenterRef center,
    void *observer,
    CFNotificationName name,
    const void *object,
    CFDictionaryRef userInfo
) {
    (void)center;
    (void)observer;
    (void)name;
    (void)object;
    (void)userInfo;
    IOSMaxReloadControl();
}

static void IOSMaxInstallCaptureManagerHook(void);

%group IOSMaxScannerHooks

%hook WAWebClientQRCodeScannerViewController

- (void)viewDidAppear:(BOOL)animated {
    %orig;
    if (NSClassFromString(@"FBCaptureManager") != nil &&
        !gCaptureManagerHookInstalled.exchange(true, std::memory_order_acq_rel)) {
        IOSMaxInstallCaptureManagerHook();
    }
    gTargetScannerVisible.store(true, std::memory_order_release);
    IOSMaxReloadControl();
    IOSMaxWriteStatus(@"target-scanner-visible", 0, 0, 0);
}

- (void)viewWillDisappear:(BOOL)animated {
    gTargetScannerVisible.store(false, std::memory_order_release);
    IOSMaxWriteStatus(@"target-scanner-hidden", 0, 0, 0);
    %orig;
}

%end

%end

%group IOSMaxCaptureManagerHook

%hook FBCaptureManager

- (void)captureOutput:(id)output
    didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer
    fromConnection:(id)connection {
    (void)output;
    (void)connection;
    // Mutate the sample before FBCaptureManager forwards it to its QR/POI
    // detector and video producers. Other WhatsApp camera pages are untouched.
    IOSMaxProcessSampleBuffer(sampleBuffer);
    %orig;
}

%end

%end

static void IOSMaxInstallCaptureManagerHook(void) {
    %init(IOSMaxCaptureManagerHook);
}


static void IOSMaxInstallPipelineHooks(void) {
    @autoreleasepool {
        %init(IOSMaxScannerHooks);
        gHookInstalled.store(true, std::memory_order_release);
        IOSMaxSetError(nil);
        IOSMaxWriteStatus(@"pipeline-hook-installed-disabled", 0, 0, 0);
    }
}

%ctor {
    @autoreleasepool {
        if (![NSBundle.mainBundle.bundleIdentifier isEqualToString:@"net.whatsapp.WhatsApp"]) return;

        gStateLock = [NSObject new];
        gPreparedImages = [NSMutableDictionary dictionary];
        gCIContext = [CIContext contextWithOptions:@{ kCIContextUseSoftwareRenderer: @NO }];
        gStatusQueue = dispatch_queue_create("com.iosmax.virtualcamera.status", DISPATCH_QUEUE_SERIAL);
        gColorSpace = CGColorSpaceCreateDeviceRGB();
        [[NSFileManager defaultManager] createDirectoryAtPath:IOSMaxDirectory()
                                  withIntermediateDirectories:YES
                                                   attributes:nil
                                                        error:nil];

        CFNotificationCenterAddObserver(
            CFNotificationCenterGetDarwinNotifyCenter(),
            nullptr,
            IOSMaxReloadNotification,
            (__bridge CFStringRef)kIOSMaxReloadNotification,
            nullptr,
            CFNotificationSuspensionBehaviorDeliverImmediately
        );
        IOSMaxReloadControl();
        IOSMaxInstallPipelineHooks();
    }
}

#endif
