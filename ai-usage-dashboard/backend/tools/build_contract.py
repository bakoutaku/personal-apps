"""Generate the reviewable v0.2 contract and synthetic fixtures; no collection/network."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from build_history import generate_history
from build_label_workflow import generate_label_workflow

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'contracts'
S = {}
VERSION = '0.2.0'
MOCK_REVISION = 6
COVERAGE_REASONS = {
    'local_device_only': {'display_text':'仅本机日志，其他设备未覆盖', 'current_producer':'live_and_mock',
                          'meaning':'只说明采集范围，不代表本机全部请求已完整捕获。'},
    'no_records_not_proof_of_zero': {'display_text':'没有已记录事件，不等于没有使用', 'current_producer':'live_and_mock',
                                   'meaning':'当前范围没有匹配记录，不能据此将未知用量填为零。'},
    'selected_products_not_configured': {'display_text':'所选产品中有未接入的来源', 'current_producer':'live_and_mock',
                                        'meaning':'至少一个所选产品来源未配置；不代表全部未接入，需结合 sources 判断。'},
    'not_yet_elapsed': {'display_text':'该时段尚未发生', 'current_producer':'live_and_mock',
                       'meaning':'未来区间，不是采集缺口，也不是零用量。'},
    'synthetic_local_history': {'display_text':'模拟本机历史，仅包含样例记录', 'current_producer':'mock_example',
                                'meaning':'虚构历史样例的覆盖依据；不是实际设备或全账户覆盖证据。'},
    'collector_could_not_read_source': {'display_text':'采集时无法读取来源，此段覆盖存在缺口', 'current_producer':'mock_example',
                                       'meaning':'当前用于失败状态样例；应保留之前有效记录，不将缺口当作零。'},
    'one_event_has_unknown_usage': {'display_text':'该桶中有一条记录的用量未知', 'current_producer':'mock_example',
                                   'meaning':'当前部分已知样例中恰好一条记录未知；一般情况以 unknown_total_count 为准。'},
}


def ref(name):
    return {'$ref': '#/components/schemas/' + name}


def obj(props, required=None):
    return {'type': 'object', 'properties': props,
            'required': list(props) if required is None else required,
            'additionalProperties': False}


def array(item):
    return {'type': 'array', 'items': item}


def enum(*values):
    return {'type': 'string', 'enum': list(values)}


def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}


string = {'type': 'string', 'minLength': 1}
stamp = {'type': 'string', 'format': 'date-time'}
count = {'type': 'integer', 'minimum': 0, 'maximum': 9007199254740991}
provider = enum('gpt', 'claude')
product = enum('chat', 'work', 'codex', 'code', 'cowork')
coverage = enum('complete', 'partial', 'gap', 'unknown')
products = {'type': 'array', 'items': product, 'minItems': 1, 'uniqueItems': True}
components = obj({k: nullable(count) for k in (
    'uncached_input_tokens', 'cache_read_input_tokens',
    'cache_write_input_tokens', 'output_tokens')})
S['Meta'] = obj({
    'api_version': {'const': VERSION}, 'data_mode': enum('mock', 'live'),
    'as_of': stamp, 'data_revision': count, 'scenario_id': nullable(string),
    'timezone': string, 'stale_after_seconds': {'type': 'integer', 'minimum': 1},
    'warnings': array(string)})
S['Page'] = obj({'next_cursor': nullable(string), 'has_more': {'type': 'boolean'}})
S['Account'] = obj({'id': string, 'provider': provider, 'label': string,
                    'identity_status': enum('confirmed', 'local_unverified')})
S['CoverageInterval'] = obj({'from': stamp, 'to': stamp, 'status': coverage,
                             'scope': enum('local_device', 'account'),
                             'reason': string, 'evidence': string})
S['SourceErrorCode'] = enum('source_unreadable', 'source_missing', 'permission_denied',
    'unsupported_format', 'auth_required', 'auth_expired', 'rate_limited',
    'network_unavailable', 'source_timeout', 'collector_internal_error', 'unknown_error')
S['Source'] = obj({
    'id': string, 'provider': provider, 'account_id': string,
    'product': nullable(product), 'kind': enum('local_log', 'official_client', 'manual', 'telemetry'),
    'device_id': nullable(string), 'device_label': nullable(string),
    'connection_status': enum('not_configured', 'available', 'error', 'disabled'),
    'last_attempt_at': nullable(stamp), 'last_success_at': nullable(stamp),
    'last_record_at': nullable(stamp), 'error_code': nullable(ref('SourceErrorCode')),
    'history_status': enum('has_records', 'empty', 'unknown'),
    'consecutive_failure_count': nullable(count),
    'retry_mode': enum('automatic', 'manual', 'disabled'), 'next_attempt_at': nullable(stamp),
    'capabilities': array(enum('token_events', 'quota_snapshots', 'session_ids', 'manual_labels')),
    'coverage': array(ref('CoverageInterval')), 'limitations': array(string)})
S['QuotaPool'] = obj({
    'id': string, 'provider': provider, 'account_id': string, 'label': string,
    'provider_bucket_key': nullable(string), 'products': nullable(products),
    'product_membership_complete': {'type': 'boolean'},
    'membership_evidence': string, 'source_ids': array(string)})
S['QuotaSnapshot'] = obj({
    'id': string, 'pool_id': string, 'window_id': string, 'source_id': string,
    'observed_at': nullable(stamp), 'recorded_at': nullable(stamp), 'ingested_at': stamp,
    'effective_at': stamp, 'time_basis': enum('observed_at', 'recorded_at'),
    'used_percent': nullable({'type': 'number', 'minimum': 0}),
    'value_basis': enum('reported', 'manual', 'unknown')})
S['QuotaWindow'] = obj({
    'id': string, 'pool_id': string, 'slot': string,
    'starts_at': nullable(stamp), 'ends_at': nullable(stamp),
    'duration_seconds': nullable({'type': 'integer', 'minimum': 1}),
    'start_source': enum('reported', 'derived', 'unknown'),
    'end_source': enum('reported', 'derived', 'unknown'),
    'semantics': enum('fixed', 'rolling', 'unknown'),
    'status': enum('current', 'expired', 'unknown'),
    'freshness': enum('fresh', 'stale', 'unknown'),
    'latest_snapshot': nullable(ref('QuotaSnapshot')),
    'previous_window_id': nullable(string), 'next_window_id': nullable(string)})
S['QuotaWindowSummary'] = obj({
    'window_id': string, 'pool_id': string,
    'scope_from': stamp, 'scope_to': stamp,
    'max_observed_percent': nullable({'type': 'number', 'minimum': 0}),
    'sample_count': count, 'known_value_count': count,
    'first_sample_at': nullable(stamp), 'last_sample_at': nullable(stamp),
    'label': {'const': 'highest_observed_in_selected_range'}})
S['UsageBucket'] = obj({
    'from': stamp, 'to': stamp, 'is_partial_bucket': {'type': 'boolean'},
    'record_state': enum('observed', 'no_records', 'future'),
    'coverage_status': coverage, 'coverage_reasons': array(string),
    'source_ids': array(string), 'event_count': count,
    'known_total_count': count, 'unknown_total_count': count,
    'total_tokens': nullable(count), 'total_status': enum('known', 'partial', 'unknown'),
    'components': components, 'components_complete': {'type': 'boolean'}})
S['UsageSeries'] = obj({
    'provider': provider, 'account_id': string, 'products': products,
    'from': stamp, 'to': stamp, 'bucket': enum('15m', 'hour', 'day', 'week', 'month'),
    'buckets': array(ref('UsageBucket'))})
S['UsageEvent'] = obj({
    'id': string, 'provider': provider, 'account_id': string, 'product': product,
    'source_id': string, 'session_id': nullable(string), 'occurred_at': stamp,
    'recorded_at': nullable(stamp), 'ingested_at': stamp,
    'total_tokens': nullable(count), 'total_basis': enum('reported', 'derived', 'unknown'),
    'components': components, 'components_complete': {'type': 'boolean'},
    'reasoning_output_tokens': nullable(count), 'label_ids': array(string)})
S['Session'] = obj({
    'id': string, 'provider': provider, 'account_id': string, 'product': product,
    'source_id': string, 'started_at': stamp, 'last_record_at': stamp,
    'range_from': stamp, 'range_to': stamp, 'event_count_in_range': count,
    'first_record_in_range_at': stamp, 'last_record_in_range_at': stamp,
    'activity_bounds_basis': {'const': 'record_timestamps'},
    'known_total_count': count, 'unknown_total_count': count,
    'total_tokens_in_range': nullable(count), 'label_ids': array(string)})
S['RangeTarget'] = obj({'kind': {'const': 'range'}, 'from': stamp,
                         'to': nullable(stamp), 'products': products})
S['SessionTarget'] = obj({'kind': {'const': 'session'}, 'session_id': string})
S['LabelTarget'] = {'oneOf': [ref('RangeTarget'), ref('SessionTarget')]}
label_name = {'type': 'string', 'minLength': 1, 'maxLength': 80, 'pattern': r'\S'}
S['LabelCreate'] = obj({'provider': provider, 'account_id': string,
                         'client_request_id': {'type': 'string', 'format': 'uuid'},
                         'name': label_name, 'target': ref('LabelTarget')})
S['LabelPatch'] = obj({'name': label_name, 'target': ref('LabelTarget')}, [])
S['LabelPatch']['minProperties'] = 1
S['Label'] = obj({'id': string, 'provider': provider, 'account_id': string,
                   'name': label_name, 'target': ref('LabelTarget'),
                   'revision': {'type': 'integer', 'minimum': 1},
                   'created_at': stamp, 'updated_at': stamp})
S['Health'] = obj({'status': {'const': 'ok'}, 'storage_schema_version': {'const': 1},
                    'backend_implemented': {'type': 'boolean'}})
S['PairSessionRequest'] = obj({'pairing_code': {'type': 'string', 'minLength': 22,
    'maxLength': 128, 'pattern': '^[A-Za-z0-9_-]+$'}})
S['BrowserSession'] = obj({'authenticated': {'const': True},
    'auth_mode': {'const': 'cookie_session'}, 'csrf_token': string,
    'expires_at': stamp, 'idle_timeout_seconds': {'const': 86400}})
S['Error'] = obj({'code': enum('unauthorized', 'forbidden_origin', 'not_found',
                              'forbidden_host',
                              'csrf_invalid', 'pairing_invalid', 'pairing_expired', 'too_many_attempts',
                              'invalid_query', 'invalid_body', 'cursor_expired',
                              'idempotency_conflict', 'revision_conflict',
                              'precondition_required', 'internal_error'),
                   'message': string, 'details': array(obj({'field': string, 'reason': string}))})


def response_schema(name, data, paged=False):
    props = {'data': data, 'meta': ref('Meta')}
    if paged:
        props['page'] = ref('Page')
    S[name] = obj(props)


response_schema('HealthResponse', ref('Health'))
response_schema('AccountsResponse', array(ref('Account')))
response_schema('SourcesResponse', array(ref('Source')))
response_schema('PoolsResponse', array(ref('QuotaPool')))
for name, item in [('Windows', 'QuotaWindow'), ('Snapshots', 'QuotaSnapshot'),
                   ('WindowSummaries', 'QuotaWindowSummary'), ('Events', 'UsageEvent'),
                   ('Sessions', 'Session'), ('Labels', 'Label')]:
    response_schema(name + 'Response', array(ref(item)), True)
response_schema('SeriesResponse', ref('UsageSeries'))
response_schema('LabelResponse', ref('Label'))
response_schema('BrowserSessionResponse', ref('BrowserSession'))
S['ErrorResponse'] = obj({'error': ref('Error'), 'meta': ref('Meta')})


def query(name, schema=string, required=False, description=''):
    return {'name': name, 'in': 'query', 'required': required,
            'description': description, 'schema': schema}


scope = [query('provider', provider, True), query('account_id', string, True)]
time_range = [query('from', stamp, True), query('to', stamp, True)]
tz = query('timezone', {'type': 'string', 'default': 'Asia/Tokyo'}, description='IANA timezone')
product_filter = query('products', {'type': 'string', 'pattern': '^[a-z]+(,[a-z]+)*$'},
                       description='Comma-separated product OR filter; validated against provider')
page = [query('limit', {'type': 'integer', 'minimum': 1, 'maximum': 500, 'default': 100}),
        query('cursor')]
pool = query('pool_id', string, True)
paths = {}


def operation(path, method, name, schema=None, params=(), body=None, status='200'):
    op = {'operationId': name, 'summary': name,
          'parameters': list(params), 'responses': {}}
    if body:
        op['requestBody'] = {'required': True, 'content': {'application/json': {'schema': ref(body)}}}
    if schema:
        op['responses'][status] = {'description': 'Success',
                                  'content': {'application/json': {'schema': ref(schema)}}}
    else:
        op['responses'][status] = {'description': 'Success, no response body'}
    for code in ('401', '403', '404', '409', '412', '422', '428', '429', '500'):
        op['responses'][code] = {'description': 'See error.code',
                                'content': {'application/json': {'schema': ref('ErrorResponse')}}}
    if method in ('post', 'patch') and schema == 'LabelResponse':
        op['responses'][status]['headers'] = {'ETag': {'description': 'Quoted integer label revision', 'schema': string}}
    paths.setdefault(path, {})[method] = op
    return op


operation('/health', 'get', 'getHealth', 'HealthResponse')
operation('/accounts', 'get', 'listAccounts', 'AccountsResponse')
operation('/sources', 'get', 'listSources', 'SourcesResponse', scope + [tz])
operation('/quota-pools', 'get', 'listQuotaPools', 'PoolsResponse', scope + [tz])
operation('/quota-windows', 'get', 'listQuotaWindows', 'WindowsResponse', scope + [pool] + time_range + [tz] + page)
operation('/quota-snapshots', 'get', 'listQuotaSnapshots', 'SnapshotsResponse', scope + [pool] + time_range + [query('window_id'), tz] + page)
operation('/quota-window-summaries', 'get', 'listQuotaWindowSummaries', 'WindowSummariesResponse', scope + [pool] + time_range + [tz] + page)
operation('/usage-series', 'get', 'getUsageSeries', 'SeriesResponse', scope + time_range + [
    product_filter, tz, query('bucket', enum('15m', 'hour', 'day', 'week', 'month'), True)])
operation('/usage-events', 'get', 'listUsageEvents', 'EventsResponse', scope + time_range + [
    product_filter, query('session_id'), query('label_id'), tz] + page)
operation('/sessions', 'get', 'listSessions', 'SessionsResponse', scope + time_range + [product_filter, tz] + page)
operation('/labels', 'get', 'listLabels', 'LabelsResponse', scope + time_range + [product_filter, tz] + page)
create = operation('/labels', 'post', 'createLabel', 'LabelResponse', body='LabelCreate', status='201')
create['responses']['200'] = create['responses']['201'].copy()
id_path = {'name': 'id', 'in': 'path', 'required': True, 'schema': string}
if_match = {'name': 'If-Match', 'in': 'header', 'required': True,
            'schema': {'type': 'string', 'pattern': '^"[1-9][0-9]*"$'}}
operation('/labels/{id}', 'patch', 'updateLabel', 'LabelResponse', [id_path, if_match], 'LabelPatch')
operation('/labels/{id}', 'delete', 'deleteLabel', params=[id_path, if_match], status='204')
for method, path in [('post', '/labels'), ('patch', '/labels/{id}'), ('delete', '/labels/{id}')]:
    paths[path][method]['security'] = [{'localBearer': []}, {'localSession': [], 'csrfHeader': []}]
pair_header = {'name': 'X-Dashboard-Pairing', 'in': 'header', 'required': True, 'schema': {'const': '1'}}
pair = operation('/auth/session', 'post', 'pairBrowserSession', 'BrowserSessionResponse',
    params=[pair_header], body='PairSessionRequest', status='201')
pair['security'] = []
pair['responses']['201']['headers'] = {'Set-Cookie': {'description': 'HttpOnly host-only app session; see browser-auth.md', 'schema': string}}
pair['responses']['429']['headers'] = {'Retry-After': {'description': 'Seconds until another pairing attempt may be made', 'schema': {'type': 'integer', 'minimum': 1}}}
restore = operation('/auth/session', 'get', 'restoreBrowserSession', 'BrowserSessionResponse')
restore['security'] = [{'localSession': []}]
logout = operation('/auth/session', 'delete', 'revokeBrowserSession', status='204')
logout['security'] = [{'localSession': [], 'csrfHeader': []}]
logout['responses']['204']['headers'] = {'Set-Cookie': {'description': 'Clear aud_session with identical Path and Max-Age=0', 'schema': string}}
for path in paths.values():
    for op in path.values():
        for response in op['responses'].values():
            response.setdefault('headers', {})['Cache-Control'] = {'description': 'no-store', 'schema': {'const': 'no-store'}}
SPEC = {'openapi': '3.1.0', 'info': {'title': 'Local AI Usage Dashboard', 'version': VERSION,
         'description': 'Contract only. No service is deployed. See README.md for statistical and security semantics.'},
        'servers': [{'url': '/api/v1'}], 'security': [{'localBearer': []}, {'localSession': []}], 'paths': paths,
        'components': {'securitySchemes': {'localBearer': {'type': 'http', 'scheme': 'bearer',
                        'description': 'Non-browser local clients only; never a provider credential'},
                        'localSession': {'type': 'apiKey', 'in': 'cookie', 'name': 'aud_session',
                                         'description': 'Browser app session; HttpOnly; host-only'},
                        'csrfHeader': {'type': 'apiKey', 'in': 'header', 'name': 'X-CSRF-Token',
                                       'description': 'Required with cookie-authenticated unsafe methods'}}, 'schemas': S}}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


NOW = '2026-10-22T04:01:00.000Z'
START = '2026-10-22T03:00:00.000Z'
END = '2026-10-22T04:00:00.000Z'
RECENT_FROM = '2026-10-21T23:01:00.000Z'
UNKNOWN_COMPONENTS = {k: None for k in components['properties']}
CATALOG = []


def meta(scenario):
    return {'api_version': VERSION, 'data_mode': 'mock', 'as_of': NOW,
            'data_revision': MOCK_REVISION, 'scenario_id': scenario, 'timezone': 'Asia/Tokyo',
            'stale_after_seconds': 900, 'warnings': ['synthetic_data_not_real_usage']}


def envelope(data, scenario, paged=False):
    r = {'data': data, 'meta': meta(scenario)}
    if paged:
        r['page'] = {'next_cursor': None, 'has_more': False}
    return r


def fixture(file, schema, response, path, query_args=None, method='GET', status=200, note=''):
    save(OUT / 'mocks' / file, response)
    CATALOG.append({'file': file, 'schema': schema, 'method': method,
                    'path': '/api/v1' + path, 'query': query_args or {}, 'status': status,
                    'scenario_id': response['meta']['scenario_id'], 'note': note})


def stamp_at(minute):
    return '2026-10-22T03:%02d:00.000Z' % minute


def window_buckets(events, from_at, to_at, source_id='src_demo_gpt'):
    """Synthetic chart generation only; never fills unknown history with zero."""
    parse = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00'))
    fmt = lambda d: d.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    now, end, cursor = parse(NOW), parse(to_at), parse(from_at)
    buckets = []
    while cursor < end:
        tile_end = min(cursor + timedelta(minutes=15), end)
        cuts = [cursor, now, tile_end] if cursor < now < tile_end else [cursor, tile_end]
        for a, b in zip(cuts, cuts[1:]):
            future = a >= now
            selected = [e for e in events if a <= parse(e['occurred_at']) < b] if not future else []
            known = [e['total_tokens'] for e in selected if e['total_tokens'] is not None]
            complete = bool(selected) and all(e['components_complete'] for e in selected)
            buckets.append({'from': fmt(a), 'to': fmt(b),
                'is_partial_bucket': a != cursor or b != tile_end or (tile_end-cursor).total_seconds() < 900,
                'record_state': 'future' if future else ('observed' if selected else 'no_records'),
                'coverage_status': 'partial' if selected else 'unknown',
                'coverage_reasons': ['not_yet_elapsed'] if future else (['local_device_only'] if selected else ['no_records_not_proof_of_zero']),
                'source_ids': [] if future else [source_id], 'event_count': len(selected),
                'known_total_count': len(known), 'unknown_total_count': len(selected)-len(known),
                'total_tokens': sum(known) if known else None,
                'total_status': ('known' if len(known)==len(selected) else 'partial') if known else 'unknown',
                'components_complete': complete,
                'components': {k:sum(e['components'][k] for e in selected) for k in UNKNOWN_COMPONENTS} if complete else dict(UNKNOWN_COMPONENTS)})
        cursor = tile_end
    return buckets


def make_event(provider_name, product_name, i, total):
    # Synthetic integers deliberately share no real account, session or task metadata.
    complete = i == 0
    c = {'uncached_input_tokens': 100, 'cache_read_input_tokens': 600,
         'cache_write_input_tokens': 100, 'output_tokens': 200} if complete else dict(UNKNOWN_COMPONENTS)
    return {'id': 'evt_' + provider_name + '_' + str(i), 'provider': provider_name,
            'account_id': 'acct_demo_' + provider_name, 'product': product_name,
            'source_id': 'src_demo_' + provider_name, 'session_id': 'ses_demo_' + provider_name,
            'occurred_at': stamp_at([5, 20, 50][i]), 'recorded_at': stamp_at([5, 20, 50][i]),
            'ingested_at': NOW, 'total_tokens': total,
            'total_basis': 'reported' if total is not None else 'unknown',
            'components': c, 'components_complete': complete,
            'reasoning_output_tokens': 50 if complete else None,
            'label_ids': ['label_' + provider_name + '_range', 'label_' + provider_name + '_session']}


def generate():
    save(OUT / 'openapi.json', SPEC)
    save(OUT / 'coverage-reasons.json', {'registry_version':1,'api_version':VERSION,
        'closed_enum':False,'unknown_display_text':'未识别的覆盖原因','reasons':COVERAGE_REASONS})
    fixture('health.json', 'HealthResponse', envelope({'status': 'ok',
            'storage_schema_version': 1, 'backend_implemented': False}, 'catalog'), '/health')
    accounts = [{'id': 'acct_demo_' + p, 'provider': p, 'label': p.upper() + ' 本机演示',
                 'identity_status': 'local_unverified'} for p in ('gpt', 'claude')]
    fixture('accounts.json', 'AccountsResponse', envelope(accounts, 'catalog'), '/accounts')
    for p, prod, scenario in [('gpt', 'codex', 'gpt-observed'), ('claude', 'code', 'claude-tokens')]:
        account = 'acct_demo_' + p
        source_id = 'src_demo_' + p
        params = {'provider': p, 'account_id': account, 'from': START, 'to': END,
                  'products': prod, 'timezone': 'Asia/Tokyo'}
        scope_query = {k: params[k] for k in ('provider', 'account_id')}
        source = {'id': source_id, 'provider': p, 'account_id': account, 'product': prod,
                  'kind': 'local_log', 'device_id': 'device_demo', 'device_label': '演示设备（虚构）',
                  'connection_status': 'available', 'last_attempt_at': NOW, 'last_success_at': NOW,
                  'last_record_at': stamp_at(59 if p == 'gpt' else 50), 'error_code': None,
                  'history_status': 'has_records', 'consecutive_failure_count': 0,
                  'retry_mode': 'manual', 'next_attempt_at': None,
                  'capabilities': ['token_events', 'session_ids'] + (['quota_snapshots'] if p == 'gpt' else []),
                  'coverage': [{'from': START, 'to': END, 'status': 'partial', 'scope': 'local_device',
                                'reason': 'local_device_only', 'evidence': 'synthetic_local_log_sample'}],
                  'limitations': ['其他设备未覆盖；不保证捕获本机全部请求']}
        off = {'id': 'src_unconfigured_' + p, 'provider': p, 'account_id': account, 'product': None,
               'kind': 'official_client', 'device_id': None, 'device_label': None,
               'connection_status': 'not_configured', 'last_attempt_at': None,
               'last_success_at': None, 'last_record_at': None, 'error_code': None,
               'history_status': 'unknown', 'consecutive_failure_count': None,
               'retry_mode': 'disabled', 'next_attempt_at': None,
               'capabilities': [], 'coverage': [], 'limitations': ['额度实时接入尚未验证']}
        disconnected_products = ['chat','work'] if p == 'gpt' else ['chat','cowork']
        disconnected = [{**off, 'id': 'src_unconfigured_' + p + '_' + item, 'product': item,
                         'limitations': ['该产品的自动采集入口尚未验证']} for item in disconnected_products]
        fixture(scenario + '/sources.json', 'SourcesResponse', envelope([source, off] + disconnected, scenario), '/sources', scope_query)
        events = [make_event(p, prod, i, v) for i, v in enumerate((1000, 2000, None))]
        fixture(scenario + '/usage-events.json', 'EventsResponse', envelope(events, scenario, True), '/usage-events', params)
        first_page = envelope(events[:2], scenario, True)
        first_page['page'] = {'next_cursor': 'demo_cursor_page_2_not_a_real_token', 'has_more': True}
        fixture(scenario + '/usage-events-page-1.json', 'EventsResponse', first_page, '/usage-events',
                {**params, 'limit': 2}, note='Pagination example; same logical records as usage-events.json.')
        fixture(scenario + '/usage-events-page-2.json', 'EventsResponse', envelope(events[2:], scenario, True), '/usage-events',
                {**params, 'limit': 2, 'cursor': 'demo_cursor_page_2_not_a_real_token'})
        buckets = []
        for i in range(4):
            selected = [e for e in events if i * 15 <= int(e['occurred_at'][14:16]) < (i + 1) * 15]
            known = [e['total_tokens'] for e in selected if e['total_tokens'] is not None]
            complete = bool(selected) and all(e['components_complete'] for e in selected)
            bucket = {'from': stamp_at(i * 15), 'to': stamp_at((i + 1) * 15) if i < 3 else END,
                      'is_partial_bucket': False, 'record_state': 'observed' if selected else 'no_records',
                      'coverage_status': 'partial' if selected else 'unknown',
                      'coverage_reasons': ['local_device_only'] if selected else ['no_records_not_proof_of_zero'],
                      'source_ids': [source_id], 'event_count': len(selected), 'known_total_count': len(known),
                      'unknown_total_count': len(selected) - len(known),
                      'total_tokens': sum(known) if known else None,
                      'total_status': 'known' if known and len(known) == len(selected) else ('partial' if known else 'unknown'),
                      'components': {k: sum(e['components'][k] for e in selected) for k in UNKNOWN_COMPONENTS} if complete else dict(UNKNOWN_COMPONENTS),
                      'components_complete': complete}
            buckets.append(bucket)
        series = {'provider': p, 'account_id': account, 'products': [prod], 'from': START,
                  'to': END, 'bucket': '15m', 'buckets': buckets}
        fixture(scenario + '/usage-series.json', 'SeriesResponse', envelope(series, scenario), '/usage-series', {**params, 'bucket': '15m'})
        session = {'id': 'ses_demo_' + p, 'provider': p, 'account_id': account,
                   'product': prod, 'source_id': source_id, 'started_at': stamp_at(5),
                   'last_record_at': stamp_at(50), 'range_from': START, 'range_to': END,
                   'first_record_in_range_at': stamp_at(5), 'last_record_in_range_at': stamp_at(50),
                   'activity_bounds_basis': 'record_timestamps',
                   'event_count_in_range': 3, 'known_total_count': 2, 'unknown_total_count': 1,
                   'total_tokens_in_range': 3000,
                   'label_ids': ['label_' + p + '_range', 'label_' + p + '_session']}
        fixture(scenario + '/sessions.json', 'SessionsResponse', envelope([session], scenario, True), '/sessions', params)
        if p == 'gpt':
            selected_session = {**session, 'range_from': stamp_at(15), 'range_to': stamp_at(30),
                'first_record_in_range_at': stamp_at(20), 'last_record_in_range_at': stamp_at(20),
                'event_count_in_range': 1, 'known_total_count': 1, 'unknown_total_count': 0, 'total_tokens_in_range': 2000}
            fixture(scenario + '/sessions-selected-range.json', 'SessionsResponse', envelope([selected_session], scenario, True),
                    '/sessions', {**params, 'from': stamp_at(15), 'to': stamp_at(30)},
                    note='A single in-range record is a point, not the clipped lifetime span of the session.')
        labels = [{'id': 'label_' + p + '_' + k, 'provider': p, 'account_id': account,
                   'name': '学习示例' if k == 'range' else '开发示例',
                   'target': {'kind': 'range', 'from': START, 'to': END, 'products': [prod]} if k == 'range' else {'kind': 'session', 'session_id': session['id']},
                   'revision': 1, 'created_at': START, 'updated_at': START} for k in ('range', 'session')]
        fixture(scenario + '/labels.json', 'LabelsResponse', envelope(labels, scenario, True), '/labels', params)
        # Activity is a time range, independent of quota pools/windows. Include
        # unconfigured product examples without inventing zero account usage.
        all_products = ['chat','work','codex'] if p == 'gpt' else ['chat','code','cowork']
        for selected, suffix in [([prod],prod), (all_products,'all')] + [([item],item) for item in disconnected_products]:
            selected_events = events if prod in selected else []
            selected_labels = labels if selected_events else []
            rp = {**scope_query,'from':RECENT_FROM,'to':NOW,'timezone':'Asia/Tokyo'}
            if suffix != 'all':
                rp['products'] = suffix
            rb = window_buckets(selected_events, RECENT_FROM, NOW, source_id)
            selected_sources = [s['id'] for s in [source]+disconnected if s['product'] in selected]
            for bucket in rb:
                bucket['source_ids'] = sorted(selected_sources)
                if any(item in selected for item in disconnected_products):
                    bucket['coverage_reasons'].append('selected_products_not_configured')
            recent_series = {'provider':p,'account_id':account,'products':selected,'from':RECENT_FROM,
                             'to':NOW,'bucket':'15m','buckets':rb}
            prefix = scenario+'/recent5h/'+suffix+'-'
            note = 'Activity only, not a quota window. Unconfigured products are not proof of zero account usage.'
            fixture(prefix+'usage-series.json','SeriesResponse',envelope(recent_series,scenario),'/usage-series',{**rp,'bucket':'15m'},note=note)
            fixture(prefix+'usage-events.json','EventsResponse',envelope(selected_events,scenario,True),'/usage-events',rp)
            fixture(prefix+'sessions.json','SessionsResponse',envelope([{**session,'range_from':RECENT_FROM,'range_to':NOW}] if selected_events else [],scenario,True),'/sessions',rp)
            fixture(prefix+'labels.json','LabelsResponse',envelope(selected_labels,scenario,True),'/labels',rp)
        create_body = {'provider': p, 'account_id': account, 'client_request_id': 'c83133b2-690c-48ca-8b29-47e680b38353',
                       'name': labels[0]['name'], 'target': labels[0]['target']}
        save(OUT / 'mocks' / scenario / 'label-create-request.json', create_body)
        fixture(scenario + '/label-created.json', 'LabelResponse', envelope(labels[0], scenario), '/labels', method='POST', status=201,
                note='Request: label-create-request.json; response header ETag: "1". Separate example, not an operation on this screen dataset.')
        pool_id = 'pool_demo_' + p
        pools = [{'id': pool_id, 'provider': p, 'account_id': account, 'label': 'Codex 演示额度池',
                  'provider_bucket_key': 'codex', 'products': ['codex'], 'product_membership_complete': False,
                  'membership_evidence': '演示来源报告 Codex 桶；Chat / Work 是否关联未知',
                  'source_ids': [source_id]}] if p == 'gpt' else []
        fixture(scenario + '/quota-pools.json', 'PoolsResponse', envelope(pools, scenario), '/quota-pools', scope_query,
                note='No pool for Claude; do not call pool endpoints with an invented ID.')
        if p == 'gpt':
            snaps = [{'id': 'snap_demo_' + str(i), 'pool_id': pool_id, 'window_id': 'win_demo_5h',
                      'source_id': source_id, 'observed_at': None, 'recorded_at': stamp_at(m), 'ingested_at': NOW,
                      'effective_at': stamp_at(m), 'time_basis': 'recorded_at', 'used_percent': percent,
                      'value_basis': 'reported'} for i, (m, percent) in enumerate([(5, 42), (20, 50), (59, 62)])]
            window = {'id': 'win_demo_5h', 'pool_id': pool_id, 'slot': 'primary',
                      'starts_at': '2026-10-22T00:58:00.000Z', 'ends_at': '2026-10-22T05:58:00.000Z',
                      'duration_seconds': 18000, 'start_source': 'derived', 'end_source': 'reported',
                      'semantics': 'unknown', 'status': 'current', 'freshness': 'fresh',
                      'latest_snapshot': snaps[-1], 'previous_window_id': None, 'next_window_id': None}
            weekly_snapshot = {**snaps[-1], 'id': 'snap_demo_week', 'window_id': 'win_demo_week', 'used_percent': 31}
            weekly_window = {**window, 'id': 'win_demo_week', 'slot': 'secondary',
                             'starts_at': '2026-10-20T00:00:00.000Z', 'ends_at': '2026-10-27T00:00:00.000Z',
                             'duration_seconds': 604800, 'latest_snapshot': weekly_snapshot}
            pq = {**scope_query, 'pool_id': pool_id, 'from': START, 'to': END}
            fixture(scenario + '/quota-windows.json', 'WindowsResponse', envelope([window, weekly_window], scenario, True), '/quota-windows', pq)
            fixture(scenario + '/quota-snapshots.json', 'SnapshotsResponse', envelope(snaps + [weekly_snapshot], scenario, True), '/quota-snapshots', pq)
            peak = {'window_id': window['id'], 'pool_id': pool_id, 'scope_from': START, 'scope_to': END,
                    'max_observed_percent': 62, 'sample_count': 3, 'known_value_count': 3,
                    'first_sample_at': snaps[0]['effective_at'], 'last_sample_at': snaps[-1]['effective_at'],
                    'label': 'highest_observed_in_selected_range'}
            weekly_peak = {**peak, 'window_id': weekly_window['id'], 'max_observed_percent': 31,
                           'sample_count': 1, 'known_value_count': 1,
                           'first_sample_at': weekly_snapshot['effective_at'], 'last_sample_at': weekly_snapshot['effective_at']}
            fixture(scenario + '/quota-window-summaries.json', 'WindowSummariesResponse', envelope([peak, weekly_peak], scenario, True), '/quota-window-summaries', pq)
            # Same underlying records, now queried over the ENTIRE primary window.
            # Do not invent earlier events or future activity to make the chart look full.
            wf, wt = window['starts_at'], window['ends_at']
            wparams = {**params, 'from': wf, 'to': wt}
            wpool = {**pq, 'from': wf, 'to': wt}
            full_series = {**series, 'from': wf, 'to': wt, 'buckets': window_buckets(events, wf, wt)}
            fixture(scenario + '/usage-series-window.json', 'SeriesResponse', envelope(full_series, scenario),
                    '/usage-series', {**wparams, 'bucket': '15m'}, note='Whole 09:58-14:58 JST window, split at 13:01 now. Elapsed unknown is not zero; future is separate.')
            fixture(scenario + '/usage-events-window.json', 'EventsResponse', envelope(events, scenario, True), '/usage-events', wparams)
            fixture(scenario + '/sessions-window.json', 'SessionsResponse', envelope([{**session,'range_from':wf,'range_to':wt}], scenario, True), '/sessions', wparams)
            fixture(scenario + '/labels-window.json', 'LabelsResponse', envelope(labels, scenario, True), '/labels', wparams)
            # All products means all selected scopes, not invented Chat/Work events.
            all_params = {k:v for k,v in wparams.items() if k != 'products'}
            all_series = json.loads(json.dumps(full_series))
            all_series['products'] = ['chat', 'work', 'codex']
            for bucket in all_series['buckets']:
                if bucket['record_state'] != 'future':
                    bucket['source_ids'] = sorted([source_id] + [s['id'] for s in disconnected])
                    bucket['coverage_reasons'].append('selected_products_not_configured')
            fixture(scenario + '/usage-series-window-all.json', 'SeriesResponse', envelope(all_series, scenario),
                    '/usage-series', {**all_params, 'bucket':'15m'},
                    note='All GPT products selected; only local Codex events are known. Chat/Work remain unconfigured, never zero-filled.')
            fixture(scenario + '/usage-events-window-all.json', 'EventsResponse', envelope(events, scenario, True), '/usage-events', all_params)
            fixture(scenario + '/sessions-window-all.json', 'SessionsResponse', envelope([{**session,'range_from':wf,'range_to':wt}], scenario, True), '/sessions', all_params)
            fixture(scenario + '/labels-window-all.json', 'LabelsResponse', envelope(labels, scenario, True), '/labels', all_params)
            fixture(scenario + '/quota-windows-full.json', 'WindowsResponse', envelope([window,weekly_window], scenario, True), '/quota-windows', wpool)
            fixture(scenario + '/quota-snapshots-full.json', 'SnapshotsResponse', envelope(snaps+[weekly_snapshot], scenario, True), '/quota-snapshots', wpool)
            fixture(scenario + '/quota-snapshots-window.json', 'SnapshotsResponse', envelope(snaps, scenario, True), '/quota-snapshots',
                    {**wpool,'window_id':window['id']}, note='Only selected primary window, not the weekly slot.')
            fixture(scenario + '/quota-window-summaries-full.json', 'WindowSummariesResponse',
                    envelope([{**row,'scope_from':wf,'scope_to':wt} for row in [peak,weekly_peak]], scenario, True),
                    '/quota-window-summaries', wpool)
            expired = json.loads(json.dumps(window))
            expired.update({'id': 'win_demo_expired', 'starts_at': '2026-10-21T22:00:00.000Z',
                            'ends_at': '2026-10-22T03:00:00.000Z', 'status': 'expired', 'freshness': 'stale'})
            expired['latest_snapshot'].update({'id': 'snap_demo_expired', 'window_id': expired['id'],
                                              'recorded_at': '2026-10-22T02:40:00.000Z',
                                              'effective_at': '2026-10-22T02:40:00.000Z'})
            fixture('states/expired-window.json', 'WindowsResponse', envelope([expired], 'expired-window', True), '/quota-windows',
                    {**pq, 'from': '2026-10-22T02:00:00.000Z'}, note='Hide current percentage; do not reset to 0.')
            unknown = json.loads(json.dumps(window))
            unknown.update({'id': 'win_demo_unknown', 'starts_at': None, 'ends_at': None,
                            'duration_seconds': None, 'start_source': 'unknown', 'end_source': 'unknown', 'status': 'unknown'})
            unknown['latest_snapshot']['window_id'] = unknown['id']
            fixture('states/unknown-boundaries.json', 'WindowsResponse', envelope([unknown], 'unknown-boundaries', True), '/quota-windows', pq,
                    note='No window background band/navigation; keep observation detail.')
            stale = json.loads(json.dumps(window))
            stale['freshness'] = 'stale'
            stale['latest_snapshot'].update({'recorded_at': START, 'effective_at': START})
            fixture('states/stale-current-window.json', 'WindowsResponse', envelope([stale], 'stale-current-window', True),
                    '/quota-windows', pq, note='Window has not ended, but last recorded value is too old.')
        else:
            failed = json.loads(json.dumps(source))
            failed.update({'connection_status': 'error', 'last_attempt_at': NOW,
                           'last_success_at': '2026-10-22T03:30:00.000Z', 'last_record_at': stamp_at(20),
                           'consecutive_failure_count': 3, 'retry_mode': 'automatic',
                           'next_attempt_at': '2026-10-22T04:06:00.000Z',
                           'error_code': 'source_unreadable'})
            failed['coverage'] = [
                {'from': START, 'to': '2026-10-22T03:30:00.000Z', 'status': 'partial', 'scope': 'local_device',
                 'reason': 'local_device_only', 'evidence': 'synthetic_local_log_sample'},
                {'from': '2026-10-22T03:30:00.000Z', 'to': NOW, 'status': 'gap', 'scope': 'local_device',
                 'reason': 'collector_could_not_read_source', 'evidence': 'synthetic_failed_collection_run'}]
            fixture('states/sync-error.json', 'SourcesResponse', envelope([failed], 'sync-error'), '/sources', scope_query,
                    note='Only source-state example. Do not merge with the normal scenario and keep its known records.')
            for state, history in [('confirmed-empty-source', 'empty'), ('unknown-history-source', 'unknown')]:
                s = json.loads(json.dumps(source))
                s.update({'last_record_at': None, 'history_status': history, 'coverage': [],
                          'limitations': ['首次完整扫描成功且无有效记录'] if history == 'empty' else ['初始扫描尚未完成，不能判定无历史']})
                fixture('states/' + state + '.json', 'SourcesResponse', envelope([s], state), '/sources', scope_query)
    empty = {'provider': 'gpt', 'account_id': 'acct_demo_gpt', 'products': ['codex'],
             'from': START, 'to': END, 'bucket': 'hour', 'buckets': [{
                 'from': START, 'to': END, 'is_partial_bucket': False, 'record_state': 'no_records',
                 'coverage_status': 'unknown', 'coverage_reasons': ['no_records_not_proof_of_zero'],
                 'source_ids': [], 'event_count': 0, 'known_total_count': 0, 'unknown_total_count': 0,
                 'total_tokens': None, 'total_status': 'unknown', 'components': dict(UNKNOWN_COMPONENTS),
                 'components_complete': False}]}
    fixture('states/empty-history.json', 'SeriesResponse', envelope(empty, 'empty-history'), '/usage-series',
            {'provider': 'gpt', 'account_id': 'acct_demo_gpt', 'from': START, 'to': END, 'bucket': 'hour'})
    partial = json.loads(json.dumps(empty))
    partial['buckets'][0].update({'record_state': 'observed', 'coverage_status': 'partial',
        'coverage_reasons': ['local_device_only', 'one_event_has_unknown_usage'], 'source_ids': ['src_demo_gpt'],
        'event_count': 3, 'known_total_count': 2, 'unknown_total_count': 1, 'total_tokens': 3000, 'total_status': 'partial'})
    fixture('states/partial-known-total.json', 'SeriesResponse', envelope(partial, 'partial-known-total'),
            '/usage-series', {'provider': 'gpt', 'account_id': 'acct_demo_gpt', 'from': START, 'to': END, 'bucket': 'hour'},
            note='Same three events as gpt-observed; 3000 is a known subtotal, not a complete measurement.')
    future = json.loads(json.dumps(empty))
    future.update({'from': '2026-10-22T04:00:00.000Z', 'to': '2026-10-22T04:30:00.000Z', 'bucket': '15m'})
    future['buckets'] = []
    for a, b, state, is_partial in [
        ('2026-10-22T04:00:00.000Z', NOW, 'no_records', True),
        (NOW, '2026-10-22T04:15:00.000Z', 'future', True),
        ('2026-10-22T04:15:00.000Z', '2026-10-22T04:30:00.000Z', 'future', False)]:
        entry = json.loads(json.dumps(empty['buckets'][0]))
        entry.update({'from': a, 'to': b, 'record_state': state, 'is_partial_bucket': is_partial,
                      'coverage_reasons': ['not_yet_elapsed'] if state == 'future' else ['no_records_not_proof_of_zero']})
        future['buckets'].append(entry)
    fixture('states/future-range.json', 'SeriesResponse', envelope(future, 'future-range'), '/usage-series',
            {'provider': 'gpt', 'account_id': 'acct_demo_gpt', 'from': future['from'], 'to': future['to'], 'bucket': '15m'},
            note='Split at as_of: future is not missing collection and cannot be drawn as zero usage.')
    # Historical charts use one independent synthetic event dataset for all three resolutions.
    hist_from, hist_to = '2026-10-01T15:00:00.000Z', '2026-10-21T15:00:00.000Z'
    hist_events = []
    for i, day in enumerate((2, 7, 14, 20)):
        event = make_event('gpt', 'codex', 0, 1000)
        event.update({'id': 'evt_hist_' + str(i), 'session_id': None, 'label_ids': [],
                      'occurred_at': '2026-10-%02dT03:00:00.000Z' % day,
                      'recorded_at': '2026-10-%02dT03:00:00.000Z' % day})
        hist_events.append(event)
    hp = {'provider': 'gpt', 'account_id': 'acct_demo_gpt', 'products': 'codex',
          'from': hist_from, 'to': hist_to, 'timezone': 'Asia/Tokyo'}
    fixture('history/usage-events.json', 'EventsResponse', envelope(hist_events, 'history', True), '/usage-events', hp,
            note='Independent synthetic historical dataset; used by all history series resolutions.')
    tzinfo = ZoneInfo('Asia/Tokyo')
    parse = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00'))
    fmt = lambda d: d.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    begin, finish = parse(hist_from).astimezone(tzinfo), parse(hist_to).astimezone(tzinfo)
    for kind in ('day', 'week', 'month'):
        cursor = begin.replace(hour=0, minute=0, second=0, microsecond=0)
        if kind == 'week': cursor -= timedelta(days=cursor.weekday())
        if kind == 'month': cursor = cursor.replace(day=1)
        hb = []
        while cursor < finish:
            next_at = (cursor + timedelta(days=1 if kind == 'day' else 7)) if kind != 'month' else cursor.replace(
                year=cursor.year + (cursor.month == 12), month=cursor.month % 12 + 1, day=1)
            a, b = max(cursor, begin), min(next_at, finish)
            selected = [e for e in hist_events if a <= parse(e['occurred_at']) < b]
            bucket = dict(empty['buckets'][0])
            bucket.update({'from': fmt(a), 'to': fmt(b), 'is_partial_bucket': a != cursor or b != next_at,
                           'record_state': 'observed' if selected else 'no_records',
                           'coverage_status': 'partial' if selected else 'unknown',
                           'coverage_reasons': ['synthetic_local_history'] if selected else ['no_records_not_proof_of_zero'],
                           'source_ids': ['src_demo_gpt'], 'event_count': len(selected),
                           'known_total_count': len(selected), 'total_tokens': len(selected)*1000 if selected else None,
                           'total_status': 'known' if selected else 'unknown',
                           'components_complete': bool(selected),
                           'components': {k: sum(e['components'][k] for e in selected) for k in UNKNOWN_COMPONENTS} if selected else dict(UNKNOWN_COMPONENTS)})
            hb.append(bucket)
            cursor = next_at
        data = {'provider': 'gpt', 'account_id': 'acct_demo_gpt', 'products': ['codex'],
                'from': hist_from, 'to': hist_to, 'bucket': kind, 'buckets': hb}
        fixture('history/usage-series-' + kind + '.json', 'SeriesResponse', envelope(data, 'history'),
                '/usage-series', {**hp, 'bucket': kind})
    for code, status, field, msg in [('invalid_query', 422, 'products', 'Quota endpoints do not accept product filters'),
                                     ('revision_conflict', 412, 'If-Match', 'Label has changed; reload before editing'),
                                     ('cursor_expired', 409, 'cursor', 'Restart pagination from the first page')]:
        body = {'error': {'code': code, 'message': msg, 'details': [{'field': field, 'reason': msg}]}, 'meta': meta('error-' + code)}
        fixture('errors/' + code + '.json', 'ErrorResponse', body,
                '/labels/{id}' if status == 412 else ('/usage-events' if status == 409 else '/quota-pools'),
                method='PATCH' if status == 412 else 'GET', status=status,
                note='Error shape example, not a successful screen dataset.')
    # These are response shapes only: no session token or valid pairing/CSRF credential is generated.
    browser_session = {'authenticated': True, 'auth_mode': 'cookie_session',
        'csrf_token': 'MOCK_CSRF_VALUE_NOT_VALID_FOR_AUTH', 'expires_at': '2026-10-29T04:01:00.000Z', 'idle_timeout_seconds': 86400}
    save(OUT / 'mocks/auth/pair-request.json', {'pairing_code': 'MOCK_PAIRING_CODE_NEVER_VALID'})
    fixture('auth/paired.json', 'BrowserSessionResponse', envelope(browser_session, 'auth'), '/auth/session',
            method='POST', status=201, note='Request pair-request.json; X-Dashboard-Pairing: 1. No cookie is issued by these static files.')
    fixture('auth/restored.json', 'BrowserSessionResponse', envelope(browser_session, 'auth'), '/auth/session',
            note='Refresh restores using HttpOnly cookie; frontend stores returned CSRF value only in memory.')
    auth_error = {'error': {'code': 'unauthorized', 'message': 'Pair this browser with the local application', 'details': []}, 'meta': meta('auth-unpaired')}
    fixture('auth/unpaired.json', 'ErrorResponse', auth_error, '/auth/session', status=401)
    history_contexts = generate_history(fixture, envelope, make_event, NOW)
    generate_label_workflow(fixture, envelope, save, OUT, NOW, VERSION)
    save(OUT / 'mocks' / 'catalog.json', {'contract_version': VERSION, 'data_mode': 'mock',
         'as_of': NOW, 'data_revision': MOCK_REVISION,
         'scenarios': {'gpt-observed': {
             'initial_view': 'window', 'provider': 'gpt', 'account_id': 'acct_demo_gpt',
             'products': ['codex'], 'pool_id': 'pool_demo_gpt', 'window_id': 'win_demo_5h',
             'from': '2026-10-22T00:58:00.000Z', 'to': '2026-10-22T05:58:00.000Z',
             'bucket': '15m', 'timezone': 'Asia/Tokyo',
             'activity': {'initial_view':'recent5h','from':RECENT_FROM,'to':NOW,'bucket':'15m'}},
             'claude-tokens': {
                 'initial_view':'recent5h','provider':'claude','account_id':'acct_demo_claude',
                 'products':['code'],'pool_id':None,'window_id':None,
                 'from':RECENT_FROM,'to':NOW,'bucket':'15m','timezone':'Asia/Tokyo'}, **history_contexts},
         'fixtures': CATALOG,
         'notes': ['All identifiers, amounts, labels and timestamps are synthetic.',
                   'Each states file is an isolated state example, not a dataset to merge.',
                   'No provider credentials or real conversation text are included.']})


if __name__ == '__main__':
    generate()
    print('Generated openapi.json and %d response fixtures.' % len(CATALOG))
