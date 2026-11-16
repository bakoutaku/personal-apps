-- Contract schema draft v1. Apply only to a new empty database.
-- UTC epoch milliseconds; opaque IDs; no supplier credentials/transcripts.
-- Local application sessions store domain-separated token DIGESTS only.
-- Application must enable foreign_keys on EVERY connection (including tests).
PRAGMA foreign_keys = ON;
BEGIN;

CREATE TABLE accounts (
    id TEXT PRIMARY KEY NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('gpt','claude')),
    label TEXT NOT NULL,
    identity_status TEXT NOT NULL CHECK (identity_status IN ('confirmed','local_unverified')),
    UNIQUE (id, provider)
);
CREATE TABLE devices (
    id TEXT PRIMARY KEY NOT NULL,
    label TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('macos','windows'))
);
CREATE TABLE source_error_codes (code TEXT PRIMARY KEY NOT NULL);
INSERT INTO source_error_codes(code) VALUES
    ('source_unreadable'),('source_missing'),('permission_denied'),('unsupported_format'),
    ('auth_required'),('auth_expired'),('rate_limited'),('network_unavailable'),
    ('source_timeout'),('collector_internal_error'),('unknown_error');
CREATE TABLE sources (
    id TEXT PRIMARY KEY NOT NULL,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    product TEXT,
    device_id TEXT REFERENCES devices(id),
    kind TEXT NOT NULL CHECK (kind IN ('local_log','official_client','manual','telemetry')),
    connection_status TEXT NOT NULL CHECK (connection_status IN ('not_configured','available','error','disabled')),
    last_attempt_ms INTEGER,
    last_success_ms INTEGER,
    last_record_ms INTEGER,
    error_code TEXT REFERENCES source_error_codes(code),
    history_status TEXT NOT NULL DEFAULT 'unknown' CHECK (history_status IN ('has_records','empty','unknown')),
    consecutive_failure_count INTEGER CHECK (consecutive_failure_count IS NULL OR (typeof(consecutive_failure_count)='integer' AND consecutive_failure_count>=0)),
    retry_mode TEXT NOT NULL DEFAULT 'disabled' CHECK (retry_mode IN ('automatic','manual','disabled')),
    next_attempt_ms INTEGER,
    adapter_version TEXT,
    FOREIGN KEY (account_id, provider) REFERENCES accounts(id, provider),
    CHECK (product IS NULL OR (provider='gpt' AND product IN ('chat','work','codex'))
           OR (provider='claude' AND product IN ('chat','code','cowork'))),
    CHECK (next_attempt_ms IS NULL OR retry_mode='automatic'),
    CHECK (history_status<>'has_records' OR last_record_ms IS NOT NULL),
    CHECK (history_status<>'empty' OR (last_record_ms IS NULL AND last_success_ms IS NOT NULL)),
    UNIQUE (id, account_id, provider),
    UNIQUE (id, account_id, provider, product)
);
CREATE TABLE coverage_intervals (
    id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id),
    from_ms INTEGER NOT NULL,
    to_ms INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('complete','partial','gap','unknown')),
    scope TEXT NOT NULL CHECK (scope IN ('local_device','account')),
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL CHECK (length(trim(evidence)) > 0),
    CHECK (from_ms < to_ms)
);
CREATE TABLE source_capabilities (
    source_id TEXT NOT NULL REFERENCES sources(id),
    capability TEXT NOT NULL CHECK (capability IN ('token_events','quota_snapshots','session_ids','manual_labels')),
    PRIMARY KEY (source_id, capability)
);
CREATE TABLE source_limitations (
    source_id TEXT NOT NULL REFERENCES sources(id),
    code TEXT NOT NULL,
    description TEXT NOT NULL,
    PRIMARY KEY (source_id, code)
);
CREATE TABLE collection_runs (
    id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources(id),
    started_ms INTEGER NOT NULL,
    ended_ms INTEGER,
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    records_seen INTEGER NOT NULL DEFAULT 0 CHECK (records_seen >= 0),
    error_code TEXT REFERENCES source_error_codes(code),
    CHECK (ended_ms IS NULL OR ended_ms >= started_ms)
);
CREATE TABLE sessions (
    id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    product TEXT NOT NULL,
    external_session_key TEXT NOT NULL,
    started_ms INTEGER NOT NULL,
    last_record_ms INTEGER NOT NULL,
    FOREIGN KEY (source_id, account_id, provider, product)
        REFERENCES sources(id, account_id, provider, product),
    CHECK (started_ms <= last_record_ms),
    UNIQUE (source_id, external_session_key),
    UNIQUE (id, account_id, provider),
    UNIQUE (id, source_id, account_id, provider, product)
);
CREATE TABLE usage_events (
    id TEXT PRIMARY KEY NOT NULL,
    source_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    product TEXT NOT NULL,
    session_id TEXT,
    -- Adapter-stable per-session request/message identity, NOT JSONL line number.
    external_event_key TEXT NOT NULL,
    occurred_ms INTEGER NOT NULL,
    recorded_ms INTEGER,
    ingested_ms INTEGER NOT NULL,
    source_revision INTEGER NOT NULL DEFAULT 1 CHECK (source_revision >= 1),
    total_tokens INTEGER CHECK (total_tokens IS NULL OR (typeof(total_tokens)='integer' AND total_tokens >= 0)),
    total_basis TEXT NOT NULL CHECK (total_basis IN ('reported','derived','unknown')),
    uncached_input_tokens INTEGER CHECK (uncached_input_tokens IS NULL OR (typeof(uncached_input_tokens)='integer' AND uncached_input_tokens >= 0)),
    cache_read_input_tokens INTEGER CHECK (cache_read_input_tokens IS NULL OR (typeof(cache_read_input_tokens)='integer' AND cache_read_input_tokens >= 0)),
    cache_write_input_tokens INTEGER CHECK (cache_write_input_tokens IS NULL OR (typeof(cache_write_input_tokens)='integer' AND cache_write_input_tokens >= 0)),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR (typeof(output_tokens)='integer' AND output_tokens >= 0)),
    reasoning_output_tokens INTEGER CHECK (reasoning_output_tokens IS NULL OR (typeof(reasoning_output_tokens)='integer' AND reasoning_output_tokens >= 0)),
    components_complete INTEGER NOT NULL CHECK (components_complete IN (0,1)),
    FOREIGN KEY (source_id, account_id, provider, product)
        REFERENCES sources(id, account_id, provider, product),
    FOREIGN KEY (session_id, source_id, account_id, provider, product)
        REFERENCES sessions(id, source_id, account_id, provider, product),
    CHECK ((total_tokens IS NULL AND total_basis='unknown') OR (total_tokens IS NOT NULL AND total_basis IN ('reported','derived'))),
    CHECK (components_complete=0 OR (total_tokens IS NOT NULL
        AND uncached_input_tokens IS NOT NULL AND cache_read_input_tokens IS NOT NULL
        AND cache_write_input_tokens IS NOT NULL AND output_tokens IS NOT NULL
        AND total_tokens=uncached_input_tokens+cache_read_input_tokens+cache_write_input_tokens+output_tokens)),
    CHECK (reasoning_output_tokens IS NULL OR output_tokens IS NULL OR reasoning_output_tokens<=output_tokens),
    UNIQUE (source_id, external_event_key)
);
CREATE INDEX usage_range ON usage_events(account_id, provider, occurred_ms, id);
CREATE INDEX usage_session ON usage_events(session_id, occurred_ms, id);

