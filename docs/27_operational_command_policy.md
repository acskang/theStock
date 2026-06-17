# Operational Command Policy

## 1. Purpose

This document defines which Toss-related management commands operators may run,
which commands require explicit approval and guard options, and which command
patterns are forbidden in production.

It is based on the implementation summary in
`docs/26_current_implementation_final_summary.md`.

## 2. Baseline Rules

Always apply these rules before running any command:

- Do not print `.env` contents.
- Do not print raw client id, client secret, access token, account id,
  accountNo, accountSeq, `X-Tossinvest-Account`, or Authorization header.
- Do not print request headers, request bodies, or raw API responses.
- Do not run order APIs. Order create/amend/cancel/history/info flows are not
  implemented and remain disabled.
- Do not run automatic trading workflows.
- Treat `DataIngestionLog` writes as production DB writes. Even no-network
  commands may create log rows.
- Do not use `--commit`, `--confirm-save`, or `--update-existing` unless the
  row in this document explicitly allows that exact combination.

Current last-known production state:

| Model | Last-known count |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 2 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 60+ |

## 3. Green List: Normally Allowed Commands

These commands are allowed for routine operational checks. They may still write
safe `DataIngestionLog` rows.

| Command | Network | Domain DB writes | Log write | Allowed when | Notes |
|---|---:|---:|---:|---|---|
| `python manage.py check` | No | No | No | Routine check | Does not call Toss |
| `python manage.py check_toss_provider` | No | No | Yes | Routine preflight | Shows configured/masked state only |
| `python manage.py run_scheduled_ingestion --list-profiles` | No | No | No | Routine inspection | Lists wrapper profiles only |
| `python manage.py run_scheduled_ingestion --profile=toss_readonly_smoke` | No | No | Yes | Safe gate test | Must refuse without `--allow-network` |

## 4. Yellow List: Allowed With Caution

These commands are safe in design, but they either call Toss read-only APIs or
write `DataIngestionLog`. Use them intentionally and record the reason in the
operation notes.

| Command | Network | Domain DB writes | Log write | Required guard | Notes |
|---|---:|---:|---:|---|---|
| `python manage.py toss_token_smoke --no-network` | No | No | Yes | `--no-network` | Token endpoint not called |
| `python manage.py toss_quote_smoke --symbol=005930 --market=KR --no-network` | No | No | Yes | `--no-network` | Quote endpoint not called |
| `python manage.py toss_provider_quote_smoke --symbol=005930 --market=KR --no-network` | No | No | Yes | `--no-network` | Provider path, no endpoint call |
| `python manage.py toss_registry_quote_smoke --symbol=005930 --market=KR --no-network` | No | No | Yes | `--no-network` | Registry path, no endpoint call |
| `python manage.py toss_daily_price_ingest_dryrun --symbol=005930 --market=KR --count=1 --no-network` | No | No | Yes | `--no-network`, `count=1` | DailyPrice not saved |
| `python manage.py toss_holdings_sync_dryrun --no-network` | No | No | Yes | `--no-network` | Holdings endpoint not called |
| `python manage.py toss_holdings_sync_dryrun --diagnose-account --no-network` | No | No | Yes | `--no-network` | Accounts endpoint not called |
| `python manage.py toss_holdings_sync_dryrun --map-user-holdings --no-network` | No | No | Yes | `--no-network` | UserHolding not saved |
| `python manage.py run_scheduled_ingestion --profile=toss_no_network_preflight` | No | No | Yes | no commit flags | Runs no-network child commands |

Read-only actual network commands below are allowed only for manual smoke checks.
They must not include commit flags.

