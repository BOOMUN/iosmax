typedef unsigned long iosmax_size_t;

extern int open(const char *path, int flags, ...);
extern long write(int fd, const void *buffer, iosmax_size_t size);
extern int close(int fd);

enum {
    IOSMAX_O_WRONLY = 0x0001,
    IOSMAX_O_CREAT = 0x0200,
    IOSMAX_O_TRUNC = 0x0400,
};

__attribute__((constructor))
static void IOSMaxDaemonProbeInitialize(void) {
    static const char marker[] = "iosmax-native-arm64e-loaded\n";
    int fd = open(
        "/var/mobile/iosmax-native-arm64e-loaded.txt",
        IOSMAX_O_WRONLY | IOSMAX_O_CREAT | IOSMAX_O_TRUNC,
        0644
    );
    if (fd < 0) return;
    (void)write(fd, marker, sizeof(marker) - 1);
    (void)close(fd);
}
