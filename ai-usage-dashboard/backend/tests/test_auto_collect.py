import copy
import http.client
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from usage_dashboard.auto_collect import AutoCollector, CollectorConfig, SourceConfig, load_config
from usage_dashboard.collect import collect, parse_file
from usage_dashboard.common import canonical, iso
from usage_dashboard.store import connect, initialize
from usage_dashboard.query import sources
from usage_dashboard.server import make_server
from test_backend import NOW, BEARER, codex_rows, claude_row, raw_usage
from test_contract import check, SCHEMAS


class AutoCollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.logs=self.root/'logs'
        self.logs.mkdir()
        self.file=self.logs/'session.jsonl'
        self.db=self.root/'private/usage.sqlite3'
        initialize(self.db)
        self.at=NOW
        self.mono=0
        self.collectors=[]

    def tearDown(self):
        for collector in self.collectors:
            collector.stop()
        self.temp.cleanup()

    def scheduler(self,provider='gpt',path=None,namespace='local'):
        cfg=CollectorConfig(60,(SourceConfig(provider,path or self.logs,namespace),))
        collector=AutoCollector(self.db,cfg,clock=lambda:self.at,monotonic=lambda:self.mono)
        self.collectors.append(collector)
        return collector

    def advance(self,seconds=60,wall=True,mono=True):
        if wall:
            self.at+=seconds*1000
        if mono:
            self.mono+=seconds

    def write(self,rows,path=None,tail=''):
        file=path or self.file
        old=file.stat().st_mtime_ns if file.exists() else 0
        file.write_text(''.join(canonical(r)+'\n' for r in rows)+tail)
        stamp=max(time.time_ns(),old+1000000000)
        os.utime(file,ns=(stamp,stamp))

    def rows(self,sql):
        with connect(self.db) as db:
            return [dict(r) for r in db.execute(sql)]

    def source(self,provider='gpt'):
        return self.rows("SELECT * FROM sources WHERE kind='local_log' AND provider='"+provider+"'")[0]

    def test_unchanged_files_skip_parsing_but_keep_snapshot_time(self):
        self.write(codex_rows())
        collector=self.scheduler()
        with patch('usage_dashboard.collect.parse_file',wraps=parse_file) as parser:
            self.assertEqual(collector.run_due()[0]['files_processed'],1)
            self.assertEqual(collector.run_due(),[])
            self.advance(1800)
            self.assertEqual(collector.run_due()[0]['result'],'unchanged')
            self.assertEqual(parser.call_count,1)
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)
        self.assertEqual(self.source()['last_success_ms'],self.at)
        self.assertTrue(all(s['effective_ms']==NOW-120000 for s in self.rows('SELECT * FROM quota_snapshots')))
        self.assertEqual(self.source()['next_attempt_ms'],self.at+60000)

    def test_only_changed_file_is_reparsed_and_copies_are_deduplicated(self):
        rows=codex_rows()
        self.write(rows)
        self.write(rows,self.logs/'copy.jsonl')
        collector=self.scheduler()
        self.assertEqual(collector.run_due()[0]['files_processed'],2)
        new={'type':'token_usage_record','timestamp':'2026-10-22T03:45:00.000Z',
             'payload':{'thread_id':'synthetic_thread','response_id':'new_response','usage':raw_usage()}}
        self.write(rows+[new])
        self.advance()
        self.assertEqual(collector.run_due()[0]['files_processed'],1)
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),3)

    def test_rotation_and_truncation_keep_known_history(self):
        rows=codex_rows()
        self.write(rows)
        collector=self.scheduler()
        collector.run_due()
        self.file.rename(self.logs/'rotated.jsonl')
        self.advance()
        self.assertEqual(collector.run_due()[0]['files_processed'],1)
        self.write(rows[:2],self.logs/'rotated.jsonl')
        self.advance()
        collector.run_due()
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)

    def test_rotation_during_discovery_does_not_permanently_pause_source(self):
        self.write(codex_rows())
        collector=self.scheduler()
        with patch('usage_dashboard.collect.os.walk',return_value=[(str(self.logs),[],['gone.jsonl',self.file.name])]):
            collector.run_due()
        self.assertFalse(collector.jobs[0].paused)
        self.assertEqual(self.source()['connection_status'],'available')

    def test_incomplete_tail_is_imported_only_after_completion(self):
        rows=codex_rows()
        extra={'type':'token_usage_record','timestamp':'2026-10-22T03:45:00.000Z',
               'payload':{'thread_id':'synthetic_thread','response_id':'tail_response','usage':raw_usage()}}
        self.write(rows,tail=canonical(extra))
        collector=self.scheduler()
        collector.run_due()
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)
        with self.file.open('a') as f:
            f.write('\n')
        self.advance()
        collector.run_due()
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),3)

    def test_missing_source_backoff_recovery_and_schema(self):
        self.write(codex_rows())
        collector=self.scheduler()
        collector.run_due()
        shutil.rmtree(self.logs)
        self.advance()
        collector.run_due()
        first=self.source()
        self.assertEqual((first['error_code'],first['history_status'],first['retry_mode']),('source_missing','has_records','automatic'))
        self.assertEqual(first['last_success_ms'],NOW)
        self.assertEqual(first['next_attempt_ms'],self.at+60000)
        self.advance()
        collector.run_due()
        self.assertEqual(self.source()['next_attempt_ms'],self.at+120000)
        self.assertEqual(self.source()['consecutive_failure_count'],2)
        self.logs.mkdir()
        self.write(codex_rows())
        self.advance(120)
        collector.run_due()
        self.assertEqual((self.source()['connection_status'],self.source()['consecutive_failure_count']),('available',0))
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)
        with connect(self.db) as db:
            check({'data':sources(db,'gpt',self.source()['account_id']),
                   'meta':{'api_version':'0.2.0','data_mode':'live','as_of':iso(self.at),'data_revision':1,
                           'scenario_id':None,'timezone':'Asia/Tokyo','stale_after_seconds':900,'warnings':[]}},SCHEMAS['SourcesResponse'])

    def test_empty_directory_is_unknown_until_recognized_scan(self):
        collector=self.scheduler()
        collector.run_due()
        self.assertEqual(self.source()['history_status'],'unknown')
        self.assertEqual(self.source()['error_code'],'unsupported_format')
        self.write(codex_rows()[:1])
        self.advance()
        collector.run_due()
        self.assertEqual((self.source()['history_status'],self.source()['connection_status']),('empty','available'))

    def test_account_change_pauses_and_does_not_merge(self):
        rows=codex_rows()
        rows[0]['payload']['creator_account_id']='PRIVATE_ACCOUNT_A'
        self.write(rows)
        collector=self.scheduler()
        collector.run_due()
        rows[0]['payload']['creator_account_id']='PRIVATE_ACCOUNT_B'
        self.write(rows)
        self.advance()
        collector.run_due()
        self.assertEqual(self.source()['retry_mode'],'disabled')
        self.assertIsNone(self.source()['next_attempt_ms'])
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)
        self.advance(3600)
        self.assertEqual(collector.run_due(),[])
        self.assertNotIn(b'PRIVATE_ACCOUNT_',self.db.read_bytes())

    def test_worker_errors_are_sanitized_and_paths_not_persisted(self):
        self.write(codex_rows())
        collector=self.scheduler(namespace='PRIVATE_NAMESPACE')
        with patch('usage_dashboard.collect.parse_file',side_effect=RuntimeError('PRIVATE_EXCEPTION_SECRET')):
            collector.run_due()
        self.assertEqual(self.source()['error_code'],'collector_internal_error')
        data=self.db.read_bytes()
        for private in (str(self.file).encode(),str(self.logs).encode(),b'PRIVATE_NAMESPACE',b'PRIVATE_EXCEPTION_SECRET'):
            self.assertNotIn(private,data)

    def test_permission_error_retries_without_false_empty(self):
        collector=self.scheduler()
        with patch.object(collector,'_snapshot',side_effect=PermissionError('PRIVATE_PATH')):
            collector.run_due()
        self.assertEqual((self.source()['error_code'],self.source()['history_status']),('permission_denied','unknown'))

    def test_symlinks_are_not_followed(self):
        self.write(codex_rows())
        outside=self.root/'outside'
        outside.mkdir()
        (outside/'secret.jsonl').write_text('NOT_A_TRANSCRIPT\n')
        try:
            (self.logs/'linked-dir').symlink_to(outside,target_is_directory=True)
            (self.logs/'linked.jsonl').symlink_to(outside/'secret.jsonl')
        except OSError:
            self.skipTest('Symlink creation is not available')
        collector=self.scheduler()
        self.assertEqual(collector.run_due()[0]['files_processed'],1)
        self.assertEqual(self.source()['connection_status'],'available')

    def test_restart_rescans_without_duplicate_and_stop_clears_plan(self):
        self.write(codex_rows())
        one=self.scheduler()
        one.run_due()
        one.stop()
        self.assertEqual(self.source()['retry_mode'],'manual')
        self.assertIsNone(self.source()['next_attempt_ms'])
        two=self.scheduler()
        self.assertEqual(two.run_due()[0]['files_processed'],1)
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)

    def test_manual_import_can_run_after_automatic_without_constraint_failure(self):
        self.write(codex_rows())
        collector=self.scheduler()
        collector.run_due()
        collect(self.db,'gpt',self.file,clock=lambda:self.at)
        self.assertEqual(self.source()['retry_mode'],'manual')
        self.assertIsNone(self.source()['next_attempt_ms'])
        self.advance()
        collector.run_due()
        self.assertEqual(self.source()['retry_mode'],'automatic')

    def test_cancellation_rolls_back_in_progress_import(self):
        self.write(codex_rows())
        collector=self.scheduler()
        collector.run_due()
        new=copy.deepcopy(codex_rows())
        new[1]['payload']['response_id']='cancelled_response'
        self.write(new)
        def cancel_after_parse(*args):
            result=parse_file(*args)
            collector.cancel.set()
            return result
        self.advance()
        with patch('usage_dashboard.collect.parse_file',side_effect=cancel_after_parse):
            collector.run_due()
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)
        self.assertFalse(self.rows("SELECT * FROM collection_runs WHERE status='running'"))
        collector.stop()
        self.assertIsNone(self.source()['next_attempt_ms'])

    def test_clock_jump_or_resume_runs_once_without_catchup_burst(self):
        self.write(codex_rows())
        collector=self.scheduler()
        collector.run_due()
        self.advance(3600,mono=False)
        self.assertEqual(len(collector.run_due()),1)
        self.assertEqual(collector.run_due(),[])
        self.advance(60,wall=False)
        self.assertEqual(len(collector.run_due()),1)

    def test_wall_clock_rollback_during_parse_does_not_lose_batch(self):
        self.write(codex_rows())
        collector=self.scheduler()
        def rollback(*args):
            result=parse_file(*args)
            self.at-=1000
            return result
        with patch('usage_dashboard.collect.parse_file',side_effect=rollback):
            collector.run_due()
        self.assertEqual(self.source()['connection_status'],'available')
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)
        self.assertTrue(all(r['ended_ms']>=r['started_ms'] for r in self.rows('SELECT * FROM collection_runs')))

    def test_future_record_is_revisited_without_file_change(self):
        row=claude_row()
        row['timestamp']=iso(NOW+180000)
        self.write([row])
        collector=self.scheduler('claude')
        collector.run_due()
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),0)
        self.advance(180)
        collector.run_due()
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),1)

    def test_thread_stops_and_does_not_collect_after_shutdown(self):
        self.write(codex_rows())
        collector=self.scheduler()
        collector.start()
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not self.rows('SELECT * FROM usage_events'):
            time.sleep(.01)
        collector.stop()
        self.assertFalse(collector.thread.is_alive())
        self.assertEqual(len(self.rows('SELECT * FROM usage_events')),2)
        self.advance(3600)
        self.assertEqual(collector.run_due(),[])

    def test_one_source_failure_does_not_block_other_provider(self):
        claude_path=self.root/'claude.jsonl'
        self.write([claude_row()],claude_path)
        cfg=CollectorConfig(60,(SourceConfig('gpt',self.root/'missing'),SourceConfig('claude',claude_path)))
        collector=AutoCollector(self.db,cfg,clock=lambda:self.at,monotonic=lambda:self.mono)
        self.collectors.append(collector)
        self.assertEqual([r['result'] for r in collector.run_due()],['error','available'])
        self.assertEqual(self.source('claude')['connection_status'],'available')

    def test_backoff_is_capped_and_does_not_poll_before_due(self):
        collector=self.scheduler(path=self.root/'missing')
        for delay in (60,120,240,480,900,900):
            collector.run_due()
            self.assertEqual(self.source()['next_attempt_ms']-self.at,delay*1000)
            self.assertEqual(collector.run_due(),[])
            self.advance(delay)

    def test_changed_legacy_file_keeps_cumulative_baseline(self):
        rows=codex_rows(modern=False)
        self.write(rows)
        collector=self.scheduler()
        collector.run_due()
        last=copy.deepcopy(rows[2])
        last['timestamp']='2026-10-22T03:45:00.000Z'
        addition=raw_usage()
        info=last['payload']['info']
        info['total_token_usage']={k:v+addition[k] for k,v in info['total_token_usage'].items()}
        info['last_token_usage']=addition
        self.write(rows+[last])
        self.advance()
        collector.run_due()
        self.assertEqual([r['total_tokens'] for r in self.rows('SELECT total_tokens FROM usage_events ORDER BY occurred_ms')],[120,240,120])

    def test_scheduled_data_and_retry_metadata_are_visible_over_http(self):
        self.write(codex_rows())
        collector=self.scheduler()
        collector.run_due()
        try:
            server=make_server(self.db,0,bearer=BEARER,clock=lambda:self.at)
        except PermissionError:
            self.skipTest('Loopback socket permission required')
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
        try:
            query={'provider':'gpt','account_id':self.source()['account_id']}
            client.request('GET','/api/v1/sources?'+urlencode(query),headers={'Authorization':'Bearer '+BEARER})
            response=client.getresponse()
            self.assertEqual(response.status,200)
            body=json.loads(response.read())
            check(body,SCHEMAS['SourcesResponse'])
            source=next(s for s in body['data'] if s['kind']=='local_log')
            self.assertEqual(source['retry_mode'],'automatic')
            self.assertEqual(source['next_attempt_at'],iso(self.at+60000))
        finally:
            client.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


