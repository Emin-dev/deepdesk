#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#if __has_include(<ffi/ffi.h>)
#include <ffi/ffi.h>
#elif __has_include(<ffi.h>)
#include <ffi.h>
#else
#error sdk_libffi_header_absent
#endif
#include <iconv.h>
#include <zlib.h>
#include <CoreFoundation/CoreFoundation.h>
#include <CoreServices/CoreServices.h>
#include <mach-o/dyld.h>
static int target(int x, double y, void *p) { return x + (int)y + *(int *)p; }
static void images(void) {
    for (uint32_t i=0; i<_dyld_image_count(); i++) printf("image=%s\n", _dyld_get_image_name(i));
}
int main(void) {
    ffi_cif cif; int x=4, z=7, result=0; double y=6.0; void *p=&z;
    ffi_type *types[]={&ffi_type_sint,&ffi_type_double,&ffi_type_pointer};
    void *values[]={&x,&y,&p};
    if (ffi_prep_cif(&cif,FFI_DEFAULT_ABI,3,&ffi_type_sint,types)!=FFI_OK) return 11;
    ffi_arg ret=0; ffi_call(&cif,FFI_FN(target),&ret,values);result=(int)ret;
    if(result!=17) return 12;
    char input[]={0x63,0x61,0x66,(char)0xc3,(char)0xa9}; char converted[32]={0};
    char *in=input,*out=converted; size_t il=sizeof input,ol=sizeof converted;
    iconv_t cd=iconv_open("UTF-16LE","UTF-8");if(cd==(iconv_t)-1)return 13;
    if(iconv(cd,&in,&il,&out,&ol)==(size_t)-1||il) return 14;iconv_close(cd);
    char back[32]={0};in=converted;out=back;il=sizeof converted-ol;ol=sizeof back;
    cd=iconv_open("UTF-8","UTF-16LE");if(cd==(iconv_t)-1)return 15;
    if(iconv(cd,&in,&il,&out,&ol)==(size_t)-1||il||sizeof back-ol!=sizeof input||memcmp(input,back,sizeof input))return 16;
    iconv_close(cd);
    const unsigned char text[]="deepdesk-zlib-sdk-probe";unsigned char compressed[128],plain[128];
    uLongf cn=sizeof compressed,pn=sizeof plain;
    if(compress2(compressed,&cn,text,sizeof text,Z_BEST_SPEED)!=Z_OK)return 17;
    if(uncompress(plain,&pn,compressed,cn)!=Z_OK||pn!=sizeof text||memcmp(plain,text,pn))return 18;
    CFStringRef s=CFStringCreateWithCString(NULL,"foundation",kCFStringEncodingUTF8);
    if(!s||CFStringGetLength(s)!=10)return 19;CFRelease(s);
    puts("sdk_ffi_iconv_zlib_frameworks_passed");images();return 0;
}
