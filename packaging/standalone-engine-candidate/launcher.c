/* First-party standalone launcher candidate. No interpreter discovery or shell.
 * This file does not attest native dependency completeness or code signatures.
 * Build on macOS: /usr/bin/clang -std=c11 -O2 -Wall -Wextra -Werror launcher.c -o DeepdeskEngine
 * The Linux branch exists only for first-party synthetic contract tests.
 */
#define _XOPEN_SOURCE 700
#if defined(__APPLE__) && !defined(_DARWIN_C_SOURCE)
#define _DARWIN_C_SOURCE 1
#endif
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#elif !defined(__linux__)
#error This launcher supports macOS and the Linux synthetic test host only.
#endif

#ifndef PATH_MAX
#define PATH_MAX 4096
#endif

static int fail(const char *message) {
    /* Never echo inherited inputs, paths, credentials, or errno strings. */
    fprintf(stderr, "DeepdeskEngine: %s\n", message);
    return 78;
}

static int append(char out[PATH_MAX], const char *base, const char *suffix) {
    int size = snprintf(out, PATH_MAX, "%s%s", base, suffix);
    return size >= 0 && size < PATH_MAX;
}

static int regular(const char *path, int executable) {
    struct stat info;
    return stat(path, &info) == 0 && S_ISREG(info.st_mode) &&
           !(info.st_mode & (S_ISUID | S_ISGID)) &&
           (!executable || access(path, X_OK) == 0);
}

static int native_header(const unsigned char header[20], int macos) {
    if (macos) {
        /* The exact approved CPython image is thin arm64, never x86_64/fat. */
        return header[0] == 0xcf && header[1] == 0xfa && header[2] == 0xed &&
               header[3] == 0xfe && header[4] == 12 && header[5] == 0 &&
               header[6] == 0 && header[7] == 1 && header[12] == 2 &&
               header[13] == 0 && header[14] == 0 && header[15] == 0;
    }
    return memcmp(header, "\177ELF", 4) == 0 && header[4] == 2 && header[5] == 1 &&
           (header[16] == 2 || header[16] == 3) && header[17] == 0;
}

static int native_image(const char *path) {
    /* Refuse text/shebang dispatch. Complete architecture/load edges and bytes
     * are independently gated by the reviewed manifest and native audit. */
    unsigned char header[20];
    int file = open(path, O_RDONLY | O_NOFOLLOW);
    if (file < 0) return 0;
    ssize_t count = read(file, header, sizeof header);
    close(file);
    if (count != (ssize_t)sizeof header) return 0;
#ifdef __APPLE__
    return native_header(header, 1);
#else
    return native_header(header, 0); /* ELF is for the Linux test host only. */
#endif
}

static int directory(const char *path) {
    struct stat info;
    /* The structural directories must not themselves be symlinks. */
    return lstat(path, &info) == 0 && S_ISDIR(info.st_mode);
}

/* Every traversed symlink must be relative and remain lexically inside root.
 * realpath then catches dangling links, loops and final containment failures.
 * Check all path prefixes, including symlink targets, without executing them.
 */
static int safe_path(const char *root, const char *relative,
                     char result[PATH_MAX], unsigned int depth) {
    char current[PATH_MAX], rest[PATH_MAX], target[PATH_MAX], combined[PATH_MAX];
    const char *part;
    struct stat info;
    if (depth > 40 || relative[0] == '/' || !append(current, root, "") ||
        !append(rest, relative, "")) return 0;
    char *save = NULL;
    part = strtok_r(rest, "/", &save);
    while (part != NULL) {
        if (strcmp(part, ".") == 0) {
            part = strtok_r(NULL, "/", &save);
            continue;
        }
        if (strcmp(part, "..") == 0) {
            if (strcmp(current, root) == 0) return 0;
            char *slash = strrchr(current, '/');
            if (slash == NULL || (size_t)(slash - current) < strlen(root)) return 0;
            *slash = '\0';
        } else {
            if (!append(combined, current, "/") ||
                !append(current, combined, part) || lstat(current, &info) != 0) return 0;
            if (S_ISLNK(info.st_mode)) {
                ssize_t count = readlink(current, target, sizeof target - 1);
                if (count <= 0 || (size_t)count >= sizeof target - 1) return 0;
                target[count] = '\0';
                if (target[0] == '/') return 0;
                char *slash = strrchr(current, '/');
                *slash = '\0';
                const char *parent_relative = current + strlen(root);
                if (*parent_relative == '/') parent_relative++;
                int size = snprintf(combined, sizeof combined, "%s%s%s%s%s",
                    parent_relative, *parent_relative ? "/" : "", target,
                    save != NULL && *save ? "/" : "", save != NULL ? save : "");
                if (size < 0 || (size_t)size >= sizeof combined) return 0;
                return safe_path(root, combined, result, depth + 1);
            }
            if (save != NULL && *save && !S_ISDIR(info.st_mode)) return 0;
        }
        part = strtok_r(NULL, "/", &save);
    }
    if (realpath(current, result) == NULL) return 0;
    size_t size = strlen(root);
    return strncmp(root, result, size) == 0 &&
           (result[size] == '/' || result[size] == '\0');
}