class CollectorConfigurationTests(unittest.TestCase):
    def test_example_is_disabled_and_has_no_implicit_scan(self):
        config=load_config(Path(__file__).resolve().parents[1]/'examples/collector-config.example.json')
        self.assertEqual(config.sources,())
        with tempfile.TemporaryDirectory() as folder:
            db=Path(folder)/'db.sqlite3'
            initialize(db)
            collector=AutoCollector(db,config)
            with patch('usage_dashboard.auto_collect.source_files',side_effect=AssertionError('Must not scan')):
                collector.start()
                self.assertIsNone(collector.thread)
                collector.stop()
            with connect(db) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM accounts').fetchone()[0],0)

    def test_strict_configuration_validation_and_duplicate_namespace(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            base={'version':1,'interval_seconds':60,'sources':[{'enabled':True,'provider':'gpt','path':str(Path(folder).resolve()),'account_namespace':'local'}]}
            path.write_text(canonical(base))
            self.assertEqual(len(load_config(path).sources),1)
            variants=[{**base,'version':True},{**base,'interval_seconds':True},{**base,'interval_seconds':29},
                      {**base,'cookie':'PRIVATE_SECRET'},{**base,'sources':base['sources']*2},
                      {**base,'sources':[{**base['sources'][0],'path':'relative/path'}]}]
            for data in variants:
                path.write_text(canonical(data))
                with self.subTest(data_fields=list(data)),self.assertRaises(ValueError) as caught:
                    load_config(path)
                self.assertNotIn('PRIVATE_SECRET',str(caught.exception))
            path.write_text('{"version":1,"version":1,"interval_seconds":60,"sources":[]}')
            with self.assertRaises(ValueError):
                load_config(path)

    def test_oversized_and_symlink_config_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                load_config(Path(folder))
            path=Path(folder)/'large.json'
            path.write_text(' '*65537)
            with self.assertRaises(ValueError):
                load_config(path)
            link=Path(folder)/'link.json'
            try:
                link.symlink_to(path)
            except OSError:
                self.skipTest('Symlink creation is not available')
            with self.assertRaises(ValueError):
                load_config(link)