CREATE TABLE quota_pools (
    id TEXT PRIMARY KEY NOT NULL,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    label TEXT NOT NULL,
    provider_bucket_key TEXT,
    product_membership_known INTEGER NOT NULL CHECK (product_membership_known IN (0,1)),
    product_membership_complete INTEGER NOT NULL CHECK (product_membership_complete IN (0,1)),
    membership_evidence TEXT NOT NULL,
    FOREIGN KEY (account_id, provider) REFERENCES accounts(id, provider),
    CHECK (product_membership_complete=0 OR product_membership_known=1),
    UNIQUE (id, account_id, provider)
);
CREATE TABLE quota_pool_sources (
    pool_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    PRIMARY KEY (pool_id, source_id),
    FOREIGN KEY (pool_id, account_id, provider) REFERENCES quota_pools(id, account_id, provider),
    FOREIGN KEY (source_id, account_id, provider) REFERENCES sources(id, account_id, provider)
);
CREATE TABLE quota_pool_products (
    pool_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    product TEXT NOT NULL,
    evidence TEXT NOT NULL,
    PRIMARY KEY (pool_id, product),
    FOREIGN KEY (pool_id, account_id, provider) REFERENCES quota_pools(id, account_id, provider),
    CHECK ((provider='gpt' AND product IN ('chat','work','codex'))
        OR (provider='claude' AND product IN ('chat','code','cowork')))
);
CREATE TABLE quota_windows (
    id TEXT PRIMARY KEY NOT NULL,
    pool_id TEXT NOT NULL REFERENCES quota_pools(id),
    slot TEXT NOT NULL,
    -- Stable adapter grouping, not proof of vendor window semantics.
    external_window_key TEXT NOT NULL,
    starts_ms INTEGER,
    ends_ms INTEGER,
    duration_seconds INTEGER CHECK (duration_seconds IS NULL OR duration_seconds > 0),
    start_source TEXT NOT NULL CHECK (start_source IN ('reported','derived','unknown')),
    end_source TEXT NOT NULL CHECK (end_source IN ('reported','derived','unknown')),
    semantics TEXT NOT NULL CHECK (semantics IN ('fixed','rolling','unknown')),
    CHECK ((starts_ms IS NULL AND start_source='unknown') OR (starts_ms IS NOT NULL AND start_source<>'unknown')),
    CHECK ((ends_ms IS NULL AND end_source='unknown') OR (ends_ms IS NOT NULL AND end_source<>'unknown')),
    CHECK (starts_ms IS NULL OR ends_ms IS NULL OR starts_ms < ends_ms),
    CHECK (start_source<>'derived' OR (starts_ms IS NOT NULL AND ends_ms IS NOT NULL
        AND duration_seconds IS NOT NULL AND starts_ms=ends_ms-duration_seconds*1000)),
    UNIQUE (pool_id, external_window_key),
    UNIQUE (id, pool_id)
);
CREATE INDEX quota_window_range ON quota_windows(pool_id, ends_ms, id);
CREATE TABLE quota_snapshots (
    id TEXT PRIMARY KEY NOT NULL,
    pool_id TEXT NOT NULL,
    window_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    external_snapshot_key TEXT NOT NULL,
    observed_ms INTEGER,
    recorded_ms INTEGER,
    ingested_ms INTEGER NOT NULL,
    effective_ms INTEGER NOT NULL,
    time_basis TEXT NOT NULL CHECK (time_basis IN ('observed_at','recorded_at')),
    used_percent REAL CHECK (used_percent IS NULL OR used_percent >= 0),
    value_basis TEXT NOT NULL CHECK (value_basis IN ('reported','manual','unknown')),
    FOREIGN KEY (window_id, pool_id) REFERENCES quota_windows(id, pool_id),
    FOREIGN KEY (pool_id, source_id) REFERENCES quota_pool_sources(pool_id, source_id),
    CHECK ((time_basis='observed_at' AND observed_ms IS NOT NULL AND effective_ms=observed_ms)
        OR (time_basis='recorded_at' AND observed_ms IS NULL AND recorded_ms IS NOT NULL AND effective_ms=recorded_ms)),
    CHECK ((used_percent IS NULL AND value_basis='unknown') OR (used_percent IS NOT NULL AND value_basis<>'unknown')),
    UNIQUE (source_id, external_snapshot_key)
);
CREATE INDEX quota_snapshot_range ON quota_snapshots(pool_id, effective_ms, id);

