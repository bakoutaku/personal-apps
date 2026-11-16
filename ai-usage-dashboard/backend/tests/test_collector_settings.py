"""App-managed collection settings: synthetic logs only, temporary data and home directories."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from usage_dashboard.app import Application
from usage_dashboard.auto_collect import AutoCollector
from usage_dashboard.collect import parse_file
from usage_dashboard.collector_settings import CollectorService, SETTINGS_FILE, display_path, load_settings
from usage_dashboard.common import APIError, canonical, parse_time
from usage_dashboard.store import connect, initialize
from test_backend import NOW, raw_usage, claude_row


class ManualCollector(AutoCollector):
    """No background thread: the test drives each scheduled round explicitly."""
    def start(self):
        self._started=True


def response(rid,minute,thread='synthetic_thread',**usage):
    return {'type':'token_usage_record','timestamp':'2026-10-22T03:%02d:00.000Z'%minute,
            'payload':{'thread_id':thread,'response_id':rid,'usage':raw_usage(**usage)}}


def meta(thread='synthetic_thread'):
    return {'type':'session_meta','timestamp':'2026-10-22T02:00:00.000Z','payload':{'id':thread,'base_instructions':'DO_NOT_STORE_PRIVATE'}}


def message(mid,minute,output=4,request=None):
    row=claude_row(output=output,minute=minute)
    row['message']['id']=mid
    row['requestId']=request or 'req_'+mid
    return row


class SettingsCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        base=Path(self.temp.name).resolve()
        self.home=base/'home'
        self.data=base/'home/Library/Application Support/AI Usage Dashboard'
        self.codex=self.home/'.codex/sessions'
        self.claude=self.home/'.claude/projects'
        self.codex.mkdir(parents=True)
        self.claude.mkdir(parents=True)
        self.db=self.data/'usage.sqlite3'
        initialize(self.db)
        self.at=NOW
        self.mono=0
        self.services=[]

    def tearDown(self):
        for service in self.services:
            service.stop()
        self.temp.cleanup()

    def service(self,**options):
        service=CollectorService(self.db,self.data,factory=ManualCollector,clock=lambda:self.at,
                                 monotonic=lambda:self.mono,home=self.home,**options)
        service.start()
        self.services.append(service)
        return service

    def restart(self,service):
        service.stop()
        return self.service()

    def advance(self,seconds=60):
        self.at+=seconds*1000
        self.mono+=seconds

    def round(self,service):
        return service.collector.run_due() if service.collector else []

    def tick(self,service):
        self.advance()
        return self.round(service)

    def append(self,file,rows,tail=''):
        file.parent.mkdir(parents=True,exist_ok=True)
        old=file.stat().st_mtime_ns if file.exists() else 0
        with file.open('a') as f:
            f.write(''.join(canonical(r)+'\n' for r in rows)+tail)
        stamp=max(time.time_ns(),old+1000000000)
        os.utime(file,ns=(stamp,stamp))

    def enable(self,service,provider='gpt',history='from_enable',location='standard',custom=None,confirm=None):
        body={'provider':provider,'enabled':True,'location':'custom' if custom else location,'history':history}
        if custom is not None:
            body['custom_path']=custom
        root=Path(custom) if custom else (self.codex if provider=='gpt' else self.claude)
        body['confirm_scope']=confirm if confirm is not None else display_path(root,self.home)
        return service.update(body)

    def reason(self,service,body):
        with self.assertRaises(APIError) as raised:
            service.update(body)
        self.assertEqual(raised.exception.status,422)
        return raised.exception.details[0]['reason']

    def events(self,provider='gpt'):
        with connect(self.db) as db:
            return [dict(r) for r in db.execute('SELECT * FROM usage_events WHERE provider=? ORDER BY occurred_ms,id',(provider,))]

    def source(self,provider='gpt'):
        with connect(self.db) as db:
            return dict(db.execute("SELECT * FROM sources WHERE provider=? AND kind='local_log'",(provider,)).fetchone())


class FirstRunAndScope(SettingsCase):
    def test_never_set_up_reads_nothing_and_reports_not_configured(self):
        self.append(self.codex/'a.jsonl',[meta(),response('r1',5)])
        with patch('usage_dashboard.auto_collect.source_files') as walk, patch('usage_dashboard.collect.source_files') as walk2:
            service=self.service()
            self.assertIsNone(service.collector)
            status=service.status()
            walk.assert_not_called()
            walk2.assert_not_called()
        self.assertFalse(status['configured'])
        self.assertEqual([s['enabled'] for s in status['sources']],[False,False])
        self.assertEqual(status['sources'][0]['standard_display_path'],'~/.codex/sessions')
        self.assertFalse((self.data/SETTINGS_FILE).exists())
        self.assertEqual(self.events(),[])

    def test_scope_must_be_confirmed_and_never_be_broad(self):
        service=self.service()
        self.assertEqual(self.reason(service,{'provider':'gpt','enabled':True,'location':'standard','history':'from_enable','confirm_scope':'~/.codex'}),'scope_not_confirmed')
        self.assertEqual(self.reason(service,{'provider':'gpt','enabled':True,'location':'standard','history':'from_enable'}),'scope_not_confirmed')
        for path,reason in [(str(self.home),'path_too_broad'),(str(self.home.parent),'path_too_broad'),('/','path_too_broad'),
                            (str(self.data.parent),'path_too_broad'),(str(self.data),'path_too_broad'),
                            ('relative/logs','not_absolute'),(str(self.home/'missing'),'path_not_directory')]:
            with self.subTest(path=path):
                self.assertEqual(self.reason(service,{'provider':'gpt','enabled':True,'location':'custom','history':'from_enable',
                                                      'custom_path':path,'confirm_scope':path}),reason)
        link=self.home/'linked'
        link.symlink_to(self.codex,target_is_directory=True)
        self.assertEqual(self.reason(service,{'provider':'gpt','enabled':True,'location':'custom','history':'from_enable',
                                              'custom_path':str(link),'confirm_scope':'~/linked'}),'path_symlink')
        self.assertEqual(self.reason(service,{'provider':'gpt','enabled':True,'surprise':1}),'unknown_field')
        self.assertFalse((self.data/SETTINGS_FILE).exists())
        self.assertIsNone(service.collector)

    def test_custom_directory_and_tilde_display(self):
        custom=self.home/'work/codex-logs'
        custom.mkdir(parents=True)
        self.append(custom/'a.jsonl',[meta(),response('r1',5)])
        service=self.service()
        status=self.enable(service,custom='~/work/codex-logs'.replace('~',str(self.home)),history='import_history')
        gpt=status['sources'][0]
        self.assertEqual((gpt['location'],gpt['display_path']),('custom','~/work/codex-logs'))
        self.round(service)
        self.assertEqual(len(self.events()),1)
        self.assertNotIn(str(self.home),json.dumps(service.status()))

    def test_settings_are_private_and_survive_restart(self):
        service=self.service()
        self.enable(service)
        path=self.data/SETTINGS_FILE
        if os.name!='nt':
            self.assertEqual(path.stat().st_mode&0o777,0o600)
        restarted=self.restart(service)
        self.assertIsNotNone(restarted.collector)
        self.assertTrue(restarted.status()['sources'][0]['enabled'])
        raw=self.db.read_bytes()
        self.assertNotIn(str(self.home).encode(),raw)

    def test_invalid_settings_file_never_collects_and_can_be_replaced(self):
        self.append(self.codex/'a.jsonl',[meta(),response('r1',5)])
        (self.data/SETTINGS_FILE).write_text('{"version":1,"interval_seconds":60,"sources":{"gpt":{"enabled":true}}}')
        service=self.service()
        self.assertIsNone(service.collector)
        self.assertEqual(service.status()['settings_error'],'invalid_settings_file')
        self.enable(service,history='import_history')
        self.assertEqual(len(list(self.data.glob('collector-settings.invalid-*.json'))),1)
        self.round(service)
        self.assertEqual(len(self.events()),1)

    def test_hand_edited_broad_path_is_rejected_on_load(self):
        service=self.service()
        self.enable(service,history='import_history')
        data=json.loads((self.data/SETTINGS_FILE).read_text())
        data['sources']['gpt'].update(location='custom',path=str(self.home))
        (self.data/SETTINGS_FILE).write_text(json.dumps(data))
        settings,error=load_settings(self.data,self.home)
        self.assertEqual((settings,error),(None,'invalid_settings_file'))

    def test_startup_config_mode_is_read_only(self):
        from usage_dashboard.auto_collect import CollectorConfig, SourceConfig
        service=self.service(startup_config=CollectorConfig(60,(SourceConfig('gpt',self.codex,'local'),)))
        self.assertEqual(service.status()['mode'],'startup_config')
        self.assertEqual(self.reason(service,{'provider':'gpt','enabled':False}),'locked_by_startup_config')
        disabled=CollectorService(self.db,self.data,disabled=True,home=self.home)
        self.assertEqual(self.reason(disabled,{'provider':'gpt','enabled':False}),'collection_disabled_for_this_run')


class HistoryBoundaryTests(SettingsCase):
    def test_only_after_enabling_survives_restarts_and_counts_appends_and_new_chats(self):
        old=self.codex/'2026/10/22/rollout-old.jsonl'
        self.append(old,[meta(),response('history_1',5),response('history_2',20)])
        service=self.service()
        status=self.enable(service)
        self.assertEqual(status['sources'][0]['boundary_status'],'pending')
        self.round(service)
        self.assertEqual(service.status()['sources'][0]['boundary_status'],'ready')
        self.assertEqual(self.events(),[])
        self.assertEqual(self.source()['connection_status'],'available')
        self.append(old,[response('after_1',58)])
        self.tick(service)
        self.assertEqual([e['total_tokens'] for e in self.events()],[120])
        # New chat → new file in a new dated folder.
        self.append(self.codex/'2026/10/23/rollout-new.jsonl',[meta('new_thread'),response('after_2',59,thread='new_thread')])
        self.tick(service)
        self.assertEqual(len(self.events()),2)
        for _ in range(2):
            service=self.restart(service)
            self.round(service)
            self.tick(service)
        self.assertEqual(len(self.events()),2)
        self.append(old,[response('after_3',59)])
        self.tick(service)
        self.assertEqual(len(self.events()),3)
        with connect(self.db) as db:
            notes=[r[0] for r in db.execute('SELECT code FROM source_limitations WHERE source_id=?',(self.source()['id'],))]
        self.assertIn('history_before_enable_excluded',notes)

    def test_delayed_write_with_earlier_timestamp_is_counted(self):
        file=self.codex/'a.jsonl'
        self.append(file,[meta(),response('history',5)])
        service=self.service()
        self.enable(service)
        self.round(service)
        # Written after enabling, but stamped before the boundary (e.g. long-running turn).
        self.append(file,[response('late',30)])
        self.tick(service)
        self.assertEqual([e['occurred_ms'] for e in self.events()],[parse_time('2026-10-22T03:30:00.000Z')])

    def test_boundary_captured_at_confirmation_even_if_scan_happens_after_restart(self):
        file=self.codex/'a.jsonl'
        self.append(file,[meta(),response('history',5)])
        service=self.service()
        self.enable(service)
        service.stop()  # Closed before the first scheduled round.
        self.append(file,[response('after',50)])
        self.advance(3600)
        service=self.service()
        self.round(service)
        self.assertEqual([e['external_event_key'] for e in self.events()].__len__(),1)

    def test_codex_cumulative_counter_uses_pre_boundary_baseline(self):
        file=self.codex/'legacy.jsonl'
        first=raw_usage(800,100,200)
        rows=[meta('legacy_thread'),{'type':'event_msg','timestamp':'2026-10-22T03:05:00.000Z','payload':{'type':'token_count',
              'info':{'total_token_usage':first,'last_token_usage':first}}}]
        self.append(file,rows)
        service=self.service()
        self.enable(service)
        self.round(service)
        self.assertEqual(self.events(),[])
        second=raw_usage(250,50,50)
        total={k:first[k]+second[k] for k in first}
        self.append(file,[{'type':'event_msg','timestamp':'2026-10-22T03:58:00.000Z','payload':{'type':'token_count',
                          'info':{'total_token_usage':total,'last_token_usage':second}}}])
        self.tick(service)
        self.assertEqual([(e['total_tokens'],e['total_basis']) for e in self.events()],[(300,'derived')])
        self.restart(service)
        self.assertEqual(len(self.events()),1)

    def test_claude_streaming_revision_of_pre_boundary_message_is_not_counted(self):
        file=self.claude/'project/session.jsonl'
        self.append(file,[message('m_history',5,output=4)])
        service=self.service()
        self.enable(service,'claude')
        self.round(service)
        self.append(file,[message('m_history',6,output=90),message('m_new',58,output=7)])
        self.tick(service)
        self.append(file,[message('m_new',59,output=9)])
        self.tick(service)
        rows=self.events('claude')
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['output_tokens'],9)

    def test_resumed_copy_in_new_file_does_not_bring_history_back(self):
        old=self.claude/'project/old.jsonl'
        self.append(old,[message('m1',5),message('m2',10)])
        outside=[message('m_outside',3)]  # never present inside the source before; old timestamp
        service=self.service()
        self.enable(service,'claude')
        self.round(service)
        self.append(self.claude/'project/resumed.jsonl',[message('m1',5),message('m2',10)]+outside+[message('m_live',59)])
        self.tick(service)
        self.assertEqual([r['external_event_key'] for r in self.events('claude')].__len__(),1)
        self.assertEqual(self.events('claude')[0]['occurred_ms'],parse_time('2026-10-22T03:59:00.000Z'))

    def test_half_line_truncation_and_replacement(self):
        file=self.codex/'a.jsonl'
        self.append(file,[meta(),response('history',5)])
        service=self.service()
        self.enable(service)
        self.round(service)
        partial=canonical(response('partial',57))
        self.append(file,[],tail=partial[:25])
        self.tick(service)
        self.assertEqual(self.events(),[])
        self.append(file,[],tail=partial[25:]+'\n')
        self.tick(service)
        self.assertEqual(len(self.events()),1)
        # Replaced by an atomic rewrite (new inode) holding history plus one new record.
        replacement=self.codex/'tmp'
        replacement.write_text(''.join(canonical(r)+'\n' for r in [meta(),response('history',5),response('partial',57),response('after_replace',59)]))
        os.replace(replacement,file)
        self.tick(service)
        self.assertEqual(len(self.events()),2)
        # Truncated to nothing: known records stay.
        file.write_text('')
        self.tick(service)
        self.assertEqual(len(self.events()),2)

    def test_missing_then_unreadable_then_recovered_source(self):
        shutil.rmtree(self.codex)
        service=self.service()
        self.enable(service)
        self.round(service)
        source=self.source()
        self.assertEqual((source['connection_status'],source['error_code'],source['retry_mode']),('error','source_missing','automatic'))
        self.assertEqual(source['next_attempt_ms'],self.at+60000)  # Waiting keeps the 60 s check.
        self.tick(service)
        self.assertEqual(self.source()['next_attempt_ms'],self.at+60000)
        self.append(self.codex/'new.jsonl',[meta(),response('first',58)])
        self.tick(service)
        self.assertEqual((self.source()['connection_status'],len(self.events())),('available',1))
        if os.name!='nt' and os.geteuid()!=0:
            self.codex.chmod(0)
            try:
                self.tick(service)
                self.assertEqual(self.source()['connection_status'],'error')
            finally:
                self.codex.chmod(0o700)
            self.append(self.codex/'new.jsonl',[response('second',59)])
            self.advance(900)
            self.round(service)
            self.assertEqual((self.source()['connection_status'],len(self.events())),('available',2))

    def test_missing_boundary_pauses_instead_of_importing_history(self):
        self.append(self.codex/'a.jsonl',[meta(),response('history',5)])
        service=self.service()
        self.enable(service)
        service.stop()
        with connect(self.db) as db:
            db.execute('DELETE FROM collector_boundaries')
        service=self.service()
        self.round(service)
        source=self.source()
        self.assertEqual((source['connection_status'],source['retry_mode'],source['next_attempt_ms']),('error','disabled',None))
        self.assertEqual(self.events(),[])
        self.assertEqual(service.status()['sources'][0]['boundary_status'],'missing')

    def test_upgrade_from_enable_to_import_history_fills_history_once(self):
        file=self.codex/'a.jsonl'
        self.append(file,[meta(),response('history',5)])
        service=self.service()
        self.enable(service)
        self.round(service)
        self.append(file,[response('after',58)])
        self.tick(service)
        self.assertEqual(len(self.events()),1)
        self.assertEqual(self.reason(service,{'provider':'gpt','enabled':True,'location':'custom','history':'from_enable',
                                              'custom_path':str(self.codex),'confirm_scope':'~/.codex/sessions'}),'disable_first')
        self.enable(service,history='import_history')
        self.round(service)
        self.assertEqual(len(self.events()),2)
        self.restart(service)
        self.assertEqual(len(self.events()),2)


class ImportAndLifecycle(SettingsCase):
    def test_import_history_then_restart_without_duplicates_or_reparsing(self):
        for i in range(3):
            self.append(self.codex/('f%d.jsonl'%i),[meta('t%d'%i),response('r%d'%i,5+i,thread='t%d'%i)])
        service=self.service()
        self.enable(service,history='import_history')
        self.round(service)
        self.assertEqual(len(self.events()),3)
        with patch('usage_dashboard.collect.parse_file',wraps=parse_file) as parser:
            service=self.restart(service)
            self.assertEqual(self.round(service)[0]['result'],'unchanged')
            self.assertEqual(parser.call_count,0)  # Checkpoints survive the restart.
        self.append(self.codex/'f1.jsonl',[response('r_new',59,thread='t1')])
        with patch('usage_dashboard.collect.parse_file',wraps=parse_file) as parser:
            self.tick(service)
            self.assertEqual(parser.call_count,1)
        self.assertEqual(len(self.events()),4)

    def test_failed_commit_keeps_checkpoint_and_retries_without_loss_or_double_count(self):
        file=self.codex/'a.jsonl'
        self.append(file,[meta(),response('r1',5)])
        service=self.service()
        self.enable(service,history='import_history')
        self.round(service)
        self.append(file,[response('r2',58)])
        with patch('usage_dashboard.collect.bump_revision',side_effect=RuntimeError('disk full')):
            self.assertEqual(self.tick(service)[0]['result'],'error')
        self.assertEqual(len(self.events()),1)
        self.advance(900)
        self.round(service)
        self.assertEqual(len(self.events()),2)
        self.advance(900)
        self.round(service)
        self.assertEqual(len(self.events()),2)

    def test_disable_stops_reading_and_keeps_data(self):
        file=self.codex/'a.jsonl'
        self.append(file,[meta(),response('r1',5)])
        service=self.service()
        self.enable(service,history='import_history')
        self.round(service)
        status=service.update({'provider':'gpt','enabled':False})
        self.assertIsNone(service.collector)
        self.assertFalse(status['sources'][0]['enabled'])
        source=self.source()
        self.assertEqual((source['retry_mode'],source['next_attempt_ms']),('manual',None))
        self.append(file,[response('r2',58)])
        with patch('usage_dashboard.collect.parse_file') as parser, patch('usage_dashboard.auto_collect.source_files') as walk:
            service=self.restart(service)
            self.assertIsNone(service.collector)
            parser.assert_not_called()
            walk.assert_not_called()
        self.assertEqual(len(self.events()),1)

    def test_one_provider_change_keeps_the_other_collecting(self):
        self.append(self.codex/'a.jsonl',[meta(),response('r1',5)])
        service=self.service()
        self.enable(service,history='import_history')
        self.enable(service,'claude')
        self.round(service)
        self.append(self.claude/'p/s.jsonl',[message('m1',58)])
        service.update({'provider':'gpt','enabled':False})
        self.tick(service)
        self.assertEqual((len(self.events()),len(self.events('claude'))),(1,1))

    def test_account_change_pauses_without_mixing(self):
        def owned(owner,rid):
            row=meta('t_'+owner)
            row['payload']['creator_account_id']=owner
            return [row,response(rid,5+len(owner),thread='t_'+owner)]
        self.append(self.codex/'a.jsonl',owned('one',1 and 'r1'))
        service=self.service()
        self.enable(service,history='import_history')
        self.round(service)
        self.append(self.codex/'b.jsonl',owned('two','r2'))
        self.tick(service)
        source=self.source()
        self.assertEqual((source['connection_status'],source['retry_mode']),('error','disabled'))
        self.assertEqual(len(self.events()),1)


class HttpSettings(SettingsCase):
    def pair(self,app):
        h={'Host':'127.0.0.1:49173','Origin':'http://127.0.0.1:49173','Content-Type':'application/json','X-Dashboard-Pairing':'1'}
        status,data,extra=app.handle('POST','/api/v1/auth/session',h,canonical({'pairing_code':app.auth.pairing_code}).encode())
        self.assertEqual(status,201)
        return {'Host':h['Host'],'Origin':h['Origin'],'Cookie':extra['Set-Cookie'].split(';')[0],'Content-Type':'application/json'},data['data']['csrf_token']

    def test_endpoint_requires_session_csrf_and_hides_paths(self):
        app=Application(self.db,clock=lambda:self.at)
        app.collector=self.service()
        self.assertEqual(app.handle('GET','/api/v1/collector-settings',{'Host':'127.0.0.1:49173'})[0],401)
        headers,csrf=self.pair(app)
        status,body,_=app.handle('GET','/api/v1/collector-settings',headers)
        self.assertEqual(status,200)
        self.assertEqual(body['meta']['api_version'],'0.2.0')
        self.assertNotIn(str(self.home),json.dumps(body))
        request={'provider':'gpt','enabled':True,'location':'standard','history':'from_enable','confirm_scope':'~/.codex/sessions'}
        self.assertEqual(app.handle('POST','/api/v1/collector-settings',headers,canonical(request).encode())[0],403)
        self.assertEqual(app.handle('POST','/api/v1/collector-settings',{**headers,'Origin':'http://127.0.0.1:5174','X-CSRF-Token':csrf},canonical(request).encode())[0],403)
        self.assertEqual(app.handle('PUT','/api/v1/collector-settings',{**headers,'X-CSRF-Token':csrf},canonical(request).encode())[0],404)
        self.assertEqual(app.handle('GET','/api/v1/collector-settings?x=1',headers)[0],422)
        status,body,_=app.handle('POST','/api/v1/collector-settings',{**headers,'X-CSRF-Token':csrf},canonical(request).encode())
        self.assertEqual(status,200,body)
        self.assertTrue(body['data']['sources'][0]['enabled'])
        bad={**request,'confirm_scope':'~'}
        status,body,_=app.handle('POST','/api/v1/collector-settings',{**headers,'X-CSRF-Token':csrf},canonical({**bad,'provider':'claude'}).encode())
        self.assertEqual((status,body['error']['code'],body['error']['details']),(422,'invalid_body',[{'field':'confirm_scope','reason':'scope_not_confirmed'}]))

    def test_plain_application_without_service_reports_disabled(self):
        app=Application(self.db,clock=lambda:self.at)
        headers,csrf=self.pair(app)
        status,body,_=app.handle('GET','/api/v1/collector-settings',headers)
        self.assertEqual((status,body['data']['mode']),(200,'disabled'))
        self.assertEqual(app.handle('POST','/api/v1/collector-settings',{**headers,'X-CSRF-Token':csrf},b'{"provider":"gpt","enabled":false}')[0],422)


class CliStartup(unittest.TestCase):
    def invoke(self,folder,*extra):
        import contextlib, io
        from types import SimpleNamespace
        from unittest.mock import Mock
        from usage_dashboard.__main__ import main
        order=Mock()
        order.serve.side_effect=KeyboardInterrupt
        server=SimpleNamespace(server_port=49173,serve_forever=order.serve,server_close=order.close)
        out,err=io.StringIO(),io.StringIO()
        argv=['usage_dashboard','--data-dir',str(folder),'serve','--port','49283',*extra]
        with patch.object(sys,'argv',argv), patch('usage_dashboard.__main__.make_server',return_value=server) as make, \
             patch('usage_dashboard.__main__.AutoCollector',return_value=order.collector) as factory, \
             contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result=main()
        return result,factory,make,order,out.getvalue()+err.getvalue()

    def enabled_settings(self,folder):
        home=Path(folder)/'home'
        (home/'.codex/sessions').mkdir(parents=True)
        initialize(Path(folder)/'usage.sqlite3')
        service=CollectorService(Path(folder)/'usage.sqlite3',folder,factory=ManualCollector,home=home)
        service.update({'provider':'gpt','enabled':True,'location':'standard','history':'from_enable','confirm_scope':'~/.codex/sessions'})
        service.stop()

    def test_plain_serve_without_settings_never_starts_collector(self):
        with tempfile.TemporaryDirectory() as folder:
            result,factory,make,_,text=self.invoke(folder)
        self.assertEqual(result,0)
        factory.assert_not_called()
        self.assertIsNotNone(make.call_args.kwargs['collector'])
        self.assertIn('not set up',text)

    def test_saved_settings_restart_collection_on_next_launch(self):
        with tempfile.TemporaryDirectory() as folder:
            self.enabled_settings(folder)
            result,factory,_,order,text=self.invoke(folder)
            self.assertEqual(result,0)
            config=factory.call_args.args[1]
            self.assertEqual([s.provider for s in config.sources],['gpt'])
            self.assertIsNotNone(config.sources[0].boundary_id)
            self.assertEqual([c[0] for c in order.mock_calls],['collector.start','serve','collector.stop','close'])
            self.assertNotIn(str(Path(folder)),text)

    def test_no_collection_flag_skips_saved_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            self.enabled_settings(folder)
            result,factory,_,_,text=self.invoke(folder,'--no-collection')
            self.assertEqual(result,0)
            factory.assert_not_called()
            self.assertIn('--no-collection',text)
            result,_,_,_,text=self.invoke(folder,'--no-collection','--collector-config',str(Path(folder)/'x.json'))
            self.assertEqual(result,1)


class MacLauncher(unittest.TestCase):
    def test_double_click_launch_uses_saved_settings_and_auto_connect(self):
        import importlib.util
        source=Path(__file__).resolve().parents[2]/'packaging/mac/launch.py'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            shutil.copy(source,root/'launch.py')
            for name in ('backend/usage_dashboard/__main__.py','backend/sql/001_initial.sql','contracts/openapi.json'):
                (root/name).parent.mkdir(parents=True,exist_ok=True)
                (root/name).write_text('')
            (root/'web').mkdir()
            (root/'web/index.html').write_text('<meta name="usage-dashboard-launch-pairing" content="fragment-v1">')
            spec=importlib.util.spec_from_file_location('bundle_launch',root/'launch.py')
            module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            seen=[]
            import contextlib, io
            for extra in ([],['--no-collection']):
                with patch.object(sys,'argv',['launch.py',*extra]), patch('usage_dashboard.__main__.main',side_effect=lambda:seen.append(list(sys.argv)) or 0), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(module.main(),0)
        self.assertEqual(seen[0],['usage_dashboard','serve','--frontend-dist',str(root/'web'),'--open-browser'])
        self.assertEqual(seen[1][-1],'--no-collection')
        self.assertNotIn('--collector-config',seen[0])


class LegacyCompatibility(unittest.TestCase):
    def test_existing_database_gains_bookkeeping_tables_without_data_change(self):
        with tempfile.TemporaryDirectory() as folder:
            db_path=Path(folder)/'usage.sqlite3'
            initialize(db_path)
            with connect(db_path) as db:
                for table in ('collector_boundaries','collector_boundary_files','collector_history_exclusions','collector_file_checkpoints'):
                    db.execute('DROP TABLE '+table)
                db.execute("UPDATE app_state SET value='41' WHERE key='data_revision'")
            initialize(db_path)
            with connect(db_path) as db:
                names={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({'collector_boundaries','collector_file_checkpoints'}<=names)
                self.assertEqual(db.execute("SELECT value FROM app_state WHERE key='data_revision'").fetchone()[0],'41')
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
