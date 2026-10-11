"""Inactive, receipt-closed PDF prerequisite lane. No package execution on import."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import resource
import shutil
import signal
import struct
import sys
import tempfile
import time
sys.dont_write_bytecode=True
SCOPE='pdf-foundation-prerequisites-v1'
CANDIDATE_REVISION=4
BRANCH='engine-pdf-foundation-v1-ci'
WORKFLOW='.github/workflows/engine-pdf-foundation-v1-macos.yml'
INPUT_HASHES={
'gettext':'85d99b79c981a404874c02e0342176cf75c7698e2b51fe41031cf6526d974f1a',
'pcre2':'53c156e1ba416a20da8e65395daa132da0d80e76910424caca3fcdae7831d384',
'pkgconf':'943f0bc88bcaeceb630b00262e2a8ad5ea4fac3fba72a4267d8b9ec6b35d1194',
'meson':'9774eb62bbf2cb8043aa3feb771c09b510d112c0c382221e29aea7453ecce753',
'ninja':'fd82e26c0706ad4ab88e5fdd26f3fab0a987a90f810160f6c322e752c6af298b',
'python':'83dcb04777c798bd95f3687acf9ae84b09860272ee6bdfb05be8bcf9447f75b8'}
FALSE_GATES={'glib_runtime':False,'gobject_runtime':False,'gio_runtime':False,'gmodule_runtime':False,'pango_runtime':False,
'pdf_rendering':False,'font_closure':False,'relocation':False,'release_ready':False,
'model_loaded':False,'provider_queried':False,'artifact_uploaded':False,'cache_used':False}

REQUIRED_APIS={
 'header_ffi':(b'ffi/ffi.h',b'ffi.h',b'sdk_libffi_header_absent'),
 'header_iconv':(b'iconv.h',),'header_zlib':(b'zlib.h',),
 'header_corefoundation':(b'CoreFoundation/CoreFoundation.h',),
 'header_coreservices':(b'CoreServices/CoreServices.h',),
 'header_pcre2':(b'pcre2.h',),'header_libintl':(b'libintl.h',),
 'symbol_ffi_prep_cif':(b'ffi_prep_cif',),'symbol_ffi_call':(b'ffi_call',),
 'symbol_iconv':(b'iconv_open',b'iconv_close',b'iconv('),
 'symbol_zlib':(b'compress2',b'uncompress'),
 'symbol_corefoundation':(b'CFStringCreateWithCString',b'CFStringGetLength',b'CFRelease'),
 'symbol_pcre2_jit':(b'pcre2_jit_compile',b'pcre2_jit_match'),
 'symbol_pcre2_match':(b'pcre2_compile',b'pcre2_match',b'pcre2_dfa_match'),
 'symbol_gettext':(b'bindtextdomain',b'bind_textdomain_codeset',b'ngettext',b'gettext('),
}
FIXTURE_EXITS={11:'ffi_prep_cif_failed',12:'ffi_call_value_failed',13:'iconv_open_failed',14:'iconv_conversion_failed',
15:'iconv_reverse_open_failed',16:'iconv_roundtrip_failed',17:'zlib_compress_failed',18:'zlib_roundtrip_failed',19:'corefoundation_failed',
21:'pcre2_unicode_or_jit_config_failed',22:'pcre2_compile_failed',23:'pcre2_match_data_failed',24:'pcre2_match_failed',25:'pcre2_named_capture_failed',
26:'pcre2_jit_compile_failed',27:'pcre2_jit_match_failed',28:'pcre2_dfa_failed',29:'pcre2_invalid_utf_not_rejected',30:'pcre2_invalid_pattern_not_rejected',
31:'fixture_argument_contract_failed',32:'utf8_locale_unavailable',33:'language_environment_failed',34:'gettext_binding_failed',35:'gettext_domain_failed',
36:'gettext_singular_translation_failed',37:'gettext_plural_one_failed',38:'gettext_plural_many_failed',39:'gettext_missing_key_fallback_failed',40:'pcre2_valid_nonmatch_contract_failed'}
def required_api_mentions(data):
    return sorted(name for name,tokens in REQUIRED_APIS.items() if any(token in data for token in tokens))

class LaneError(Exception):pass
class PhaseError(Exception):
    def __init__(self,record):self.record=record

def need(ok):
    if not ok:raise LaneError()

def digest(path):
    p=Path(path);need(p.is_file() and not p.is_symlink());h=hashlib.sha256()
    with p.open('rb') as f:
        for part in iter(lambda:f.read(1024**2),b''):h.update(part)
    return h.hexdigest()

def validate_receipt(root,helpers,receipt,execute):
    need(receipt.get('scope')==SCOPE and receipt.get('schema')==1 and receipt.get('candidate_revision')==CANDIDATE_REVISION)
    need(receipt.get('destination_branch')==BRANCH and receipt.get('source_changes_allowed') is False)
    need(receipt.get('input_sha256')==INPUT_HASHES and receipt.get('false_gates')==FALSE_GATES)
    expected=receipt.get('sha256',{});need(bool(expected))
    observed={p.relative_to(helpers).as_posix() for p in helpers.rglob('*') if p.is_file() and p!=helpers/'review-receipt.json'}
    need(set(expected)==observed and not any(p.is_symlink() for p in helpers.rglob('*')))
    for name,value in expected.items():
        need(not name.startswith('/') and '..' not in Path(name).parts and re.fullmatch('[0-9a-f]{64}',value) and digest(helpers/name)==value)
    if execute:
        need(receipt.get('execution_approved') is True and receipt.get('independent_review_passed') is True
             and receipt.get('temporary_linker_adhoc_signing_approved') is True
             and receipt.get('install_name_linker_assignment_approved') is True)
        need(receipt.get('explicit_codesign_allowed') is False and receipt.get('personal_signing_allowed') is False)
        need(digest(root/WORKFLOW)==digest(helpers/'pdf-foundation-macos.yml.template'))

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def write_mo(path):
    messages={'':'Content-Type: text/plain; charset=UTF-8\nLanguage: fr\nPlural-Forms: nplurals=2; plural=(n != 1);\n',
              'coffee':'caf\u00e9','one apple\x00many apples':'une pomme\x00des pommes'}
    keys=sorted(messages);original=[k.encode() for k in keys];translated=[messages[k].encode() for k in keys];n=len(keys)
    start=28+16*n;raw=b'';ot=[];tt=[]
    for b in original:ot.append((len(b),start+len(raw)));raw+=b+b'\0'
    for b in translated:tt.append((len(b),start+len(raw)));raw+=b+b'\0'
    data=struct.pack('<7I',0x950412de,0,n,28,28+8*n,0,0)+b''.join(struct.pack('<2I',*x) for x in ot+tt)+raw
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)

class InputChecks:
    """Cheap deadline check per member; full filesystem/free-space scan at most every 2 seconds.
    During input extraction there is no downloaded code or background build process.
    Exact member hashes, sizes and aggregate expansion remain checked by extract().
    """
    def __init__(self,deadline,scan,clock=time.monotonic):
        self.deadline=deadline;self.scan=scan;self.clock=clock;self.next_scan=0;self.scan_count=0;self.calls=0
    def __call__(self,force=False):
        self.calls+=1;now=self.clock();need(now<self.deadline)
        if force or now>=self.next_scan:
            self.scan();self.scan_count+=1
            now=self.clock();need(now<self.deadline);self.next_scan=now+2.0


def read_input(archive, diagnostics, pin, target, destination, manifest, deadline, input_checks):
    """Keep the exact input operations/checkpoints; add only fixed failure metadata."""
    observer=diagnostics.Observer(archive,pin,(LaneError,));subphase='input_checkpoint'
    previous_trace=sys.gettrace()
    try:
        input_checks(force=True);subphase='download'
        try:
            sys.settrace(observer.trace);archive.download(pin,target,deadline)
        finally:sys.settrace(previous_trace)
        subphase='download_checkpoint';input_checks(force=True)
        subphase='extract';tree=archive.extract(pin,target,destination,manifest,input_checks)
        subphase='extraction_checkpoint';input_checks(force=True)
        return tree
    except Exception as error:
        record=observer.failure_record(error,subphase)
        print(json.dumps(record,sort_keys=True),flush=True)
        raise PhaseError(record) from None

class Lane:
    def __init__(self,root,helpers,work,modules):
        self.root,self.helpers,self.work=root,helpers,work;self.archive,self.bounds,self.native=modules
        self.immutable=work/'immutable';self.immutable.mkdir(mode=0o700)
        self.phases=work/'phases';self.phases.mkdir(mode=0o700)
        self.deadline=time.monotonic()+540;self.output=0;self.steps=[];self.phase='preflight';self.base={}
        self.env={'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LC_ALL':'C','LANG':'C','TZ':'UTC','SOURCE_DATE_EPOCH':'0',
         'PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','MACOSX_DEPLOYMENT_TARGET':'26.0',
         'PKG_CONFIG_PATH':'','PKG_CONFIG_LIBDIR':str(self.immutable/'providers/lib/pkgconfig'),
         'CONFIG_SITE':'/dev/null','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null','CCACHE_DISABLE':'1'}
        self.provider=self.immutable/'providers';self.provider.mkdir()
    def checkpoint(self):
        need(time.monotonic()<self.deadline and self.bounds.disk_bytes(self.work)<=2*1024**3 and shutil.disk_usage(self.work).free>=1024**3)
    def directory(self,name):
        p=self.phases/name;p.mkdir(mode=0o700,exist_ok=True)
        for n in ('home','tmp'):(p/n).mkdir(mode=0o700,exist_ok=True)
        return p
    def run(self,name,command,*,directory=None,timeout=60,expected=(0,),extra_env=None):
        self.phase=name;self.checkpoint();p=directory or self.directory(name)
        env=dict(self.env,HOME=str(p/'home'),TMPDIR=str(p/'tmp'));env.update(extra_env or {})
        wrapped=['/usr/bin/sandbox-exec','-D','PHASE_DIR='+str(p),'-D','IMMUTABLE_DIR='+str(self.immutable),
                 '-D','CONTROL_DIR='+str(self.root),'-f',str(self.helpers/'offline.sb'),*map(str,command)]
        record,out,err=self.bounds.run(wrapped,cwd=p,env=env,work=self.work,deadline=min(self.deadline,time.monotonic()+timeout),
            output_remaining=8*1024**2-self.output,expected_codes=expected)
        self.output+=record['stdout_bytes']+record['stderr_bytes'];record={'phase':name,**record}
        if record['status']=='failed' and name in ('pkgconf-build','pcre2-build','gettext-headers','gettext-gnulib-build','gettext-libintl-build'):
            diagnostic=load_module('pdf_build_diagnostics',self.helpers/'build_diagnostics.py')
            record['build_diagnostics']=diagnostic.summarize(name,out,err,self.helpers/'build-diagnostic-catalog.json',self.immutable,p,self.root)
        if record['status']=='failed' and name in ('sdk-probe-compile','provider-probe-compile'):
            record['required_api_mentions']=required_api_mentions(out+err)
        if record['status']=='failed' and name in ('sdk-probe-run','provider-probe-run'):
            record['fixture_failure']=FIXTURE_EXITS.get(record['exit_code'],'unclassified_fixture_exit')
        if record['status']=='failed':record['private_diagnostics']=[self.bounds.private_file_record(p/'config.log','config_log'),self.bounds.private_file_record(p/'out/meson-logs/meson-log.txt','meson_log')]
        self.steps.append(record);print(json.dumps(record,sort_keys=True),flush=True)
        if record['status']!='passed':raise PhaseError(record)
        return out,err,record
    def canaries(self,python):
        p=self.directory('sandbox-canaries')
        for mode in ('network','loopback','bind','inherited'):
            out,err,_=self.run('canary-'+mode,[python,'-I','-S',self.helpers/'canary.py',mode],directory=p,timeout=10);need(out==b'canary_ok\n' and not err)
        for label,target in [('immutable',self.immutable/'forbidden'),('control',self.helpers/'forbidden'),('other-phase',self.phases/'forbidden')]:
            out,err,_=self.run('canary-write-'+label,[python,'-I','-S',self.helpers/'canary.py','deny-write',target],directory=p,timeout=10);need(out==b'canary_ok\n' and not target.exists())
        for label,destination in [('immutable',self.immutable),('control',self.helpers)]:
            alias=p/(label+'-link')
            if not alias.is_symlink():alias.symlink_to(destination,target_is_directory=True)
            out,err,_=self.run('canary-symlink-write-'+label,[python,'-I','-S',self.helpers/'canary.py','deny-write',alias/'symlink-forbidden'],directory=p,timeout=10)
            need(out==b'canary_ok\n' and not (destination/'symlink-forbidden').exists())
        out,err,_=self.run('canary-write-allowed',[python,'-I','-S',self.helpers/'canary.py','allow-write',p/'allowed'],directory=p,timeout=10);need((p/'allowed').read_bytes()==b'first-party-canary')
        # An actual pre-existing Homebrew byte must be denied, not merely absent.
        candidates=[Path('/opt/homebrew/bin/git'),Path('/opt/homebrew/bin/brew')];target=next((x for x in candidates if x.is_file()),None);need(target is not None)
        self.run('canary-homebrew-read',[python,'-I','-S',self.helpers/'canary.py','deny-read',target],directory=p,timeout=10)
    def freeze(self,source,target,executable=False):
        self.checkpoint();need(source.is_file() and source.resolve().is_relative_to(self.phases.resolve()) and not target.exists())
        need(self.archive.snapshot(self.immutable)==self.base)
        before=digest(source.resolve());target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target);os.chmod(target,0o555 if executable else 0o444);need(digest(target)==before)
        self.base=self.archive.snapshot(self.immutable)
    def alias(self,name,target):
        need(self.archive.snapshot(self.immutable)==self.base and not name.exists() and '/' not in target and (name.parent/target).is_file())
        name.symlink_to(target);self.base=self.archive.snapshot(self.immutable)
    def inspect(self,label,path):
        self.phase='native-inspect-'+label
        record,loads=self.native.macho(path,self.provider)
        print(json.dumps({'phase':'native-inspect-'+label,'status':'passed','output_sha256':digest(path.resolve()),'output_bytes':path.stat().st_size,**record},sort_keys=True))
        return record,loads
    def symbols(self,label,path,required):
        out,_,_=self.run('exports-'+label,[self.tools['nm'],'-gU',path],timeout=30)
        exports=set(re.findall(rb'\b_[A-Za-z][A-Za-z0-9_]*$',out,re.M))
        need({('_'+x).encode() for x in required}<=exports)
        print(json.dumps({'phase':'export-contract-'+label,'status':'passed','required_export_count':len(required)}))
    def execute(self,trees):
        host=Path(sys.executable).resolve();self.canaries(host)
        p=self.directory('sdk-preflight');self.tools={}
        for tool in ('clang','ar','ranlib','nm','ld','strip'):
            out,err,_=self.run('tool-path-'+tool,['/usr/bin/xcrun','--sdk','macosx','--find',tool],directory=p,timeout=10)
            text=out.decode().strip();need(text.startswith(('/Applications/','/Library/Developer/','/usr/bin/')) and not re.search(r'\s',text) and Path(text).is_file());self.tools[tool]=str(Path(text).resolve())
            print(json.dumps({'phase':'tool-identity-'+tool,'status':'passed','binary_sha256':digest(Path(text).resolve())}))
        sdkraw,_,_=self.run('sdk-path',['/usr/bin/xcrun','--sdk','macosx','--show-sdk-path'],directory=p,timeout=10)
        sdk=sdkraw.decode().strip();need(sdk.startswith(('/Applications/','/Library/Developer/')) and not re.search(r'\s',sdk) and Path(sdk).is_dir())
        version,_,_=self.run('sdk-version',['/usr/bin/xcrun','--sdk','macosx','--show-sdk-version'],directory=p,timeout=10);need(re.fullmatch(rb'26(?:\.[0-9]+){0,2}\n?',version))
        self.run('compiler-version',[self.tools['clang'],'--version'],directory=p,timeout=10)
        self.run('os-version',['/usr/bin/sw_vers'],directory=p,timeout=10)
        self.run('xcode-version',['/usr/bin/xcodebuild','-version'],directory=p,timeout=15)
        self.run('make-version',['/usr/bin/make','--version'],directory=p,timeout=10)
        flags='-arch arm64 -isysroot '+sdk+' -mmacosx-version-min=26.0 -O2'
        self.env.update({'CC':self.tools['clang'],'AR':self.tools['ar'],'RANLIB':self.tools['ranlib'],'NM':self.tools['nm'],'LD':self.tools['ld'],'STRIP':self.tools['strip'],
            'SDKROOT':sdk,'CFLAGS':flags,'CPPFLAGS':'-isysroot '+sdk,'LDFLAGS':'-arch arm64 -isysroot '+sdk+' -mmacosx-version-min=26.0'})
        cflags=['-arch','arm64','-isysroot',sdk,'-mmacosx-version-min=26.0','-O2']
        fixture=p/'sdk-probe'
        self.run('sdk-probe-compile',[self.tools['clang'],*cflags,self.helpers/'sdk_probe.c','-lffi','-liconv','-lz','-framework','CoreFoundation','-framework','CoreServices','-o',fixture],directory=p,timeout=30)
        self.inspect('sdk-probe',fixture);out,err,_=self.run('sdk-probe-run',[fixture],directory=p,timeout=10)
        self.native.fixture_output(out,['sdk_ffi_iconv_zlib_frameworks_passed'],fixture,self.provider);need(not err)
        py=trees['python']/'bin/python3.12';need(py.is_file());self.canaries(py)
        out,err,_=self.run('pinned-python-version',[py,'-I','-S','--version'],timeout=10);need(out.strip()==b'Python 3.12.15' and not err)
        ninja=trees['ninja']/'ninja-1.13.2.data/scripts/ninja'
        out,err,_=self.run('ninja-version',[ninja,'--version'],timeout=10);need(out.strip()==b'1.13.2.git.kitware.jobserver-pipe-1' and not err)
        # Build pkgconf static; freeze its executable, never execute it from a mutable build tree later.
        p=self.directory('pkgconf-build');toolbin=self.immutable/'toolbin';toolbin.mkdir()
        self.base=self.archive.snapshot(self.immutable)
        self.run('pkgconf-configure',['/bin/sh',trees['pkgconf']/'configure','--prefix='+str(self.immutable/'toolprefix'),'--disable-shared','--enable-static','--with-pkg-config-dir='+str(self.provider/'lib/pkgconfig')],directory=p,timeout=80)
        self.run('pkgconf-build',['/usr/bin/make','-j2','pkgconf'],directory=p,timeout=90)
        self.inspect('pkgconf',p/'pkgconf');self.freeze(p/'pkgconf',toolbin/'pkgconf',True);self.alias(toolbin/'pkg-config','pkgconf')
        self.env.update({'PATH':str(toolbin)+':/usr/bin:/bin:/usr/sbin:/sbin','PKG_CONFIG':str(toolbin/'pkgconf'),'NINJA':str(ninja)})
        out,err,_=self.run('pkgconf-version',[toolbin/'pkgconf','--version'],timeout=10);need(out.strip()==b'3.0.8' and not err)
        self.run('pkgconf-sentinel-positive',[toolbin/'pkgconf','--exists','deepdesk_unreviewed_host_only'],extra_env={'PKG_CONFIG_PATH':str(self.immutable/'host-pc')},timeout=10)
        # Exact --exists false is a negative test. A code 1 here is expected and must not mask other failures.
        _,_,neg=self.run('pkgconf-host-search-negative',[toolbin/'pkgconf','--exists','deepdesk_unreviewed_host_only'],expected=(1,),timeout=10);need(neg['exit_code']==1)
        p=self.directory('meson-probe')
        out,err,_=self.run('meson-version',[py,'-I','-S',self.helpers/'meson_entry.py','--version'],directory=p,timeout=10);need(out.strip()==b'1.11.0' and not err)
        # Exercise an actual Meson internal helper with the same stable adapter.
        helper_source=self.helpers/'probe_project/helper-input.txt';helper_output=p/'helper-copy.txt'
        self.run('meson-internal-copy',[py,'-I','-S',self.helpers/'meson_entry.py','--internal','copy',helper_source,helper_output],directory=p,timeout=15)
        need(helper_output.is_file() and digest(helper_output)==digest(helper_source))
        # Copy only the first-party fixture into the mutable phase. No downloaded
        # source or reviewed control file is modified for the regeneration test.
        project=p/'source';project.mkdir()
        for name in ('meson.build','main.c'):
            shutil.copyfile(self.helpers/'probe_project'/name,project/name)
            need(digest(project/name)==digest(self.helpers/'probe_project'/name))
        self.run('meson-configure',[py,'-I','-S',self.helpers/'meson_entry.py','setup',p/'out',project,'--wrap-mode=nofallback','--buildtype=release'],directory=p,timeout=45)
        self.run('meson-ninja-build',[ninja,'-C',p/'out','-j2'],directory=p,timeout=30)
        original=(project/'meson.build').read_bytes();need(original.count(b"version: '1.0'")==1)
        (project/'meson.build').write_bytes(original.replace(b"version: '1.0'",b"version: '1.1'",1))
        # Make this reviewed fixture's changed input unambiguously newer than
        # build.ninja, then use Ninja's GENERATED --internal regenerate command.
        changed=max(time.time_ns(),(p/'out/build.ninja').stat().st_mtime_ns+1_000_000)
        os.utime(project/'meson.build',ns=(changed,changed))
        self.run('meson-ninja-regenerate',[ninja,'-C',p/'out','-j2'],directory=p,timeout=45)
        info_path=p/'out/meson-info/intro-projectinfo.json';need(info_path.is_file() and not info_path.is_symlink() and info_path.stat().st_size<65536)
        info=json.loads(info_path.read_text());need(info.get('version')=='1.1')
        print(json.dumps({'phase':'meson-internal-regeneration-contract','status':'passed','internal_copy_hash_matched':True,'fixture_project_version':'1.1','isolated_adapter_required':True}))
        self.inspect('meson-probe',p/'out/tool-probe');out,err,_=self.run('meson-tool-probe-run',[p/'out/tool-probe'],directory=p,timeout=10);need(out==b'tool_probe_passed\n' and not err)
        # Required PCRE2 provider only: no CLI/upstream-test target expansion.
        p=self.directory('pcre2-build')
        self.run('pcre2-configure',['/bin/sh',trees['pcre2']/'configure','--prefix='+str(self.provider),'--enable-shared','--disable-static','--enable-pcre2-8','--enable-unicode','--enable-jit','--disable-maintainer-mode'],directory=p,timeout=70)
        self.run('pcre2-build',['/usr/bin/make','-j2','libpcre2-8.la'],directory=p,timeout=100)
        library=p/'.libs/libpcre2-8.0.dylib';self.inspect('pcre2',library)
        self.freeze(library,self.provider/'lib/libpcre2-8.0.dylib');self.alias(self.provider/'lib/libpcre2-8.dylib','libpcre2-8.0.dylib')
        self.freeze(p/'src/pcre2.h',self.provider/'include/pcre2.h');self.freeze(p/'libpcre2-8.pc',self.provider/'lib/pkgconfig/libpcre2-8.pc')
        contract=json.loads((self.helpers/'provider-contract.json').read_text());self.symbols('pcre2',self.provider/'lib/libpcre2-8.0.dylib',contract['glib_regex_pcre2_exports'])
        out,err,_=self.run('pcre2-pkgconf-version',[toolbin/'pkgconf','--modversion','libpcre2-8'],timeout=10);need(out.strip()==b'10.49' and not err)
        # Real standalone libintl, with source release layout and parser mtimes unchanged.
        p=self.directory('gettext-build')
        self.run('gettext-configure',['/bin/sh',trees['gettext']/'gettext-runtime/intl/configure','--prefix='+str(self.provider),'--with-included-libintl','--enable-nls','--enable-shared','--disable-static','--enable-threads=posix','--without-libintl-prefix','--without-libiconv-prefix'],directory=p,timeout=110)
        self.run('gettext-headers',['/usr/bin/make','libintl.h','libgnuintl.h'],directory=p,timeout=20)
        self.run('gettext-gnulib-build',['/usr/bin/make','-C','gnulib-lib','-j2','all'],directory=p,timeout=140)
        self.run('gettext-libintl-build',['/usr/bin/make','-j2','libintl.la'],directory=p,timeout=90)
        library=p/'.libs/libintl.8.dylib';self.inspect('libintl',library)
        self.freeze(library,self.provider/'lib/libintl.8.dylib');self.alias(self.provider/'lib/libintl.dylib','libintl.8.dylib');self.freeze(p/'libintl.h',self.provider/'include/libintl.h')
        self.symbols('libintl',self.provider/'lib/libintl.8.dylib',contract['libintl_minimum_exports'])
        p=self.directory('provider-probe');fixture=p/'provider-probe'
        self.run('provider-probe-compile',[self.tools['clang'],*cflags,'-I'+str(self.provider/'include'),self.helpers/'provider_probe.c',self.provider/'lib/libpcre2-8.0.dylib',self.provider/'lib/libintl.8.dylib','-o',fixture],directory=p,timeout=30)
        self.inspect('provider-probe',fixture)
        out,err,_=self.run('provider-probe-run',[fixture,self.immutable/'catalog'],directory=p,timeout=15)
        tests=self.native.fixture_output(out,['pcre2_unicode_jit_dfa_errors_passed','gnu_libintl_catalog_plural_utf8_passed'],fixture,self.provider,['libpcre2-8.0.dylib','libintl.8.dylib']);need(not err)
        need(self.archive.snapshot(self.immutable)==self.base);self.checkpoint()
        print(json.dumps({'phase':'prerequisite-result','status':'passed','scope':SCOPE,'pdf_foundation_prerequisites':True,
            'input_count':6,'source_changes':False,'output_total_bytes':self.output,'fixture_summary':tests,
            'peak_child_rss_bytes':resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,**FALSE_GATES},sort_keys=True))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--repository',type=Path,required=True);parser.add_argument('--validate-candidate',action='store_true');args=parser.parse_args()
    root=args.repository.resolve(strict=True);helpers=root/'packaging/pdf-foundation-candidate';phase='receipt-validation';lane=None
    try:
        receipt=json.loads((helpers/'review-receipt.json').read_text());validate_receipt(root,helpers,receipt,not args.validate_candidate)
        if args.validate_candidate:
            print(json.dumps({'status':'static_candidate_integrity_passed','execution_approved':receipt['execution_approved'],'native_execution':False,'candidate_revision':CANDIDATE_REVISION}));return 0
        phase='host-and-destination-guards'
        need(platform.system()=='Darwin' and platform.machine()=='arm64' and sys.version_info>=(3,9))
        need(os.environ.get('GITHUB_REPOSITORY')=='Emin-dev/deepdesk' and os.environ.get('GITHUB_REF')=='refs/heads/'+BRANCH)
        need(os.environ.get('GITHUB_EVENT_NAME') in ('push','workflow_dispatch'))
        event_path=Path(os.environ.get('GITHUB_EVENT_PATH',''));need(event_path.is_file() and event_path.stat().st_size<2*1024**2)
        event=json.loads(event_path.read_text());need(event.get('repository',{}).get('private') is False and event.get('repository',{}).get('full_name')=='Emin-dev/deepdesk')
        need(Path('/usr/bin/sandbox-exec').is_file() and str(Path(sys.executable).resolve()).startswith(('/Applications/','/Library/Developer/','/usr/bin/')))
        modules=tuple(load_module('pdf_'+x,helpers/(x+'.py')) for x in ('archive_tools','bounds','native_checks'))
        diagnostics=load_module('pdf_input_diagnostics',helpers/'input_diagnostics.py')
        lock=json.loads((helpers/'input-lock.json').read_text());need(lock['scope']==SCOPE and lock['source_changes_allowed'] is False)
        need({x['id']:x['sha256'] for x in lock['inputs']}==INPUT_HASHES and len(lock['inputs'])==6 and lock['total_compressed_bytes']==61858201 and lock['total_expanded_bytes']==335134815)
        temp=os.environ.get('RUNNER_TEMP');need(temp and Path(temp).is_dir() and shutil.disk_usage(temp).free>=4*1024**3)
        def interrupted(signum,frame):raise LaneError()
        signal.signal(signal.SIGTERM,interrupted);signal.signal(signal.SIGINT,interrupted)
        with tempfile.TemporaryDirectory(prefix='deepdesk-pdf-foundation-',dir=temp) as td:
            work=Path(td).resolve();need(not re.search(r'\s',str(work)) and not work.is_relative_to(root));lane=Lane(root,helpers,work,modules)
            # Only first-party retrieval/extraction executes before the contained 540-second phase.
            phase='input-phase';deadline=time.monotonic()+120;trees={};input_checks=InputChecks(deadline,lane.checkpoint)
            def alarm(signum,frame):raise LaneError()
            previous=signal.signal(signal.SIGALRM,alarm);signal.setitimer(signal.ITIMER_REAL,120)
            try:
                for pin in lock['inputs']:
                    phase='input-'+pin['id'];target=lane.immutable/pin['filename']
                    trees[pin['id']]=read_input(modules[0],diagnostics,pin,target,lane.immutable/('tree-'+pin['id']),helpers/pin['member_manifest'],deadline,input_checks)
                    print(json.dumps({'phase':phase,'status':'passed','archive_bytes':pin['size'],'archive_sha256':pin['sha256'],'member_count':pin['member_count']}),flush=True)
                write_mo(lane.immutable/'catalog/fr/LC_MESSAGES/deepdesk-proof.mo')
                sentinel=lane.immutable/'host-pc/deepdesk_unreviewed_host_only.pc';sentinel.parent.mkdir();sentinel.write_text('Name: deepdesk_unreviewed_host_only\nDescription: First-party search exclusion sentinel\nVersion: 1.0\n')
                lane.base=modules[0].snapshot(lane.immutable);input_checks(force=True)
                print(json.dumps({'phase':'input-checkpoint-summary','status':'passed','per_member_deadline_checks':input_checks.calls,'filesystem_scan_count':input_checks.scan_count}))
            finally:signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous)
            phase='contained-execution';lane.deadline=time.monotonic()+540;lane.execute(trees)
        return 0
    except PhaseError as error:
        print(json.dumps({'phase':error.record['phase'],'status':'failed','scope':SCOPE,'pdf_foundation_prerequisites':False,'failure_class':error.record['failure_class'],'exit_code':error.record['exit_code'],**FALSE_GATES},sort_keys=True),flush=True);return 1
    except Exception:
        print(json.dumps({'phase':lane.phase if lane is not None and phase=='contained-execution' else phase,'status':'failed','failure_class':'contract_or_input_failure','exit_code':None,**FALSE_GATES},sort_keys=True),flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
