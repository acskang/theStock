# Additional Buy Simulation API Design

## 1. 목적

이 문서는 사용자의 기존 `UserHolding`을 기준으로 추가매수 시뮬레이션을
계산하는 read-only API를 설계한다.

목표는 주문 실행이 아니라 산술 계산 결과를 안전하게 제공하는 것이다. MVP는
DB-only로 설계하며 `UserHolding`, `Stock`, 최신 `DailyPrice`만 사용한다.
Toss API, 주문 API, 계좌 API, 자동매매, DB 저장은 범위에 포함하지 않는다.

이 API는 투자 권유나 매수 추천이 아니다. 응답에는 계산 전용임을 나타내는
`simulation_only=true`, 주문 실행이 없음을 나타내는
`order_execution=false`를 포함한다.

## 2. 현재 상태와 배경

현재 검증된 흐름:

- Toss holdings 기반 `UserHolding` 저장/skip/update 성공.
- Toss candle 기반 `DailyPrice` 저장/skip/update 성공.
- `Portfolio Summary` service와 API 구현 완료.
- `GET /api/portfolio/summary/`는 `request.user` 기준 owner scope를 적용한다.
- Portfolio Summary API는 DB-only이며 Toss API, DB write,
  `DataIngestionLog` write를 하지 않는다.
- 보유종목 `035250`은 `DailyPrice` 저장 후 평가금액과 손익 계산이 가능하다.

현재 관련 모델:

- `holdings.UserHolding`
  - `user`
  - `stock`
  - `average_price`
  - `quantity`
  - `is_active`
  - `max_additional_budget`
  - `risk_level`
  - `memo`
- `stocks.Stock`
  - `code`
  - `name`
  - `market`
- `marketdata.DailyPrice`
  - `stock`
  - `date`
  - `close_price`
  - OHLC/volume

관련 API 구조:

- `holdings` 앱은 이미 보유종목 단위 API를 제공한다.
- `holdings/urls.py`에는 다음과 같은 detail endpoint가 있다.
  - `/api/holdings/<id>/evaluate/`
  - `/api/holdings/<id>/probability/`
  - `/api/holdings/<id>/consult/`
- 기존 detail API는 `request.user` 기준으로 holding owner scope를 적용한다.

## 3. API 위치 후보

### 후보 A. holdings 앱 detail endpoint

```text
POST /api/holdings/{id}/additional-buy-simulation/
```

장점:

- 특정 `UserHolding` 기준 계산이라는 의미가 명확하다.
- 기존 `holdings` 앱의 owner scope 패턴을 재사용할 수 있다.
- `evaluate`, `probability`, `consult`와 같은 보유종목 단위 계산 API와
  구조가 일관된다.

단점:

- holdings CRUD 앱에 계산 endpoint가 하나 더 추가된다.
- endpoint가 holding id에 의존한다.

### 후보 B. decisions 앱 endpoint

```text
POST /api/decisions/additional-buy-simulation/
```

장점:

- 판단/시뮬레이션 도메인이라는 의미가 명확하다.
- 향후 확률, 백테스트, 리스크 판단과 연결하기 쉽다.

단점:

- `UserHolding` owner scope를 별도로 구현해야 한다.
- 기존 `AveragingDecision`, `HoldingConsultRecord`처럼 저장되는 판단 기록과
  혼동될 수 있다.
- MVP는 저장 없는 계산 API이므로 decisions 기록 모델과 결합하지 않는 편이
  안전하다.

### 후보 C. portfolio 앱 endpoint

```text
POST /api/portfolio/additional-buy-simulation/
```

장점:

- Portfolio Summary와 같은 사용자 포트폴리오 맥락에서 확장하기 쉽다.
- 향후 전체 포트폴리오 예산 배분 시뮬레이션으로 확장할 수 있다.

단점:

- 특정 holding 기준 계산을 위해 별도 `holding_id` 입력과 owner scope 검증이
  필요하다.
- 현재 portfolio summary API와 달리 입력 검증과 detail object lookup이 필요하다.

### 권장 위치

MVP 권장안:

```text
POST /api/holdings/{id}/additional-buy-simulation/
```

이유:

