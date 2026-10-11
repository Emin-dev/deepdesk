"""Fixed-schema CI failure diagnostics. Never publish exception messages or locals."""
import json
import os
from pathlib import Path
import re
import sys
import traceback

PHASES={'controller','register','seed','persisted'}
CHECKPOINTS={'controller-setup','fixture-input','transport-import','wrapper-load','wrapper-serve',
    'uvicorn-contract','lifespan-enter','lifespan-exit','routes','seed-main','worker-result',
    'health','managed-boundary','csrf-refresh','registration','identity','history',
    'invalid-start','report','status','settings','terminal-stop','login','logout','unknown'}
EXCEPTIONS={'RuntimeError','AssertionError','ValueError','TypeError','KeyError','AttributeError',
    'ImportError','ModuleNotFoundError','PermissionError','FileNotFoundError','OSError',
    'TimeoutError','ConnectionError','JSONDecodeError','OperationalError','DatabaseError',
    'IntegrityError','InvalidRequestError','ExceptionGroup','BaseExceptionGroup','SystemExit',
    'KeyboardInterrupt','OtherException'}
SOURCES={'fixture','production-wrapper','installed-package','stdlib','unknown'}
SOURCE_FILES=json.loads(Path(__file__).with_name('asgi-diagnostic-source-allowlist.json').read_text())['files']
ASSERTIONS = {'ASGI identity metadata must be checked before authenticated requests': 'A001', 'ASGI instance metadata differs': 'A002', 'ASGI lifecycle did not complete exactly once': 'A003', 'ASGI response limit exceeded': 'A004', 'Account-context rejection failed': 'A005', 'Already-terminal stop failed': 'A006', 'Authenticated settings failed': 'A007', 'Bootstrap included synthetic secret': 'A008', 'CSRF refresh failed': 'A009', 'CSRF rejection failed': 'A010', 'Correct-key login after process reopen failed': 'A011', 'Could not unlock the synthetic fixture database': 'A012', 'Expected distinct ASGI worker processes': 'A013', 'Fixture account is not empty': 'A014', 'Fixture citation missing': 'A015', 'Fixture history missing': 'A016', 'Fixture report mismatch': 'A017', 'Fixture root must be new': 'A018', 'Fixture seed failed': 'A019', 'Fixture status mismatch': 'A020', 'History accepted unauthenticated caller': 'A021', 'Initial ASGI health failed': 'A022', 'Invalid fixture account': 'A023', 'Invalid fixture marker': 'A024', 'Invalid fixture research identifier': 'A025', 'Invalid fixture research identity': 'A026', 'Invalid start did not fail before research': 'A027', 'Invalid synthetic fixture shape': 'A028', 'Invalid synthetic password shape': 'A029', 'Logout failed': 'A030', 'Logout retained authentication': 'A031', 'Managed ASGI boundary accepted invalid request': 'A032', 'Missing CSRF token': 'A033', 'Missing controller arguments': 'A034', 'Oversized fixture input': 'A035', 'Oversized synthetic stdin': 'A036', 'Persisted report accepted unauthenticated caller': 'A037', 'Refusing a non-fixture account': 'A038', 'Refusing a non-fixture data directory': 'A039', 'Refusing non-fixture data': 'A040', 'Registration session failed': 'A041', 'Rejected start created research state': 'A042', 'Reopened account identity differs': 'A043', 'SQLCipher is required': 'A044', 'Synthetic account not empty': 'A045', 'Synthetic registration failed; do not retry': 'A046', 'Unexpected ASGI phase': 'A047', 'Unexpected ASGI request destination': 'A048', 'Unexpected ASGI worker result': 'A049', 'Unexpected account context': 'A050', 'Unexpected fixture input fields': 'A051', 'Unexpected fixture route': 'A052', 'Unexpected repeated server startup': 'A053', 'Unexpected uvicorn app target': 'A054', 'Unreviewed ASGI client backend': 'A055', 'Unreviewed uvicorn launch arguments': 'A056', 'Unsafe bootstrap request': 'A057', 'Upstream imported before managed wrapper setup': 'A058', 'Wrong password accepted': 'A059', 'macOS arm64 fixture only': 'A060'}


