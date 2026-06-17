# Current Implementation Final Summary

## 1. Purpose

This document summarizes the current Toss OpenAPI integration state for
operators. It separates implemented features, actually verified behavior, and
work that is still intentionally deferred.

This document is a summary only. It does not change code, settings, migrations,
database schema, scheduler registration, or runtime behavior.

## 2. Current Operating State

Latest known operating data state after Step 21C verification:

| Model | Count / State | Notes |
|---|---:|---|
| `Stock` | 17 | No automatic Stock creation in Toss commands |
| `DailyPrice` | 2 | Includes real Toss candle saves from previous smoke steps |
| `UserHolding` | 1 | One real holdings-derived row saved for explicit user and symbol |
| `DataProviderStatus` | 0 | Toss commands currently rely on `DataIngestionLog`; provider status automation is not connected |
| `DataIngestionLog` | 79 | Includes smoke, dry-run, commit, skip, update, and scheduler wrapper logs |

Known saved rows from previous smoke steps:

| Domain | Saved Data | Notes |
|---|---|---|
| DailyPrice | `005930` Samsung Electronics, plus one additional existing Stock symbol from save smoke | Stored through `--commit --confirm-save`; duplicate skip and update paths verified |
| UserHolding | `user_id=6`, `stock_code=035250`, quantity `2`, average price `15116.50`, active | Stored through explicit owner, symbol, `--commit --confirm-save` |

Account identifiers, access tokens, authorization headers, request headers,
request bodies, and raw API responses are not stored in these summaries.

## 3. Toss Auth / Client / Provider

Implemented:

- Toss environment-backed configuration loading through Django settings.
- OAuth2 client credentials token issuing helper.
- `TossOpenApiClient` with relative URL enforcement, token header construction,
  optional account header support, timeout handling, and safe error detail
  extraction.
- `TossOpenApiProvider` with health, quote, daily candle candidate, accounts,
  and holdings candidate methods.
- Safe masking helpers for client/account-like values.
- Order guard with `TOSS_ORDER_EXECUTION_ENABLED` defaulting to disabled.
- `get_provider("toss")` opt-in registry path.

Verified:

- Actual token smoke succeeded.
- Actual quote smoke succeeded.
- Actual `TossOpenApiProvider.get_quote()` smoke succeeded.
- Actual registry quote smoke succeeded.
- `check_toss_provider` reports provider configured and
  `order_execution_enabled=false` without network calls.

Still deferred:

- Toss is not part of `AutoProvider`.
- Toss is not the default provider.
- Provider fallback status automation is not connected.
- Token persistence/cache beyond command execution is not implemented.

## 4. Quote / Current Price

Implemented:

- Current price lookup through `GET /api/v1/prices`.
- Direct command path: `toss_quote_smoke`.
- Provider path: `toss_provider_quote_smoke`.
- Registry path: `toss_registry_quote_smoke`.
- Safe DataIngestionLog writes for no-network, success, and failure paths.

Verified:

| Item | State | Notes |
|---|---|---|
| `/api/v1/prices` actual lookup | Complete | Actual network smoke succeeded |
| Direct quote smoke | Complete | DB save not supported |
| Provider quote smoke | Complete | Uses Toss provider instance |
| Registry quote smoke | Complete | Uses `get_provider("toss")` |
| Sensitive output | Complete | Token/header/account raw values not printed |

DB write policy:

- Quote commands do not create or update `Stock`, `DailyPrice`,
  `UserHolding`, or `DataProviderStatus`.
- `--commit` on quote smoke commands is treated as not supported.

## 5. DailyPrice

Implemented:

- Candle lookup through `GET /api/v1/candles`.
- `symbol` single parameter support for Toss candle API.
- `toss_daily_price_ingest_dryrun` command.
- Dry-run candidate normalization.
- Commit save path guarded by `--commit --confirm-save`.
- Existing row skip by default for `(stock, date)`.
- Existing row update only with `--update-existing`.
- DataIngestionLog counts for candidate, saved, updated, skipped, and failed
  records.

