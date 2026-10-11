#include <libintl.h>
#include <locale.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
  if (argc != 2 || !setlocale(LC_ALL, "")) return 91;
  if (!bindtextdomain("deepdesk-proof", argv[1]) || !textdomain("deepdesk-proof")) return 92;
  if (!bind_textdomain_codeset("deepdesk-proof", "ISO-8859-1")) return 93;
  if (strcmp(gettext("coffee"), "caf\xe9")) return 94;
  if (!bind_textdomain_codeset("deepdesk-proof", "UTF-8")) return 95;
  if (strcmp(gettext("coffee"), "caf\xc3\xa9") || strcmp(ngettext("one apple", "many apples", 1), "une pomme") ||
      strcmp(ngettext("one apple", "many apples", 2), "des pommes") || strcmp(gettext("missing-key"), "missing-key")) return 96;
  puts("gnu_libintl_utf8_latin1_plural_fallback_passed");
  Dl_info info;
  if (!dladdr((void *)gettext, &info) || !info.dli_fname) return 97;
  printf("origin=gettext|%s\n", info.dli_fname);
  for (uint32_t i = 0; i < _dyld_image_count(); i++) printf("image=%s\n", _dyld_get_image_name(i));
  return 0;
}
