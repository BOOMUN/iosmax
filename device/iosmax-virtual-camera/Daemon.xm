#import <Foundation/Foundation.h>

static NSString *IOSMaxDaemonDirectory(void) {
    return @"/var/mobile/Library/Caches/com.iosmax.virtualcamera";
}

static NSString *IOSMaxDaemonStatusPath(void) {
    return [IOSMaxDaemonDirectory() stringByAppendingPathComponent:@"daemon-status.plist"];
}

%ctor {
    @autoreleasepool {
        if (![NSProcessInfo.processInfo.processName isEqualToString:@"mediaserverd"]) return;
        NSError *directoryError = nil;
        BOOL directoryReady = [[NSFileManager defaultManager]
            createDirectoryAtPath:IOSMaxDaemonDirectory()
            withIntermediateDirectories:YES
            attributes:@{ NSFilePosixPermissions: @0755 }
            error:&directoryError];
        NSMutableDictionary *status = [@{
            @"ProbeLoaded": @YES,
            @"HookInstalled": @NO,
            @"Enabled": @NO,
            @"Event": @"daemon-load-probe",
            @"PID": @(NSProcessInfo.processInfo.processIdentifier),
            @"Process": NSProcessInfo.processInfo.processName ?: @"",
            @"UpdatedAt": [NSDate date],
        } mutableCopy];
        if (!directoryReady && directoryError != nil) {
            status[@"LastError"] = directoryError.localizedDescription ?: @"Unable to create daemon status directory";
        }
        [status writeToFile:IOSMaxDaemonStatusPath() atomically:YES];
    }
}
