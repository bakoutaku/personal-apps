"""Offline artifact checks, not end-to-end backend or supplier integration tests.

The schema checker deliberately implements only the JSON Schema keywords used
in this contract. It fails on unknown keywords; it is not a general OAS validator.
"""
import copy
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sqlite3
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / 'contracts'
SPEC = json.loads((CONTRACT / 'openapi.json').read_text())
SCHEMAS = SPEC['components']['schemas']
CATALOG = json.loads((CONTRACT / 'mocks/catalog.json').read_text())


def load(path):
    return json.loads((CONTRACT / 'mocks' / path).read_text())


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def ms(value):
    return None if value is None else int(instant(value).timestamp() * 1000)


class Invalid(ValueError):
    pass


def check(value, schema):
    if '$ref' in schema:
        prefix = '#/components/schemas/'
        if not schema['$ref'].startswith(prefix):
            raise Invalid('unsupported reference')
        return check(value, SCHEMAS[schema['$ref'][len(prefix):]])
    for mode in ('anyOf', 'oneOf'):
        if mode in schema:
            successes = 0
            for branch in schema[mode]:
                try:
                    check(value, branch)
                    successes += 1
                except Invalid:
                    pass
            if successes == 0 or (mode == 'oneOf' and successes != 1):
                raise Invalid(mode)
    if 'const' in schema and (value != schema['const'] or
            isinstance(value, bool) != isinstance(schema['const'], bool)):
        raise Invalid('const')
    if 'enum' in schema and value not in schema['enum']:
        raise Invalid('enum')
    kind = schema.get('type')
    valid_type = {'object': lambda: isinstance(value, dict),
                  'array': lambda: isinstance(value, list),
                  'string': lambda: isinstance(value, str),
                  'null': lambda: value is None,
                  'integer': lambda: isinstance(value, int) and not isinstance(value, bool),
                  'number': lambda: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value),
                  'boolean': lambda: isinstance(value, bool)}
    if kind and not valid_type[kind]():
        raise Invalid('type ' + kind)
    if isinstance(value, dict):
        if not set(schema.get('required', [])) <= set(value):
            raise Invalid('required')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(props):
            raise Invalid('additionalProperties')
        if len(value) < schema.get('minProperties', 0):
            raise Invalid('minProperties')
        for key, item in value.items():
            if key in props:
                check(item, props[key])
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0):
            raise Invalid('minItems')
        if schema.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            raise Invalid('uniqueItems')
        for item in value:
            check(item, schema.get('items', {}))
    if isinstance(value, str):
        if not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', float('inf')):
            raise Invalid('length')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            raise Invalid('pattern')
        try:
            if schema.get('format') == 'date-time':
                if instant(value).tzinfo is None:
                    raise ValueError('timezone missing')
            if schema.get('format') == 'uuid':
                uuid.UUID(value)
        except ValueError as exc:
            raise Invalid('format') from exc
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not schema.get('minimum', -float('inf')) <= value <= schema.get('maximum', float('inf')):
            raise Invalid('range')


def walk_schema(schema):
    supported = {'$ref', 'type', 'enum', 'const', 'minimum', 'maximum', 'minLength', 'maxLength',
                 'pattern', 'format', 'properties', 'required', 'additionalProperties', 'items',
                 'minItems', 'uniqueItems', 'minProperties', 'anyOf', 'oneOf', 'default'}
    if set(schema) - supported:
        raise Invalid('unchecked schema keyword: ' + str(set(schema) - supported))
    if '$ref' in schema:
        assert schema['$ref'].split('/')[-1] in SCHEMAS
    for child in schema.get('properties', {}).values():
        walk_schema(child)
    for mode in ('anyOf', 'oneOf'):
        for child in schema.get(mode, []):
            walk_schema(child)
    if 'items' in schema:
        walk_schema(schema['items'])