def validate(report):
    expected={'status','kind','phase','checkpoint','exception_type','cause_type','assertion_id','source_category','source_file','source_line'}
    if not isinstance(report,dict) or set(report)!=expected: raise RuntimeError('Invalid diagnostic schema')
    if report['status']!='failed' or report['kind']!='synthetic-ASGI-diagnostic': raise RuntimeError('Invalid diagnostic kind')
    for field,values in (('phase',PHASES),('checkpoint',CHECKPOINTS),('exception_type',EXCEPTIONS),
                         ('cause_type',EXCEPTIONS),('assertion_id',{'none',*ASSERTIONS.values()}),('source_category',SOURCES)):
        if not isinstance(report[field],str) or report[field] not in values: raise RuntimeError('Unreviewed diagnostic enum')
    filename=report['source_file']
    if not isinstance(filename,str) or len(filename)>160 or not re.fullmatch(r'[A-Za-z0-9_./-]+',filename):
        raise RuntimeError('Invalid diagnostic source')
    if filename.startswith('/') or '..' in filename.split('/'): raise RuntimeError('Unsafe diagnostic source')
    category=report['source_category']
    if category=='fixture' and filename not in {'smoke_asgi_authenticated.py','seed_fixture.py','asgi_diagnostics.py','bounded_runtime.py'}:
        raise RuntimeError('Unreviewed fixture diagnostic source')
    if category=='production-wrapper' and filename!='engine_entry.py': raise RuntimeError('Unreviewed wrapper diagnostic source')
    if category in SOURCE_FILES and filename not in SOURCE_FILES[category]: raise RuntimeError('Unreviewed diagnostic source file')
    if category=='unknown' and filename!='unknown': raise RuntimeError('Unexpected unknown diagnostic source')
    if category in {'installed-package','stdlib'} and not filename.endswith('.py'): raise RuntimeError('Non-source diagnostic location')
    if type(report['source_line']) is not int or not 0<=report['source_line']<=100000: raise RuntimeError('Invalid diagnostic line')
    if len(json.dumps(report))>2048: raise RuntimeError('Oversized diagnostic')
    return report


def failure(exc,phase,checkpoint,engine):
    name=type(exc).__name__
    seen=set()
    for _ in range(4):
        if id(exc) in seen: break
        seen.add(id(exc))
        nested=exc.exceptions[0] if isinstance(exc,BaseExceptionGroup) and exc.exceptions else (exc.__cause__ or exc.__context__)
        if nested is None or id(nested) in seen: break
        exc=nested
    cause=type(exc).__name__
    # Only equality with fixed reviewed assertion texts affects public output.
    # All other messages/arguments/locals stay private.
    assertion=ASSERTIONS.get(str(exc),'none') if type(exc) in (RuntimeError,AssertionError) else 'none'
    report={'status':'failed','kind':'synthetic-ASGI-diagnostic','phase':phase,'checkpoint':checkpoint,
        'exception_type':name if name in EXCEPTIONS else 'OtherException',
        'cause_type':cause if cause in EXCEPTIONS else 'OtherException','assertion_id':assertion,
        'source_category':'unknown','source_file':'unknown','source_line':0}
    roots=[('fixture',Path(__file__).resolve().parent),('production-wrapper',Path(engine).resolve().parent),
        ('installed-package',Path(sys.prefix)/'lib/python3.12/site-packages'),
        ('stdlib',Path(sys.base_prefix)/'lib/python3.12')]
    for frame,line in traceback.walk_tb(exc.__traceback__):
        candidate=Path(frame.f_code.co_filename)
        if not candidate.is_file(): continue
        candidate=candidate.resolve()
        for category,root in roots:
            try: relative=str(candidate.relative_to(root.resolve()))
            except ValueError: continue
            proposed={**report,'source_category':category,'source_file':relative,'source_line':line}
            try: validate(proposed)
            except RuntimeError: continue
            report=proposed;break
    return validate(report)


def private_context(exc,phase):
    """Bounded local runner-only traceback. Never returned or uploaded."""
    home=Path(os.environ.get('HOME',''))
    if not home.is_absolute() or not (home/'deepdesk-ci-fixture-only').is_file(): return
    path=home/('private-asgi-'+phase+'.log')
    try:
        with path.open('xb') as stream:
            remaining=1024*1024
            for part in traceback.TracebackException.from_exception(exc,capture_locals=False).format():
                chunk=part[:remaining].encode('utf-8',errors='replace')[:remaining]
                stream.write(chunk);remaining-=len(chunk)
                if not remaining: break
    except OSError:
        pass