- 현재 구조에서 `UserHolding` detail 계산 API가 이미 holdings 앱에 모여 있다.
- `_get_owned_holding(request.user, pk)`와 같은 owner scope 패턴을 재사용할 수 있다.
- 특정 보유종목의 현재 수량, 평균단가, 최신 가격을 기준으로 계산하므로
  holdings detail endpoint가 가장 직접적이다.
- DB write가 없는 계산 API라는 점은 view, serializer, response 이름에서
  명확히 분리한다.

후속으로 전체 포트폴리오 예산 배분이나 복수 종목 시뮬레이션이 필요해지면
portfolio 앱 endpoint를 별도 설계한다.

## 4. HTTP method 정책

권장 method:

```text
POST
```

권장 endpoint:

```text
POST /api/holdings/{id}/additional-buy-simulation/
```

POST를 쓰는 이유:

- 입력값이 `additional_budget`, `additional_quantity`, `buy_price`,
  `target_price`처럼 늘어날 수 있다.
- DRF serializer로 Decimal validation을 처리하기 쉽다.
- GET query string보다 요청 의미와 입력 검증이 명확하다.

주의:

- POST를 사용하지만 DB write를 하지 않는다.
- response에 `simulation_only=true`, `order_execution=false`를 포함한다.
- 주문 생성, 주문 정정, 주문 취소, 매수 가능 금액 조회와 연결하지 않는다.

## 5. 입력 schema

MVP 입력 schema:

```json
{
  "additional_budget": "100000",
  "buy_price": null,
  "target_price": null
}
```

후속 확장 후보:

```json
{
  "additional_budget": "100000",
  "additional_quantity": null,
  "buy_price": null,
  "target_price": null,
  "fee_rate": null,
  "tax_rate": null
}
```

MVP 정책:

- `additional_budget`은 필수다.
- `additional_budget`은 0보다 커야 한다.
- `buy_price`는 optional이다.
- `buy_price`가 없으면 최신 `DailyPrice.close_price`를 사용한다.
- `buy_price`가 있으면 0보다 커야 한다.
- `target_price`는 optional이다.
- `target_price`가 있으면 0보다 커야 한다.
- `additional_quantity`는 MVP에서 받지 않는다.

후속 정책:

- `additional_budget` 또는 `additional_quantity` 중 하나를 허용할 수 있다.
- 둘 다 입력되면 validation error로 처리한다.
- 국내 주식 MVP에서는 정수 수량만 지원한다.
- 수수료/세금은 별도 fee/tax model 설계 후 추가한다.

권장 validation error code:

| code | 의미 |
|---|---|
| `invalid_additional_budget` | additional_budget이 없거나 0 이하 |
| `invalid_buy_price` | buy_price가 0 이하 |
| `invalid_target_price` | target_price가 0 이하 |
| `latest_price_required` | buy_price가 없고 최신 DailyPrice도 없음 |
| `additional_quantity_too_small` | 예산으로 1주도 계산되지 않음 |
| `inactive_holding` | inactive holding |
| `holding_not_found` | request.user 소유 holding이 아님 또는 없음 |
| `unsupported_market` | MVP에서 지원하지 않는 시장 |

## 6. 데이터 소스 정책

MVP에서 사용하는 데이터:

- `holdings.models.UserHolding`
- `stocks.models.Stock`
- `marketdata.models.DailyPrice`

MVP에서 사용하지 않는 데이터:

- Toss live quote
- Toss holdings API
- Toss accounts API
- Toss order API
- buying-power API
- sellable-quantity API
- raw API response
- `DataIngestionLog`

최신 가격 조회:

```python
DailyPrice.objects.filter(stock=holding.stock).order_by("-date").first()
```

또는 기존 helper가 적합하면:

```python
marketdata.services.price_service.get_latest_price(holding.stock)
```

후속 확장:

- live quote optional
- TechnicalIndicator 요약
- probability calibration
- backtesting
- fee/tax model

## 7. owner scope / permission

권장 정책:

- `IsAuthenticated` 필수.
- `request.user`의 `UserHolding`만 조회한다.
- 다른 사용자의 holding id는 404 또는 403으로 차단한다.
- staff/admin override는 MVP에서 제외한다.
- username, email, user_id는 response에 포함하지 않는다.
- inactive holding은 MVP에서 시뮬레이션 대상에서 제외한다.
- inactive holding 요청은 400 또는 404로 처리한다.

권장 lookup:

```python
get_object_or_404(
    UserHolding.objects.select_related("stock").filter(user=request.user),
    id=pk,
)
```

inactive 처리:

```text
holding.is_active is False -> 400 inactive_holding
holding.quantity <= 0 -> 400 inactive_holding
```

## 8. 계산 공식

기본 값:

```text
current_quantity = holding.quantity
current_average_price = holding.average_price
current_invested_amount = current_quantity * current_average_price
latest_price = latest DailyPrice.close_price
simulation_buy_price = request.buy_price or latest_price
```

`additional_budget` 기반 추가 수량:

```text
additional_quantity = floor(additional_budget / simulation_buy_price)
additional_invested_amount = additional_quantity * simulation_buy_price
unused_budget = additional_budget - additional_invested_amount
```

정책:

- 국내 주식 MVP는 정수 수량만 지원한다.
- `additional_quantity < 1`이면 validation error 또는 warning으로 처리한다.
- MVP에서는 validation error를 권장한다.

추가매수 후:

```text
new_quantity = current_quantity + additional_quantity
new_total_invested_amount = current_invested_amount + additional_invested_amount
new_average_price = new_total_invested_amount / new_quantity
break_even_price = new_average_price
```

현재가 기준 기존 손익:

```text
current_market_value = current_quantity * latest_price
current_profit_loss_amount = current_market_value - current_invested_amount
current_profit_loss_rate = current_profit_loss_amount / current_invested_amount * 100
```

추가매수 후 latest price 기준 손익:

```text
simulated_market_value_at_latest = new_quantity * latest_price
simulated_profit_loss_amount_at_latest =
    simulated_market_value_at_latest - new_total_invested_amount
simulated_profit_loss_rate_at_latest =
    simulated_profit_loss_amount_at_latest / new_total_invested_amount * 100
```

손익분기점까지 필요 상승률:

```text
required_rise_to_break_even =
    (break_even_price - latest_price) / latest_price * 100
```

목표가 기준:

```text
target_market_value = new_quantity * target_price
target_profit_loss_amount = target_market_value - new_total_invested_amount
target_profit_loss_rate = target_profit_loss_amount / new_total_invested_amount * 100
```

예외:

- `latest_price`가 없고 `buy_price`도 없으면 계산 불가.
- latest price가 없지만 `buy_price`가 있으면 추가매수 후 평균단가 계산은 가능하다.
- latest price가 없으면 현재 손익, simulated latest 손익,
  `required_rise_to_break_even`은 `null`로 둔다.
- 모든 계산은 `Decimal` 기반으로 한다.
- response 금액과 비율은 문자열로 반환한다.

반올림:

- 금액: 소수점 2자리.
- 수량: 국내 주식 MVP는 정수 문자열.
- 비율: 소수점 2자리.

## 9. response schema

