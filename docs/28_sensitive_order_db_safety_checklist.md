# Sensitive Data, Order API, and DB Write Safety Checklist

## 1. Purpose

This checklist is for operators running Toss OpenAPI related commands in
production. It focuses on three safety areas:

- sensitive data exposure
- order API and automatic trading prevention
- production database write control

Use this together with:

- `docs/26_current_implementation_final_summary.md`
- `docs/27_operational_command_policy.md`
- `docs/21_toss_openapi_security_checklist.md`

## 2. Current Safety Baseline

Last-known manually verified production state:

| Model | Count |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 2 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 60+ |

Current implementation status:

| Area | Status |
|---|---|
| Toss authentication | Implemented and actual smoke verified |
| Quote read-only API | Implemented and actual smoke verified |
| DailyPrice dry-run/save/skip/update | Implemented and verified |
| DataIngestionLog write paths | Implemented and verified |
| Holdings dry-run | Implemented and actual smoke verified |
| UserHolding mapping/save/skip/update | Implemented and verified |
| Scheduler wrapper | Implemented for no-network and read-only gated profiles |
| Order API | Not implemented and disabled |
| Automatic trading | Not implemented |

## 3. Sensitive Data Checklist

Before running any Toss command:

```text
[ ] I will not print `.env` or secret manager contents.
[ ] I will not run `cat .env`.
[ ] I will not print raw client id.
[ ] I will not print raw client secret.
[ ] I will not print raw access token.
[ ] I will not print raw account id.
[ ] I will not print raw accountNo.
[ ] I will not print raw accountSeq.
[ ] I will not print raw `X-Tossinvest-Account`.
[ ] I will not print Authorization header.
[ ] I will not print request headers.
[ ] I will not print request body.
[ ] I will not print raw API response body.
```

Allowed output:

```text
[ ] configured / missing booleans
[ ] masked client/account values
[ ] endpoint names such as `/api/v1/prices`
[ ] safe status values such as success/failed/skipped
[ ] safe reason codes such as no_network or allow_network_required
[ ] counts such as candidate_count/saved_count/skipped_count
```

Forbidden in terminal output, logs, docs, tests, fixtures, and
`DataIngestionLog.metadata`:

```text
[ ] access_token
[ ] Bearer token
[ ] client_secret
[ ] accountNo raw value
[ ] accountSeq raw value
[ ] X-Tossinvest-Account raw value
[ ] Authorization raw value
[ ] full request headers
[ ] full request body
[ ] full raw response
```

## 4. DataIngestionLog Safety Checklist

Remember: `DataIngestionLog` is a production DB write.

Before running a command that writes logs:

```text
[ ] I expect a `DataIngestionLog` row to be created.
[ ] I confirmed this log write is acceptable for the operation.
[ ] I confirmed metadata will contain only safe summary fields.
[ ] I confirmed the command does not store token/secret/account/header data.
[ ] I confirmed raw API response storage is not enabled.
```

Allowed metadata examples:

```text
command
provider
symbol
market
endpoint_name
network_call
dry_run
commit_mode
candidate_count
saved_count
updated_count
skipped_count
failed_count
http_status_code
error_code
error_field
safe_message
```

Forbidden metadata examples:

```text
access_token
client_secret
accountNo
accountSeq
account_id
Authorization
X-Tossinvest-Account
headers
request_body
response_body
raw_response
```

## 5. Order API Safety Checklist

Order API status:

| Area | Status |
|---|---|
| Order create | Not implemented |
| Order amend/correct | Not implemented |
| Order cancel | Not implemented |
| Order history/info | Not implemented for current workflow |
| Automatic trading | Not implemented |
| `TOSS_ORDER_EXECUTION_ENABLED` | Must remain false unless separately approved |

Before any Toss-related operation:

```text
[ ] The command is not an order create command.
[ ] The command is not an order amend/correct command.
[ ] The command is not an order cancel command.
[ ] The command is not an order history/info expansion.
[ ] The command is not a buying-power or sellable-quantity expansion.
[ ] The command does not connect consulting output to order execution.
[ ] The command does not implement or trigger automatic trading.
[ ] `order_execution_enabled` remains false in provider checks.
```

If any order API call is observed:

```text
[ ] Stop the operation.
[ ] Treat as a P0 safety incident.
[ ] Preserve command, timestamp, and safe logs.
[ ] Do not print or copy secrets while investigating.
[ ] Re-check recent code changes for order API implementation or guard bypass.
```

## 6. DB Write Safety Checklist

Production DB writes are split into four categories:

| Category | Examples | Routine allowed |
|---|---|---:|
| No DB write | `python manage.py check`, `--list-profiles` | Yes |
| Log-only write | smoke/no-network/read-only commands | With caution |
| Domain write | DailyPrice/UserHolding commit commands | Approval required |
| Schema write | migrations | Separate approval required |

Before any command:

```text
[ ] I know whether the command writes no DB rows, log rows only, or domain rows.
[ ] I confirmed expected before counts when domain writes are possible.
[ ] I confirmed no migration/schema command is being run.
[ ] I confirmed the operation is not a batch save unless separately designed.
```

## 7. DailyPrice Save Checklist

Use only for explicit DailyPrice save/update operations.

Before running a DailyPrice commit:

```text
[ ] The command targets exactly one symbol.
[ ] `--count=1` is used.
[ ] The target `Stock` already exists.
[ ] Stock auto-create is not expected.
[ ] `--commit --confirm-save` is present.
[ ] `--update-existing` is absent unless update is explicitly intended.
[ ] Expected DailyPrice count change is known.
[ ] Existing row skip/update behavior is understood.
```

