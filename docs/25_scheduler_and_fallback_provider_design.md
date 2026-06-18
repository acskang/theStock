# Scheduler and Fallback Provider Design

## 0. Purpose

This document defines how `theStock` should connect Toss OpenAPI ingestion to a scheduler and fallback provider policy.

This document started as a design-only step. As of 2026-06-18, the repository also contains an OS-level systemd timer/service candidate for decision input collection:

```text
deploy/production/thestock_investor_flow_collect.service
deploy/production/thestock_investor_flow_collect.timer
```

The repository files are the desired operational definition. The actual `/etc/systemd/system` unit on a server must still be checked separately because it may lag behind the repository copy.

## 1. Current State

### Scheduler / Job Runtime

Current repository inspection shows no Celery, Celery Beat, django-crontab, or APScheduler integration for data jobs.

The repository now includes a systemd oneshot/timer candidate for the decision input collection flow. It uses Django management commands and does not introduce a new worker dependency.

The current operational pattern is management-command based:

- `run_daily_pipeline`
- `ingest_daily_prices`
- `ingest_stock_master`
- `ingest_investor_flows`
- `ingest_market_indices`
- `ingest_risk_events`
- `ingest_financial_data`
- `update_data_quality`
- Toss-specific smoke and ingestion commands

Deployment files now include scheduled decision input ingestion candidates in addition to web runtime operations.

### Existing Pipeline Orchestration

`run_daily_pipeline` delegates to service functions and supports `--dry-run`.

Current pipeline domains:

- stock master
- daily prices
- investor flows
- market indices
- risk events
- financial data
- data quality refresh

The existing orchestrator uses provider abstraction through `get_provider(...)`.

### Provider Selection

`data_pipeline.providers.get_provider()` uses:

```text
provider_name argument if provided
else settings.DATA_PIPELINE_PROVIDER
else mock fallback in function default
```

Project settings currently default `DATA_PIPELINE_PROVIDER` to `auto`.

`AutoProvider` delegates by domain:

- stock master: KRX provider
- daily prices: Finance provider, with domestic Naver daily price fallback in the direct collector path
- investor flows: Naver investor flow fallback first for domestic stocks, with pykrx as a secondary helper where applicable
- market indices: Finance provider
- risk events: OpenDART disclosure provider, with Naver notice/news fallback when the API key or corp code path cannot produce rows
- financial snapshots: FinancialStatement provider

Toss is intentionally opt-in:

```text
get_provider("toss")
```

Toss is not included in `AutoProvider`, and enabling `TOSS_INVEST_PROVIDER_ENABLED=true` does not change the default provider path.

Stock master automation target:

```text
1. 국내 종목 master는 KRX 기반 자동 적재로 대체한다.
2. 미국 종목 master는 별도 미국 시장 provider 또는 Toss 종목 기본정보 조회 결과를 검증해 자동 적재 후보로 둔다.
3. 기존 `/symbols/` 수동 화면은 운영 메뉴의 `종목마스터 관리/등록`으로 유지하되, 장기적으로는 누락/충돌 보정용으로 축소한다.
4. 자동 적재는 Stock 자동 생성 정책, market 분류, 기존 거래/보유 매핑 영향 검증 후 별도 단계에서 구현한다.
```

## 2. Relevant Models

### DataIngestionLog

`DataIngestionLog` now supports safe operational logging for provider jobs:

- provider/provider_name
- job_name/job_type
- target_type/target_symbol/market
- endpoint_name
- status: started, success, partial, failed, skipped
- network_call
- dry_run
- commit_mode
- candidate_count
- saved_count
- updated_count
- skipped_count
- failed_count
- safe_reason
- error_code
- http_status_code
- duration_ms
- metadata/details

Sensitive values must never be stored in `metadata` or `details`.

### DataProviderStatus

`DataProviderStatus` tracks provider and data type health:

- provider
- data_type
- last_success_at
- last_failed_at
- last_error_message
- consecutive_failures
- average_latency_ms
- is_active

It has a unique constraint on `(provider, data_type)`.

The current helper `update_provider_status(...)` can be reused after scheduler integration, but Toss command paths currently rely primarily on `DataIngestionLog`.

### DailyPrice

`DailyPrice` stores daily candles:

- stock FK
- date
- open/high/low/close
- volume
- change_rate

