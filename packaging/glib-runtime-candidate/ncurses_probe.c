#include <curses.h>
#include <stdio.h>
#include <string.h>
int main(void) {
  const char *version = curses_version();
  if (!version || !strstr(version, "ncurses")) return 41;
  puts("sdk_ncurses_passed");
  return 0;
}
