"""Static Mach-O and fixed runtime-output verification; no native imports."""
from pathlib import Path,PurePosixPath
import struct

class NativeError(Exception):pass

def need(ok):
    if not ok:raise NativeError()

APPLE_LOADS={
'/usr/lib/libSystem.B.dylib','/usr/lib/libiconv.2.dylib','/usr/lib/libiconv.dylib',
'/usr/lib/libffi.dylib','/usr/lib/libz.1.dylib','/usr/lib/libz.dylib',
'/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation',
'/System/Library/Frameworks/CoreServices.framework/Versions/A/CoreServices',
}

def macho(path,provider_dir):
    b=Path(path).read_bytes();need(len(b)>=32 and b[:4]==b'\xcf\xfa\xed\xfe')
    magic,cpu,sub,filetype,ncmds,sizeofcmds,flags,reserved=struct.unpack_from('<8I',b)
    need(cpu==0x100000c and filetype in (2,6) and ncmds<=256 and 32+sizeofcmds<=len(b))
    cursor=32;loads=[];identity=None;minos=[];signature=False
    for _ in range(ncmds):
        cmd,size=struct.unpack_from('<II',b,cursor);need(size>=8 and cursor+size<=32+sizeofcmds)
        if cmd in (0xc,0xd,0x80000018,0x8000001f,0x80000023):
            off=struct.unpack_from('<I',b,cursor+8)[0];need(24<=off<size)
            name=b[cursor+off:cursor+size].split(b'\0',1)[0].decode('utf-8');need(name and '..' not in PurePosixPath(name).parts)
            if cmd==0xd:identity=name
            else:
                need(name in APPLE_LOADS or (Path(name).parent==Path(provider_dir)/'lib' and Path(name).name in ('libintl.8.dylib','libpcre2-8.0.dylib')));loads.append(name)
        elif cmd==0x8000001c:raise NativeError() # No unreviewed rpath.
        elif cmd==0x32:
            platform,minimum,sdk,ntools=struct.unpack_from('<4I',b,cursor+8);need(platform==1);minos.append(minimum)
        elif cmd==0x1d:signature=True
        cursor+=size
    need(cursor==32+sizeofcmds and minos==[26<<16] and loads)
    if filetype==6:need(identity==str(Path(provider_dir)/'lib'/Path(path).name))
    return {'arm64':True,'filetype':filetype,'minimum_macos':'26.0','direct_load_count':len(loads),'implicit_signature_load_command':signature},loads


def fixture_output(data,expected,executable,provider_dir,required_provider_names=()):
    text=data.decode('utf-8');lines=text.splitlines();markers=[x for x in lines if not x.startswith('image=')]
    need(markers==list(expected));images=[x[6:] for x in lines if x.startswith('image=')];need(0<len(images)<500)
    found=set()
    for name in images:
        need(name.startswith('/') and '..' not in PurePosixPath(name).parts)
        if name.startswith(('/usr/lib/','/System/Library/')):continue # Apple dyld transitive system images.
        p=Path(name);need(p.is_file())
        if p.resolve()==Path(executable).resolve():continue
        need(p.resolve().is_relative_to(Path(provider_dir).resolve()));found.add(p.name)
    need(set(required_provider_names)<=found)
    return {'fixture_markers':len(markers),'loaded_image_count':len(images),'required_provider_count':len(required_provider_names)}