Verified:

| Item | State | Notes |
|---|---|---|
| Actual DailyPrice dry-run | Complete | Actual candle endpoint smoke succeeded |
| New DailyPrice save | Complete | Requires existing `Stock`; no Stock auto-create |
| Existing row skip | Complete | No `--update-existing`; count unchanged |
| Existing row update | Complete | `--update-existing`; count unchanged |
| Confirm-save required guard | Complete | `--commit` without `--confirm-save` rejected |
| DataIngestionLog commit/skip/update | Complete | Counts recorded |

Current policy:

- `Stock` must already exist.
- `Stock` auto-create is forbidden.
- `count` should remain narrow in smoke workflows.
- Batch ingestion is not implemented yet.

## 6. DataIngestionLog

Implemented:

- Schema extension design completed.
- Migrations `0002`, `0003`, and `0004` applied.
- Added/verified fields include:
  - `job_type`
  - `provider_name`
  - `endpoint_name`
  - `target_symbol`
  - `market`
  - `network_call`
  - `dry_run`
  - `commit_mode`
  - `candidate_count`
  - `saved_count`
  - `updated_count`
  - `skipped_count`
  - `failed_count`
  - `safe_reason`
  - `error_code`
  - `http_status_code`
  - `duration_ms`
  - `metadata`
- Added `status=skipped`.
- Added target types for provider health, auth, quote, smoke, daily price, and
  holdings.
- Admin, serializer, and API exposure were updated for safe extended fields.
- Common writer/service implemented:
  - `data_pipeline.services.ingestion_log_writer.record_data_ingestion_log`

Verified:

| Logging Area | State | Notes |
|---|---|---|
| no-network command logs | Complete | Smoke and dry-run commands write safe skipped logs |
| actual token/quote logs | Complete | Network success/failure paths connected |
| DailyPrice dry-run logs | Complete | Candidate counts recorded |
| DailyPrice commit/skip/update logs | Complete | Save/update/skip counts recorded |
| holdings logs | Complete | `target_type=holdings` recorded |
| scheduler wrapper logs | Complete | Wrapper summary row recorded |

Security policy:

- Metadata allowlist is enforced by the writer.
- Keys containing secret, token, authorization, account, header, request body, or
  raw response language are blocked.
- Raw API responses are not stored.

## 7. Holdings / UserHolding

Implemented:

- `GET /api/v1/accounts` account diagnostic path.
- `GET /api/v1/holdings` read-only dry-run path.
- Account selection:
  - explicit `--account` must be accountSeq-like
  - invalid explicit account does not fallback
  - invalid/missing env account can fallback to `/api/v1/accounts` when exactly
    one account exists
- Safe account diagnostics:
  - account count
  - account type summary
  - env/account shape
  - fallback source
  - whether account header is configured
- `--map-user-holdings` dry-run mapping.
- Explicit owner selection through `--user-id` or `--username`.
- Commit save path guarded by:
  - `--map-user-holdings`
  - `--commit`
  - `--confirm-save`
  - explicit user selector
  - network path only
- Existing active row skip by default.
- Existing active row update only with `--update-existing`.
- Inactive rows are not automatically reactivated.

Verified:

| Item | State | Notes |
|---|---|---|
| Accounts diagnostic | Complete | Actual `/api/v1/accounts` succeeded |
| AccountSeq fallback | Complete | Env value shape was unsuitable; single-account fallback worked |
| Holdings dry-run | Complete | Actual `/api/v1/holdings` succeeded |
| Symbol holdings dry-run | Complete | `--symbol=005930` path succeeded safely |
| UserHolding mapping dry-run | Complete | Owner-required and user-id paths verified |
| UserHolding new save | Complete | One row saved with explicit user and symbol |
| Existing UserHolding skip | Complete | No `--update-existing`; count unchanged |
| Existing UserHolding update | Complete | `--update-existing`; count unchanged |