Unique constraint:

```text
(stock, date)
```

Scheduler must preserve existing commit rules:

- no Stock auto-create
- existing row skip by default
- update only with explicit update mode

### UserHolding

`UserHolding` stores user-owned holdings:

- user FK
- stock FK
- average_price
- quantity
- is_active
- max_additional_budget
- risk_level
- memo

Unique constraint:

```text
(user, stock)
```

Scheduler must preserve existing commit rules:

- explicit user required
- no Stock auto-create
- KR/KRW positive integer quantity only
- existing active row skip by default
- update only with explicit update mode
- inactive row is not automatically reactivated

## 3. Command Classification

### Manual Check Commands

These should stay manual and should not be scheduled as normal ingestion jobs:

| Command | Network | DB Writes | DataIngestionLog | Automation |
|---|---:|---:|---:|---|
| `check_toss_provider` | no | log only | yes | preflight/manual |
| `toss_token_smoke` | optional | log only | yes | manual smoke |
| `toss_quote_smoke` | optional | log only | yes | manual smoke |
| `toss_provider_quote_smoke` | optional | log only | yes | manual smoke |
| `toss_registry_quote_smoke` | optional | log only | yes | manual smoke |

### Automation Candidate Commands

| Command | Network | Domain Writes | Required Guard |
|---|---:|---:|---|
| `toss_daily_price_ingest_dryrun` | yes unless `--no-network` | DailyPrice only with commit | `--commit --confirm-save` |
| `toss_holdings_sync_dryrun` | yes unless `--no-network` | UserHolding only with commit | `--map-user-holdings --user-id/--username --commit --confirm-save` |

### Automation Forbidden

No command should call or schedule:

- order creation
- order correction
- order cancellation
- order history expansion beyond explicitly approved read-only scope
- buying-power/sellable-quantity/commission APIs until separately designed
- any automatic trading workflow

## 4. Scheduler Introduction Strategy

### Recommended Phase 1: External Scheduler Wrapper

Use OS-level scheduling or a deployment-managed runner to execute Django management commands.

Recommended first implementation:

```text
systemd timer or cron -> management command
```

Rationale:

- the project already uses management commands
- no new dependency is required
- operational rollback is simple
- command output and DataIngestionLog already provide observability

Do not introduce Celery/Celery Beat until there is a need for distributed workers, retries, or long-running async orchestration.

### Recommended Phase 2: Internal Scheduler Command

Add a single wrapper command later, for example:

```bash
python manage.py run_scheduled_ingestion --profile=daily-close --dry-run
python manage.py run_scheduled_ingestion --profile=daily-close --commit --confirm-save
```

This wrapper should call existing commands or extracted service functions, not duplicate ingestion logic.

### Scheduler Profiles

Recommended profiles:

| Profile | Frequency | Purpose |
|---|---|---|
| `preflight` | before scheduled jobs | provider/config/logging health |
| `daily-close-dry-run` | after market close | safe candidate validation |
| `daily-close-commit` | after dry-run passes | DailyPrice commit |
| `holdings-dry-run` | manual or low frequency | holdings candidate validation |
| `holdings-commit` | explicit opt-in only | UserHolding sync |

### Implemented Repository Candidate

The current repository-level systemd candidate is intentionally management-command based:

```bash
python manage.py collect_daily_prices --days 240
python manage.py collect_market_indices --codes KOSPI KOSDAQ USDKRW NASDAQ SP500 --days 240
python manage.py collect_investor_flows --days 60
python manage.py collect_risk_events --days 365
python manage.py collect_financial_snapshots --years 2
python manage.py update_data_quality --all-stocks
```

This job updates only local market/decision input data:

```text
DailyPrice
MarketIndex
InvestorFlow
RiskEvent
FinancialSnapshot
DataQualitySnapshot
```

It does not call Toss order creation, order modification, order cancellation, or any automatic trading flow.

## 5. DailyPrice Automation Design

### Scope

DailyPrice automation should start with a small stock allowlist, then expand.

Recommended sequence:

1. one-symbol dry-run
2. one-symbol commit
3. small allowlist dry-run
4. small allowlist commit
5. batch command after Step 22 design

### Command Policy

Use current command for single-symbol automation:

```bash
python manage.py toss_daily_price_ingest_dryrun --symbol=005930 --market=KR --count=1
python manage.py toss_daily_price_ingest_dryrun --symbol=005930 --market=KR --count=1 --commit --confirm-save
```

For scheduler use, a future batch wrapper should:

- require explicit symbol list or managed allowlist
- limit batch size
- rate-limit requests
- keep per-symbol DataIngestionLog rows or one aggregate row plus per-symbol safe details
- skip missing Stock rows
- skip existing rows by default
- use `--update-existing` only in a dedicated repair profile

### Fallback Policy

DailyPrice fallback should be explicit and domain-specific.

Proposed order:

```text
Toss candles -> existing finance/market price provider -> no write, log failed
```

Rules:

- fallback only after Toss failure types that are retryable or provider-side
- no fallback for invalid symbol or Stock missing
- record fallback use in DataIngestionLog metadata with safe keys only
- DataProviderStatus should mark Toss failure and fallback provider success separately

## 6. UserHolding Automation Design

### Scope

UserHolding sync is user/account scoped and should not be broad-scheduled by default.

Recommended default:

```text
manual or explicitly configured user/account only
```

### Command Policy

Dry-run:

```bash
python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID>
```

Commit:

```bash
python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID> --commit --confirm-save
```

Repair/update:

```bash
python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID> --commit --confirm-save --update-existing
```

Scheduler must not infer a user. It must receive an explicit user id or a future safe owner mapping config.

### Account Selection

Keep the current account selection policy:

- explicit `--account` must be accountSeq-like or fail
- env account value is used only if accountSeq-like
- if env value is missing/non-integer/too long, `/api/v1/accounts` fallback may choose accountSeq only when exactly one account exists
- never output or store accountNo/accountSeq/header raw values

### Fallback Policy

There is no provider fallback for UserHolding in the current model.

If holdings sync fails:

- do not mutate UserHolding
- leave previous holdings intact
- write DataIngestionLog failure
- update DataProviderStatus for `provider=toss`, `data_type=holdings` after status integration

## 7. Provider Fallback Design

### Current State

`AutoProvider` is static and does not implement dynamic fallback. It delegates each domain to a fixed provider.

Toss is not in `AutoProvider`. This is correct for safety until scheduler integration is explicitly implemented.

### Recommended Future Interface

Introduce a provider policy layer, separate from `AutoProvider`, for scheduled jobs:

```text
ProviderPolicy
- domain
- primary_provider
- fallback_providers
- retry_policy
- status_policy
- safe_metadata
```

Example:

```text
daily_price:
  primary=toss
  fallback=finance
  fallback_allowed=true

holdings:
  primary=toss
  fallback=none
  fallback_allowed=false
```

Avoid changing `get_provider()` default behavior in the first scheduler phase.

## 8. Failure Handling

### Authentication Failure

Examples:

- credentials missing
- token request failed
- invalid client credentials

Policy:

- do not fallback for account/holdings data
- daily price may fallback to non-account market provider after Toss auth failure if explicitly configured
- record `status=failed`, `safe_reason=authentication_failed` or `credentials_missing`
- update DataProviderStatus consecutive failures

### Rate Limit

Policy:

- stop batch early
- do not hammer fallback unless the fallback is explicitly allowed
- record `safe_reason=rate_limit_exceeded`
- next scheduler run should retry after configured interval

### Provider 5xx / Network Timeout

Policy:

- retry once with short backoff in future wrapper
- if still failed, fallback only where configured
- preserve existing DB rows

### Invalid Symbol / Stock Missing

Policy:

- do not fallback
- do not auto-create Stock
- record skipped or failed with safe reason

### Partial Data

Policy:

- do not treat partial batch as success
- use `status=partial`
- save valid rows only if command semantics explicitly support partial commit
- include counts in DataIngestionLog

## 9. DataIngestionLog Policy

Every scheduled run should create a DataIngestionLog row.

Recommended fields:

