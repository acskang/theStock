# Next Feature Priority Decision

## 1. Purpose

This document decides the next real feature priority for theStock after the
current Toss OpenAPI integration, safety policy, and command operation documents.

This is a planning document only. It does not add code, change settings, run
commands, write database rows, or register a scheduler.

## 2. Current Baseline

Implemented and verified:

- Toss authentication smoke.
- Toss quote smoke through direct, provider, and registry paths.
- Toss candle based DailyPrice dry-run.
- DailyPrice new save, existing skip, and `--update-existing`.
- DataIngestionLog schema extension, migration, API/admin exposure, and writer.
- DataIngestionLog writes for no-network, actual network, dry-run, commit, skip,
  and update paths.
- Toss accounts diagnostic.
- Toss holdings dry-run.
- UserHolding mapping dry-run.
- UserHolding new save, existing skip, and `--update-existing`.
- Scheduler wrapper command.
- No-network scheduler profile.
- Read-only scheduler profile with `--allow-network` gate.
- Operational allow/deny command policy.
- Sensitive data, order API, and DB write safety checklist.

Last-known production state:

| Model | Count |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 2 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 60+ |

Safety baseline:

- Order APIs are not implemented.
- Order execution remains disabled.
- Automatic trading is not implemented.
- Sensitive raw values are not intentionally printed or stored.
- Current production writes are manual and guarded.

## 3. Decision Criteria

The next feature should improve product value without weakening the current
safety posture.

Priority criteria:

| Criterion | Meaning |
|---|---|
| Product value | Improves actual theStock user workflows |
| Safety | Low risk of unintended trading, secret exposure, or broad DB writes |
| Operational readiness | Easy to verify with existing commands/logging |
| Data leverage | Uses already integrated Toss data effectively |
| Blast radius | Keeps changes narrow and reversible |
| Dependency fit | Does not require large schema or deployment changes first |

## 4. Candidate Options

| Candidate | Product value | Safety | Effort | Main risk |
|---|---:|---:|---:|---|
| A. DailyPrice batch ingestion design and dry-run | High | High | Medium | Batch scope must be controlled |
| B. UserHolding sync UX/admin review flow | High | Medium | Medium | User/account ownership and privacy |
| C. DataProviderStatus integration for Toss | Medium | High | Low | Duplicating DataIngestionLog semantics |
| D. Scheduler wrapper read-only smoke execution | Medium | High | Low | Actual network calls must be operator-gated |
| E. Scheduler commit profile | High | Medium/Low | High | Domain writes could run unattended |
| F. US/fractional holdings support | Medium | Medium | High | Schema gap and currency semantics |
| G. Order API / automatic trading | Low for current phase | Very low | Very high | Safety, compliance, irreversible actions |

## 5. Recommended Next Feature

Recommended next feature:

```text
Step 22: DailyPrice batch ingestion design and dry-run implementation
```

Why this is the best next step:

- It directly improves theStock's core data quality for analysis and consulting.
- The DailyPrice single-symbol flow is already verified end to end.
- It avoids account ownership and privacy complexity.
- It avoids order execution entirely.
- It can start as dry-run only.
- It can reuse existing `DailyPrice`, `Stock`, and `DataIngestionLog` models.
- It can be built with conservative allowlists and count limits.
- It prepares the system for later scheduler automation without immediately
  enabling unattended DB writes.

Recommended scope:

```text
DailyPrice batch dry-run first.
No automatic Stock creation.
No commit mode in the first batch implementation.
No scheduler registration.
No order API.
```

## 6. Proposed Step 22 Scope

### 6.1 Batch Input

Start with one or more safe input modes:

| Input mode | Priority | Notes |
|---|---:|---|
| explicit `--symbols=005930,035250` | High | Most controllable |
| `--from-user-holdings --user-id=<USER_ID>` | Medium | Uses existing active holdings |
| `--all-active-stocks` | Low | Too broad for first batch smoke |

Initial recommended command:

```bash
python manage.py toss_daily_price_batch_dryrun --symbols=005930,035250 --market=KR --count=1 --no-network
python manage.py toss_daily_price_batch_dryrun --symbols=005930,035250 --market=KR --count=1
```

### 6.2 Batch Output

Dry-run output should include:

```text
status
provider
network_call
dry_run
symbol_count
candidate_count
per_symbol status
per_symbol candidate date
per_symbol existing row status
skipped_count
failed_count
safe_reason
```

### 6.3 DataIngestionLog

Record one summary row per batch command:

```text
provider_name=toss
job_type=daily_price_batch_dryrun
target_type=daily_price
endpoint_name=/api/v1/candles
network_call=true/false
dry_run=true
commit_mode=not_requested
candidate_count=<total candidates>
saved_count=0
updated_count=0
skipped_count=<safe skips>
failed_count=<failures>
metadata.command=toss_daily_price_batch_dryrun
metadata.symbol_count=<count>
metadata.params_shape=symbols,count,market
```

