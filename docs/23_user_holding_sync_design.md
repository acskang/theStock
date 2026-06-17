# UserHolding sync design

## 1. Scope

This document defines the design for mapping Toss OpenAPI holdings candidates into the current `holdings.UserHolding` model.

This step is design-only:

- No model changes.
- No migration changes.
- No command/provider code changes.
- No database writes.
- No Toss API calls.
- No order API implementation or calls.

The next implementation step should remain dry-run first. Commit support should be added only after the mapping and safety rules below are implemented and tested.

## 2. Current model and API structure

### UserHolding

Model location: `holdings.models.UserHolding`

Current fields:

- `user`: FK to `settings.AUTH_USER_MODEL`
- `stock`: FK to `stocks.Stock`
- `average_price`: `DecimalField(max_digits=14, decimal_places=2)`
- `quantity`: `PositiveIntegerField`
- `is_active`: `BooleanField(default=True)`
- `max_additional_budget`: `DecimalField(max_digits=16, decimal_places=2, default=0)`
- `risk_level`: `conservative`, `normal`, or `aggressive`
- `memo`: free text
- `created_at`, `updated_at`

Current uniqueness:

- `(user, stock)` is unique via `unique_user_stock_holding`.

Current API behavior:

- `UserHoldingViewSet.get_queryset()` is scoped to `request.user`.
- `perform_create()` assigns `user=request.user`.
- Inactive holdings are hidden by default unless requested.
- Decision/probability/consulting endpoints only resolve holdings owned by the request user.

Current downstream usage:

- `marketdata`, `stocks`, `decisions`, and `portfolio` code treat active `UserHolding` rows as user-owned portfolio inputs.
- `data_pipeline.services.resolve_target_stocks()` uses active holdings to choose target stocks when no explicit stock list is supplied.

### Stock

Model location: `stocks.models.Stock`

Relevant fields:

- `code`: unique stock code
- `name`
- `market`: current choices are `KOSPI`, `KOSDAQ`, `KONEX`, `ETF`, `ETN`
- `is_active`

Important limitation:

- The current `Stock.market` choices are Korea-oriented. US market names from Toss holdings cannot be represented without either pre-mapped stock rows or a future schema expansion.

## 3. Toss holdings candidate structure

The current Toss holdings dry-run normalizes `/api/v1/holdings` items into candidates with these safe fields:

- `symbol`
- `name`
- `market_country`
- `currency`
- `quantity`
- `last_price`
- `average_purchase_price`
- `purchase_amount`
- `market_value`
- `market_value_after_cost`
- `profit_loss_amount`
- `profit_loss_amount_after_cost`
- `profit_loss_rate`
- `profit_loss_rate_after_cost`
- `daily_profit_loss_amount`
- `daily_profit_loss_rate`
- `source=toss`

Account identifiers are intentionally not included in candidates.

## 4. Main schema gap

The current `UserHolding` model can store only:

- owner user
- stock
- average price
- positive integer quantity
- active/manual portfolio settings

It cannot store these Toss concepts:

- broker account dimension
- account alias/source
- currency
- market country
- last price
- market value
- purchase amount
- profit/loss values
- fractional quantity
- provider/source attribution

The most important blocker is `quantity = PositiveIntegerField`. Toss holdings may include US fractional quantities, so commit sync must not blindly save every Toss candidate into the current model.

## 5. Owner mapping policy

Toss account ownership must not be inferred as a Django user.

Future sync command policy:

- Dry-run may run without an owner and only print candidate-to-model mapping status.
- Any commit mode must require an explicit owner selector.
- Supported owner selectors should be one of:
  - `--user-id`
  - `--username`
  - optionally `--email` if the project already accepts email identity elsewhere
- If no owner is supplied in commit mode, fail before calling save logic.
- Never default to the first user, first superuser, or a legacy user.
- Validate that the user exists before any save.

Recommended safe reason values:

- `owner_required`
- `owner_not_found`
- `owner_ambiguous`

## 6. Stock mapping policy

Initial mapping should be conservative:

1. Match Toss `candidate.symbol` to existing `Stock.code`.
2. Do not auto-create `Stock`.
3. If no `Stock` exists, skip the candidate with `stock_not_found`.
4. Do not use `candidate.name` alone for automatic matching.
5. Do not hard-fail the whole batch for one missing stock.

Market handling:

- For `market_country=KR`, `Stock.code == symbol` is the primary key.
- Existing `Stock.market` may be `KOSPI`, `KOSDAQ`, `ETF`, etc.; Toss `market_country=KR` is not enough to infer that field.
- For `market_country=US`, current `Stock.market` choices do not fit. US holdings should be skipped unless a compatible stock master strategy is added.

Recommended skip reasons:

- `stock_not_found`
- `unsupported_market_country`
- `stock_inactive`

## 7. Field mapping policy

For candidates that are safe to map to the current schema:

| Toss candidate | UserHolding field | Policy |
| --- | --- | --- |
| explicit command owner | `user` | Required for commit |
| `symbol` | `stock` | Existing `Stock.code` lookup only |
| `average_purchase_price` | `average_price` | Decimal, quantized to 2 places |
| `quantity` | `quantity` | Only positive whole numbers |
| candidate present | `is_active` | `True` for new rows |
| none | `risk_level` | Keep default for new rows |
| none | `max_additional_budget` | Keep default for new rows |
| none | `memo` | Preserve existing; do not write account data |

Not stored in the current schema:

- `currency`
- `market_country`
- `last_price`
- `purchase_amount`
- `market_value`
- profit/loss fields
- account identifiers
- provider/source

Unsupported quantity policy:

- If `quantity` is missing, zero, negative, non-numeric, or fractional, do not save to the current `UserHolding` schema.
- For fractional values, use `unsupported_fractional_quantity`.
- This avoids silently truncating broker holdings.

## 8. Duplicate and update policy

The current uniqueness rule is `(user, stock)`.

New row:

- Create only with `--commit --confirm-save`.
- Only if owner exists, stock exists, and quantity is a positive whole number.

Existing active row:

- Default behavior should be skip.
- `--update-existing` is required to update broker-derived values.
- On update, change only:
  - `average_price`
  - `quantity`
  - `is_active=True` if an explicit reactivation policy is accepted
- Preserve:
  - `risk_level`
  - `max_additional_budget`
  - `memo`

Existing inactive row:

- Default behavior should be skip.
- Reactivation should require a separate explicit flag such as `--reactivate-existing`.
- Do not reactivate in the first commit implementation.

Missing from Toss:

- Do not delete or deactivate existing `UserHolding` rows in the initial sync.
- A future `--deactivate-missing` mode can be designed after account dimension and owner policy are settled.

## 9. Multi-account policy

Current `UserHolding` cannot represent multiple broker accounts because there is no account field.

Initial sync policy:

- Continue using the current account selection logic for fetching holdings.
- Do not store account identifiers.
- Do not combine multiple accounts into one `UserHolding` commit path automatically.
- If future support for multiple accounts is required, add a schema design first.

Potential future schema options:

- Add a separate broker-position model with account alias, provider, symbol, currency, quantity, and valuation fields.
- Keep `UserHolding` as the user-facing aggregate/manual model.
- Optionally derive or update `UserHolding` from broker positions in a second step.

## 10. KR/US and currency policy

KR holdings:

- Can be mapped to current `Stock` rows if `Stock.code` exists.
- Currency should be expected as `KRW`, but the current model cannot store it.

US holdings:

- Do not commit to the current `UserHolding` schema until fractional quantity and US stock master support are designed.
- Dry-run should report `unsupported_market_country` or `unsupported_fractional_quantity` as appropriate.

Currency:

- Do not convert currencies in the first implementation.
- Do not mix KRW and USD into the current `average_price` without an explicit currency model.

## 11. DataIngestionLog policy

Future UserHolding sync commands should record only safe summaries.

Recommended mapping:

- `provider_name=toss`
- `job_type=toss_holdings_sync_dryrun` for dry-run mapping
- `job_type=toss_holdings_sync` if a separate commit command is later added
- `target_type=holdings`
- `endpoint_name=/api/v1/holdings`
- `target_symbol` only when a single symbol filter is used
- `status=success`, `failed`, `skipped`, or `partial`
- `candidate_count`: Toss candidate count
- `saved_count`: created `UserHolding` count
- `updated_count`: updated `UserHolding` count
- `skipped_count`: candidates intentionally skipped
- `failed_count`: candidates that failed validation or save

Safe metadata only:

- command name
- provider
- symbol filter
- candidate count
- saved/updated/skipped/failed counts
- safe skip reason categories
- dry-run and commit mode

Never store:

- accountNo
- accountSeq
- account header value
- access token
- client secret
- authorization header
- request headers/body
- raw API response

## 12. Command staging plan

### Step 20E: UserHolding sync dry-run mapping

Add mapping analysis only.

Expected behavior:

- Fetch Toss holdings candidates.
- Optionally accept `--user-id` or `--username` to compare with existing holdings.
- Do not save.
- Print candidate mapping summary:
  - `mapped`
  - `stock_not_found`
  - `unsupported_fractional_quantity`
  - `unsupported_market_country`
  - `existing_skip`
  - `would_create`
  - `would_update`
- Write `DataIngestionLog` summary.

### Step 20F: UserHolding commit implementation

Add save support only under all required guards:

- `--commit`
- `--confirm-save`
- explicit owner
- no unsupported quantities
- existing `Stock`

Default duplicate behavior:

- existing row skipped
- `--update-existing` required for update

### Step 20G: commit/skip/update smoke

Verify:

- new row save
- existing row skip
- `--update-existing`
- no Stock auto-create
- no account/raw secret leakage
- no order API calls

### Later schema design

Before syncing US/fractional holdings or account-level broker positions, design one of:

- Decimal quantity migration for `UserHolding`
- separate `BrokerHolding` or `BrokerPosition` model
- currency and account alias fields
- market-country aware stock master

## 13. Security and privacy rules

The sync path must never print, log, or store:

- `.env` contents
- client id or client secret
- access token
- authorization header
- account number
- account sequence
- account header value
- request body/header
- raw API response

Allowed safe diagnostics:

- account value shape
- account count
- account type labels
- selected account source
- fallback used boolean
- candidate counts
- field-level mapping outcomes

Order APIs remain out of scope and disabled.

## 14. Open decisions

- Whether `UserHolding.quantity` should become decimal for fractional holdings.
- Whether broker holdings should be stored in a separate model instead of overloading `UserHolding`.
- Whether `UserHolding` should remain a manual user portfolio model and broker sync should only propose changes.
- How US stock symbols and markets should be represented in `Stock`.
- Whether missing broker candidates should ever deactivate existing holdings, and under what explicit flag.
