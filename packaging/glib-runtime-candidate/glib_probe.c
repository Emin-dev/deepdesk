#include <glib.h>
#include <glib-object.h>
#include <gio/gio.h>
#include <gmodule.h>
#include <girepository/girepository.h>
#include <ffi.h>
#include <mach-o/dyld.h>
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int signal_value(GObject *object, int value, gpointer user_data) {
  (void)object; (void)user_data; return value + 7;
}
static void ffi_callback(ffi_cif *cif, void *result, void **args, void *data) {
  (void)cif; *(ffi_arg *)result = (ffi_arg)(*(int *)args[0] + *(int *)data);
}
static int idle_count(gpointer data) { (*(int *)data)++; return G_SOURCE_REMOVE; }

int main(int argc, char **argv) {
  if (argc != 3) return 51;
  if (!setlocale(LC_ALL, "")) return 52;
  if (strcmp(ffi_get_version(), "3.8.0")) return 53;
  ffi_cif cif; ffi_type *types[] = {&ffi_type_sint};
  if (ffi_prep_cif(&cif, FFI_DEFAULT_ABI, 1, &ffi_type_sint, types) != FFI_OK) return 54;
  void *entry = NULL; ffi_closure *closure = ffi_closure_alloc(sizeof(ffi_closure), &entry);
  int addend = 13;
  if (!closure || !entry || ffi_prep_closure_loc(closure, &cif, ffi_callback, &addend, entry) != FFI_OK) return 55;
  if (((int (*)(int))entry)(29) != 42) return 56;
  ffi_closure_free(closure);
  puts("source_libffi_version_and_closure_passed");

  if (glib_major_version != 2 || glib_minor_version != 90 || glib_micro_version != 1) return 57;
  GError *error = NULL; GMatchInfo *match = NULL;
  GRegex *regex = g_regex_new("^(?<word>\\p{L}+)$", G_REGEX_OPTIMIZE, 0, &error);
  if (!regex || error || !g_regex_match(regex, "caf\xc3\xa9", 0, &match)) return 58;
  char *word = g_match_info_fetch_named(match, "word");
  char *folded = g_utf8_casefold("Stra\xc3\x9f" "e", -1);
  if (!word || strcmp(word, "caf\xc3\xa9") || !folded || strcmp(folded, "strasse")) return 59;
  g_free(word); g_free(folded); g_match_info_free(match); g_regex_unref(regex);
  GMainContext *context = g_main_context_new(); GSource *idle = g_idle_source_new(); int count = 0;
  g_source_set_callback(idle, idle_count, &count, NULL); g_source_attach(idle, context);
  if (!g_main_context_iteration(context, FALSE) || count != 1) return 60;
  g_source_unref(idle); g_main_context_unref(context);
  puts("glib_regex_unicode_main_context_passed");

  guint signal = g_signal_new("deepdesk-proof", G_TYPE_OBJECT, G_SIGNAL_RUN_LAST, 0,
                             NULL, NULL, g_cclosure_marshal_generic, G_TYPE_INT, 1, G_TYPE_INT);
  GObject *object = g_object_new(G_TYPE_OBJECT, NULL); int returned = 0;
  if (!signal || !object) return 61;
  g_signal_connect(object, "deepdesk-proof", G_CALLBACK(signal_value), NULL);
  g_signal_emit(object, signal, 0, 35, &returned);
  if (returned != 42) return 62;
  g_object_unref(object);
  GIRepository *repository = gi_repository_new();
  if (!repository || !G_IS_OBJECT(repository)) return 63;
  g_object_unref(repository);
  puts("gobject_generic_ffi_marshalling_and_girepository_passed");

  if (!g_module_supported()) return 64;
  GModule *module = g_module_open(argv[1], G_MODULE_BIND_LOCAL); int (*function)(void) = NULL;
  if (!module || !g_module_symbol(module, "deepdesk_plugin_value", (gpointer *)&function) || !function || function() != 42) return 65;
  puts("gmodule_private_module_passed");

  const char *payload = "Deepdesk caf\xc3\xa9 local-file proof\n";
  GFile *file = g_file_new_for_path(argv[2]); gchar *contents = NULL; gsize length = 0;
  if (!g_file_replace_contents(file, payload, strlen(payload), NULL, FALSE, G_FILE_CREATE_PRIVATE, NULL, NULL, &error) || error) return 66;
  if (!g_file_load_contents(file, NULL, &contents, &length, NULL, &error) || error || length != strlen(payload) || memcmp(contents, payload, length)) return 67;
  g_free(contents);
  if (!g_file_delete(file, NULL, &error) || error) return 68;
  g_object_unref(file);
  puts("gio_private_local_file_roundtrip_passed");

  /* Force GLib's own gettext initialization; do not manually rebind its domain.
     GDateTime on Darwin correctly prefers nl_langinfo and is not a catalog test. */
  GRegex *invalid = g_regex_new("(", 0, 0, &error);
  if (invalid || !error || error->domain != G_REGEX_ERROR || error->code != G_REGEX_ERROR_UNMATCHED_PARENTHESIS) return 69;
  g_error_free(error); error = NULL;
  const gchar *month = g_dpgettext2("glib20", "full month name", "January");
  if (!month || strcmp(month, "janvier")) return 69;
  puts("glib_real_french_catalog_passed");
  for (uint32_t i = 0; i < _dyld_image_count(); i++) printf("image=%s\n", _dyld_get_image_name(i));
  if (!g_module_close(module)) return 70;
  return 0;
}
