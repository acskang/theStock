# Portfolio and Simulation API Reference

## 1. 목적

이 문서는 구현과 수동 smoke 검증이 완료된 Portfolio Summary API, Portfolio Summary HTML 화면, Additional Buy Simulation API의 운영 기준을 정리한다.

이 기능들은 저장된 보유종목과 일봉 데이터 기반의 요약 및 계산 기능이다. 주문 실행, 자동매매, 투자 권유, 수익 보장 기능이 아니다.

## 2. 현재 구현 상태 요약

구현 완료 항목:

- `portfolio/services.py`
  - `build_portfolio_summary(user, include_inactive=False)`
- `GET /api/portfolio/summary/`
  - `PortfolioSummaryAPIView`
  - `PortfolioSummarySerializer`
  - `IsAuthenticated`
- `GET /portfolio/summary/`
  - `portfolio_summary_page`
  - `portfolio/summary.html`
  - `login_required`
- `decisions/services/additional_buy_simulation_service.py`
  - `build_additional_buy_simulation(...)`
  - `AdditionalBuySimulationError`
- `POST /api/holdings/{id}/additional-buy-simulation/`
  - `UserHoldingViewSet.additional_buy_simulation`
  - `AdditionalBuySimulationInputSerializer`

최근 수동 검증 기준 데이터:

- `Stock count`: 17
- `DailyPrice count`: 3
- `UserHolding count`: 1
- `DataProviderStatus count`: 0
- `DataIngestionLog count`: 85
- 검증 종목: `035250` 강원랜드
- 최신 저장 종가: `16340.00`

## 3. 공통 안전 정책

Portfolio Summary API, Portfolio Summary 화면, Additional Buy Simulation API는 모두 다음 정책을 따른다.

- DB-only 기능이다.
- Toss API를 호출하지 않는다.
- DB write를 하지 않는다.
- `DataIngestionLog`를 생성하지 않는다.
- 주문 API를 호출하지 않는다.
- 자동매매를 하지 않는다.
- 주문 생성, 정정, 취소 기능을 제공하지 않는다.
- Additional Buy Simulation 결과는 계산 전용이다.
- 매수/매도 추천이나 수익 보장이 아니다.
- 응답과 화면에 username, email, user id, 계좌번호, account sequence, token, header, raw response를 포함하지 않는다.
- `UserHolding` 조회는 `request.user` 기준 owner scope를 따른다.

## 4. Portfolio Summary API

Endpoint:

```text
GET /api/portfolio/summary/
```

Authentication:

```text
IsAuthenticated
```

Owner scope:

- `request.user`의 `UserHolding`만 조회한다.
- 다른 사용자의 보유종목은 응답에 포함하지 않는다.
- user id query parameter는 지원하지 않는다.

Query parameters:

```text
include_inactive=true
```

기본 정책:

- `include_inactive` 기본값은 `false`이다.
- 기본 응답에는 `is_active=True`인 `UserHolding`만 포함한다.
- inactive 보유종목은 `include_inactive=true`를 명시한 경우에만 포함한다.

Data source:

- `holdings.models.UserHolding`
- `stocks.models.Stock`
- `marketdata.models.DailyPrice`

사용하지 않는 data source:

- Toss live quote
- Toss holdings API
- Toss account API
- Order API
- raw API response

Example response:

```json
{
  "as_of": "2026-06-16",
  "holding_count": 1,
  "active_holding_count": 1,
  "priced_holding_count": 1,
  "missing_price_count": 0,
  "totals": {
    "total_invested_amount_all": "30233.00",
    "total_invested_amount_priced": "30233.00",
    "total_market_value_priced": "32680.00",
    "total_profit_loss_amount_priced": "2447.00",
    "total_profit_loss_rate_priced": "8.09"
  },
  "holdings": [
    {
      "stock": {
        "code": "035250",
        "name": "강원랜드",
        "market": "KOSPI"
      },
      "quantity": 2,
      "average_price": "15116.50",
      "latest_price": "16340.00",
      "latest_price_date": "2026-06-16",
      "invested_amount": "30233.00",
      "market_value": "32680.00",
      "profit_loss_amount": "2447.00",
      "profit_loss_rate": "8.09",
      "risk_level": "medium",
      "max_additional_budget": "0.00",
      "is_active": true,
      "price_status": "priced"
    }
  ],
  "warnings": []
}
```

