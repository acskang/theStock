# DataIngestionLog Schema Extension Design

## 1. Purpose

This document designs a safe extension of `data_pipeline.models.DataIngestionLog`
so Toss OpenAPI smoke checks and DailyPrice ingestion commands can write
operational history without weakening the meaning of existing ingestion logs.

This is a design-only step. It does not change models, migrations, commands, or
database schema.

## 2. Current Model

`DataIngestionLog` currently lives in `data_pipeline.models`.

Current fields:

| Field | Current behavior |
|---|---|
| `job_name` | Required command or job name |
| `provider` | Required provider name |
| `target_type` | Required choice field |
| `target_code` | Optional code string |
| `status` | Required choice field, default `started` |
| `started_at` | Required indexed datetime |
| `finished_at` | Optional datetime |
| `total_count` | Count of attempted targets |
| `success_count` | Count of successful targets |
| `failed_count` | Count of failed targets |
| `skipped_count` | Count of skipped targets |
| `error_message` | Optional representative safe error |
| `details` | Optional JSONField |
| `created_at` | Auto-created datetime |

Current `status` choices:

```text
started
success
partial
failed
```

Current `target_type` choices:

```text
stock
price
flow
market
risk
financial
quality
```

Current display and API usage:

- Django admin lists `job_name`, `provider`, `target_type`, `target_code`,
  `status`, `started_at`, and `finished_at`.
- `DataIngestionLogSerializer` exposes all current fields read-only.
- `DataIngestionLogViewSet` filters by `status`, `job_name`, `provider`,
  `target_type`, and `target_code`.
- `build_data_pipeline_summary()` uses recent logs, latest successful log, and
  failed or partial logs to calculate data pipeline health.

Current limitation:

- `target_type` cannot represent provider health, authentication, quote smoke,
  registry smoke, or dry-run diagnostics cleanly.
- `status` cannot represent skipped no-network, disabled provider, or intentionally
  skipped duplicate rows.
- Forcing Toss smoke results into existing choices would make operational
  dashboards ambiguous.

## 3. Extension Goals

The schema should support these records:

- provider configuration check
- token smoke
- quote smoke
- provider `get_quote` smoke
- registry quote smoke
- DailyPrice candle dry-run
- DailyPrice commit save, duplicate skip, and update-existing paths

It must also preserve these guarantees:

- No secrets or account identifiers are stored.
- No raw request headers, request body, response body, or Authorization header are
  stored.
- Existing API/admin behavior remains compatible.
- Existing ingestion summaries continue to work.
- Toss provider registration does not change automatic provider priority.
- Order API activity remains out of scope and should be explicitly detectable as
  not implemented or not called.

## 4. Recommended Schema Changes

Prefer adding small nullable fields and extending choices. Keep existing fields
for compatibility.

### 4.1 Choice Extensions

Add target types:

```text
provider_health
auth
quote
smoke
daily_price
```

Rationale:

- `provider_health` covers `check_toss_provider`.
- `auth` covers token issuance smoke.
- `quote` covers price quote smoke paths.
- `smoke` is a fallback for generic smoke commands.
- `daily_price` is more explicit than the existing broad `price` for candle
  ingestion. Existing `price` can remain for legacy or generic pipelines.

Add status:

```text
skipped
```

Keep canonical final statuses simple:

```text
success
failed
skipped
partial
```

Keep `started` for long-running future jobs that create a row before completion.

Do not add `disabled`, `misconfigured`, `dry_run`, or `no_network` as statuses.
Represent those as `safe_reason`, `error_code`, or `details` values.

### 4.2 New Fields

Recommended additive fields:

| Field | Type | Null/blank | Purpose |
|---|---|---:|---|
| `job_type` | `CharField(max_length=50)` | yes | Stable category such as `smoke`, `ingestion`, `health_check` |
| `provider_name` | `CharField(max_length=50)` | yes | Normalized provider name; initially mirror `provider` |
| `endpoint_name` | `CharField(max_length=100)` | yes | Safe endpoint label such as `candles`, not a full URL |
| `target_symbol` | `CharField(max_length=50)` | yes | Symbol-level target separate from generic `target_code` |
| `market` | `CharField(max_length=20)` | yes | Market hint such as `KR` |
| `network_call` | `BooleanField(null=True)` | yes | Whether external network was attempted |
| `dry_run` | `BooleanField(null=True)` | yes | Whether DB writes were intentionally disabled |
| `commit_mode` | `CharField(max_length=30)` | yes | `not_requested`, `rejected`, `confirmed`, `not_supported` |
| `saved_count` | `PositiveIntegerField(default=0)` | no | Rows created by command |
| `updated_count` | `PositiveIntegerField(default=0)` | no | Rows updated by command |
| `safe_reason` | `CharField(max_length=100)` | yes | Controlled reason code |
| `error_code` | `CharField(max_length=100)` | yes | Provider-safe error code |
| `http_status_code` | `PositiveIntegerField(null=True)` | yes | Provider-safe HTTP status |
| `duration_ms` | `PositiveIntegerField(null=True)` | yes | End-to-end command duration |

`details` remains the place for low-volume safe metadata. Do not duplicate large
payloads or raw API responses there.

### 4.3 Compatibility Mapping

While both old and new fields exist:

- Keep writing `provider="toss"` and `provider_name="toss"`.
- Keep writing `target_code` with the symbol for symbol-based commands.
- Also write `target_symbol` with the same symbol for clarity.
- Map `created_count` from command output to `saved_count`.
- Continue writing aggregate `total_count`, `success_count`, `failed_count`, and
  `skipped_count` for existing dashboards.

## 5. Command Logging Design

### 5.1 Status Policy

Use these final statuses:

| Situation | `status` | `safe_reason` |
|---|---|---|
| Successful smoke or save | `success` | blank |
| `--no-network` provided | `skipped` | `no_network` |
| Provider disabled | `skipped` | `provider_disabled` |
| Credentials missing | `failed` | `credentials_missing` |
| Authentication failed | `failed` | `authentication_failed` |
| Rate limit exceeded | `failed` | `rate_limit_exceeded` |
| Quote request failed | `failed` | `quote_request_failed` |
| Candle request failed | `failed` | `candle_request_failed` |
| Provider not registered | `failed` | `provider_not_registered` |
| Registry error | `failed` | `registry_error` |
| Duplicate DailyPrice skipped | `success` if all targets skipped safely, else `partial` | `existing_row_skipped` |
| Mixed saved/updated/skipped/failed | `partial` | `partial_success` |

`dry_run=true` is metadata, not a status.

### 5.2 Command Matrix

| Command | job_type | target_type | endpoint_name | status rules | Safe details |
|---|---|---|---|---|---|
| `check_toss_provider` | `health_check` | `provider_health` | blank | configured=`success`, disabled=`skipped`, misconfigured=`failed` | `enabled`, `order_execution_enabled`, `transport_check` |
| `toss_token_smoke` | `smoke` | `auth` | `token` | OK=`success`, no-network=`skipped`, auth/config failures=`failed` | `token_type`, `expires_in`, `network_call` |
| `toss_quote_smoke` | `smoke` | `quote` | `prices` | OK=`success`, no-network/provider-disabled=`skipped`, request/auth failures=`failed` | `symbol`, `market`, `currency`, `has_price` |
| `toss_provider_quote_smoke` | `smoke` | `quote` | `prices` | Same as quote smoke | `provider_path=true` |
| `toss_registry_quote_smoke` | `smoke` | `quote` | `prices` | Same as quote smoke, registry failures=`failed` | `registry_path=true`, `provider_registered` |
| `toss_daily_price_ingest_dryrun` no-network | `ingestion_dry_run` | `daily_price` | `candles` | `skipped` | `count`, `adjusted`, `registry_path` |
| `toss_daily_price_ingest_dryrun` dry-run | `ingestion_dry_run` | `daily_price` | `candles` | candidate success=`success`, failures=`failed` | `candidate_count`, `adjusted`, `interval=1d` |
| `toss_daily_price_ingest_dryrun --commit --confirm-save` | `ingestion` | `daily_price` | `candles` | all saved/updated/skipped safely=`success`, mixed failures=`partial`, all failed=`failed` | `saved_count`, `updated_count`, `skipped_count`, `failed_count`, `update_existing` |