class ContractTests(unittest.TestCase):
    def test_used_schema_keywords_and_references_are_checked(self):
        for schema in SCHEMAS.values():
            walk_schema(schema)

    def test_all_response_fixtures_match_their_schemas(self):
        for item in CATALOG['fixtures']:
            with self.subTest(file=item['file']):
                check(load(item['file']), SCHEMAS[item['schema']])

    def test_all_fixture_coverage_codes_have_documented_display_text(self):
        registry=json.loads((CONTRACT/'coverage-reasons.json').read_text())
        self.assertFalse(registry['closed_enum'])
        self.assertEqual(registry['api_version'],SPEC['info']['version'])
        codes=set()
        def visit(value):
            if isinstance(value,dict):
                codes.update(value.get('coverage_reasons',[]))
                if 'reason' in value and 'evidence' in value:
                    codes.add(value['reason'])
                for child in value.values():
                    visit(child)
            elif isinstance(value,list):
                for child in value:
                    visit(child)
        for item in CATALOG['fixtures']:
            visit(load(item['file']))
        self.assertTrue(codes.issubset(registry['reasons']))
        for code in codes:
            record=registry['reasons'][code]
            self.assertTrue(record['display_text'])
            self.assertNotEqual(record['display_text'],code)
            self.assertIn(record['current_producer'],('live_and_mock','mock_example'))

    def test_request_fixtures_match_their_schema(self):
        for name in ('gpt-observed', 'claude-tokens'):
            check(load(name + '/label-create-request.json'), SCHEMAS['LabelCreate'])
        check(load('auth/pair-request.json'), SCHEMAS['PairSessionRequest'])

    def test_browser_cookie_and_csrf_security_requirements(self):
        auth = SPEC['paths']['/auth/session']
        self.assertEqual(auth['get']['security'], [{'localSession': []}])
        self.assertEqual(auth['post']['security'], [])
        self.assertEqual(auth['delete']['security'], [{'localSession': [], 'csrfHeader': []}])
        for path, method in [('/labels','post'),('/labels/{id}','patch'),('/labels/{id}','delete')]:
            self.assertEqual(SPEC['paths'][path][method]['security'],
                             [{'localBearer': []}, {'localSession': [], 'csrfHeader': []}])
        self.assertEqual(SPEC['components']['securitySchemes']['localSession']['in'], 'cookie')
        self.assertIn('Set-Cookie', auth['post']['responses']['201']['headers'])
        self.assertIn('Retry-After', auth['post']['responses']['429']['headers'])

    def test_no_store_and_no_cookie_value_in_session_json(self):
        for path in SPEC['paths'].values():
            for operation in path.values():
                for response in operation['responses'].values():
                    self.assertEqual(response['headers']['Cache-Control']['schema']['const'], 'no-store')
        for file in ('auth/paired.json','auth/restored.json'):
            data = load(file)['data']
            self.assertNotIn('session_token', data)
            self.assertNotIn('cookie', data)
            self.assertTrue(data['csrf_token'].startswith('MOCK_'))

    def test_source_history_null_is_not_proof_of_empty(self):
        confirmed = load('states/confirmed-empty-source.json')['data'][0]
        unknown = load('states/unknown-history-source.json')['data'][0]
        self.assertIsNone(confirmed['last_record_at'])
        self.assertIsNone(unknown['last_record_at'])
        self.assertEqual(confirmed['history_status'], 'empty')
        self.assertIsNotNone(confirmed['last_success_at'])
        self.assertEqual(unknown['history_status'], 'unknown')

    def test_retry_fields_and_error_codes_are_explicit(self):
        errors = set(SCHEMAS['SourceErrorCode']['enum'])
        for item in CATALOG['fixtures']:
            if item['schema'] != 'SourcesResponse':
                continue
            for source in load(item['file'])['data']:
                if source['error_code'] is not None:
                    self.assertIn(source['error_code'], errors)
                if source['retry_mode'] != 'automatic':
                    self.assertIsNone(source['next_attempt_at'])
                if source['history_status'] == 'has_records':
                    self.assertIsNotNone(source['last_record_at'])
        failure = load('states/sync-error.json')['data'][0]
        self.assertEqual(failure['consecutive_failure_count'], 3)
        self.assertEqual(failure['retry_mode'], 'automatic')
        self.assertGreater(failure['next_attempt_at'], failure['last_attempt_at'])

    def test_session_track_bounds_come_from_selected_records(self):
        record = load('gpt-observed/sessions-selected-range.json')['data'][0]
        events = load('gpt-observed/usage-events.json')['data']
        selected = [e for e in events if record['range_from']<=e['occurred_at']<record['range_to']]
        self.assertEqual(record['first_record_in_range_at'], min(e['occurred_at'] for e in selected))
        self.assertEqual(record['last_record_in_range_at'], max(e['occurred_at'] for e in selected))
        self.assertLess(record['started_at'], record['first_record_in_range_at'])
        self.assertGreater(record['last_record_at'], record['last_record_in_range_at'])
        self.assertEqual(record['first_record_in_range_at'], record['last_record_in_range_at'])

    def test_catalog_operations_and_status_schemas_exist(self):
        for item in CATALOG['fixtures']:
            path = item['path'].removeprefix('/api/v1')
            operation = SPEC['paths'][path][item['method'].lower()]
            response = operation['responses'][str(item['status'])]
            self.assertEqual(response['content']['application/json']['schema']['$ref'],
                             '#/components/schemas/' + item['schema'])

    def test_catalog_scenarios_disambiguate_request_matches(self):
        seen = set()
        for item in CATALOG['fixtures']:
            self.assertEqual(item['scenario_id'], load(item['file'])['meta']['scenario_id'])
            key = (item['scenario_id'],item['method'],item['path'],json.dumps(item['query'],sort_keys=True),item['status'])
            self.assertNotIn(key, seen)
            seen.add(key)

    def test_recent_activity_ranges_and_counts_do_not_require_quota_windows(self):
        for scenario, product in [('gpt-observed','codex'),('claude-tokens','code')]:
            data = load(scenario+'/recent5h/'+product+'-usage-series.json')['data']
            events = load(scenario+'/recent5h/'+product+'-usage-events.json')['data']
            self.assertEqual((instant(data['to'])-instant(data['from'])).total_seconds(),18000)
            self.assertEqual(data['to'],CATALOG['as_of'])
            self.assertEqual(len(data['buckets']),20)
            self.assertEqual(sum(b['event_count'] for b in data['buckets']),len(events))
            self.assertEqual(sum(b['unknown_total_count'] for b in data['buckets']),1)
            self.assertEqual(sum(b['total_tokens'] or 0 for b in data['buckets']),3000)
            previous=data['from']
            for bucket in data['buckets']:
                self.assertEqual(bucket['from'],previous)
                self.assertNotEqual(bucket['record_state'],'future')
                if bucket['event_count']==0:
                    self.assertIsNone(bucket['total_tokens'])
                previous=bucket['to']
            self.assertEqual(previous,data['to'])
            session=load(scenario+'/recent5h/'+product+'-sessions.json')['data'][0]
            self.assertEqual((session['range_from'],session['range_to']),(data['from'],data['to']))
        boot=CATALOG['scenarios']['claude-tokens']
        self.assertEqual(boot['initial_view'],'recent5h')
        self.assertIsNone(boot['pool_id'])
        self.assertIsNone(boot['window_id'])
        self.assertEqual(load('claude-tokens/quota-pools.json')['data'],[])

    def test_recent_activity_all_and_unconfigured_products_are_honest(self):
        for scenario, product, missing in [('gpt-observed','codex',('chat','work')),('claude-tokens','code',('chat','cowork'))]:
            all_data=load(scenario+'/recent5h/all-usage-series.json')['data']
            self.assertEqual(set(all_data['products']),{product,*missing})
            self.assertEqual(load(scenario+'/recent5h/all-usage-events.json')['data'],
                             load(scenario+'/recent5h/'+product+'-usage-events.json')['data'])
            for item in missing:
                data=load(scenario+'/recent5h/'+item+'-usage-series.json')['data']
                self.assertEqual(load(scenario+'/recent5h/'+item+'-usage-events.json')['data'],[])
                for bucket in data['buckets']:
                    self.assertEqual(bucket['record_state'],'no_records')
                    self.assertEqual(bucket['coverage_status'],'unknown')
                    self.assertIsNone(bucket['total_tokens'])
                    self.assertIn('selected_products_not_configured',bucket['coverage_reasons'])

    def test_full_window_series_covers_window_and_reconciles_records(self):
        response = load('gpt-observed/usage-series-window.json')
        data = response['data']
        window = load('gpt-observed/quota-windows-full.json')['data'][0]
        events = load('gpt-observed/usage-events-window.json')['data']
        self.assertEqual(data['from'],window['starts_at'])
        self.assertEqual(data['to'],window['ends_at'])
        self.assertEqual((instant(data['to'])-instant(data['from'])).total_seconds(),18000)
        previous = data['from']
        for b in data['buckets']:
            self.assertEqual(b['from'],previous)
            selected = [e for e in events if b['from']<=e['occurred_at']<b['to']]
            known = [e['total_tokens'] for e in selected if e['total_tokens'] is not None]
            self.assertEqual(b['event_count'],len(selected))
            self.assertEqual(b['total_tokens'],sum(known) if known else None)
            if b['record_state']=='future':
                self.assertGreaterEqual(b['from'],response['meta']['as_of'])
                self.assertEqual(b['event_count'],0)
            else:
                self.assertLessEqual(b['to'],response['meta']['as_of'])
            previous = b['to']
        self.assertEqual(previous,data['to'])
        self.assertEqual(len(data['buckets']),21)  # 20 nominal bins; current bin split at now.
        self.assertEqual(sum(b['event_count'] for b in data['buckets']),3)
        self.assertEqual(sum(b['total_tokens'] or 0 for b in data['buckets']),3000)

    def test_full_window_companion_queries_have_consistent_scope(self):
        series = load('gpt-observed/usage-series-window.json')['data']
        session = load('gpt-observed/sessions-window.json')['data'][0]
        self.assertEqual((session['range_from'],session['range_to']),(series['from'],series['to']))
        for summary in load('gpt-observed/quota-window-summaries-full.json')['data']:
            self.assertEqual((summary['scope_from'],summary['scope_to']),(series['from'],series['to']))
        self.assertTrue(all(p['window_id']=='win_demo_5h' for p in load('gpt-observed/quota-snapshots-window.json')['data']))

    def test_all_products_window_preserves_records_and_missing_coverage(self):
        all_data = load('gpt-observed/usage-series-window-all.json')['data']
        filtered = load('gpt-observed/usage-series-window.json')['data']
        self.assertEqual(set(all_data['products']), {'chat','work','codex'})
        for bucket, original in zip(all_data['buckets'], filtered['buckets']):
            for key in ('from','to','record_state','coverage_status','total_tokens','event_count','total_status','components'):
                self.assertEqual(bucket[key], original[key])
            if bucket['record_state'] != 'future':
                self.assertIn('selected_products_not_configured', bucket['coverage_reasons'])
                self.assertIn('src_unconfigured_gpt_chat', bucket['source_ids'])
                self.assertIn('src_unconfigured_gpt_work', bucket['source_ids'])
        for name in ('usage-events','sessions','labels'):
            self.assertEqual(load('gpt-observed/'+name+'-window-all.json')['data'],
                             load('gpt-observed/'+name+'-window.json')['data'])
        entries = [f for f in CATALOG['fixtures'] if f['file'].endswith('-window-all.json')]
        self.assertEqual(len(entries),4)
        self.assertTrue(all('products' not in f['query'] for f in entries))

    def test_unconnected_product_states_are_provided_not_inferred(self):
        sources = load('gpt-observed/sources.json')['data']
        for product in ('chat','work'):
            selected = [s for s in sources if s['product']==product]
            self.assertEqual(len(selected),1)
            self.assertEqual(selected[0]['connection_status'],'not_configured')
            self.assertEqual(selected[0]['history_status'],'unknown')

    def test_no_duplicate_operation_ids_or_parameters(self):
        operation_ids = []
        for path in SPEC['paths'].values():
            for operation in path.values():
                operation_ids.append(operation['operationId'])
                keys = [(x['in'], x['name']) for x in operation['parameters']]
                self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    def test_quota_queries_cannot_accept_product_filters(self):
        for path, value in SPEC['paths'].items():
            if path.startswith('/quota-'):
                self.assertNotIn('products', [x['name'] for x in value['get']['parameters']])

    def test_label_revision_and_idempotency_contract(self):
        for method in ('patch', 'delete'):
            op = SPEC['paths']['/labels/{id}'][method]
            match = next(x for x in op['parameters'] if x['name'] == 'If-Match')
            self.assertTrue(match['required'])
            self.assertIn('428', op['responses'])
            self.assertIn('412', op['responses'])
        self.assertIn('client_request_id', SCHEMAS['LabelCreate']['required'])

    def test_mock_mode_clock_and_no_real_credentials(self):
        for item in CATALOG['fixtures']:
            response = load(item['file'])
            self.assertEqual(response['meta']['data_mode'], 'mock')
            self.assertEqual(response['meta']['as_of'], CATALOG['as_of'])
            text = json.dumps(response).lower()
            for forbidden in ('access_token', 'refresh_token', 'cookie', 'prompt', 'api_key'):
                self.assertNotIn('"' + forbidden + '"', text)

    def test_strict_body_and_exclusive_label_targets(self):
        body = load('gpt-observed/label-create-request.json')
        for change in ({'unexpected': True}, {'name': '   '}, {'name': 'x'*81}):
            with self.subTest(change=change), self.assertRaises(Invalid):
                check({**body, **change}, SCHEMAS['LabelCreate'])
        bad = copy.deepcopy(body)
        bad['target']['session_id'] = 'session_accidentally_mixed_with_range'
        with self.assertRaises(Invalid):
            check(bad, SCHEMAS['LabelCreate'])
        with self.assertRaises(Invalid):
            check({}, SCHEMAS['LabelPatch'])

    def test_provider_and_label_references_in_screen_datasets(self):
        for scenario in ('gpt-observed', 'claude-tokens'):
            sources = {s['id']: s for s in load(scenario + '/sources.json')['data']}
            sessions = {s['id']: s for s in load(scenario + '/sessions.json')['data']}
            labels = {s['id']: s for s in load(scenario + '/labels.json')['data']}
            for event in load(scenario + '/usage-events.json')['data']:
                self.assertEqual(sources[event['source_id']]['account_id'], event['account_id'])
                self.assertLessEqual(event['recorded_at'], sources[event['source_id']]['last_record_at'])
                self.assertEqual(sessions[event['session_id']]['product'], event['product'])
                self.assertTrue(set(event['label_ids']) <= labels.keys())
            if scenario == 'gpt-observed':
                for point in load(scenario + '/quota-snapshots.json')['data']:
                    self.assertLessEqual(point['recorded_at'], sources[point['source_id']]['last_record_at'])

    def test_bins_reconcile_with_events_without_imputing_zero(self):
        for scenario in ('gpt-observed', 'claude-tokens'):
            events = load(scenario + '/usage-events.json')['data']
            series = load(scenario + '/usage-series.json')['data']
            previous = series['from']
            for bucket in series['buckets']:
                self.assertEqual(bucket['from'], previous)
                selected = [e for e in events if bucket['from'] <= e['occurred_at'] < bucket['to']]
                known = [e['total_tokens'] for e in selected if e['total_tokens'] is not None]
                self.assertEqual(bucket['event_count'], len(selected))
                self.assertEqual(bucket['known_total_count'], len(known))
                self.assertEqual(bucket['unknown_total_count'], len(selected)-len(known))
                self.assertEqual(bucket['total_tokens'], sum(known) if known else None)
                if bucket['components_complete']:
                    self.assertEqual(sum(bucket['components'].values()), bucket['total_tokens'])
                previous = bucket['to']
            self.assertEqual(previous, series['to'])

    def test_daily_weekly_monthly_charts_have_same_historical_total(self):
        events = load('history/usage-events.json')['data']
        for resolution in ('day', 'week', 'month'):
            data = load('history/usage-series-' + resolution + '.json')['data']
            previous = data['from']
            for bucket in data['buckets']:
                self.assertEqual(bucket['from'], previous)
                records = [e for e in events if bucket['from'] <= e['occurred_at'] < bucket['to']]
                self.assertEqual(bucket['event_count'], len(records))
                self.assertEqual(bucket['total_tokens'], sum(e['total_tokens'] for e in records) if records else None)
                previous = bucket['to']
            self.assertEqual(previous, data['to'])
            self.assertEqual(sum(b['total_tokens'] or 0 for b in data['buckets']), 4000)
        weekly = load('history/usage-series-week.json')['data']['buckets']
        self.assertTrue(weekly[0]['is_partial_bucket'])
        self.assertEqual(instant(weekly[1]['from']).astimezone(__import__('zoneinfo').ZoneInfo('Asia/Tokyo')).weekday(), 0)

    def test_snapshots_use_record_time_not_import_time(self):
        points = load('gpt-observed/quota-snapshots.json')['data']
        for point in points:
            self.assertIsNone(point['observed_at'])
            self.assertEqual(point['effective_at'], point['recorded_at'])
            self.assertEqual(point['time_basis'], 'recorded_at')
            self.assertLess(instant(point['effective_at']), instant(point['ingested_at']))

    def test_window_boundaries_freshness_and_expiry(self):
        for file in ('gpt-observed/quota-windows.json', 'states/expired-window.json',
                     'states/unknown-boundaries.json', 'states/stale-current-window.json'):
            response = load(file)
            for window in response['data']:
                for field, basis in [('starts_at', 'start_source'), ('ends_at', 'end_source')]:
                    self.assertEqual(window[field] is None, window[basis] == 'unknown')
                if window['start_source'] == 'derived':
                    self.assertEqual((instant(window['ends_at'])-instant(window['starts_at'])).total_seconds(), window['duration_seconds'])
                if window['ends_at'] is None:
                    self.assertEqual(window['status'], 'unknown')
                else:
                    self.assertEqual(window['status'] == 'expired', window['ends_at'] <= response['meta']['as_of'])
                age = (instant(response['meta']['as_of'])-instant(window['latest_snapshot']['effective_at'])).total_seconds()
                self.assertEqual(window['freshness'] == 'stale', age > response['meta']['stale_after_seconds'])

    def test_quota_peak_is_observed_max_not_sum(self):
        points = load('gpt-observed/quota-snapshots.json')['data']
        for summary in load('gpt-observed/quota-window-summaries.json')['data']:
            samples = [p for p in points if p['window_id'] == summary['window_id']]
            self.assertEqual(summary['sample_count'], len(samples))
            self.assertEqual(summary['max_observed_percent'], max(p['used_percent'] for p in samples))
            if len(samples) > 1:
                self.assertNotEqual(summary['max_observed_percent'], sum(p['used_percent'] for p in samples))

    def test_future_is_split_from_elapsed_time_and_never_zero(self):
        response = load('states/future-range.json')
        for bucket in response['data']['buckets']:
            self.assertLess(bucket['from'], bucket['to'])
            if bucket['record_state'] == 'future':
                self.assertGreaterEqual(bucket['from'], response['meta']['as_of'])
                self.assertIsNone(bucket['total_tokens'])
                self.assertEqual(bucket['event_count'], 0)
            else:
                self.assertLessEqual(bucket['to'], response['meta']['as_of'])

    def test_claude_does_not_invent_a_quota_pool(self):
        self.assertEqual(load('claude-tokens/quota-pools.json')['data'], [])

    def test_paginated_example_has_no_duplicates_or_missing_events(self):
        for scenario in ('gpt-observed', 'claude-tokens'):
            a = load(scenario + '/usage-events-page-1.json')
            b = load(scenario + '/usage-events-page-2.json')
            self.assertTrue(a['page']['has_more'])
            self.assertIsNotNone(a['page']['next_cursor'])
            self.assertFalse(b['page']['has_more'])
            self.assertEqual(a['data'] + b['data'], load(scenario + '/usage-events.json')['data'])


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript((ROOT / 'backend/sql/001_initial.sql').read_text())
        for a in load('accounts.json')['data']:
            self.insert('accounts', **a)
        self.insert('accounts', id='acct_other', provider='gpt', label='Other', identity_status='local_unverified')
        self.insert('devices', id='device_demo', label='Mock', platform='macos')
        for scenario in ('gpt-observed', 'claude-tokens'):
            for s in load(scenario + '/sources.json')['data']:
                self.insert('sources', **{k: s[k] for k in ('id','account_id','provider','product','device_id','kind','connection_status')})
            for s in load(scenario + '/sessions.json')['data']:
                self.insert('sessions', **{k: s[k] for k in ('id','source_id','account_id','provider','product')},
                            external_session_key=s['id'], started_ms=ms(s['started_at']), last_record_ms=ms(s['last_record_at']))
        for p in load('gpt-observed/quota-pools.json')['data']:
            self.insert('quota_pools', **{k: p[k] for k in ('id','account_id','provider','label','provider_bucket_key','product_membership_complete','membership_evidence')}, product_membership_known=1)
            self.insert('quota_pool_sources', pool_id=p['id'], source_id=p['source_ids'][0], account_id=p['account_id'], provider=p['provider'])
        w = load('gpt-observed/quota-windows.json')['data'][0]
        self.insert('quota_windows', **{k: w[k] for k in ('id','pool_id','slot','duration_seconds','start_source','end_source','semantics')},
                    external_window_key=w['id'], starts_ms=ms(w['starts_at']), ends_ms=ms(w['ends_at']))

    def tearDown(self):
        self.db.close()

    def insert(self, table, **fields):
        # Table/column identifiers originate only from these tests and fixed schemas.
        sql = 'INSERT INTO ' + table + ' (' + ','.join(fields) + ') VALUES (' + ','.join('?' for _ in fields) + ')'
        self.db.execute(sql, list(fields.values()))

    def event(self, **overrides):
        e = load('gpt-observed/usage-events.json')['data'][0]
        values = {k: e[k] for k in ('id','source_id','account_id','provider','product','session_id','total_tokens','total_basis','components_complete','reasoning_output_tokens')}
        values.update(e['components'])
        values.update(external_event_key=e['id'], occurred_ms=ms(e['occurred_at']), recorded_ms=ms(e['recorded_at']), ingested_ms=ms(e['ingested_at']))
        values.update(overrides)
        return values

    def label(self, **overrides):
        values = dict(id='label_test', account_id='acct_demo_gpt', provider='gpt', client_request_id='request_test',
                      create_request_hash='synthetic_hash', name='Task', target_kind='range', from_ms=1, to_ms=5,
                      revision=1, created_ms=1, updated_ms=1)
        values.update(overrides)
        return values

    def test_schema_version_and_foreign_keys(self):
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0], 1)
        self.assertEqual(self.db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_source_error_table_matches_fixed_contract_enum(self):
        codes = {row[0] for row in self.db.execute('SELECT code FROM source_error_codes')}
        self.assertEqual(codes, set(SCHEMAS['SourceErrorCode']['enum']))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE sources SET error_code='raw_vendor_error' WHERE id='src_demo_gpt'")

    def test_source_history_and_schedule_constraints(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE sources SET history_status='empty',last_success_ms=NULL WHERE id='src_demo_gpt'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE sources SET retry_mode='manual',next_attempt_ms=100 WHERE id='src_demo_gpt'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE sources SET consecutive_failure_count=-1 WHERE id='src_demo_gpt'")
        self.db.execute("UPDATE sources SET history_status='empty',last_success_ms=100,last_record_ms=NULL WHERE id='src_demo_gpt'")

    def test_app_session_storage_accepts_digest_not_raw_secret(self):
        fields = dict(id='local_session',token_digest='a'*64,origin='http://127.0.0.1:49173',
                      created_ms=1,last_seen_ms=2,expires_ms=3)
        self.insert('app_sessions', **fields)
        for bad in ({'id':'bad_secret','token_digest':'raw-session-value'},
                    {'id':'bad_time','token_digest':'b'*64,'expires_ms':2}):
            with self.subTest(bad=bad), self.assertRaises(sqlite3.IntegrityError):
                self.insert('app_sessions', **{**fields,**bad})

    def test_valid_events_roundtrip_and_unknown_stays_null(self):
        self.insert('usage_events', **self.event())
        self.insert('usage_events', **self.event(id='unknown', external_event_key='unknown', total_tokens=None,
                    total_basis='unknown', components_complete=False, uncached_input_tokens=None,
                    cache_read_input_tokens=None, cache_write_input_tokens=None, output_tokens=None, reasoning_output_tokens=None))
        self.assertIsNone(self.db.execute("SELECT total_tokens FROM usage_events WHERE id='unknown'").fetchone()[0])

    def test_duplicate_source_event_is_rejected(self):
        self.insert('usage_events', **self.event())
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert('usage_events', **self.event(id='different_local_id'))

    def test_cross_account_and_cross_product_event_rejected(self):
        for bad in ({'account_id':'acct_other'}, {'product':'work'}, {'session_id':'ses_demo_claude'}):
            with self.subTest(bad=bad), self.assertRaises(sqlite3.IntegrityError):
                self.insert('usage_events', **self.event(**bad))

    def test_incomplete_or_double_counted_components_rejected(self):
        for bad in ({'total_tokens':1050}, {'cache_read_input_tokens':None}, {'reasoning_output_tokens':201}, {'total_tokens':-1}, {'total_tokens':1000.5}):
            with self.subTest(bad=bad), self.assertRaises(sqlite3.IntegrityError):
                self.insert('usage_events', **self.event(**bad))

    def test_unknown_total_cannot_be_reported(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert('usage_events', **self.event(total_tokens=None, total_basis='reported', components_complete=False))

    def test_quota_snapshot_time_basis_and_scope_enforced(self):
        point = load('gpt-observed/quota-snapshots.json')['data'][0]
        row = {k:point[k] for k in ('id','pool_id','window_id','source_id','time_basis','used_percent','value_basis')}
        row.update(external_snapshot_key=point['id'], observed_ms=None, recorded_ms=ms(point['recorded_at']),
                   ingested_ms=ms(point['ingested_at']), effective_ms=ms(point['effective_at']))
        for bad in ({'source_id':'src_demo_claude'}, {'effective_ms':ms(point['ingested_at'])}, {'used_percent':-1}, {'window_id':'missing'}):
            with self.subTest(bad=bad), self.assertRaises(sqlite3.IntegrityError):
                self.insert('quota_snapshots', **{**row, **bad})
        self.insert('quota_snapshots', **row)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert('quota_snapshots', **{**row, 'id':'duplicate'})

    def test_unknown_boundary_cannot_claim_reported(self):
        row = dict(id='bad_win', pool_id='pool_demo_gpt', slot='primary', external_window_key='bad_win',
                   start_source='reported', end_source='unknown', semantics='unknown')
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert('quota_windows', **row)

    def test_label_range_session_and_account_constraints(self):
        for bad in ({'from_ms':6}, {'name':'   '}, {'target_kind':'session'},
                    {'target_kind':'session','from_ms':None,'to_ms':None,'session_id':'ses_demo_claude'}):
            with self.subTest(bad=bad), self.assertRaises(sqlite3.IntegrityError):
                self.insert('labels', **self.label(**bad))
        self.insert('labels', **self.label(target_kind='session', from_ms=None, to_ms=None, session_id='ses_demo_gpt'))

    def test_label_create_idempotency_key_unique(self):
        self.insert('labels', **self.label())
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert('labels', **self.label(id='another'))

    def test_label_revision_compare_and_swap_and_delete_preserves_usage(self):
        self.insert('usage_events', **self.event())
        self.insert('labels', **self.label())
        good = self.db.execute("UPDATE labels SET revision=revision+1 WHERE id=? AND revision=?", ('label_test',1))
        stale = self.db.execute("UPDATE labels SET revision=revision+1 WHERE id=? AND revision=?", ('label_test',1))
        self.assertEqual(good.rowcount, 1)
        self.assertEqual(stale.rowcount, 0)
        self.db.execute("UPDATE labels SET deleted_ms=10,revision=revision+1 WHERE id='label_test'")
        self.assertEqual(self.db.execute('SELECT count(*) FROM usage_events').fetchone()[0],1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.insert('labels', **self.label(id='replayed'))

    def test_overlapping_labels_do_not_require_duplicate_event_rows(self):
        event = self.event()
        self.insert('usage_events', **event)
        at = event['occurred_ms']
        self.insert('labels', **self.label(from_ms=at-1,to_ms=at+1))
        self.insert('labels', **self.label(id='label_two',client_request_id='request_two',from_ms=at-2,to_ms=at+2))
        rows = self.db.execute('''SELECT DISTINCT e.id,e.total_tokens FROM usage_events e JOIN labels l
          ON e.account_id=l.account_id AND e.provider=l.provider AND l.target_kind='range'
          AND e.occurred_ms>=l.from_ms AND (l.to_ms IS NULL OR e.occurred_ms<l.to_ms)''').fetchall()
        self.assertEqual(sum(row[1] for row in rows), event['total_tokens'])


if __name__ == '__main__':
    unittest.main()
