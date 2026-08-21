#include <objc/runtime.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <unistd.h>

typedef struct opaqueCMSampleBuffer *CMSampleBufferRef;
typedef void (*IOSMaxBWMRCOriginal)(id, SEL, CMSampleBufferRef, id);

static _Atomic(bool) gIOSMaxHookInstalled = false;
static IOSMaxBWMRCOriginal gIOSMaxOriginalRender = 0;

static void IOSMaxRenderSampleBuffer(
    id self,
    SEL command,
    CMSampleBufferRef sampleBuffer,
    id input
) {
    IOSMaxBWMRCOriginal original = gIOSMaxOriginalRender;
    if (original != 0) original(self, command, sampleBuffer, input);
}

static bool IOSMaxTryInstallHook(void) {
    if (atomic_load_explicit(&gIOSMaxHookInstalled, memory_order_acquire)) return true;
    Class nodeClass = objc_getClass("BWMRCNode");
    if (nodeClass == Nil) return false;
    SEL selector = sel_registerName("renderSampleBuffer:forInput:");
    Method method = class_getInstanceMethod(nodeClass, selector);
    if (method == 0) return false;
    IMP previous = method_setImplementation(method, (IMP)&IOSMaxRenderSampleBuffer);
    if (previous == 0) return false;
    gIOSMaxOriginalRender = (IOSMaxBWMRCOriginal)previous;
    atomic_store_explicit(&gIOSMaxHookInstalled, true, memory_order_release);
    return true;
}

static void *IOSMaxHookInstallerThread(void *unused) {
    (void)unused;
    for (unsigned int attempt = 0; attempt < 600; ++attempt) {
        if (IOSMaxTryInstallHook()) return 0;
        sleep(1);
    }
    return 0;
}

__attribute__((constructor))
static void IOSMaxNativeDaemonCoreInitialize(void) {
    if (IOSMaxTryInstallHook()) return;
    pthread_t thread;
    if (pthread_create(&thread, 0, IOSMaxHookInstallerThread, 0) == 0) {
        pthread_detach(thread);
    }
}
