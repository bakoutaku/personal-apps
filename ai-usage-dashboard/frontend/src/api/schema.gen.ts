/* 由 scripts/gen-types.mjs 根据 contracts/openapi.json 生成，请勿手改。 */
export interface paths {
    "/health": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** getHealth */
        get: operations["getHealth"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/accounts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listAccounts */
        get: operations["listAccounts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sources": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listSources */
        get: operations["listSources"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quota-pools": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listQuotaPools */
        get: operations["listQuotaPools"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quota-windows": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listQuotaWindows */
        get: operations["listQuotaWindows"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quota-snapshots": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listQuotaSnapshots */
        get: operations["listQuotaSnapshots"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/quota-window-summaries": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listQuotaWindowSummaries */
        get: operations["listQuotaWindowSummaries"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/usage-series": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** getUsageSeries */
        get: operations["getUsageSeries"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/usage-events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listUsageEvents */
        get: operations["listUsageEvents"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/sessions": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listSessions */
        get: operations["listSessions"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/labels": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** listLabels */
        get: operations["listLabels"];
        put?: never;
        /** createLabel */
        post: operations["createLabel"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/labels/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** deleteLabel */
        delete: operations["deleteLabel"];
        options?: never;
        head?: never;
        /** updateLabel */
        patch: operations["updateLabel"];
        trace?: never;
    };
    "/auth/session": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** restoreBrowserSession */
        get: operations["restoreBrowserSession"];
        put?: never;
        /** pairBrowserSession */
        post: operations["pairBrowserSession"];
        /** revokeBrowserSession */
        delete: operations["revokeBrowserSession"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        Meta: {
            /** @constant */
            api_version: "0.2.0";
            /** @enum {string} */
            data_mode: "mock" | "live";
            /** Format: date-time */
            as_of: string;
            data_revision: number;
            scenario_id: string | null;
            timezone: string;
            stale_after_seconds: number;
            warnings: string[];
        };
        Page: {
            next_cursor: string | null;
            has_more: boolean;
        };
        Account: {
            id: string;
            /** @enum {string} */
            provider: "gpt" | "claude";
            label: string;
            /** @enum {string} */
            identity_status: "confirmed" | "local_unverified";
        };
        CoverageInterval: {
            /** Format: date-time */
            from: string;
            /** Format: date-time */
            to: string;
            /** @enum {string} */
            status: "complete" | "partial" | "gap" | "unknown";
            /** @enum {string} */
            scope: "local_device" | "account";
            reason: string;
            evidence: string;
        };
        /** @enum {string} */
        SourceErrorCode: "source_unreadable" | "source_missing" | "permission_denied" | "unsupported_format" | "auth_required" | "auth_expired" | "rate_limited" | "network_unavailable" | "source_timeout" | "collector_internal_error" | "unknown_error";
        Source: {
            id: string;
            /** @enum {string} */
            provider: "gpt" | "claude";
            account_id: string;
            product: ("chat" | "work" | "codex" | "code" | "cowork") | null;
            /** @enum {string} */
            kind: "local_log" | "official_client" | "manual" | "telemetry";
            device_id: string | null;
            device_label: string | null;
            /** @enum {string} */
            connection_status: "not_configured" | "available" | "error" | "disabled";
            last_attempt_at: string | null;
            last_success_at: string | null;
            last_record_at: string | null;
            error_code: components["schemas"]["SourceErrorCode"] | null;
            /** @enum {string} */
            history_status: "has_records" | "empty" | "unknown";
            consecutive_failure_count: number | null;
            /** @enum {string} */
            retry_mode: "automatic" | "manual" | "disabled";
            next_attempt_at: string | null;
            capabilities: ("token_events" | "quota_snapshots" | "session_ids" | "manual_labels")[];
            coverage: components["schemas"]["CoverageInterval"][];
            limitations: string[];
        };
        QuotaPool: {
            id: string;
            /** @enum {string} */
            provider: "gpt" | "claude";
            account_id: string;
            label: string;
            provider_bucket_key: string | null;
            products: ("chat" | "work" | "codex" | "code" | "cowork")[] | null;
            product_membership_complete: boolean;
            membership_evidence: string;
            source_ids: string[];
        };
        QuotaSnapshot: {
            id: string;
            pool_id: string;
            window_id: string;
            source_id: string;
            observed_at: string | null;
            recorded_at: string | null;
            /** Format: date-time */
            ingested_at: string;
            /** Format: date-time */
            effective_at: string;
            /** @enum {string} */
            time_basis: "observed_at" | "recorded_at";
            used_percent: number | null;
            /** @enum {string} */
            value_basis: "reported" | "manual" | "unknown";
        };
        QuotaWindow: {
            id: string;
            pool_id: string;
            slot: string;
            starts_at: string | null;
            ends_at: string | null;
            duration_seconds: number | null;
            /** @enum {string} */
            start_source: "reported" | "derived" | "unknown";
            /** @enum {string} */
            end_source: "reported" | "derived" | "unknown";
            /** @enum {string} */
            semantics: "fixed" | "rolling" | "unknown";
            /** @enum {string} */
            status: "current" | "expired" | "unknown";
            /** @enum {string} */
            freshness: "fresh" | "stale" | "unknown";
            latest_snapshot: components["schemas"]["QuotaSnapshot"] | null;
            previous_window_id: string | null;
            next_window_id: string | null;
        };
        QuotaWindowSummary: {
            window_id: string;
            pool_id: string;
            /** Format: date-time */
            scope_from: string;
            /** Format: date-time */
            scope_to: string;
            max_observed_percent: number | null;
            sample_count: number;
            known_value_count: number;
            first_sample_at: string | null;
            last_sample_at: string | null;
            /** @constant */
            label: "highest_observed_in_selected_range";
        };
        UsageBucket: {
            /** Format: date-time */
            from: string;
            /** Format: date-time */
            to: string;
            is_partial_bucket: boolean;
            /** @enum {string} */
            record_state: "observed" | "no_records" | "future";
            /** @enum {string} */
            coverage_status: "complete" | "partial" | "gap" | "unknown";
            coverage_reasons: string[];
            source_ids: string[];
            event_count: number;
            known_total_count: number;
            unknown_total_count: number;
            total_tokens: number | null;
            /** @enum {string} */
            total_status: "known" | "partial" | "unknown";
            components: {
                uncached_input_tokens: number | null;
                cache_read_input_tokens: number | null;
                cache_write_input_tokens: number | null;
                output_tokens: number | null;
            };
            components_complete: boolean;
        };
        UsageSeries: {
            /** @enum {string} */
            provider: "gpt" | "claude";
            account_id: string;
            products: ("chat" | "work" | "codex" | "code" | "cowork")[];
            /** Format: date-time */
            from: string;
            /** Format: date-time */
            to: string;
            /** @enum {string} */
            bucket: "15m" | "hour" | "day" | "week" | "month";
            buckets: components["schemas"]["UsageBucket"][];
        };
        UsageEvent: {
            id: string;
            /** @enum {string} */
            provider: "gpt" | "claude";
            account_id: string;
            /** @enum {string} */
            product: "chat" | "work" | "codex" | "code" | "cowork";
            source_id: string;
            session_id: string | null;
            /** Format: date-time */
            occurred_at: string;
            recorded_at: string | null;
            /** Format: date-time */
            ingested_at: string;
            total_tokens: number | null;
            /** @enum {string} */
            total_basis: "reported" | "derived" | "unknown";
            components: {
                uncached_input_tokens: number | null;
                cache_read_input_tokens: number | null;
                cache_write_input_tokens: number | null;
                output_tokens: number | null;
            };
            components_complete: boolean;
            reasoning_output_tokens: number | null;
            label_ids: string[];
        };
        Session: {
            id: string;
            /** @enum {string} */
            provider: "gpt" | "claude";
            account_id: string;
            /** @enum {string} */
            product: "chat" | "work" | "codex" | "code" | "cowork";
            source_id: string;
            /** Format: date-time */
            started_at: string;
            /** Format: date-time */
            last_record_at: string;
            /** Format: date-time */
            range_from: string;
            /** Format: date-time */
            range_to: string;
            event_count_in_range: number;
            /** Format: date-time */
            first_record_in_range_at: string;
            /** Format: date-time */
            last_record_in_range_at: string;
            /** @constant */
            activity_bounds_basis: "record_timestamps";
            known_total_count: number;
            unknown_total_count: number;
            total_tokens_in_range: number | null;
            label_ids: string[];
        };
        RangeTarget: {
            /** @constant */
            kind: "range";
            /** Format: date-time */
            from: string;
            to: string | null;
            products: ("chat" | "work" | "codex" | "code" | "cowork")[];
        };
        SessionTarget: {
            /** @constant */
            kind: "session";
            session_id: string;
        };
        LabelTarget: components["schemas"]["RangeTarget"] | components["schemas"]["SessionTarget"];
        LabelCreate: {
            /** @enum {string} */
            provider: "gpt" | "claude";
            account_id: string;
            /** Format: uuid */
            client_request_id: string;
            name: string;
            target: components["schemas"]["LabelTarget"];
        };
        LabelPatch: {
            name?: string;
            target?: components["schemas"]["LabelTarget"];
        };
        Label: {
            id: string;
            /** @enum {string} */
            provider: "gpt" | "claude";
            account_id: string;
            name: string;
            target: components["schemas"]["LabelTarget"];
            revision: number;
            /** Format: date-time */
            created_at: string;
            /** Format: date-time */
            updated_at: string;
        };
        Health: {
            /** @constant */
            status: "ok";
            /** @constant */
            storage_schema_version: 1;
            backend_implemented: boolean;
        };
        PairSessionRequest: {
            pairing_code: string;
        };
        BrowserSession: {
            /** @constant */
            authenticated: true;
            /** @constant */
            auth_mode: "cookie_session";
            csrf_token: string;
            /** Format: date-time */
            expires_at: string;
            /** @constant */
            idle_timeout_seconds: 86400;
        };
        Error: {
            /** @enum {string} */
            code: "unauthorized" | "forbidden_origin" | "not_found" | "forbidden_host" | "csrf_invalid" | "pairing_invalid" | "pairing_expired" | "too_many_attempts" | "invalid_query" | "invalid_body" | "cursor_expired" | "idempotency_conflict" | "revision_conflict" | "precondition_required" | "internal_error";
            message: string;
            details: {
                field: string;
                reason: string;
            }[];
        };
        HealthResponse: {
            data: components["schemas"]["Health"];
            meta: components["schemas"]["Meta"];
        };
        AccountsResponse: {
            data: components["schemas"]["Account"][];
            meta: components["schemas"]["Meta"];
        };
        SourcesResponse: {
            data: components["schemas"]["Source"][];
            meta: components["schemas"]["Meta"];
        };
        PoolsResponse: {
            data: components["schemas"]["QuotaPool"][];
            meta: components["schemas"]["Meta"];
        };
        WindowsResponse: {
            data: components["schemas"]["QuotaWindow"][];
            meta: components["schemas"]["Meta"];
            page: components["schemas"]["Page"];
        };
        SnapshotsResponse: {
            data: components["schemas"]["QuotaSnapshot"][];
            meta: components["schemas"]["Meta"];
            page: components["schemas"]["Page"];
        };
        WindowSummariesResponse: {
            data: components["schemas"]["QuotaWindowSummary"][];
            meta: components["schemas"]["Meta"];
            page: components["schemas"]["Page"];
        };
        EventsResponse: {
            data: components["schemas"]["UsageEvent"][];
            meta: components["schemas"]["Meta"];
            page: components["schemas"]["Page"];
        };
        SessionsResponse: {
            data: components["schemas"]["Session"][];
            meta: components["schemas"]["Meta"];
            page: components["schemas"]["Page"];
        };
        LabelsResponse: {
            data: components["schemas"]["Label"][];
            meta: components["schemas"]["Meta"];
            page: components["schemas"]["Page"];
        };
        SeriesResponse: {
            data: components["schemas"]["UsageSeries"];
            meta: components["schemas"]["Meta"];
        };
        LabelResponse: {
            data: components["schemas"]["Label"];
            meta: components["schemas"]["Meta"];
        };
        BrowserSessionResponse: {
            data: components["schemas"]["BrowserSession"];
            meta: components["schemas"]["Meta"];
        };
        ErrorResponse: {
            error: components["schemas"]["Error"];
            meta: components["schemas"]["Meta"];
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    getHealth: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listAccounts: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["AccountsResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listSources: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                /** @description IANA timezone */
                timezone?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SourcesResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listQuotaPools: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                /** @description IANA timezone */
                timezone?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PoolsResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listQuotaWindows: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                pool_id: string;
                from: string;
                to: string;
                /** @description IANA timezone */
                timezone?: string;
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WindowsResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listQuotaSnapshots: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                pool_id: string;
                from: string;
                to: string;
                window_id?: string;
                /** @description IANA timezone */
                timezone?: string;
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SnapshotsResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listQuotaWindowSummaries: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                pool_id: string;
                from: string;
                to: string;
                /** @description IANA timezone */
                timezone?: string;
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["WindowSummariesResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    getUsageSeries: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                from: string;
                to: string;
                /** @description Comma-separated product OR filter; validated against provider */
                products?: string;
                /** @description IANA timezone */
                timezone?: string;
                bucket: "15m" | "hour" | "day" | "week" | "month";
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SeriesResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listUsageEvents: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                from: string;
                to: string;
                /** @description Comma-separated product OR filter; validated against provider */
                products?: string;
                session_id?: string;
                label_id?: string;
                /** @description IANA timezone */
                timezone?: string;
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EventsResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listSessions: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                from: string;
                to: string;
                /** @description Comma-separated product OR filter; validated against provider */
                products?: string;
                /** @description IANA timezone */
                timezone?: string;
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SessionsResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    listLabels: {
        parameters: {
            query: {
                provider: "gpt" | "claude";
                account_id: string;
                from: string;
                to: string;
                /** @description Comma-separated product OR filter; validated against provider */
                products?: string;
                /** @description IANA timezone */
                timezone?: string;
                limit?: number;
                cursor?: string;
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabelsResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    createLabel: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LabelCreate"];
            };
        };
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description Quoted integer label revision */
                    ETag?: string;
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabelResponse"];
                };
            };
            /** @description Success */
            201: {
                headers: {
                    /** @description Quoted integer label revision */
                    ETag?: string;
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabelResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    deleteLabel: {
        parameters: {
            query?: never;
            header: {
                "If-Match": string;
            };
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success, no response body */
            204: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    updateLabel: {
        parameters: {
            query?: never;
            header: {
                "If-Match": string;
            };
            path: {
                id: string;
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LabelPatch"];
            };
        };
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description Quoted integer label revision */
                    ETag?: string;
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LabelResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    restoreBrowserSession: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success */
            200: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BrowserSessionResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    pairBrowserSession: {
        parameters: {
            query?: never;
            header: {
                "X-Dashboard-Pairing": "1";
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PairSessionRequest"];
            };
        };
        responses: {
            /** @description Success */
            201: {
                headers: {
                    /** @description HttpOnly host-only app session; see browser-auth.md */
                    "Set-Cookie"?: string;
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["BrowserSessionResponse"];
                };
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description Seconds until another pairing attempt may be made */
                    "Retry-After"?: number;
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
    revokeBrowserSession: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Success, no response body */
            204: {
                headers: {
                    /** @description Clear aud_session with identical Path and Max-Age=0 */
                    "Set-Cookie"?: string;
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content?: never;
            };
            /** @description See error.code */
            401: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            403: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            404: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            409: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            412: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            422: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            428: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            429: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
            /** @description See error.code */
            500: {
                headers: {
                    /** @description no-store */
                    "Cache-Control"?: "no-store";
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ErrorResponse"];
                };
            };
        };
    };
}