예시:

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
    "type": "daily_price",
    "latest_price": "16340.00",
    "latest_price_date": "2026-06-16"
  },
  "current_position": {
    "quantity": "2",
    "average_price": "15116.50",
    "invested_amount": "30233.00",
    "market_value": "32680.00",
    "profit_loss_amount": "2447.00",
    "profit_loss_rate": "8.09"
  },
  "input": {
    "additional_budget": "100000.00",
    "buy_price": "16340.00",
    "target_price": null
  },
  "simulation": {
    "additional_quantity": "6",
    "additional_invested_amount": "98040.00",
    "unused_budget": "1960.00",
    "new_quantity": "8",
    "new_total_invested_amount": "128273.00",
    "new_average_price": "16034.13",
    "break_even_price": "16034.13",
    "required_rise_to_break_even": "-1.87",
    "simulated_market_value_at_latest": "130720.00",
    "simulated_profit_loss_amount_at_latest": "2447.00",
    "simulated_profit_loss_rate_at_latest": "1.91"
  },
  "target_projection": null,
  "warnings": [
    "This is a calculation-only simulation and does not place orders."
  ]
}
```

`target_price`가 있는 경우:

```json
{
  "target_projection": {
    "target_price": "17000.00",
    "target_market_value": "136000.00",
    "target_profit_loss_amount": "7727.00",
    "target_profit_loss_rate": "6.02"
  }
}
```

포함 금지:

- username
- email
- user_id
- accountNo
- accountSeq
- `X-Tossinvest-Account`
- `access_token`
- Authorization header
- raw response
- order id
- 주문 가능 금액
- 매도 가능 수량

문구 정책:

- "추천 매수", "매수하라", "수익 보장" 같은 표현을 쓰지 않는다.
- "추가매수 시뮬레이션", "계산 결과", "가정 입력" 같은 표현을 사용한다.

## 10. validation / error 정책

권장 error response:

```json
{
  "error": "invalid_additional_budget",
  "message": "additional_budget must be greater than zero."
}
```

필수 validation:

| 조건 | 처리 |
|---|---|
| 인증 없음 | 401 또는 403 |
| holding이 request.user 소유가 아님 | 404 또는 403 |
| inactive holding | 400 `inactive_holding` |
| `additional_budget` 누락 | 400 `invalid_additional_budget` |
| `additional_budget <= 0` | 400 `invalid_additional_budget` |
| `buy_price <= 0` | 400 `invalid_buy_price` |
| `target_price <= 0` | 400 `invalid_target_price` |
| buy_price 없고 latest DailyPrice 없음 | 400 `latest_price_required` |
| 계산된 additional_quantity가 0 | 400 `additional_quantity_too_small` |
| MVP 미지원 시장 | 400 `unsupported_market` |

시장 정책:

- MVP는 KR 국내 주식만 지원한다.
- `Stock.market`이 KOSPI/KOSDAQ/KONEX/ETF/ETN 중 하나일 때 허용한다.
- US/USD, fractional quantity는 후속 설계로 분리한다.

## 11. service / serializer / view 설계

### Service

권장 파일:

```text
decisions/services/additional_buy_simulation_service.py
```

권장 함수:

```python
def build_additional_buy_simulation(
    *,
    holding,
    additional_budget,
    buy_price=None,
    target_price=None,
) -> dict:
    ...
