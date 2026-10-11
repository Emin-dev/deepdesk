#include <iconv.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <string.h>

int upstream_iconv_semantic_main(void);
static int origin(const char *name, void *function) {
  Dl_info info;
  if (!dladdr(function, &info) || !info.dli_fname) return 81;
  printf("origin=%s|%s\n", name, info.dli_fname);
  return 0;
}
int main(int argc, char **argv) {
  if (argc != 2 || _LIBICONV_VERSION != 0x0113 || _libiconv_version != 0x0113) return 82;
  int result = upstream_iconv_semantic_main();
  if (result) return result;
  puts("upstream_iconv_semantics_and_version_passed");
  if (origin("iconv_open", (void *)iconv_open) || origin("iconv", (void *)iconv) ||
      origin("iconv_close", (void *)iconv_close) || origin("iconv_version", (void *)&_libiconv_version)) return 83;
  void *handle = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
  if (!handle) return 84;
  const char *(*charset)(void) = (const char *(*)(void))dlsym(handle, "locale_charset");
  if (!charset || !charset() || !strlen(charset()) || origin("locale_charset", (void *)charset)) return 85;
  puts("libcharset_runtime_passed");
  for (uint32_t i = 0; i < _dyld_image_count(); i++) printf("image=%s\n", _dyld_get_image_name(i));
  if (dlclose(handle)) return 86;
  return 0;
}
