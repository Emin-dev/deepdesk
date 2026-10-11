"""Inert process/signal/clock doubles; no subprocess or native payload is run."""
import contextlib
import errno
import importlib.util
import io
import json
from pathlib import Path
import types
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent

def load(name):
    spec=importlib.util.spec_from_file_location('supervisor_test_'+name,HERE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

bounds,stage=load('glib_bounds'),load('stage')


def run_case(module, *, primary='success', signal_result='sent', probe='absent', wait='reaped', expected=(0,)):
    alive=primary in ('deadline','workspace','free_space','output','supervisor','stdout')
    class Selector:
        active=alive
        def register(self,*args):pass
        def get_map(self):return {'pipe':True} if self.active else {}
        def select(self,*,timeout):
            if primary=='supervisor':raise OSError(errno.EIO,'INVALID_INERT_EXCEPTION_TEXT')
            return [(types.SimpleNamespace(fileobj=types.SimpleNamespace(fileno=lambda:12),data=0),0)]
        def unregister(self,*args):self.active=False
        def close(self):pass
    class Process:
        pid=12345
        returncode=None if alive and primary!='stdout' else 2 if primary=='child_exit' else 0
        def __init__(self):self.stdout=io.BytesIO();self.stderr=io.BytesIO();self.waits=[]
        def poll(self):return self.returncode
        def wait(self,*,timeout):
            self.waits.append(timeout)
            if timeout==3 and wait=='timeout':raise module.subprocess.TimeoutExpired('INVALID_INERT_COMMAND',3)
            if timeout==3 and wait=='error':raise OSError(errno.ECHILD,'INVALID_INERT_EXCEPTION_TEXT')
            return self.returncode
    selector,process=Selector(),Process()
    signals=[];probes=0
    def killpg(pid,sig):
        nonlocal probes
        signals.append(sig)
        if sig==module.signal.SIGKILL:
            if signal_result=='absent':raise ProcessLookupError(errno.ESRCH,'INVALID_INERT_EXCEPTION_TEXT')
            if signal_result=='error':raise PermissionError(errno.EPERM,'INVALID_INERT_EXCEPTION_TEXT')
            if process.returncode is None and wait!='timeout':process.returncode=-9
        else:
            probes+=1
            if probe=='error':raise PermissionError(errno.EPERM,'INVALID_INERT_EXCEPTION_TEXT')
            if probe=='other_error':raise OSError(987654,'INVALID_INERT_EXCEPTION_TEXT')
            if probe=='present' or (probe=='present_then_absent' and probes==1):return
            raise ProcessLookupError(errno.ESRCH,'INVALID_INERT_EXCEPTION_TEXT')
    ticks=0
    def clock():
        nonlocal ticks
        ticks+=1
        return 100 if primary=='deadline' and ticks>1 else 0
    spaces=iter([8*1024**3,0] if primary=='free_space' else [])
    disk=iter([0,5*1024**3] if primary=='workspace' else [])
    def disk_bytes(work):return next(disk) if primary=='workspace' else 0
    def disk_usage(work):return types.SimpleNamespace(free=next(spaces) if primary=='free_space' else 8*1024**3)
    with contextlib.ExitStack() as stack:
        popen=stack.enter_context(mock.patch.object(module.subprocess,'Popen',return_value=process))
        stack.enter_context(mock.patch.object(module.selectors,'DefaultSelector',return_value=selector))
        stack.enter_context(mock.patch.object(module,'disk_bytes',side_effect=disk_bytes))
        stack.enter_context(mock.patch.object(module.shutil,'disk_usage',side_effect=disk_usage))
        stack.enter_context(mock.patch.object(module.os,'killpg',side_effect=killpg))
        stack.enter_context(mock.patch.object(module.os,'read',side_effect=[b'first-party bytes',b'']))
        stack.enter_context(mock.patch.object(module.time,'monotonic',side_effect=[0,2] if probe=='present' else [0,0]))
        sleep=stack.enter_context(mock.patch.object(module.time,'sleep'))
        kwargs={'cwd':Path('/inert'),'env':{},'work':Path('/inert'),'deadline':100,
                'output_remaining':1 if primary=='output' else 1024,'expected_codes':expected,'clock':clock}
        if 'deadline_source' in module.run.__code__.co_varnames:
            kwargs.update(deadline_source='command',requested_timeout=100)
        record,out,err=module.run(['INVALID_INERT_NEVER_EXECUTED'],**kwargs)
        assert popen.call_count==1
        return record,out,err,{'signals':signals,'waits':process.waits,'sleeps':sleep.call_args_list}


class SupervisorTests(unittest.TestCase):
    def test_normal_success_preserves_legacy_fields_and_mandatory_cleanup(self):
        record,out,err,events=run_case(bounds)
        self.assertEqual(record['status'],'passed');self.assertIsNone(record['failure_class'])
        self.assertEqual(record['cleanup'],'process_group_killed_and_leader_reaped')
        self.assertEqual(events['signals'],[bounds.signal.SIGKILL,0]);self.assertEqual(events['waits'],[100,3])
        self.assertEqual((out,err),(b'',b''))
        detail=record['supervisor_diagnostics'];self.assertIsNone(detail['primary_failure_class'])
        self.assertEqual(detail['cleanup']['leader_wait']['result'],'reaped')
        self.assertEqual(detail['cleanup']['group_probe']['result'],'absent')

    def test_normal_stdout_bytes_and_hash_are_retained(self):
        record,out,err,_=run_case(bounds,primary='stdout')
        self.assertEqual(record['status'],'passed');self.assertEqual(out,b'first-party bytes');self.assertEqual(err,b'')
        self.assertEqual(record['stdout_bytes'],len(out))

    def test_expected_nonzero_exit_remains_success(self):
        record,_,_,_=run_case(bounds,primary='child_exit',expected=(2,))
        self.assertEqual(record['status'],'passed');self.assertEqual(record['exit_code'],2)

    def test_primary_child_exit_survives_later_probe_error(self):
        record,_,_,_=run_case(bounds,primary='child_exit',probe='error')
        detail=record['supervisor_diagnostics']
        self.assertEqual(record['failure_class'],'cleanup_failure')
        self.assertEqual(detail['primary_failure_class'],'child_exit')
        self.assertEqual(detail['primary_operation'],'child_exit_contract')
        self.assertEqual(detail['leader_exit_before_cleanup'],2)

    def test_successful_wait_plus_eperm_probe_never_claims_wait_failure(self):
        record,_,_,_=run_case(bounds,probe='error');detail=record['supervisor_diagnostics']
        self.assertEqual(record['status'],'failed');self.assertEqual(record['cleanup'],'leader_not_reaped')
        self.assertEqual(detail['cleanup']['leader_wait']['result'],'reaped')
        self.assertEqual(detail['cleanup']['group_probe'],{'result':'error','operation':'group_probe','error':{'kind':'os_error','errno':'EPERM'}})

    def test_actual_wait_timeout_remains_fatal_and_probe_unreached(self):
        record,_,_,events=run_case(bounds,primary='deadline',wait='timeout');detail=record['supervisor_diagnostics']
        self.assertEqual(record['failure_class'],'cleanup_failure')
        self.assertEqual(detail['primary_failure_class'],'deadline_exceeded')
        self.assertEqual(detail['primary_operation'],'monitor_deadline')
        self.assertEqual(detail['cleanup']['leader_wait']['result'],'timeout')
        self.assertEqual(detail['cleanup']['group_probe']['result'],'not_started')
        self.assertEqual(events['signals'],[bounds.signal.SIGKILL]);self.assertEqual(events['waits'],[3])

    def test_leader_wait_os_error_remains_fatal(self):
        record,_,_,_=run_case(bounds,wait='error');detail=record['supervisor_diagnostics']
        self.assertEqual(record['status'],'failed')
        self.assertEqual(detail['cleanup']['leader_wait']['error'],{'kind':'os_error','errno':'ECHILD'})

    def test_vanished_group_is_normal_cleanup(self):
        record,_,_,_=run_case(bounds,signal_result='absent')
        self.assertEqual(record['status'],'passed')
        self.assertEqual(record['supervisor_diagnostics']['cleanup']['signal']['result'],'group_absent')

    def test_signal_error_stays_fatal_even_if_wait_and_probe_succeed(self):
        record,_,_,_=run_case(bounds,signal_result='error');detail=record['supervisor_diagnostics']
        self.assertEqual(record['status'],'failed');self.assertEqual(record['failure_class'],'cleanup_failure')
        self.assertEqual(detail['cleanup']['signal']['error']['errno'],'EPERM')
        self.assertEqual(detail['cleanup']['leader_wait']['result'],'reaped')
        self.assertEqual(detail['cleanup']['group_probe']['result'],'absent')

    def test_group_survival_deadline_stays_fatal_and_unchanged(self):
        record,_,_,events=run_case(bounds,probe='present')
        self.assertEqual(record['cleanup'],'process_group_still_present');self.assertEqual(record['status'],'failed')
        self.assertEqual(record['supervisor_diagnostics']['cleanup']['group_probe']['result'],'still_present_at_deadline')
        self.assertEqual(events['sleeps'],[])

    def test_group_eventually_vanishes_with_same_probe_sleep(self):
        record,_,_,events=run_case(bounds,probe='present_then_absent')
        self.assertEqual(record['status'],'passed');self.assertEqual(events['signals'],[bounds.signal.SIGKILL,0,0])
        self.assertEqual(events['sleeps'],[mock.call(0.02)])

    def test_primary_deadline_resource_and_output_failures_survive_cleanup(self):
        for primary,reason,operation in [('deadline','deadline_exceeded','monitor_deadline'),
                ('workspace','workspace_limit','monitor_workspace_scan'),('free_space','free_space_floor','monitor_free_space'),
                ('output','output_limit','monitor_output_limit')]:
            record,_,_,_=run_case(bounds,primary=primary,probe='error');detail=record['supervisor_diagnostics']
            self.assertEqual(record['failure_class'],'cleanup_failure')
            self.assertEqual(detail['primary_failure_class'],reason);self.assertEqual(detail['primary_operation'],operation)

    def test_supervisor_operation_and_errno_survive_cleanup_error(self):
        record,_,_,_=run_case(bounds,primary='supervisor',probe='error');detail=record['supervisor_diagnostics']
        self.assertEqual(detail['primary_failure_class'],'supervisor_or_spawn_failure')
        self.assertEqual(detail['primary_operation'],'pipe_select')
        self.assertEqual(detail['primary_exception'],{'kind':'os_error','errno':'EIO'})

    def test_deadline_initial_remaining_and_expiry_are_bounded(self):
        record,_,_,_=run_case(bounds,primary='deadline')
        self.assertEqual(record['supervisor_diagnostics']['deadline'],{'source':'command','requested_timeout_seconds':100,
            'effective_remaining_ms_at_start':100000,'effective_remaining_ms_before_cleanup':0,'reached_before_cleanup':True})
        self.assertEqual(bounds.remaining_ms(999999,0),1500000)
        self.assertEqual(bounds.remaining_ms(0,1),0)
        self.assertIsNone(bounds.remaining_ms(float('nan'),0))

    def test_unknown_errno_and_exception_text_are_never_disclosed(self):
        record,_,_,_=run_case(bounds,probe='other_error')
        text=json.dumps(record['supervisor_diagnostics'])
        self.assertNotIn('987654',text);self.assertNotIn('INVALID_INERT',text)
        self.assertEqual(record['supervisor_diagnostics']['cleanup']['group_probe']['error']['errno'],'other')
        self.assertLess(len(text.encode()),2048)

    def test_additive_diagnostic_has_separate_enforced_two_kib_bound(self):
        self.assertEqual(bounds.MAX_SUPERVISOR_DIAGNOSTIC_BYTES,2048)
        for primary in ('success','child_exit','deadline','workspace','free_space','output','supervisor'):
            record,_,_,_=run_case(bounds,primary=primary,probe='error')
            detail=record['supervisor_diagnostics']
            self.assertIs(bounds.bounded_diagnostic(detail),detail)
            self.assertLessEqual(len(json.dumps(detail,sort_keys=True,allow_nan=False).encode()),2048)
        with self.assertRaisesRegex(ValueError,'^supervisor_diagnostic_bound$'):
            bounds.bounded_diagnostic({'INVALID_INERT': 'x' * 2048})
        with self.assertRaises(ValueError):bounds.bounded_diagnostic({'value':float('nan')})

    def test_preflight_failures_do_not_spawn_or_weaken(self):
        with mock.patch.object(bounds.subprocess,'Popen') as popen:
            record,_,_=bounds.run(['INVALID_INERT_NEVER_EXECUTED'],cwd=Path('/inert'),env={},work=Path('/inert'),deadline=0,output_remaining=1024,clock=lambda:1)
        popen.assert_not_called();self.assertEqual(record['failure_class'],'deadline_exceeded')
        self.assertEqual(record['supervisor_diagnostics']['primary_operation'],'preflight_deadline')
        self.assertEqual(record['cleanup'],'not_started')

    def test_other_preflight_limits_remain_fatal_without_spawn(self):
        for remaining,used,free,reason in ((0,0,8*1024**3,'output_limit'),
                (1024,5*1024**3,8*1024**3,'workspace_limit'),(1024,0,0,'free_space_floor')):
            with mock.patch.object(bounds.subprocess,'Popen') as popen, \
                 mock.patch.object(bounds,'disk_bytes',return_value=used), \
                 mock.patch.object(bounds.shutil,'disk_usage',return_value=types.SimpleNamespace(free=free)):
                record,_,_=bounds.run(['INVALID_INERT_NEVER_EXECUTED'],cwd=Path('/inert'),env={},work=Path('/inert'),deadline=100,output_remaining=remaining,clock=lambda:1)
            popen.assert_not_called();self.assertEqual(record['failure_class'],reason)
            self.assertEqual(record['supervisor_diagnostics']['primary_failure_class'],reason)
            self.assertEqual(record['cleanup'],'not_started')

    def test_spawn_error_is_fixed_and_does_not_claim_cleanup(self):
        with mock.patch.object(bounds.subprocess,'Popen',side_effect=OSError(errno.ENOMEM,'INVALID_INERT_EXCEPTION_TEXT')), \
             mock.patch.object(bounds,'disk_bytes',return_value=0), \
             mock.patch.object(bounds.shutil,'disk_usage',return_value=types.SimpleNamespace(free=8*1024**3)):
            record,_,_=bounds.run(['INVALID_INERT_NEVER_EXECUTED'],cwd=Path('/inert'),env={},work=Path('/inert'),deadline=100,output_remaining=1024,clock=lambda:1)
        detail=record['supervisor_diagnostics'];self.assertEqual(record['status'],'failed')
        self.assertEqual(detail['primary_operation'],'spawn')
        self.assertEqual(detail['primary_exception'],{'kind':'os_error','errno':'ENOMEM'})
        self.assertEqual(detail['cleanup']['signal']['result'],'not_started')
        self.assertNotIn('INVALID_INERT',json.dumps(detail))

    def test_lane_passes_exact_command_or_lane_deadline_source(self):
        for lane_deadline,expected_deadline,source in ((1000,160,'command'),(120,120,'shared_lane')):
            lane=object.__new__(stage.Lane);lane.deadline=lane_deadline;lane.output=0;lane.steps=[]
            lane.work=Path('/inert/work');lane.phases=Path('/inert/work/phases');lane.immutable=Path('/inert/work/immutable')
            lane.root=Path('/inert/root');lane.helpers=HERE;lane.env={};lane.bounds=types.SimpleNamespace()
            lane.directory=mock.Mock(return_value=Path('/inert/work/phases/probe'));lane.checkpoint=mock.Mock()
            lane.bounds.run=mock.Mock(return_value=({'status':'passed','stdout_bytes':0,'stderr_bytes':0},b'',b''))
            with mock.patch.object(stage.time,'monotonic',return_value=100),contextlib.redirect_stdout(io.StringIO()):
                lane.run('inert-command',['/usr/bin/false'],timeout=60)
            kwargs=lane.bounds.run.call_args.kwargs
            self.assertEqual(kwargs['deadline'],expected_deadline);self.assertEqual(kwargs['deadline_source'],source)
            self.assertEqual(kwargs['requested_timeout'],60)
            self.assertEqual(lane.bounds.run.call_args.args[0][-1],'/usr/bin/false')

if __name__=='__main__':unittest.main()