Current UserHolding save constraints:

- Existing `Stock` row required.
- No `Stock` auto-create.
- Explicit user required.
- KR/KRW positive integer quantity only.
- US holdings and unsupported currencies are skipped.
- Fractional quantities are skipped.
- Existing inactive rows are skipped.
- Account identifiers are not saved.
- Username/email are not stored in DataIngestionLog metadata.

## 8. Scheduler Wrapper

Implemented:

- Management command:

```bash
python manage.py run_scheduled_ingestion
```

- Profiles:
  - `toss_no_network_preflight`
  - `toss_readonly_smoke`
- Options:
  - `--profile`
  - `--list-profiles`
  - `--no-network`
  - `--allow-network`
  - `--stop-on-error`
- Wrapper summary row is written to `DataIngestionLog`.
- Existing child command DataIngestionLog rows remain unchanged.

Profile behavior:

| Profile | State | Network | Domain DB Writes | Notes |
|---|---|---:|---:|---|
| `toss_no_network_preflight` | Implemented and verified | No | No | Runs safe no-network checks only |
| `toss_readonly_smoke` | Implemented, actual execution deferred | Yes only with `--allow-network` | No | Refuses execution without `--allow-network` |

Verified:

- `toss_no_network_preflight` ran 7/7 steps successfully.
- `toss_readonly_smoke` refused execution without `--allow-network`.
- The refusal wrote a safe skipped summary log.

Not implemented:

- No cron registration.
- No systemd timer registration.
- No Celery or Celery Beat.
- No APScheduler.
- No automatic production schedule.
- No save/commit scheduler profile.

## 9. Implemented Commands

| Command | Purpose | Network | Domain DB Writes | Safety Notes |
|---|---|---:|---:|---|
| `check_toss_provider` | Provider configuration check | No | Log only | Shows masked/configured values only |
| `toss_token_smoke` | Token smoke | Optional | Log only | `--no-network` supported; token raw value hidden |
| `toss_quote_smoke` | Direct price smoke | Optional | Log only | `--commit` not supported |
| `toss_provider_quote_smoke` | Provider quote smoke | Optional | Log only | `--commit` not supported |
| `toss_registry_quote_smoke` | Registry quote smoke | Optional | Log only | Uses `get_provider("toss")` |
| `toss_daily_price_ingest_dryrun` | Daily candle dry-run/save | Optional | DailyPrice only with explicit commit guard | Existing row skip/update policy enforced |
| `toss_holdings_sync_dryrun` | Holdings dry-run/UserHolding sync | Optional | UserHolding only with explicit commit guard | Owner and mapping guards enforced |
| `run_scheduled_ingestion` | Scheduler wrapper | Depends on profile | Log only in current profiles | Network profile requires `--allow-network` |

## 10. Actual API Calls Verified

| API | Endpoint | Verified | Used By | Notes |
|---|---|---:|---|---|
| Token | `POST /oauth2/token` | Yes | `toss_token_smoke`, client token provider | Access token raw value not printed/stored |
| Quote | `GET /api/v1/prices` | Yes | quote smoke/provider/registry commands | DB save not supported |
| Candles | `GET /api/v1/candles` | Yes | `toss_daily_price_ingest_dryrun` | Dry-run/save/skip/update verified |
| Accounts | `GET /api/v1/accounts` | Yes | holdings diagnostic/fallback | accountNo/accountSeq raw values not printed/stored |
| Holdings | `GET /api/v1/holdings` | Yes | `toss_holdings_sync_dryrun` | Dry-run/mapping/save/skip/update verified |

Not called or implemented:

- Order create.
- Order amend/correct.
- Order cancel.
- Order history.
- Order info.
- Buying power.
- Sellable quantity.
- Any automatic trading workflow.

## 11. Verification Matrix

