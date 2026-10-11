#define PCRE2_CODE_UNIT_WIDTH 8
#include <pcre2.h>
#include <libintl.h>
#include <locale.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdint.h>
#include <mach-o/dyld.h>
static int regex_test(void) {
    uint32_t unicode=0,jit=0;
    if(pcre2_config(PCRE2_CONFIG_UNICODE,&unicode)||pcre2_config(PCRE2_CONFIG_JIT,&jit)||!unicode||!jit)return 21;
    int error;PCRE2_SIZE offset;
    pcre2_code *re=pcre2_compile((PCRE2_SPTR)"^(?<word>\\p{L}+)$",PCRE2_ZERO_TERMINATED,PCRE2_UTF|PCRE2_UCP,&error,&offset,NULL);
    if(!re)return 22;
    pcre2_match_data *md=pcre2_match_data_create_from_pattern(re,NULL);if(!md)return 23;
    const char word[]="caf\xc3\xa9";
    if(pcre2_match(re,(PCRE2_SPTR)word,strlen(word),0,0,md,NULL)!=2)return 24;
    PCRE2_UCHAR *capture=NULL;PCRE2_SIZE length=0;
    if(pcre2_substring_get_byname(md,(PCRE2_SPTR)"word",&capture,&length)||length!=strlen(word)||memcmp(capture,word,length))return 25;
    pcre2_substring_free(capture);
    if(pcre2_jit_compile(re,PCRE2_JIT_COMPLETE))return 26;
    if(pcre2_jit_match(re,(PCRE2_SPTR)word,strlen(word),0,0,md,NULL)!=2)return 27;
    int workspace[256];if(pcre2_dfa_match(re,(PCRE2_SPTR)word,strlen(word),0,0,md,NULL,workspace,256)<1)return 28;
    /* A normal non-match is not invalid-UTF rejection. The exact 10.49
       header and valid_utf.c define illegal 0xff as UTF8_ERR21 (-23). */
    int utf8_result=pcre2_match(re,(PCRE2_SPTR)"\xff",1,0,0,md,NULL);
    if(utf8_result!=PCRE2_ERROR_UTF8_ERR21)return 29;
    if(pcre2_match(re,(PCRE2_SPTR)"123",3,0,0,md,NULL)!=PCRE2_ERROR_NOMATCH)return 40;
    pcre2_match_data_free(md);pcre2_code_free(re);
    re=pcre2_compile((PCRE2_SPTR)"(",PCRE2_ZERO_TERMINATED,PCRE2_UTF,&error,&offset,NULL);
    if(re){pcre2_code_free(re);return 30;}return 0;
}
int main(int argc,char **argv) {
    if(argc!=2)return 31;
    int r=regex_test();if(r)return r;
    if(!setlocale(LC_ALL,"en_US.UTF-8"))return 32;
    if(setenv("LANGUAGE","fr",1))return 33;
    if(!bindtextdomain("deepdesk-proof",argv[1])||!bind_textdomain_codeset("deepdesk-proof","UTF-8"))return 34;
    if(!textdomain("deepdesk-proof"))return 35;
    if(strcmp(gettext("coffee"),"caf\xc3\xa9"))return 36;
    if(strcmp(ngettext("one apple","many apples",1),"une pomme"))return 37;
    if(strcmp(ngettext("one apple","many apples",2),"des pommes"))return 38;
    if(strcmp(dgettext("deepdesk-proof","missing-key"),"missing-key"))return 39;
    puts("pcre2_unicode_jit_dfa_errors_passed");puts("gnu_libintl_catalog_plural_utf8_passed");
    for(uint32_t i=0;i<_dyld_image_count();i++)printf("image=%s\n",_dyld_get_image_name(i));
    return 0;
}
