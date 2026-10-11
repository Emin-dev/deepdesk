/* Isolated first-party mock contract test. No real spawn/wait or libmagic linkage. */
#define _POSIX_C_SOURCE 200809L
#include <assert.h>
#include <errno.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/types.h>
static int spawn_result, spawn_calls, wait_calls, wait_eintr, wait_failure, mark_fail;
static pid_t spawn_pid;
static char tokens[128], output[256];
static int fake_mark(const char *path, const char *token) {
    assert(!strcmp(path, "synthetic-marker"));
    if (mark_fail == 1 || (mark_fail == 2 && tokens[0])) return -1;
    assert(strlen(tokens) + strlen(token) < sizeof tokens);
    strcat(tokens, token); return 0;
}
static int fake_output(const char *token) {
    assert(strlen(output) + strlen(token) + 1 < sizeof output);
    strcat(output, token); strcat(output, "\n"); return 0;
}
static int fake_spawn(pid_t *pid, const char *path,
    const posix_spawn_file_actions_t *actions, const posix_spawnattr_t *attributes,
    char *const args[], char *const environment[]) {
    spawn_calls++;
    assert(!strcmp(path, "/usr/bin/true"));
    assert(actions == NULL && attributes == NULL);
    assert(args && !strcmp(args[0], "/usr/bin/true") && args[1] == NULL);
    assert(environment && environment[0] == NULL);
    *pid = spawn_pid; return spawn_result;
}
static pid_t fake_wait(pid_t pid, int *status, int options) {
    wait_calls++; assert(pid == spawn_pid && pid > 0 && status && options == 0);
    if (wait_eintr) { wait_eintr = 0; errno = EINTR; return -1; }
    if (wait_failure) { errno = ECHILD; return -1; }
    *status = 0; return pid;
}
#define CANARY_MARK fake_mark
#define CANARY_OUTPUT fake_output
#define CANARY_SPAWN fake_spawn
#define CANARY_WAIT fake_wait
#include "exec_denial_canary.h"
static void reset(void) {
    spawn_result = spawn_calls = wait_calls = wait_eintr = wait_failure = mark_fail = 0;
    spawn_pid = 123; tokens[0] = output[0] = '\0';
}
int main(void) {
    const int denied[] = {EPERM, EACCES};
    for (size_t i = 0; i < sizeof denied / sizeof denied[0]; i++) {
        reset(); spawn_result = denied[i]; assert(verify_exec_denial("synthetic-marker") == 0);
        assert(spawn_calls == 1 && wait_calls == 0);
        assert(!strcmp(tokens, "entered\npermission_denied\n"));
        assert(!strcmp(output, "native_exec_canary_entered\nnative_exec_canary_permission_denied\n"));
    }
    reset(); spawn_result = ENOENT; assert(verify_exec_denial("synthetic-marker") == 1);
    assert(spawn_calls == 1 && wait_calls == 0); assert(!strcmp(tokens, "entered\nunexpected_spawn_error\n"));
    reset(); assert(verify_exec_denial("synthetic-marker") == 1);
    assert(wait_calls == 1); assert(!strcmp(tokens, "entered\nexec_allowed_child_reaped\n"));
    reset(); wait_eintr = 1; assert(verify_exec_denial("synthetic-marker") == 1);
    assert(wait_calls == 2); assert(!strcmp(tokens, "entered\nexec_allowed_child_reaped\n"));
    reset(); wait_failure = 1; assert(verify_exec_denial("synthetic-marker") == 1);
    assert(wait_calls == 1); assert(!strcmp(tokens, "entered\nexec_allowed_reap_failed\n"));
    reset(); spawn_pid = -1; assert(verify_exec_denial("synthetic-marker") == 1);
    assert(wait_calls == 0); assert(!strcmp(tokens, "entered\nexec_allowed_reap_failed\n"));
    reset(); mark_fail = 1; assert(verify_exec_denial("synthetic-marker") == 2);
    assert(spawn_calls == 0 && wait_calls == 0 && output[0] == '\0');
    reset(); mark_fail = 2; spawn_result = EPERM;
    assert(verify_exec_denial("synthetic-marker") == 2);
    assert(spawn_calls == 1 && wait_calls == 0);
    assert(!strcmp(tokens, "entered\n")); assert(!strcmp(output, "native_exec_canary_entered\n"));
    puts("first_party_mock_canary_contract_passed");
    return 0;
}
