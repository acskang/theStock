# Portfolio / Holding / Decision Structure Diagnosis

## 1. Purpose

This document diagnoses the current Portfolio, Holding, and Decision screen/API
structure after the Toss OpenAPI, DailyPrice, UserHolding, DataIngestionLog, and
batch dry-run work.

This is a diagnosis document only. It does not change code, settings,
migrations, database schema, scheduler registration, or runtime behavior.

## 2. Current Verified Baseline

Last checked in this diagnosis:

| Model | Count / State |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 2 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 83 |
| `AveragingDecision` | 0 |
| `AveragingProbabilityRecord` | 0 |
| `HoldingConsultRecord` | 0 |
| `portfolio.Transaction` | 248 |

Current saved `UserHolding` row:

| Field | Value |
|---|---|
| `user_id` | 6 |
| `stock_code` | 035250 |
| `stock_name` | 강원랜드 |
| `quantity` | 2 |
| `average_price` | 15116.50 |
| `is_active` | true |

Safety baseline:

- Toss token, quote, candle, accounts, and holdings read paths were verified.
- DailyPrice single-symbol save/skip/update was verified.
- DailyPrice batch dry-run was verified through explicit symbols and
  `--from-stock-db`.
- UserHolding save/skip/update was verified.
- Order APIs remain unimplemented and disabled.
- Automatic trading is not implemented.
- This diagnosis did not call Toss APIs and did not write domain rows.

## 3. URL And Surface Map

### 3.1 Web Screens

| URL | View | Template | Auth | Current role |
|---|---|---|---|---|
| `/` | `portfolio.views.landing_page` | `portfolio/landing.html` | Public | Landing page |
| `/workspace/` | `portfolio.views.dashboard` | `portfolio/dashboard.html` | Not decorated | Legacy transaction dashboard |
| `/transactions/` | `portfolio.views.transaction_list` | `portfolio/transaction_list.html` | Not decorated | Legacy transaction list |
| `/upload/` | `portfolio.views.upload_csv` | `portfolio/upload.html` | Not decorated | CSV import for legacy transactions |
| `/analysis/` | `portfolio.views.analysis_view` | `portfolio/analysis.html` | Not decorated | Legacy transaction-based retrospective analysis |
| `/consulting/holdings/` | `portfolio.views.consulting_holding_list` | `portfolio/holding_list.html` | `login_required` | UserHolding-based consulting entry |
| `/consulting/holdings/<pk>/` | `portfolio.views.holding_consult_page` | `portfolio/holding_consult.html` | `login_required` and owner scoped | UserHolding consulting detail |
| `/operations/data-pipeline/` | `portfolio.views.data_pipeline_status_page` | `portfolio/data_pipeline_status.html` | `login_required` | Data pipeline operator view |
| `/operations/data-pipeline/stocks/<code>/` | `portfolio.views.data_pipeline_stock_detail_page` | `portfolio/data_pipeline_stock_detail.html` | `login_required` | Stock data quality/log detail with consult link |

### 3.2 API Endpoints

| Prefix / Path | View | Method shape | Owner scope | Writes |
|---|---|---|---|---|
| `/api/holdings/` | `UserHoldingViewSet` | CRUD | Current user only | Creates/updates `UserHolding` through API |
| `/api/holdings/<id>/evaluate/` | `HoldingEvaluateAPIView` | POST | Current user only | Creates `AveragingDecision` |
| `/api/holdings/<id>/decisions/` | `HoldingDecisionHistoryAPIView` | GET | Current user only | No |
| `/api/holdings/<id>/probability/` | `HoldingProbabilityAPIView` | POST | Current user only | Creates `AveragingProbabilityRecord` |
| `/api/holdings/<id>/probabilities/` | `HoldingProbabilityHistoryAPIView` | GET | Current user only | No |
| `/api/holdings/<id>/consult/` | `HoldingConsultAPIView` | POST | Current user only | Creates `HoldingConsultRecord` |
| `/api/holdings/<id>/consults/` | `HoldingConsultHistoryAPIView` | GET | Current user only | No |
| `/api/decisions/averaging-decisions/` | `AveragingDecisionViewSet` | Read-only | Current user's holdings | No |
| `/api/decisions/probability-records/` | `AveragingProbabilityRecordViewSet` | Read-only | Current user's holdings | No |
| `/api/decisions/consult-records/` | `HoldingConsultRecordViewSet` | Read-only | Current user's holdings | No |
| `/api/decisions/risk-events/` | `RiskEventViewSet` | Read/write | Authenticated read, staff write | Writes only for staff |

## 4. Model Structure

### 4.1 UserHolding

`holdings.models.UserHolding` is the canonical current holding model.

Fields:

- `user`
- `stock`
- `average_price`
- `quantity`
- `is_active`
- `max_additional_budget`
- `risk_level`
- `memo`
- `created_at`
- `updated_at`

Constraints and behavior:

- Unique constraint: `(user, stock)`.
- Default ordering: `-updated_at`, `-id`.
- `quantity` is `PositiveIntegerField`.
- No currency field.
- No account field.
- No broker/source field.
- `total_invested_amount` is computed as `average_price * quantity`.

Implication for Toss holdings:

- Current model fits KR/KRW integer-quantity holdings.
- US holdings, fractional quantity, multiple brokerage accounts, and per-account
  position tracking are not representable without a schema extension.

### 4.2 Decision Models

Decision records are derived from `UserHolding`.

| Model | Purpose | Created by |
|---|---|---|
| `AveragingDecision` | 물타기/추가매수 판단 record | `/api/holdings/<id>/evaluate/` |
| `AveragingProbabilityRecord` | Scenario probability record | `/api/holdings/<id>/probability/` |
| `HoldingConsultRecord` | Combined consulting report record | `/api/holdings/<id>/consult/` |
| `RiskEvent` | Stock risk event data | Staff/API/admin/data pipeline paths |

The current operating DB has no decision/probability/consult records yet.

### 4.3 Legacy Portfolio Models

`portfolio.Transaction` and `portfolio.StockSymbol` remain separate from
`UserHolding`.

`portfolio.Transaction` powers:

- legacy dashboard
- transaction list/create/edit/delete
- CSV upload
- retrospective analysis

Legacy transactions can sync into `UserHolding` through
`holdings.services.sync_service.sync_all_holdings_for_legacy_user`.

Important behavior:

- Legacy sync uses `settings.LEGACY_PORTFOLIO_USERNAME`.
- Legacy sync can create, update, and deactivate `UserHolding` rows.
- Several legacy portfolio views call this sync after transaction changes.
- This is independent of the Toss holdings sync command.

## 5. Screen Behavior Diagnosis

### 5.1 Consulting Holding List

The `/consulting/holdings/` page:

- Requires login.
- Loads `UserHolding` rows for `request.user`.
- Splits rows into active and inactive sections.
- Computes latest price from `marketdata.services.price_service.get_latest_price`.
- Shows average price, current price, loss rate, budget, quantity, and invested
  amount.
- Links active holdings to the consulting detail page.

Current production implication:

- The Toss-created holding is visible only when logged in as `user_id=6`.
- The page does not directly show Toss account/source information because
  `UserHolding` has no source/account fields.

### 5.2 Consulting Detail Page

The `/consulting/holdings/<pk>/` page:

- Requires login.
- Enforces owner scope through `UserHolding.objects.filter(user=request.user)`.
- Embeds a JSON config containing:
  - holding id
  - consultability
  - consult API URL
  - consult history API URL
  - holding list URL
- Loads `portfolio/static/portfolio/js/holding_consult.js`.

The JavaScript automatically calls:

```text
POST /api/holdings/<id>/consult/
```

on page load when the holding is consultable.

Operational implication:

- The detail page is not purely read-only.
- Opening a consultable holding detail page triggers a POST request and can
  create a `HoldingConsultRecord`.
- The "다시 분석" button also POSTs to the same consult API and can create
  additional consult records.

### 5.3 Data Pipeline Stock Detail Link

The stock detail operator page can link to a consult page when:

- the logged-in user owns an active `UserHolding`
- the holding stock matches the detail stock
- quantity is greater than 0

This creates a useful bridge from data quality diagnostics to the user-facing
consulting surface, but it is still owner-scoped.

## 6. API Behavior Diagnosis

### 6.1 Owner Scope

The current owner-scope posture is good:

- `UserHoldingViewSet.get_queryset()` filters by `request.user`.
- Holding action APIs fetch holdings with both `id` and `user`.
- Decision history APIs validate holding ownership first.
- Decision read-only ViewSets filter through `holding__user=self.request.user`.
- Tests cover other-user access returning 404 or filtered results.

### 6.2 Write Behavior

The APIs are not all read-only:

| Endpoint | Write behavior |
|---|---|
| `POST /api/holdings/` | Creates `UserHolding` for current user |
| `PATCH/PUT /api/holdings/<id>/` | Can update holding fields allowed by serializer |
| `POST /api/holdings/<id>/evaluate/` | Creates `AveragingDecision` |
| `POST /api/holdings/<id>/probability/` | Creates `AveragingProbabilityRecord` |
| `POST /api/holdings/<id>/consult/` | Creates `HoldingConsultRecord` |

This is expected behavior, but it matters for smoke testing and operations:

- Do not use consulting detail pages as read-only smoke checks unless creating a
  consult record is acceptable.
- For read-only checks, prefer list/history endpoints or inspect the page
  without triggering JavaScript.

### 6.3 Permissions

Observed permission posture:

- Holding APIs require authentication by default through DRF/project defaults or
  explicit `IsAuthenticated` on action APIs.
- `RiskEventViewSet` uses `AuthenticatedReadOnlyOrStaffWrite`.
- Web consulting pages use `login_required`.

Potential follow-up:

- `UserHoldingViewSet` does not declare `permission_classes` locally. If the
  project default is changed later, holding CRUD behavior may change. Consider
  making `IsAuthenticated` explicit in a future hardening step.

## 7. Data Dependency Diagnosis

Decision and consulting quality depends on these data areas:

| Data area | Source / model | Current status |
|---|---|---|
| Holding position | `UserHolding` | 1 real row exists |
| Latest price | `DailyPrice` via `get_latest_price` | Only 2 rows currently exist |
| Price history | `DailyPrice` | Sparse for many stocks |
| Investor flow | `InvestorFlow` | Not diagnosed in this step |
| Market regime | market index data/services | Not diagnosed in this step |
| Risk events | `RiskEvent` | No current production count checked here |
| Financial/quality data | snapshots/services | Not central to this diagnosis |

Current practical consequence:

- UserHolding is now connected to real Toss holdings.
- Consulting output may be degraded or data-insufficient until DailyPrice and
  related market/risk datasets are broadened.
- DailyPrice batch dry-run is therefore a good prerequisite for improving the
  consulting screen's usefulness.

## 8. Tests And Coverage Observed

Existing tests cover:

- UserHolding model creation and `(user, stock)` uniqueness.
- UserHolding API owner scoping.
- Inactive holdings excluded by default and included by opt-in query.
- Evaluate endpoint decision creation and other-user 404.
- Probability endpoint and consult endpoint persistence.
- Consult history/current-user scoping.
- Consulting list page login requirement and render.
- Consulting detail page owner requirement and API config render.
- Data pipeline stock detail page linking to consult page when a related holding
  exists.
- Legacy transaction to UserHolding sync behavior.

Gaps to consider later:

- Explicit `UserHoldingViewSet.permission_classes` regression test if default
  permissions are ever changed.
- Browser-level test that opening consult detail creates exactly one consult
  record on initial load.
- UX test for current production-like sparse data where latest price is missing
  for the saved holding.
- Tests for coexistence of Toss-created holdings and legacy sync-created
  holdings for the same user/stock.

## 9. Main Findings

### Finding 1: The consult detail page creates records on page load

The detail page looks like a report screen, but JavaScript automatically POSTs
to `/api/holdings/<id>/consult/` for consultable holdings.

Impact:

- Opening the page can create `HoldingConsultRecord` rows.
- Reopening or refreshing can create additional records.

Recommendation:

- Treat consult detail page access as a write operation.
- Consider a future UX change that separates "view latest report/history" from
  "run new analysis".

### Finding 2: Legacy portfolio and UserHolding are both active but separate

Legacy `Transaction` data still drives dashboard, upload, and retrospective
analysis. New Toss holdings populate `UserHolding`, which drives consulting.

Impact:

- Operators may see different portfolio views depending on whether they are
  looking at legacy transaction screens or the UserHolding consulting screen.
- Legacy transaction edits can sync and modify UserHolding rows for the legacy
  user.

Recommendation:

- Keep a clear distinction between "legacy transaction portfolio" and
  "UserHolding consulting portfolio" in operations and UI copy.
- Before broader Toss holdings sync, decide whether Toss holdings should replace,
  merge with, or coexist with legacy sync for each user.

### Finding 3: UserHolding schema is intentionally narrow

Current `UserHolding` has no currency, account, provider/source, or fractional
quantity support.

Impact:

- KR/KRW integer positions work.
- US/fractional/multi-account positions cannot be faithfully represented.

Recommendation:

- Keep current Toss UserHolding commit scope limited to KR/KRW positive integer
  quantity and existing Stock rows.
- Defer US/fractional/multi-account sync until a schema design is approved.

### Finding 4: Decision APIs are owner-scoped and covered by tests

The current API access pattern consistently filters decision and consult records
through the authenticated user's holdings.

Impact:

- Cross-user leakage risk appears controlled in the current implementation.

Recommendation:

- Preserve this owner-scope pattern in any future portfolio or analytics API.

### Finding 5: Sparse DailyPrice data limits consulting quality

The current DB has 17 stocks but only 2 DailyPrice rows.

Impact:

- Consult outputs may return data-insufficient or degraded results for many
  holdings.

Recommendation:

- Continue DailyPrice batch dry-run and then design a guarded batch commit path
  before investing heavily in new consulting UI.

## 10. Recommended Next Steps

Suggested order:

1. Keep order APIs disabled and out of scope.
2. Decide whether consult detail should auto-run or show latest report first.
3. Improve DailyPrice coverage through a guarded batch commit design.
4. Add a small operator note to the UI/runbook: consult detail page creates
   consult records.
5. Design coexistence policy for legacy transaction sync and Toss holdings sync.
6. Only after data coverage improves, revisit portfolio dashboard unification.

## 11. Verification Performed

Commands run during this diagnosis:

```bash
python manage.py check
python manage.py shell -c "<safe model count queries>"
```

Result:

- `python manage.py check`: OK.
- Safe count queries completed.
- No Toss API calls were made.
- No order API calls were made.
- No domain data writes were performed.