```

decisions service에 두는 이유:

- 계산/시뮬레이션 도메인 로직은 holdings CRUD보다 decisions에 가깝다.
- view 위치는 holdings 앱이어도 계산 로직은 decisions service로 분리할 수 있다.
- 향후 probability/backtesting과 연결하기 쉽다.

서비스 정책:

- DB write 없음.
- Toss API 호출 없음.
- `DataIngestionLog` 생성 없음.
- Decimal 계산.
- username/email/user_id/account/token/header/raw response 반환 없음.

### Serializer

권장 위치:

```text
decisions/serializers.py
```

입력 serializer:

```text
AdditionalBuySimulationInputSerializer
```

필드:

- `additional_budget`
- `buy_price`
- `target_price`

출력 serializer:

```text
AdditionalBuySimulationOutputSerializer
```

또는 service dict passthrough serializer를 사용할 수 있다.

### View

권장 위치:

```text
holdings/views.py
```

권장 class:

```text
HoldingAdditionalBuySimulationAPIView
```

권장 URL:

```text
path(
    "<int:pk>/additional-buy-simulation/",
    HoldingAdditionalBuySimulationAPIView.as_view(),
    name="holding-additional-buy-simulation",
)
```

view 정책:

- `permission_classes = [IsAuthenticated]`
- `POST` only
- `_get_owned_holding(request.user, pk)` 패턴 재사용
- inactive holding 차단
- 입력 serializer validation
- service 호출
- response serializer 적용
- DB write 없음
- `create_decision_from_result`, `create_probability_record`,
  `create_consult_record` 호출 없음

## 12. DataIngestionLog 기록 여부

MVP에서는 `DataIngestionLog`에 기록하지 않는다.

이유:

- 이 API는 ingestion command가 아니다.
- 사용자 시뮬레이션 조회는 자주 호출될 수 있다.
- ingestion/audit log와 사용자 계산 event는 성격이 다르다.
- 별도 analytics/event log 설계 전까지 운영 `DataIngestionLog`를 늘리지 않는다.

정책 문구:

```text
Additional Buy Simulation API는 ingestion command가 아니므로
DataIngestionLog 기록 대상이 아니다.
```

## 13. 보안 / 투자 조언 위험 완화

주문 관련 안전 정책:

- 주문 API 호출 없음.
- 주문 생성/정정/취소 없음.
- 주문 조회/history/info 없음.
- 매수 가능 금액 API 호출 없음.
- 매도 가능 수량 API 호출 없음.
- 자동매매 없음.
- 조건 충족 시 자동 주문 로직 없음.

민감정보 정책:

- 계좌 정보 없음.
- token/secret/header 없음.
- raw API response 없음.
- username/email/user_id response 포함 없음.
- Toss API 호출 없음.

투자 조언 위험 완화:

- "시뮬레이션"과 "계산"이라는 표현을 사용한다.
- "추천", "매수하라", "수익 보장" 표현을 금지한다.
- response warning에 계산 전용 문구를 포함한다.
- 사용자가 입력한 추가 예산과 가격 가정에 따른 산술 결과임을 명확히 한다.
- 최종 투자 판단과 책임은 사용자에게 있음을 화면/API 문서에서 별도 고지한다.

권장 warning:

```text
This is a calculation-only simulation and does not place orders.
```

한국어 UI 문구 후보:

```text
이 결과는 입력값 기반 계산 시뮬레이션이며 주문을 실행하지 않습니다.
```

## 14. 테스트 전략

필수 테스트:

1. 인증되지 않은 요청은 401 또는 403.
2. 인증된 사용자의 active holding은 200.
3. 다른 사용자의 holding 접근은 404 또는 403.
4. inactive holding은 차단.
5. latest DailyPrice가 없고 `buy_price`도 없으면 오류.
6. `additional_budget <= 0`이면 오류.
7. `buy_price <= 0`이면 오류.
8. `target_price <= 0`이면 오류.
9. `additional_budget`으로 `additional_quantity` 계산.
10. `unused_budget` 계산.
11. `new_average_price` 계산.
12. `break_even_price` 계산.
13. current profit/loss 계산.
14. simulated profit/loss 계산.
15. `target_price` projection 계산.
16. response에 `simulation_only=true`.
17. response에 `order_execution=false`.
18. DB write 없음.
19. `DataIngestionLog` 생성 없음.
20. Toss API 호출 없음.
21. username/email/user_id/account/token/header/raw response 없음.
22. 주문 API 호출 없음.

테스트 데이터 예시:

- user A holding: `035250`, quantity `2`, average_price `15116.50`.
- latest `DailyPrice.close_price`: `16340.00`.
- `additional_budget`: `100000.00`.
- expected `additional_quantity`: `6`.
- expected `unused_budget`: `1960.00`.
- expected `new_average_price`: `16034.13`.

DB write 검증:

- `UserHolding` count 변화 없음.
- `DailyPrice` count 변화 없음.
- `DataIngestionLog` count 변화 없음.
- decision/probability/consult record count 변화 없음.

## 15. 단계별 구현 계획

### Step I1: Additional Buy Simulation service 구현

- `decisions/services/additional_buy_simulation_service.py` 생성.
- DB-only 계산 함수 구현.
- Decimal formatting helper 구현.
- service 단위 테스트 추가.
- API/View/URL은 아직 구현하지 않는다.

### Step I2: Additional Buy Simulation API 구현

- `HoldingAdditionalBuySimulationAPIView` 추가.
- `POST /api/holdings/{id}/additional-buy-simulation/` 연결.
- `IsAuthenticated`와 owner scope 적용.
- 입력 serializer와 response serializer 추가.
- DB write, Toss API 호출, `DataIngestionLog` 기록이 없음을 테스트한다.

### Step I3: 수동 API smoke

- user_id는 출력하지 않거나 최소화한다.
- active holding `035250` 기준으로 read-only 조회한다.
- `additional_budget` 예시로 계산값을 확인한다.
- DB count와 `DataIngestionLog` count가 변하지 않는지 확인한다.
- 주문 API 호출이 없음을 확인한다.

### Step I4: Portfolio Summary와 화면 연결

- Portfolio Summary 화면 또는 응답에서 각 holding의 simulation link를 제공한다.
- 화면 문구는 "추가매수 시뮬레이션"으로 제한한다.
- "추천", "주문", "자동매매" 표현을 피한다.

### Step I5: live quote optional 설계

- Toss quote 사용 여부를 별도로 설계한다.
- cache/rate limit, 장애 fallback, quote freshness 표시가 필요하다.
- 기본값은 DB-only/off로 유지한다.
- live quote 도입 후에도 주문 API와 연결하지 않는다.