주의:

- 위 예시는 사용자 식별자나 계좌 식별자를 포함하지 않는다.
- `latest_price`는 저장된 `DailyPrice.close_price` 기준이며 실시간 가격이 아니다.

## 5. Portfolio Summary 화면

Route:

```text
GET /portfolio/summary/
```

Authentication:

```text
login required
```

View and template:

- view: `portfolio_summary_page`
- template: `portfolio/summary.html`

표시 항목:

- summary counts
- totals
- holdings table
- warnings
- read-only 안전 문구
- 주문 미제공 문구
- 추가매수 계산 전용 안내

화면 안전 정책:

- 화면은 DB-only이다.
- 화면은 Toss API를 호출하지 않는다.
- 화면은 DB write를 하지 않는다.
- 화면은 주문 버튼을 제공하지 않는다.
- 화면은 자동매매 기능을 제공하지 않는다.
- 화면은 username, email, user id, 계좌번호, token, header, raw response를 표시하지 않는다.

## 6. Additional Buy Simulation API

Endpoint:

```text
POST /api/holdings/{id}/additional-buy-simulation/
```

Authentication:

```text
IsAuthenticated
```

Owner scope:

- `{id}`는 `request.user` 소유의 `UserHolding.id`여야 한다.
- 다른 사용자의 holding id는 접근할 수 없다.
- inactive holding은 MVP에서 차단한다.

Request body:

```json
{
  "additional_budget": "100000",
  "buy_price": "16000",
  "target_price": "18000"
}
```

MVP 입력 정책:

- `additional_budget`은 필수이다.
- `additional_budget`은 0보다 커야 한다.
- `additional_quantity`는 MVP에서 지원하지 않는다.
- `buy_price`는 optional이다.
- `target_price`는 optional이다.
- `buy_price`가 없으면 latest `DailyPrice.close_price`를 사용한다.
- latest `DailyPrice`가 없고 `buy_price`도 없으면 validation error를 반환한다.

Response fields:

- `simulation_only`
- `order_execution`
- `stock`
- `price_source`
- `current_position`
- `input`
- `simulation`
- `target_projection`
- `warnings`

Example response:

```json
{
  "simulation_only": true,
  "order_execution": false,
  "stock": {
    "code": "035250",
    "name": "강원랜드",
    "market": "KOSPI"
  },
  "price_source": {
    "type": "manual_buy_price",
    "latest_price": "16340.00",
    "latest_price_date": "2026-06-16",
    "simulation_buy_price": "16000.00"
  },
  "current_position": {
    "quantity": 2,
    "average_price": "15116.50",
    "invested_amount": "30233.00",
    "market_value": "32680.00",
    "profit_loss_amount": "2447.00",
    "profit_loss_rate": "8.09"
  },
  "input": {
    "additional_budget": "100000.00",
    "buy_price": "16000.00",
    "target_price": "18000.00"
  },
  "simulation": {
    "additional_quantity": 6,
    "additional_invested_amount": "96000.00",
    "unused_budget": "4000.00",
    "new_quantity": 8,
    "new_total_invested_amount": "126233.00",
    "new_average_price": "15779.13",
    "break_even_price": "15779.13",
    "required_rise_to_break_even": "-3.43",
    "simulated_market_value_at_latest": "130720.00",
    "simulated_profit_loss_amount_at_latest": "4487.00",
    "simulated_profit_loss_rate_at_latest": "3.55"
  },
  "target_projection": {
    "target_price": "18000.00",
    "target_market_value": "144000.00",
    "target_profit_loss_amount": "17767.00",
    "target_profit_loss_rate": "14.07"
  },
  "warnings": [
    "This is a calculation-only simulation and does not place orders.",
    "Fees and taxes are not included."
  ]
}
```

주의:

- `order_execution`은 항상 `false`여야 한다.
- 응답에 주문 ID, 주문번호, 계좌, token, user id, username, email을 포함하지 않는다.
- 결과는 산술 계산이며 투자 권유가 아니다.

## 7. 인증 / owner scope 정책

Portfolio Summary API:

- 인증된 사용자만 접근 가능하다.
- `request.user`의 `UserHolding`만 조회한다.
- 다른 사용자 데이터를 조회하기 위한 query parameter를 제공하지 않는다.