### 5.3 Count Mapping

For DailyPrice ingestion:

```text
total_count = candidate_count
success_count = saved_count + updated_count
failed_count = failed_count
skipped_count = skipped_count
saved_count = created_count
updated_count = updated_count
```

For smoke commands:

```text
total_count = 1
success_count = 1 when status=success else 0
failed_count = 1 when status=failed else 0
skipped_count = 1 when status=skipped else 0
```

## 6. Safe Metadata Policy

Allowed in `details`:

```text
command
provider
symbol
market
endpoint_name
interval
count
adjusted
network_call
dry_run
commit_mode
update_existing
provider_path
registry_path
provider_registered
order_execution_enabled
candidate_count
saved_count
updated_count
skipped_count
failed_count
http_status_code
error_code
error_field
params_shape
safe_message
```

Forbidden in `details`, `error_message`, stdout, and Python logs:

```text
client_id raw value
client_secret raw value
access_token raw value
account id raw value
Authorization header
X-Tossinvest-Account header
request body
request headers
raw API response body
raw token response
full provider exception string when it may include payloads
```

Provider request URLs should not be stored. Use `endpoint_name` or endpoint path
labels such as `prices` and `candles`.

## 7. Migration Strategy

Recommended migration sequence:

1. Add new status choice `skipped`.
2. Add new target type choices.
3. Add nullable metadata fields listed in section 4.2.
4. Keep existing fields and indexes unchanged.
5. Add indexes only after write volume is known. Initial optional candidates:
   - `provider_name, -started_at`
   - `job_type, -started_at`
   - `target_symbol, -started_at`
6. Deploy migration before commands start writing DB logs.
7. Add a small logging helper service, for example
   `data_pipeline.services.ingestion_log_writer`.
8. Update commands one at a time, starting with `toss_daily_price_ingest_dryrun`
   because it already has concrete save/update/skip counts.
9. Backfill is optional. Existing rows can keep null new fields.

Do not make `job_type`, `provider_name`, `target_symbol`, `endpoint_name`,
`network_call`, `dry_run`, `commit_mode`, `safe_reason`, `error_code`,
`http_status_code`, or `duration_ms` non-null in the first migration.

## 8. Implementation Plan After Schema Migration

Recommended order:

1. Add model fields and choices.
2. Add tests for choice compatibility and serializer output.
3. Implement a central writer that accepts only controlled safe fields.
4. Add logging to `toss_daily_price_ingest_dryrun`.
5. Add logging to quote and registry smoke commands.
6. Add logging to token and provider health smoke commands.
7. Update summary service only if skipped rows should affect health differently.
8. Add admin filters for `job_type`, `provider_name`, `network_call`, and
   `dry_run` after fields exist.

## 9. Health Summary Impact

Current `build_data_pipeline_summary()` treats `failed` and `partial` as recent
failures. This can remain unchanged.

Recommended behavior:

- `success`: contributes to latest success.
- `partial`: contributes to recent failures.
- `failed`: contributes to recent failures.
- `skipped`: should not be counted as a failure by default.

This means no-network smoke and disabled opt-in provider checks do not degrade
pipeline health unless the command maps them to `failed`.

## 10. Open Decisions

- Whether `provider disabled` should be `skipped` or `failed` when production
  expects Toss to be enabled.
- Whether duplicate DailyPrice skip should count as `success_count` or only
  `skipped_count`. This design recommends `status=success`, `success_count=0`,
  `skipped_count=1`.
- Whether DataProviderStatus should be updated by smoke commands. This design
  recommends delaying that until DataIngestionLog writes are stable.
- Whether raw response summaries should be retained at all. This design
  recommends only count and cursor summaries, never raw payloads.