CREATE TABLE labels (
    id TEXT PRIMARY KEY NOT NULL,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    client_request_id TEXT NOT NULL,
    -- Hash of canonical initial request, for idempotency conflict checks.
    create_request_hash TEXT NOT NULL,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80 AND length(trim(name))>0),
    target_kind TEXT NOT NULL CHECK (target_kind IN ('range','session')),
    from_ms INTEGER,
    to_ms INTEGER,
    session_id TEXT,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL,
    -- Tombstone preserves POST idempotency after deletion; API hides deleted rows.
    deleted_ms INTEGER,
    FOREIGN KEY (account_id, provider) REFERENCES accounts(id, provider),
    FOREIGN KEY (session_id, account_id, provider) REFERENCES sessions(id, account_id, provider),
    CHECK ((target_kind='range' AND session_id IS NULL AND from_ms IS NOT NULL AND (to_ms IS NULL OR from_ms<to_ms))
        OR (target_kind='session' AND session_id IS NOT NULL AND from_ms IS NULL AND to_ms IS NULL)),
    CHECK (updated_ms >= created_ms),
    UNIQUE (account_id, provider, client_request_id),
    UNIQUE (id, account_id, provider)
);
CREATE TABLE label_products (
    label_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    product TEXT NOT NULL,
    PRIMARY KEY (label_id, product),
    FOREIGN KEY (label_id, account_id, provider) REFERENCES labels(id, account_id, provider),
    CHECK ((provider='gpt' AND product IN ('chat','work','codex'))
        OR (provider='claude' AND product IN ('chat','code','cowork')))
);
-- Label membership and matched event IDs are derived in queries, not duplicated events.
CREATE INDEX label_range ON labels(account_id, provider, from_ms, to_ms);
CREATE TABLE app_sessions (
    id TEXT PRIMARY KEY NOT NULL,
    token_digest TEXT UNIQUE NOT NULL CHECK (length(token_digest)=64 AND token_digest NOT GLOB '*[^0-9a-f]*'),
    origin TEXT NOT NULL,
    created_ms INTEGER NOT NULL,
    last_seen_ms INTEGER NOT NULL,
    expires_ms INTEGER NOT NULL,
    revoked_ms INTEGER,
    CHECK (created_ms<=last_seen_ms AND last_seen_ms<expires_ms),
    CHECK (revoked_ms IS NULL OR revoked_ms>=created_ms)
);
-- Pairing codes remain short-lived in process memory; never store raw session/CSRF tokens.
PRAGMA user_version = 1;
COMMIT;

-- Application transaction invariants (must be tested during implementation):
-- range labels have >=1 valid product; session labels have no label_products;
-- session / pool IDs belong to requesting account; products agree with source;
-- inferred starts and meaningful grouping depend on verified adapter semantics;
-- limits, timezone, fractional/unsafe integers and full Unicode whitespace validated at API boundary;
-- updates use compare-and-swap revision; collection uses an explicit authoritative source;
-- source capabilities, limitations and configuration are managed metadata, never raw auth material.