| Field | DailyPrice | UserHolding |
|---|---|---|
| provider_name | toss/fallback provider | toss |
| job_type | scheduled_daily_price | scheduled_holdings |
| target_type | daily_price | holdings |
| target_symbol | symbol for single row | symbol if filtered |
| endpoint_name | `/api/v1/candles` | `/api/v1/holdings` |
| status | success/partial/failed/skipped | success/partial/failed/skipped |
| network_call | true unless no-network | true unless no-network |
| dry_run | true for validation | true for validation |
| commit_mode | not_requested/confirmed/rejected | not_requested/confirmed/rejected |
| candidate_count | candidates | holdings candidates |
| saved_count | created DailyPrice | created UserHolding |
| updated_count | updated DailyPrice | updated UserHolding |
| skipped_count | duplicates/missing stock | unsupported/existing/missing stock |
| failed_count | failed rows | failed rows |

Forbidden metadata:

- access token
- client secret
- accountNo
- accountSeq
- X-Tossinvest-Account
- Authorization header
- request headers/body
- raw response
- username/email

## 10. DataProviderStatus Policy

Scheduler integration should update `DataProviderStatus` after each scheduled job.

Recommended mapping:

| Job Result | DataProviderStatus |
|---|---|
| success | reset consecutive failures, set last_success_at |
| partial | increment failure or set degraded marker through last_error_message |
| failed | increment consecutive failures, set last_failed_at |
| skipped no-network | do not change provider status |
| provider disabled | mark skipped in log, do not count as provider failure unless scheduled profile required it |

Recommended data types:

- `daily_price`
- `holdings`
- existing pipeline types such as `price`, `stock`, `flow`, `market`

Because `DataProviderStatus.DATA_TYPE_CHOICES` reuses `DataIngestionLog.TARGET_TYPE_CHOICES`, both `daily_price` and `holdings` are available.

## 11. Operational Runbook Draft

### Preflight

```bash
python manage.py check
python manage.py check_toss_provider
python manage.py toss_token_smoke --no-network
python manage.py toss_holdings_sync_dryrun --no-network
```

### Manual DailyPrice Dry-Run

```bash
python manage.py toss_daily_price_ingest_dryrun --symbol=005930 --market=KR --count=1
```

### Manual DailyPrice Commit

```bash
python manage.py toss_daily_price_ingest_dryrun --symbol=005930 --market=KR --count=1 --commit --confirm-save
```

### Manual Holdings Dry-Run

```bash
python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID>
```

### Manual Holdings Commit

```bash
python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID> --symbol=<SYMBOL> --commit --confirm-save
```

### Manual Holdings Update

```bash
python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID> --symbol=<SYMBOL> --commit --confirm-save --update-existing
```

### Monitoring Queries

```bash
python manage.py shell -c "
from data_pipeline.models import DataIngestionLog
for row in DataIngestionLog.objects.order_by('-id')[:20]:
    print(row.id, row.job_name, row.target_type, row.target_symbol, row.status, row.safe_reason, row.candidate_count, row.saved_count, row.updated_count, row.skipped_count, row.failed_count)
"
```

## 12. Implementation Phases

### Step 21B: Scheduler Wrapper Command Design/Implementation

Add a wrapper command only; do not register OS scheduler yet.

Requirements:

- profile-based execution
- `--dry-run` default
- `--commit --confirm-save` required for writes
- explicit provider policy
- safe logging
- no order API

### Step 21C: DataProviderStatus Integration

Connect scheduled job outcomes to `DataProviderStatus`.

Requirements:

- no secret/error raw response storage
- no status update for no-network checks
- consecutive failure tracking

### Step 21D: External Scheduler Registration

Add deployment-level scheduling after wrapper command is verified.

Requirements:

- run as the same application user
- lock file or DB lock to prevent overlap
- log rotation
- alert on failures
- documented rollback

### Step 22: DailyPrice Batch Ingestion

Design and implement batch DailyPrice before scheduling broad daily price collection.

Requirements:

- bounded batch size
- explicit symbol source
- per-symbol skip/save/update counts
- fallback policy
- rate-limit policy

## 13. Security Constraints

Scheduler jobs must never print or persist:

- `.env` contents
- client id raw value
- client secret
- access token
- accountNo
- accountSeq
- X-Tossinvest-Account
- Authorization header
- request body/header
- raw Toss response
- username/email in log metadata

Order APIs remain disabled and out of scope.

## 14. Recommendation

Do not modify `AutoProvider` or `DATA_PIPELINE_PROVIDER` yet.

Use Toss through explicit scheduler profiles and explicit command flags. Keep the current provider default and existing domain providers unchanged until batch ingestion and fallback behavior are verified under a wrapper command.