| Command | Network | Domain DB writes | Log write | Allowed purpose | Notes |
|---|---:|---:|---:|---|---|
| `python manage.py toss_token_smoke` | Yes | No | Yes | Token smoke | Access token raw value must not print |
| `python manage.py toss_quote_smoke --symbol=005930 --market=KR` | Yes | No | Yes | Quote smoke | `/api/v1/prices` only |
| `python manage.py toss_provider_quote_smoke --symbol=005930 --market=KR` | Yes | No | Yes | Provider quote smoke | Uses Toss provider directly |
| `python manage.py toss_registry_quote_smoke --symbol=005930 --market=KR` | Yes | No | Yes | Registry quote smoke | Uses `get_provider("toss")` |
| `python manage.py toss_daily_price_ingest_dryrun --symbol=005930 --market=KR --count=1` | Yes | No | Yes | DailyPrice candidate check | No `--commit` |
| `python manage.py toss_holdings_sync_dryrun --diagnose-account` | Yes | No | Yes | Account diagnostic | Calls `/api/v1/accounts` only |
| `python manage.py toss_holdings_sync_dryrun` | Yes | No | Yes | Holdings dry-run | Calls `/api/v1/holdings`; no UserHolding save |
| `python manage.py toss_holdings_sync_dryrun --symbol=005930` | Yes | No | Yes | Holdings symbol dry-run | Single symbol filter |
| `python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID>` | Yes | No | Yes | UserHolding mapping dry-run | No save without commit guards |

Scheduler wrapper actual read-only profile:

| Command | Network | Domain DB writes | Log write | Status |
|---|---:|---:|---:|---|
| `python manage.py run_scheduled_ingestion --profile=toss_readonly_smoke --allow-network` | Yes | No | Yes | Implemented but should be run only in an explicit smoke step |

## 5. Orange List: Commit Commands Requiring Explicit Approval

These commands modify production domain data. They are not routine checks.
Before running them, confirm the intended user/symbol, current row counts, and
rollback plan.

### DailyPrice Commit

| Command | Effect | Required guards | Allowed scope | Notes |
|---|---|---|---|---|
| `python manage.py toss_daily_price_ingest_dryrun --symbol=<SYMBOL> --market=KR --count=1 --commit --confirm-save` | Creates missing `DailyPrice` row or skips existing row | `--commit --confirm-save`, `count=1`, existing `Stock` | Single symbol | No `Stock` auto-create |
| `python manage.py toss_daily_price_ingest_dryrun --symbol=<SYMBOL> --market=KR --count=1 --commit --confirm-save --update-existing` | Updates existing `DailyPrice` row | all above plus `--update-existing` | Single symbol with known existing row | Use only when update is intentional |

DailyPrice commit policy:

- `Stock` must already exist.
- `count` must be `1` for smoke/manual operations.
- Existing `(stock, date)` rows skip by default.
- `--update-existing` must be explicitly approved.
- Do not run batch DailyPrice saves until batch ingestion is separately
  designed.

### UserHolding Commit

| Command | Effect | Required guards | Allowed scope | Notes |
|---|---|---|---|---|
| `python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID> --symbol=<SYMBOL> --commit --confirm-save` | Creates one eligible `UserHolding` row or skips existing row | explicit user, symbol, `--map-user-holdings --commit --confirm-save` | Single user and single symbol | No `Stock` auto-create |
| `python manage.py toss_holdings_sync_dryrun --map-user-holdings --user-id=<USER_ID> --symbol=<SYMBOL> --commit --confirm-save --update-existing` | Updates one existing active `UserHolding` row | all above plus `--update-existing` | Single user and single symbol with known existing row | Inactive rows are not reactivated |

UserHolding commit policy:

- Owner must be explicit.
- Prefer `--user-id`; do not print username/email in operation logs.
- `Stock` must already exist.
- KR/KRW positive integer quantity only.
- US holdings, unsupported currencies, fractional quantities, missing stocks,
  and inactive existing rows are skipped.
- `--update-existing` must be explicitly approved.

## 6. Red List: Forbidden Commands And Patterns

Do not run these in production.

| Pattern | Reason |
|---|---|
| Any `toss_*` command that prints `.env`, raw token, raw account, request headers, or raw response | Sensitive data exposure |
| `cat .env` or equivalent secret dump | Sensitive data exposure |
| Any command using `--commit` without `--confirm-save` expecting a save | Save must be explicitly confirmed; command should reject |
| `toss_daily_price_ingest_dryrun` with `--count` greater than `1` for smoke/manual save | Batch save not designed |
| DailyPrice save for multiple symbols in one manual smoke | Batch ingestion not designed |
| UserHolding commit without `--symbol` during smoke/manual operation | Could create or update multiple holdings |
| UserHolding commit without explicit `--user-id` or `--username` | Owner cannot be inferred |
| UserHolding commit with `--username` if it requires printing username/email in logs | Avoid identity leakage in operation reports |
| Any Stock auto-create from Toss holdings or candles | Explicitly forbidden |
| Any scheduler/cron/systemd registration command | Scheduler registration not approved |
| Any Celery/Celery Beat/APScheduler introduction | Not part of current architecture |
| Any order create/amend/cancel/history/info API command | Order APIs are not implemented and remain disabled |
| Any buying-power or sellable-quantity API expansion | Not designed or approved |
| Any automatic trading workflow | Explicitly out of scope |