static int own_executable(char resolved[PATH_MAX]) {
    char path[PATH_MAX];
#ifdef __APPLE__
    uint32_t size = sizeof path;
    if (_NSGetExecutablePath(path, &size) != 0) return 0;
#else
    ssize_t size = readlink("/proc/self/exe", path, sizeof path - 1);
    if (size <= 0 || (size_t)size >= sizeof path - 1) return 0;
    path[size] = '\0';
#endif
    return realpath(path, resolved) != NULL;
}

int main(int argc, char **argv) {
    static const char suffix[] = "/Contents/MacOS/DeepdeskEngine";
    /* This allowlist retains only the native supervisor's explicit inputs and
     * ordinary process locale/home/temp context. PYTHON*, DYLD*, LD_*, venv,
     * package-manager, loader-map and arbitrary LDR_* controls never pass.
     * No PATH is passed or used by this launcher. This is not a sandbox.
     */
    static const char *const allowed[] = {
        "HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE", "TZ",
        "LDR_WEB_HOST", "LDR_WEB_PORT", "LDR_DATA_DIR",
        "DEEPDESK_INSTANCE_NONCE", "DEEPDESK_INFERENCE_API_KEY",
        "DEEPDESK_INFERENCE_URL", "DEEPDESK_INFERENCE_MODEL"
    };
    char executable[PATH_MAX], app[PATH_MAX], path[PATH_MAX];
    char python_root[PATH_MAX], bin[PATH_MAX], interpreter[PATH_MAX], wrapper[PATH_MAX];
    char *environment[sizeof allowed / sizeof allowed[0] + 1];
    size_t environment_count = 0;

    const char *test_mode = NULL;
    if (argc == 2 && strcmp(argv[1], "--self-test") == 0) test_mode = "--self-test";
    else if (argc == 2 && strcmp(argv[1], "--core-self-test") == 0) test_mode = "--core-self-test";
    else if (argc != 1) return fail("unsupported arguments");
    if (!own_executable(executable)) return fail("cannot resolve launcher");
    size_t length = strlen(executable), suffix_length = sizeof suffix - 1;
    if (length <= suffix_length || strcmp(executable + length - suffix_length, suffix) != 0)
        return fail("invalid launcher layout");
    memcpy(app, executable, length - suffix_length);
    app[length - suffix_length] = '\0';
    if (!directory(app) || !append(path, app, "/Contents") || !directory(path) ||
        !append(path, app, "/Contents/MacOS") || !directory(path) ||
        !append(path, app, "/Contents/Resources") || !directory(path) ||
        !append(python_root, app, "/Contents/Resources/Python") || !directory(python_root) ||
        !append(bin, python_root, "/bin") || !directory(bin))
        return fail("invalid bundle directories");
    if (!append(path, python_root, "/pyvenv.cfg") || lstat(path, &(struct stat){0}) == 0 ||
        errno != ENOENT) return fail("standalone interpreter required");
    if (!append(path, python_root, "/bin/pyvenv.cfg") || lstat(path, &(struct stat){0}) == 0 ||
        errno != ENOENT) return fail("standalone interpreter required");
    if (!safe_path(python_root, "bin/python3.12", interpreter, 0) ||
        !regular(interpreter, 1) || !native_image(interpreter))
        return fail("invalid bundled interpreter");
    char *slash = strrchr(interpreter, '/');
    if (slash == NULL || (size_t)(slash - interpreter) != strlen(bin) ||
        strncmp(interpreter, bin, strlen(bin)) != 0)
        return fail("invalid interpreter image location");
    if (!safe_path(app, "Contents/Resources/engine_entry.py", wrapper, 0) ||
        !append(path, app, "/Contents/Resources/engine_entry.py") ||
        strcmp(wrapper, path) != 0 || !regular(wrapper, 0))
        return fail("invalid bundled wrapper");
    /* safe_path rejects escaping links. This additional comparison requires the
     * wrapper itself to be the fixed regular file, rather than an internal alias. */
    struct stat wrapper_info;
    if (lstat(wrapper, &wrapper_info) != 0 || !S_ISREG(wrapper_info.st_mode))
        return fail("invalid bundled wrapper");
    for (size_t index = 0; index < sizeof allowed / sizeof allowed[0]; index++) {
        const char *value = getenv(allowed[index]);
        if (value == NULL) continue;
        size_t name_length = strlen(allowed[index]), value_length = strlen(value);
        char *entry = malloc(name_length + value_length + 2);
        if (entry == NULL) return fail("cannot prepare managed environment");
        memcpy(entry, allowed[index], name_length);
        entry[name_length] = '=';
        memcpy(entry + name_length + 1, value, value_length + 1);
        environment[environment_count++] = entry;
    }
    environment[environment_count] = NULL;
    char *child_argv[] = {interpreter, "-I", "-B", wrapper,
                          (char *)test_mode, NULL};
    /* Absolute execve preserves the supervisor-owned PID. Never use execvp,
     * posix_spawnp, a shebang wrapper, /usr/bin/env, a shell, or cwd/PATH search. */
    execve(interpreter, child_argv, environment);
    for (size_t index = 0; index < environment_count; index++) free(environment[index]);
    return fail("cannot execute bundled interpreter");
}