Do not store full raw response bodies or request headers.

### 6.4 Guardrails

First implementation should enforce:

- `--count=1` default.
- Small maximum symbol limit, for example 5 or 10.
- `--commit` not supported in the first batch step.
- Existing `Stock` required.
- No `Stock` auto-create.
- No `--update-existing`.
- No scheduler integration.
- No order API.

## 7. Why Not Scheduler Commit Next

Scheduler commit automation is not the right immediate next step because:

- Current saves are intentionally manual and explicit.
- Batch ingestion is not yet designed.
- Unattended domain writes need stricter operational rollback and alerting.
- `DataProviderStatus` is not connected to Toss health yet.
- Rate limit and partial failure policy should be proven in batch dry-run first.

The scheduler wrapper should remain limited to:

- no-network preflight
- read-only smoke gated by `--allow-network`

until batch dry-run behavior is stable.

## 8. Why Not UserHolding Sync Next

UserHolding save/update is already verified, but broadening it is less urgent
than DailyPrice data coverage.

Reasons to defer:

- Current `UserHolding` has no account dimension.
- US/fractional holdings are not supported by the current schema.
- Mapping broker holdings to user-owned portfolio rows can affect user-facing
  recommendations directly.
- Additional UX/admin confirmation may be needed before broader sync.

Recommended later direction:

```text
UserHolding sync review screen or admin preview before broad commit automation.
```

## 9. Why Not Order API

Order API work should remain out of scope.

Reasons:

- It is not implemented.
- It is explicitly disabled.
- It introduces irreversible financial actions.
- It would require separate authorization, UX confirmation, audit logging,
  failure handling, and compliance review.
- theStock's current value is better improved by reliable market and portfolio
  data, not trading execution.

Current policy:

```text
Do not implement order create/amend/cancel.
Do not add automatic trading.
Do not connect consulting results to orders.
Keep TOSS_ORDER_EXECUTION_ENABLED=false.
```

## 10. Secondary Priorities

After Step 22 batch dry-run:

| Priority | Feature | Reason |
|---:|---|---|
| 2 | DataProviderStatus integration for Toss | Adds provider health observability with low blast radius |
| 3 | Scheduler read-only smoke runbook | Operationalizes current gated wrapper safely |
| 4 | DailyPrice batch commit with strict approval | Converts stable dry-run into controlled data refresh |
| 5 | UserHolding sync review/admin workflow | Reduces risk before broader holdings sync |
| 6 | US/fractional holdings schema design | Needed before US holdings can be stored correctly |

## 11. Recommended Immediate Plan

Next concrete plan:

1. Write Step 22 design for DailyPrice batch ingestion.
2. Implement dry-run-only batch command.
3. Add fake provider tests for all success/partial/failure paths.
4. Verify no DB domain writes in batch dry-run.
5. Run a small actual dry-run with 2 symbols.
6. Only after that, design batch commit separately.

Non-goals for the next step:

- No commit mode.
- No scheduler registration.
- No automatic Stock creation.
- No holdings sync expansion.
- No order API.

## 12. Final Decision

The next real feature should be:

```text
DailyPrice batch ingestion dry-run, followed by controlled actual dry-run smoke.
```

This is the safest path that increases product value, uses the verified Toss
integration, improves analysis data coverage, and preserves the current
no-order/no-automation safety posture.

## 13. Architecture Re-prioritization Note

기존 Step 22 DailyPrice batch ingestion dry-run 우선순위는 데이터 품질 관점에서 여전히 유효하다. 이 문서의 기존 판단은 삭제하지 않는다.

다만 일반 사용자 Toss 연동 서비스로 확장하려면 user-account/credential ownership 문제가 선행되어야 한다. 따라서 다음 큰 아키텍처 작업은 `docs/54_technical_architecture_and_toss_credential_design.md` 기준 사용자별 Toss credential 보안 기반 설계/검증이다.

정리:

- DailyPrice batch 작업은 credential architecture와 충돌하지 않는다.
- DailyPrice batch는 병행 또는 후속으로 재검토 가능하다.
- 일반 사용자 holdings/order history/portfolio 자동 연결은 사용자별 Toss credential 1:1 구조 이후에 진행한다.
- 전역 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT_ID`는 일반 사용자 데이터 조회에 사용하지 않는다.
- 주문 API/자동매매/매수매도 추천 실행은 계속 제외한다.

새 architecture 선행 검증 후보:

1. application-level encrypted field 후보 조사.
2. SQLCipher와 Django 5.x 적용 가능성 조사.
3. `CREDENTIAL_ENCRYPTION_KEY`, `CREDENTIAL_HASH_PEPPER`, `SQLCIPHER_DATABASE_KEY` 운영 정책 설계.
4. Toss `client_id`/`client_secret`이 사용자 개인별 credential인지 서비스 앱 단위 credential인지 확인.