Portfolio Summary 화면:

- 로그인된 사용자만 접근 가능하다.
- 로그인되지 않은 사용자는 login redirect된다.
- 화면 context에 사용자 식별자나 계좌 정보를 넣지 않는다.

Additional Buy Simulation API:

- 인증된 사용자만 접근 가능하다.
- `request.user` 소유의 `UserHolding` detail action으로만 계산한다.
- 다른 사용자의 holding id는 차단된다.
- inactive holding은 `inactive_holding` 오류로 차단한다.

## 8. 응답 필드와 계산 공식

Portfolio Summary:

```text
invested_amount = quantity * average_price
market_value = quantity * latest_price
profit_loss_amount = market_value - invested_amount
profit_loss_rate = profit_loss_amount / invested_amount * 100
```

Portfolio totals:

```text
total_invested_amount_all = sum(invested_amount for all calculable holdings)
total_invested_amount_priced = sum(invested_amount for priced holdings)
total_market_value_priced = sum(market_value for priced holdings)
total_profit_loss_amount_priced = total_market_value_priced - total_invested_amount_priced
total_profit_loss_rate_priced = total_profit_loss_amount_priced / total_invested_amount_priced * 100
```

Additional Buy Simulation:

```text
additional_quantity = floor(additional_budget / buy_price)
additional_invested_amount = additional_quantity * buy_price
unused_budget = additional_budget - additional_invested_amount
new_quantity = current_quantity + additional_quantity
new_total_invested_amount = current_invested_amount + additional_invested_amount
new_average_price = new_total_invested_amount / new_quantity
break_even_price = new_average_price
```

Latest price 기준 simulated P/L:

```text
simulated_market_value_at_latest = new_quantity * latest_price
simulated_profit_loss_amount_at_latest = simulated_market_value_at_latest - new_total_invested_amount
simulated_profit_loss_rate_at_latest = simulated_profit_loss_amount_at_latest / new_total_invested_amount * 100
required_rise_to_break_even = (break_even_price - latest_price) / latest_price * 100
```

Target projection:

```text
target_market_value = new_quantity * target_price
target_profit_loss_amount = target_market_value - new_total_invested_amount
target_profit_loss_rate = target_profit_loss_amount / new_total_invested_amount * 100
```

공통 계산 정책:

- Decimal 기반으로 계산한다.
- 금액과 비율은 응답에서 문자열로 반환한다.
- 수수료와 세금은 포함하지 않는다.
- 실시간 가격이 아니라 저장된 latest `DailyPrice` 기준이다.
- 수익 보장이 아니다.
- 투자 권유가 아니다.

## 9. 오류 응답 정책

Additional Buy Simulation API는 safe error code와 message를 반환한다.

주요 error code:

- `invalid_additional_budget`
- `invalid_buy_price`
- `invalid_target_price`
- `latest_price_required`
- `additional_quantity_too_small`
- `additional_quantity_not_supported`
- `conflicting_input`
- `inactive_holding`
- `unsupported_market`
- `invalid_holding_price`
- `invalid_holding_quantity`

Example error:

```json
{
  "error": "invalid_additional_budget",
  "message": "additional_budget must be greater than zero."
}
```

오류 정책:

- raw exception을 그대로 노출하지 않는다.
- 오류 message에 username, email, 계좌, token, header, raw response를 넣지 않는다.
- validation error는 400으로 응답한다.
- 인증 실패는 401 또는 403으로 응답한다.
- 다른 사용자의 holding 접근은 404 또는 403 계열로 차단한다.

## 10. read-only / DB-only 보장

Portfolio Summary API:

- `build_portfolio_summary(request.user, include_inactive=...)`만 호출한다.
- DB 저장을 수행하지 않는다.
- `DataIngestionLog`를 생성하지 않는다.
- Toss API를 호출하지 않는다.

Portfolio Summary 화면:

- `build_portfolio_summary(request.user, include_inactive=...)` 결과를 template에 렌더링한다.
- DB 저장을 수행하지 않는다.
- `DataIngestionLog`를 생성하지 않는다.
- Toss API를 호출하지 않는다.

Additional Buy Simulation API:

- `build_additional_buy_simulation(...)`으로 계산만 수행한다.
- DB 저장을 수행하지 않는다.
- `DataIngestionLog`를 생성하지 않는다.
- Toss API를 호출하지 않는다.
- 주문 API를 호출하지 않는다.

## 11. 주문 API / 자동매매 금지 정책

현재 구현은 주문 API와 무관하다.

금지 상태:

- 주문 생성 API 호출 없음
- 주문 정정 API 호출 없음
- 주문 취소 API 호출 없음
- 주문 조회 API 호출 없음
- 매수 가능 금액 API 호출 없음
- 매도 가능 수량 API 호출 없음
- 자동매매 없음
- 조건 충족 시 자동 주문 없음

화면/프론트엔드 문구 정책:

- "매수하기" 금지
- "주문하기" 금지
- "자동매매" 금지
- "추천 매수" 금지
- "수익 보장" 금지
- 권장 문구: "추가매수 계산", "평균단가 시뮬레이션", "계산 전용이며 주문을 실행하지 않습니다."

## 12. 민감정보 금지 정책

응답, 화면, 문서 예시에는 다음 값을 포함하지 않는다.

- username
- email
- user id
- 계좌번호
- account sequence
- `X-Tossinvest-Account`
- access token
- Authorization header
- request header/body
- raw API response
- client id
- client secret
- password/hash

현재 Portfolio/Simulation 기능은 DB-only이므로 계좌 정보와 token이 필요하지 않다.

## 13. 수동 smoke 검증 결과

Portfolio Summary API:

- 인증 없는 요청: 403
- 인증된 요청: 200
- `035250` holding summary 확인
- `priced_holding_count`: 1
- `missing_price_count`: 0
- `latest_price`: `16340.00`
- `market_value`: `32680.00`
- `profit_loss_amount`: `2447.00`
- `profit_loss_rate`: `8.09`
- DB write 없음
- Toss API 호출 없음
- `DataIngestionLog` 생성 없음

Portfolio Summary 화면:

- 인증 없는 요청: 302 login redirect
- 인증 사용자 요청: 200
- 포트폴리오 요약 화면 렌더링 확인
- `035250` / 강원랜드 / 평균단가 / 최신가 / 평가금액 / 손익률 표시 확인
- 주문 버튼 없음
- 자동매매 UI 없음
- DB write 없음
- Toss API 호출 없음
- `DataIngestionLog` 생성 없음

Additional Buy Simulation API:

- 인증 없는 요청: 403
- 인증 사용자 요청: 200
- `additional_budget=100000` 정상 계산
- `buy_price=16000`, `target_price=18000` 정상 계산
- invalid budget 400 확인
- too small budget 400 확인
- `simulation_only=true`
- `order_execution=false`
- DB write 없음
- Toss API 호출 없음
- `DataIngestionLog` 생성 없음
- 주문 API 호출 없음

## 14. 프론트엔드 연결 가이드

Portfolio Summary 화면:

- 사용자는 `/portfolio/summary/`에서 자신의 보유 요약을 본다.
- 가격은 저장된 latest `DailyPrice.close_price` 기준이다.
- 실시간 가격이 아니다.
- 화면에는 주문 버튼을 두지 않는다.

Portfolio Summary API:

- 프론트엔드는 `GET /api/portfolio/summary/`로 JSON 요약을 가져올 수 있다.
- 인증이 필요하다.
- 기본값은 active holding만 포함한다.
- inactive holding이 필요하면 `include_inactive=true`를 사용한다.

Simulation API:

- 특정 holding row에서 `POST /api/holdings/{id}/additional-buy-simulation/`으로 연결할 수 있다.
- 버튼/폼 이름은 "추가매수 계산" 또는 "평균단가 시뮬레이션"을 권장한다.
- "매수하기", "주문하기", "추천 매수" 같은 표현은 사용하지 않는다.
- 결과 표시 시 "계산 전용이며 주문을 실행하지 않습니다." 문구를 함께 보여준다.

## 15. 후속 작업

- Step M: 투자 조언 표현 안전 문구 정리
- Step N: Portfolio Summary 화면에 Simulation 입력 UI 설계
- Step O: Simulation UI 구현
- Step P: optional live quote 설계
- Step Q: DailyPrice batch commit 설계는 보류
- 주문 API는 계속 비활성 유지