## 7. Command Classification Summary

| Command | Routine allowed | Actual network allowed | Domain save allowed | Current status |
|---|---:|---:|---:|---|
| `check_toss_provider` | Yes | No | No | Allowed |
| `toss_token_smoke --no-network` | Yes | No | No | Allowed with log write |
| `toss_token_smoke` | Manual only | Yes | No | Caution |
| `toss_quote_smoke --no-network` | Yes | No | No | Allowed with log write |
| `toss_quote_smoke` | Manual only | Yes | No | Caution |
| `toss_provider_quote_smoke --no-network` | Yes | No | No | Allowed with log write |
| `toss_provider_quote_smoke` | Manual only | Yes | No | Caution |
| `toss_registry_quote_smoke --no-network` | Yes | No | No | Allowed with log write |
| `toss_registry_quote_smoke` | Manual only | Yes | No | Caution |
| `toss_daily_price_ingest_dryrun --no-network` | Yes | No | No | Allowed with log write |
| `toss_daily_price_ingest_dryrun` | Manual only | Yes | No | Caution |
| `toss_daily_price_ingest_dryrun --commit --confirm-save` | No | Yes | Yes | Approval required |
| `toss_daily_price_ingest_dryrun --commit --confirm-save --update-existing` | No | Yes | Yes | Approval required |
| `toss_holdings_sync_dryrun --no-network` | Yes | No | No | Allowed with log write |
| `toss_holdings_sync_dryrun --diagnose-account` | Manual only | Yes | No | Caution |
| `toss_holdings_sync_dryrun` | Manual only | Yes | No | Caution |
| `toss_holdings_sync_dryrun --map-user-holdings` | Manual only | Yes | No | Caution |
| `toss_holdings_sync_dryrun --map-user-holdings --commit --confirm-save` | No | Yes | Yes | Approval required |
| `toss_holdings_sync_dryrun --map-user-holdings --commit --confirm-save --update-existing` | No | Yes | Yes | Approval required |
| `run_scheduled_ingestion --list-profiles` | Yes | No | No | Allowed |
| `run_scheduled_ingestion --profile=toss_no_network_preflight` | Yes | No | No | Allowed with log write |
| `run_scheduled_ingestion --profile=toss_readonly_smoke` | Yes | No | No | Allowed as refusal/gate test |
| `run_scheduled_ingestion --profile=toss_readonly_smoke --allow-network` | Manual only | Yes | No | Explicit smoke step only |

## 8. Pre-Run Checklist

Before any actual network command:

```text
[ ] Confirm the command is in the green/yellow/orange list.
[ ] Confirm no order API is involved.
[ ] Confirm the command does not include commit flags unless approved.
[ ] Confirm terminal output will not be shared with raw secret exposure.
[ ] Confirm expected DataIngestionLog write is acceptable.
```

Before any domain save command:

```text
[ ] Confirm single symbol.
[ ] Confirm expected model count before execution.
[ ] Confirm target Stock already exists.
[ ] Confirm owner user id for UserHolding commands.
[ ] Confirm --commit --confirm-save is intentional.
[ ] Confirm --update-existing is intentional, if present.
[ ] Confirm rollback or correction plan.
```

## 9. Post-Run Checklist

After any actual network or commit command:

```text
[ ] Confirm command status.
[ ] Confirm saved/updated/skipped/failed counts.
[ ] Confirm domain model counts changed only as expected.
[ ] Confirm DataIngestionLog row was created.
[ ] Confirm no raw account/token/header/request/response data appeared.
[ ] Confirm no order API was called.
```