| Area | Verification Item | State | Notes |
|---|---|---|---|
| Auth | `toss_token_smoke` actual execution | Complete | Token raw value hidden |
| Provider | `check_toss_provider` | Complete | No network call |
| Registry | `get_provider("toss")` path | Complete | Opt-in only |
| Quote | `/api/v1/prices` lookup | Complete | DB save none |
| Quote | provider quote smoke | Complete | Normalized quote returned |
| Quote | registry quote smoke | Complete | Toss not default provider |
| DailyPrice | actual dry-run | Complete | `/api/v1/candles` |
| DailyPrice | new save | Complete | Existing Stock required |
| DailyPrice | existing row skip | Complete | No `--update-existing` |
| DailyPrice | existing row update | Complete | With `--update-existing` |
| DataIngestionLog | schema migrations | Complete | 0002/0003/0004 applied |
| DataIngestionLog | writer/service | Complete | Safe metadata allowlist |
| DataIngestionLog | actual command logs | Complete | no-network/network/commit paths |
| Holdings | accounts diagnostic | Complete | account raw values hidden |
| Holdings | accountSeq fallback | Complete | single account fallback |
| Holdings | holdings dry-run | Complete | UserHolding save none |
| UserHolding | mapping dry-run | Complete | owner-required and user-id paths |
| UserHolding | new save | Complete | explicit user and symbol |
| UserHolding | existing row skip | Complete | update not requested |
| UserHolding | existing row update | Complete | `--update-existing` |
| Scheduler | no-network wrapper | Complete | Actual API call none |
| Scheduler | read-only network profile gate | Complete | Refuses without `--allow-network` |
| Scheduler | read-only network actual run | Deferred | To run in separate smoke step |
| Scheduler | commit/save profile | Deferred | Not implemented |
| Orders | order API | Not implemented | Remains disabled |

## 12. Safety Controls

Current controls:

- Toss provider is opt-in via `get_provider("toss")`.
- Default provider and `AutoProvider` are not changed.
- Order execution flag remains disabled.
- Quote commands do not support DB commit.
- DailyPrice commit requires `--commit --confirm-save`.
- DailyPrice update requires `--update-existing`.
- UserHolding commit requires `--map-user-holdings`, explicit owner,
  `--commit`, and `--confirm-save`.
- UserHolding update requires `--update-existing`.
- Inactive UserHolding rows are not automatically reactivated.
- Stock auto-create is forbidden in Toss ingestion commands.
- Scheduler read-only network profile requires `--allow-network`.
- Current scheduler wrapper profiles do not perform domain saves.
- Sensitive output is masked or summarized.
- DataIngestionLog metadata is allowlisted and redacted.

Forbidden by current implementation/policy:

- Storing access tokens.
- Storing accountNo/accountSeq raw values.
- Storing Authorization or X-Tossinvest-Account headers.
- Storing raw request/response bodies.
- Calling order APIs.
- Automatic trading.

## 13. Deferred Work

Still not automated or not implemented:

- Actual `toss_readonly_smoke` execution with `--allow-network` from scheduler
  wrapper.
- Scheduler registration through cron, systemd timer, Celery Beat, or another
  runtime.
- DailyPrice batch ingestion design and implementation.
- Commit/save scheduler profiles.
- DataProviderStatus integration for Toss scheduler health.
- Provider fallback execution policy.
- Multi-account holdings model support.
- US holdings commit support.
- Fractional quantity support.
- Account alias or broker-position schema.
- Order APIs and automatic trading.

## 14. Recommended Next Steps

1. Run `toss_readonly_smoke` manually with `--allow-network` in a controlled
   smoke step.
2. Design DailyPrice batch ingestion before expanding beyond one-symbol flows.
3. Decide whether Toss health should update `DataProviderStatus` in addition to
   `DataIngestionLog`.
4. Design scheduler registration separately after wrapper profiles are stable.
5. Keep all order API work disabled unless a separate safety design is approved.

