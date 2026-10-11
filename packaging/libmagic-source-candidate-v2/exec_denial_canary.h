/* First-party fixture-only exec-denial canary. No shell or environment inheritance. */
#ifndef DEEPDESK_EXEC_DENIAL_CANARY_H
#define DEEPDESK_EXEC_DENIAL_CANARY_H
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef CANARY_SPAWN
#define CANARY_SPAWN posix_spawn
#endif
#ifndef CANARY_WAIT
#define CANARY_WAIT waitpid
#endif
#ifndef CANARY_OUTPUT
#define CANARY_OUTPUT puts
#endif
#ifndef CANARY_MARK
static int canary_write_marker(const char *path, const char *token) {
    int fd = open(path, O_WRONLY | O_APPEND | O_NOFOLLOW);
    if (fd < 0) return -1;
    struct stat info;
    size_t size = strlen(token), written = 0;
    if (fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_nlink != 1 ||
        info.st_size < 0 || info.st_size > 128 || size > 128 - (size_t)info.st_size) {
        close(fd); return -1;
    }
    while (written < size) {
        ssize_t count = write(fd, token + written, size - written);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) { close(fd); return -1; }
        written += (size_t)count;
    }
    return close(fd) == 0 ? 0 : -1;
}
#define CANARY_MARK canary_write_marker
#endif

static int verify_exec_denial(const char *marker) {
    if (CANARY_MARK(marker, "entered\n")) return 2;
    CANARY_OUTPUT("native_exec_canary_entered");
    pid_t child = -1;
    char *const args[] = {"/usr/bin/true", NULL};
    char *const empty_environment[] = {NULL};
    int result = CANARY_SPAWN(&child, "/usr/bin/true", NULL, NULL,
                              args, empty_environment);
    if (result == EPERM || result == EACCES) {
        if (CANARY_MARK(marker, "permission_denied\n")) return 2;
        CANARY_OUTPUT("native_exec_canary_permission_denied");
        return 0;
    }
    if (result != 0) {
        if (CANARY_MARK(marker, "unexpected_spawn_error\n")) return 2;
        CANARY_OUTPUT("native_exec_canary_failed");
        return 1;
    }
    /* Even a harmless child being started means denial failed. Reap it, then fail. */
    int status = 0;
    pid_t waited = -1;
    if (child > 0) {
        do { waited = CANARY_WAIT(child, &status, 0); } while (waited < 0 && errno == EINTR);
    }
    const char *outcome = child > 0 && waited == child ?
        "exec_allowed_child_reaped\n" : "exec_allowed_reap_failed\n";
    if (CANARY_MARK(marker, outcome)) return 2;
    CANARY_OUTPUT("native_exec_canary_failed");
    return 1;
}
#endif
