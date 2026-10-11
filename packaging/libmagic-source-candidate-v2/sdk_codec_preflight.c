#include <stdio.h>
#include <zlib.h>
#include <bzlib.h>
int main(void) {
    const char *z = zlibVersion();
    const char *b = BZ2_bzlibVersion();
    if (!z || !b || !*z || !*b) return 1;
    printf("zlib=%s\nbzip2=%s\n", z, b);
    return 0;
}
