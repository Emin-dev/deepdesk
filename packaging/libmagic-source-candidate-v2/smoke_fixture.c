/* Review-only pilot. Compile/run only after the exact native lane is approved. */
#define _DARWIN_C_SOURCE 1
#include <dlfcn.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <magic.h>
#include <mach-o/dyld.h>
#include "synthetic_fixtures.h"
static int check(magic_t m, const char *name, const unsigned char *b,
                 size_t n, const char *expected) {
    const char *actual = magic_buffer(m, b, n);
    if (!actual || strcmp(actual, expected)) {
        fprintf(stderr, "fixture_failed=%s\n", name);
        return 1;
    }
    printf("fixture_pass=%s:%s\n", name, actual);
    return 0;
}
int main(int argc, char **argv) {
    /* Exact paths are provided by the reviewed wrapper, never by a user. */
    if (argc != 4) return 2;
    char actual_library[PATH_MAX], expected_library[PATH_MAX];
    Dl_info info;
    if (!dladdr((const void *) magic_open, &info) || !info.dli_fname ||
        !realpath(info.dli_fname, actual_library) ||
        !realpath(argv[1], expected_library) ||
        strcmp(actual_library, expected_library)) {
        fprintf(stderr, "library_identity_failed\n"); return 3;
    }
    if (magic_version() != 548) return 4;
    magic_t m = magic_open(MAGIC_MIME_TYPE | MAGIC_ERROR | MAGIC_NO_COMPRESS_FORK);
    if (!m) return 5;
    if (magic_load(m, argv[2])) { magic_close(m); return 6; }
    int failures = 0;
    failures += check(m, "plain", plain, sizeof plain, "text/plain");
    failures += check(m, "pdf", pdf, sizeof pdf, "application/pdf");
    failures += check(m, "png", png, sizeof png, "image/png");
    if (magic_setflags(m, MAGIC_MIME_TYPE | MAGIC_ERROR | MAGIC_COMPRESS |
                      MAGIC_COMPRESS_TRANSP | MAGIC_NO_COMPRESS_FORK)) {
        magic_close(m); return 7;
    }
    failures += check(m, "gzip_text_no_external_helper", gzip_text,
                      sizeof gzip_text, "text/plain");
    failures += check(m, "bzip2_text_no_external_helper", bzip2_text,
                      sizeof bzip2_text, "text/plain");
    failures += check(m, "external_compress_helper_rejected", external_compress_header,
                      sizeof external_compress_header,
                      "application/x-decompression-error-gzip-Fork-is-required-to-uncompress--but-disabled");
    magic_close(m);
    m = magic_open(MAGIC_MIME_TYPE | MAGIC_ERROR | MAGIC_NO_COMPRESS_FORK);
    if (!m) return 8;
    if (magic_load(m, argv[3]) == 0) {
        fprintf(stderr, "missing_database_was_accepted\n"); failures++;
    } else puts("fixture_pass=missing_database_rejected");
    magic_close(m);
    for (uint32_t i = 0; i < _dyld_image_count(); i++) {
        const char *name = _dyld_get_image_name(i);
        if (!name) return 9;
        printf("loaded_image=%s\n", name);
    }
    if (!failures) puts("pilot_patched_build_mime_two_codecs_and_external_rejection_passed");
    return failures ? 1 : 0;
}