Allowed save command pattern:

```bash
python manage.py toss_daily_price_ingest_dryrun \
  --symbol=<SYMBOL> \
  --market=KR \
  --count=1 \
  --commit \
  --confirm-save
```

Allowed update command pattern:

```bash
python manage.py toss_daily_price_ingest_dryrun \
  --symbol=<SYMBOL> \
  --market=KR \
  --count=1 \
  --commit \
  --confirm-save \
  --update-existing
```

Forbidden DailyPrice patterns:

```text
[ ] commit without confirm-save
[ ] count greater than 1 for smoke/manual save
[ ] multiple symbols in a smoke/manual save
[ ] Stock auto-create
[ ] update-existing without explicit approval
```

## 8. UserHolding Save Checklist

Use only for explicit UserHolding save/update operations.

Before running a UserHolding commit:

```text
[ ] The command targets exactly one symbol.
[ ] The owner user is explicitly selected.
[ ] Prefer `--user-id`; do not print username/email in reports.
[ ] The target `Stock` already exists.
[ ] Stock auto-create is not expected.
[ ] `--map-user-holdings` is present.
[ ] `--commit --confirm-save` is present.
[ ] `--update-existing` is absent unless update is explicitly intended.
[ ] The candidate is KR/KRW with positive integer quantity.
[ ] Unsupported market/currency/fractional/missing-stock candidates will skip.
[ ] Inactive existing rows will not reactivate.
```

Allowed save command pattern:

```bash
python manage.py toss_holdings_sync_dryrun \
  --map-user-holdings \
  --user-id=<USER_ID> \
  --symbol=<SYMBOL> \
  --commit \
  --confirm-save
```

Allowed update command pattern:

```bash
python manage.py toss_holdings_sync_dryrun \
  --map-user-holdings \
  --user-id=<USER_ID> \
  --symbol=<SYMBOL> \
  --commit \
  --confirm-save \
  --update-existing
```

Forbidden UserHolding patterns:

```text
[ ] commit without explicit user
[ ] commit without symbol in smoke/manual operation
[ ] commit without map-user-holdings
[ ] commit without confirm-save
[ ] Stock auto-create
[ ] update-existing without explicit approval
[ ] username/email in operation report or DataIngestionLog metadata
[ ] account raw value in operation report or DataIngestionLog metadata
```

## 9. Scheduler Wrapper Safety Checklist

Current wrapper command:

```bash
python manage.py run_scheduled_ingestion
```

Current profiles:

| Profile | Network | Domain writes | Status |
|---|---:|---:|---|
| `toss_no_network_preflight` | No | No | Verified |
| `toss_readonly_smoke` | Yes only with `--allow-network` | No | Implemented; actual network run deferred |

Before running scheduler wrapper:

```text
[ ] I selected an explicit profile.
[ ] I understand whether the profile can call network APIs.
[ ] I understand the wrapper writes a summary DataIngestionLog row.
[ ] I understand child commands may also write DataIngestionLog rows.
[ ] I am not expecting DailyPrice/UserHolding domain saves from current profiles.
```

Forbidden scheduler patterns:

```text
[ ] registering cron/systemd/Celery schedule without separate approval
[ ] adding commit/save profiles without separate design
[ ] running network profile without `--allow-network`
[ ] expecting automatic trading behavior
```

## 10. Pre-Run Snapshot Checklist

For read-only actual network commands:

```text
[ ] Confirm no commit flags.
[ ] Confirm expected DataIngestionLog count increase.
[ ] Confirm Stock/DailyPrice/UserHolding/DataProviderStatus should not change.
```

For commit commands:

```text
[ ] Record before Stock count.
[ ] Record before DailyPrice count.
[ ] Record before UserHolding count.
[ ] Record before DataProviderStatus count.
[ ] Record before DataIngestionLog count.
[ ] Record target row snapshot if updating/skipping.
```

## 11. Post-Run Verification Checklist

After read-only actual network commands:

```text
[ ] Command status is success/skipped/expected failure.
[ ] DataIngestionLog increased as expected.
[ ] Stock count unchanged.
[ ] DailyPrice count unchanged.
[ ] UserHolding count unchanged.
[ ] DataProviderStatus count unchanged.
[ ] No sensitive raw values printed or stored.
[ ] No order API called.
```

After commit commands:

```text
[ ] saved_count/updated_count/skipped_count/failed_count match expectation.
[ ] Stock count did not increase.
[ ] DailyPrice count changed only if DailyPrice save was expected.
[ ] UserHolding count changed only if UserHolding save was expected.
[ ] DataProviderStatus count did not increase.
[ ] DataIngestionLog increased as expected.
[ ] Existing row id is unchanged for update/skip checks.
[ ] No sensitive raw values printed or stored.
[ ] No order API called.
```

## 12. Security Grep Checklist

Use after code or documentation changes:

```bash
grep -RniE "access_token\s*[:=]\s*[A-Za-z0-9_\-\.]{20,}|Bearer\s+[A-Za-z0-9_\-\.]{20,}|TOSS_INVEST_CLIENT_SECRET\s*=\s*[A-Za-z0-9_\-]{8,}|X-Tossinvest-Account\s*[:=]\s*[0-9A-Za-z_\-]{1,}" \
  data_pipeline docs stock_service .env.example deploy/production/thestock.env.example \
  2>/dev/null | head -50
```

Interpretation:

```text
[ ] No output: expected clean result.
[ ] Masked examples in docs: acceptable if clearly not real secrets.
[ ] Actual-looking token/secret/account value: stop and rotate/revoke as needed.
```

Never include `.env` in this grep target.

