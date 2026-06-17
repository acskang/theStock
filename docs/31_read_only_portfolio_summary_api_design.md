# Read-only Portfolio Summary API Design

## 1. 목적

이 문서는 현재 저장된 `UserHolding`, `Stock`, `DailyPrice`만 사용해
사용자별 portfolio summary를 제공하는 read-only API를 설계한다.

목표는 Toss API 호출이나 DB 저장 없이, 이미 검증된 보유 원장과 일봉 데이터를
사용자 가치 기능으로 연결하는 것이다. 주문 API, 자동매매, 계좌 정보, token,
raw API response는 이 API의 범위에 포함하지 않는다.

이번 단계는 설계 문서 작성만 수행하며 Python 코드, 설정, migration, DB schema,
운영 DB row를 변경하지 않는다.

## 2. 현재 상태와 배경

현재 확인된 구조:

- `holdings.UserHolding`은 `user`, `stock`, `average_price`, `quantity`,
  `is_active`, `max_additional_budget`, `risk_level`, `memo`를 가진다.
- `UserHoldingViewSet`은 `request.user` 기준으로 queryset을 제한한다.
- `UserHoldingViewSet`은 기본적으로 `is_active=True` row만 반환하고,
  `include_inactive=true`가 있을 때만 inactive row를 포함한다.
- `marketdata.DailyPrice`는 `stock`, `date`, OHLC, `volume`, `change_rate`를 가진다.
- `DailyPrice`는 `(stock, date)` unique constraint와 `(stock, -date)` index가 있다.
- `marketdata.services.price_service.get_latest_price(stock)` helper가 이미 존재한다.
- `portfolio` 앱은 legacy `Transaction`/template 중심이며 현재
  `portfolio/serializers.py`, `portfolio/urls.py`가 없다.
- 현재 portfolio summary 전용 DRF API는 없다.

마지막 수동 검증 기준 운영 DB 상태:

| 모델 | 상태 |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 2 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 83 이상 |

주의:

- `DailyPrice`가 아직 2건뿐이므로 price coverage가 낮다.
- `UserHolding`이 1건뿐이므로 summary 기능의 초기 가치는 제한적이다.
- 그럼에도 DB-only read-only API로 시작하면 민감정보와 rate limit 위험 없이
  첫 사용자 가치 화면을 만들 수 있다.

## 3. API 범위

권장 endpoint:

```text
GET /api/portfolio/summary/
```

권장 이유:

- holdings CRUD와 별개로 aggregate summary 성격이 강하다.
- 이후 additional-buy simulation API와 책임을 분리하기 쉽다.
- DB-only read-only 계산 API로 운영 위험이 낮다.

대안:

```text
GET /api/holdings/summary/
```

대안의 장점:

- 기존 `holdings` 앱의 owner scope 패턴을 재사용하기 쉽다.
- `UserHoldingViewSet` action으로 빠르게 구현할 수 있다.

대안의 단점:

- holdings CRUD와 portfolio aggregate 계산이 섞인다.
- portfolio summary, live quote, additional-buy report가 커질수록
  `holdings` 앱 책임이 비대해진다.

추천안:

- `portfolio/services/portfolio_summary_service.py`를 새로 만들고,
- `portfolio/serializers.py`를 추가하고,
- `portfolio/views.py`에 read-only APIView를 추가하고,
- `portfolio/urls.py`를 생성한 뒤,
- `stock_service/urls.py`에서 `path("api/portfolio/", include("portfolio.urls"))`
  형태로 연결한다.

MVP 범위:

- GET only.
- DB-only.
- Toss API 호출 없음.
- DB write 없음.
- 주문 API와 무관.

## 4. owner scope / permission 정책

Portfolio Summary API는 owner-scoped read-only API다.
사용자는 자신의 `UserHolding` 요약만 조회한다.

정책:

- `IsAuthenticated` 필수.
- `request.user`의 `UserHolding`만 조회.
- `user_id`, `username`, `email` query parameter를 받지 않는다.
- staff/admin override는 MVP에서 제외한다.
- response에 `user_id`, username, email을 포함하지 않는다.
- 기본 조회 대상은 `is_active=True` holding이다.
- inactive holdings는 기본 제외한다.
- `include_inactive=true`는 후순위 확장으로 둔다.

권장 queryset:

```python
UserHolding.objects.filter(
    user=request.user,
    is_active=True,
).select_related("stock")
```

## 5. 데이터 소스 정책

MVP에서 사용하는 데이터:

- `holdings.models.UserHolding`
- `stocks.models.Stock`
- `marketdata.models.DailyPrice`

MVP에서 사용하지 않는 데이터:

- Toss live quote
- Toss holdings API
- Toss accounts API
- Toss raw API response
- Toss token/account/header
- `DataIngestionLog.metadata`
- 주문 API

DB-only 정책의 장점:

- 응답이 빠르고 안정적이다.
- Toss rate limit과 장애에 영향을 받지 않는다.
- 계좌 식별자, token, header가 관여하지 않는다.
- 화면/API가 조회될 때마다 운영 ingestion log가 쌓이지 않는다.

Optional live quote는 후속 단계에서 별도 설계한다.

## 6. 최신 가격 조회 정책

각 holding의 `stock`에 대해 최신 `DailyPrice` row를 조회한다.

권장 helper:

```python
from marketdata.services.price_service import get_latest_price

latest_price_row = get_latest_price(stock)
```

동등한 조회:

```python
DailyPrice.objects.filter(stock=stock).order_by("-date").first()
```

사용 필드:

- `latest_price = latest_price_row.close_price`
- `latest_price_date = latest_price_row.date`

`DailyPrice`가 없는 경우:

- `latest_price = null`
- `latest_price_date = null`
- `market_value = null`
- `profit_loss_amount = null`
- `profit_loss_rate = null`
- `price_status = "missing_daily_price"`
- 해당 holding은 priced totals에서 제외한다.

summary count:

- `holding_count`: active holding 전체 수.
- `priced_holding_count`: latest DailyPrice가 있는 holding 수.
- `missing_price_count`: latest DailyPrice가 없는 holding 수.

## 7. 계산 공식

기본 입력:

- `quantity = UserHolding.quantity`
- `average_price = UserHolding.average_price`
- `latest_close_price = DailyPrice.close_price`

holding별 계산:

```text
invested_amount = quantity * average_price
market_value = quantity * latest_close_price
profit_loss_amount = market_value - invested_amount
profit_loss_rate = profit_loss_amount / invested_amount * 100
```

예외:

- `invested_amount == 0`이면 `profit_loss_rate = null`.
- `latest_close_price`가 없으면 평가금액과 손익 관련 필드는 `null`.

숫자 정책:

- 내부 계산은 `Decimal` 기반으로 수행한다.
- 금액은 소수점 2자리로 정규화한다.
- 비율은 소수점 2자리로 정규화한다.
- DRF `DecimalField`는 문자열로 내려갈 수 있으므로 MVP response는
  금액/비율을 문자열로 통일하는 것을 권장한다.

portfolio totals:

```text
total_invested_amount_all = 모든 active holding의 invested_amount 합
total_invested_amount_priced = 가격이 있는 holding의 invested_amount 합
total_market_value_priced = 가격이 있는 holding의 market_value 합
total_profit_loss_amount = total_market_value_priced - total_invested_amount_priced
total_profit_loss_rate = total_profit_loss_amount / total_invested_amount_priced * 100
```

분리 이유:

- 가격이 없는 holding의 투자금까지 평가손익 denominator에 포함하면
  가격 coverage가 낮을 때 summary가 왜곡된다.
- `total_invested_amount_all`과 `total_invested_amount_priced`를 분리하면
  사용자에게 누락 가격의 영향을 명확히 표시할 수 있다.

## 8. response schema

응답 예시:

```json
{
  "as_of": "2026-06-16",
  "holding_count": 1,
  "priced_holding_count": 1,
  "missing_price_count": 0,
  "totals": {
    "total_invested_amount_all": "30233.00",
    "total_invested_amount_priced": "30233.00",
    "total_market_value_priced": "32680.00",
    "total_profit_loss_amount": "2447.00",
    "total_profit_loss_rate": "8.09"
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
      "risk_level": "normal",
      "max_additional_budget": "0.00",
      "price_status": "priced"
    }
  ],
  "warnings": []
}
```

`DailyPrice`가 없는 holding 예시:

```json
{
  "stock": {
    "code": "000000",
    "name": "가격없는종목",
    "market": "KOSPI"
  },
  "quantity": 3,
  "average_price": "10000.00",
  "latest_price": null,
  "latest_price_date": null,
  "invested_amount": "30000.00",
  "market_value": null,
  "profit_loss_amount": null,
  "profit_loss_rate": null,
  "risk_level": "normal",
  "max_additional_budget": "0.00",
  "price_status": "missing_daily_price"
}
```

Response에 포함하지 않는 항목:

- username
- email
- accountNo
- accountSeq
- `X-Tossinvest-Account`
- access token
- Authorization header
- request/response raw payload
- 주문 관련 필드

## 9. serializer / service / view 설계

### 후보 A: service 중심

파일 후보:

```text
portfolio/services/portfolio_summary_service.py
```

함수 후보:

```python
def build_portfolio_summary(user) -> dict:
    ...
```

또는 후속 확장 포함:

```python
def build_portfolio_summary(user, *, include_inactive=False) -> dict:
    ...
```

장점:

- 계산 로직이 view/serializer와 분리된다.
- 단위 테스트가 쉽다.
- 후속 live quote 또는 additional-buy simulation과 연결하기 쉽다.

추천한다.

### 후보 B: serializer method 중심

장점:

- 빠르게 구현할 수 있다.

단점:

- 계산 로직이 serializer에 몰린다.
- totals 계산과 missing price 정책 테스트가 어려워진다.
- N+1 쿼리 위험을 serializer 내부에서 관리해야 한다.

MVP에서는 비추천한다.

### 후보 C: holdings ViewSet action

예:

```text
GET /api/holdings/summary/
```

장점:

- 기존 owner scope 패턴을 재사용하기 쉽다.

단점:

- holdings CRUD와 portfolio aggregate 책임이 섞인다.
- 추후 quote, simulation, 화면 API가 늘어날 때 구조가 흐려진다.

대안으로만 둔다.

### 추천 구현 구조

서비스:

```text
portfolio/services/portfolio_summary_service.py
```

Serializer:

```text
portfolio/serializers.py
```

후보 serializer:

- `PortfolioSummarySerializer`
- `PortfolioSummaryHoldingSerializer`
- `PortfolioSummaryTotalsSerializer`

View:

```text
portfolio/views.py
```

후보 view:

```python
class PortfolioSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        ...
```

URL:

```text
portfolio/urls.py
```

후보 route:

```python
path("summary/", PortfolioSummaryAPIView.as_view(), name="portfolio-summary")
```

프로젝트 URL 연결:

```python
path("api/portfolio/", include("portfolio.urls"))
```

## 10. query parameter 정책

MVP:

```text
GET /api/portfolio/summary/
```

초기에는 query parameter를 두지 않는다.

후순위 후보:

- `include_inactive=false`
- `price_source=daily_price`
- `live_quote=false`

후순위로 두는 이유:

- MVP는 owner-scoped active holding summary에 집중한다.
- live quote는 네트워크 호출, latency, rate limit, 장애 대응 정책이 필요하다.
- inactive holding 포함은 화면 UX와 totals 해석 정책이 먼저 필요하다.

## 11. DataIngestionLog 기록 여부

Portfolio Summary API는 ingestion command가 아니므로 `DataIngestionLog` 기록 대상이 아니다.

MVP 정책:

- `DataIngestionLog`를 기록하지 않는다.
- DB write를 하지 않는다.
- 사용자 조회 이벤트가 필요하면 별도 analytics/event log를 설계한다.

이유:

- 사용자가 summary를 자주 조회하면 `DataIngestionLog`가 과도하게 쌓일 수 있다.
- `DataIngestionLog`는 provider ingestion, smoke, scheduler wrapper 중심의 운영 로그다.
- 사용자 화면 조회와 ingestion observability는 분리하는 것이 안전하다.

## 12. 테스트 전략

필수 테스트:

1. 미인증 사용자는 접근할 수 없다.
2. 인증 사용자는 자신의 `UserHolding`만 조회한다.
3. 다른 사용자의 `UserHolding`이 섞이지 않는다.
4. 기본 조회는 `is_active=True`만 포함한다.
5. `UserHolding + latest DailyPrice`로 holding별 평가금액을 계산한다.
6. 최신 가격은 가장 최근 `DailyPrice.date` row를 사용한다.
7. `DailyPrice`가 없는 holding은 `missing_daily_price`로 표시한다.
8. `quantity * average_price`로 `invested_amount`를 계산한다.
9. `quantity * close_price`로 `market_value`를 계산한다.
10. `profit_loss_amount`와 `profit_loss_rate`를 계산한다.
11. `total_invested_amount_all`, `total_invested_amount_priced`,
    `total_market_value_priced`, `total_profit_loss_amount`,
    `total_profit_loss_rate`를 계산한다.
12. `invested_amount == 0`이면 수익률은 `null`이다.
13. API 호출이 DB write를 하지 않는다.
14. Toss API를 호출하지 않는다.
15. 주문 API를 호출하지 않는다.
16. response에 account/token/secret/header 관련 필드가 없다.
17. response에 username/email이 없다.
18. response에 raw API response가 없다.

권장 테스트 위치:

- `portfolio/tests.py`

테스트 방식:

- `APIClient`와 `force_authenticate` 사용.
- `Stock`, `UserHolding`, `DailyPrice`를 테스트 DB에 직접 생성.
- `DailyPrice`가 없는 종목과 있는 종목을 함께 검증.
- 가능하면 service 단위 테스트와 API 통합 테스트를 분리.

## 13. 보안 / 민감정보 정책

이 API는 DB-only portfolio summary이므로 다음 값을 다루지 않는다.

금지:

- `.env` 원문
- client id
- client secret
- access token
- account id
- accountNo
- accountSeq
- `X-Tossinvest-Account`
- Authorization header
- request headers
- request body
- raw API response
- username
- email
- 주문 관련 식별자

허용:

- stock code
- stock name
- stock market
- holding quantity
- average price
- latest DailyPrice close price
- 계산된 평가금액/손익/수익률
- risk level
- max additional budget

주문 API:

- 구현하지 않는다.
- 호출하지 않는다.
- portfolio summary response에 주문 가능 수량, 매수 가능 금액, 주문 실행 링크를 넣지 않는다.

## 14. 위험 요소와 완화책

### DailyPrice 데이터 부족

위험:

- 현재 `DailyPrice`가 2건뿐이라 많은 holding이 `missing_daily_price`가 될 수 있다.

완화:

- `missing_price_count`와 holding별 `price_status`를 명확히 제공한다.
- missing row는 priced totals에서 제외한다.
- DailyPrice batch commit 설계는 별도 단계로 진행한다.

### 실시간 가격 아님

위험:

- latest close는 실시간 현재가가 아니다.

완화:

- response에 `latest_price_date`를 포함한다.
- 화면에는 "최근 종가 기준" 문구를 사용한다.
- live quote는 optional 후속 기능으로 분리한다.

### 투자 조언 오해

위험:

- 손익률과 추가 예산이 투자 조언처럼 보일 수 있다.

완화:

- MVP는 "요약"과 "시뮬레이션" 표현을 사용한다.
- 매수/매도 추천 문구를 포함하지 않는다.
- 주문 API와 연결하지 않는다.

### rate limit

위험:

- live quote를 붙이면 Toss API rate limit과 latency 영향을 받는다.

완화:

- MVP는 DB-only로 구현한다.
- live quote는 cache, timeout, fallback, DataIngestionLog 또는 별도 event log
  정책을 설계한 뒤 추가한다.

### 민감정보

위험:

- portfolio 기능이 Toss holdings와 연결되면서 계좌 식별자가 섞일 수 있다.

완화:

- 이 API는 `UserHolding`, `Stock`, `DailyPrice`만 읽는다.
- account/token/header/raw response 필드는 response schema에 없다.
- username/email도 response에서 제외한다.

## 15. 단계별 구현 계획

### Step J1: Portfolio Summary service 구현

파일:

```text
portfolio/services/portfolio_summary_service.py
```

범위:

- `build_portfolio_summary(user)` 구현.
- DB-only 계산.
- `UserHolding`, `Stock`, `DailyPrice`만 사용.
- service 단위 테스트 작성.

### Step J2: Portfolio Summary API 구현

파일 후보:

```text
portfolio/serializers.py
portfolio/views.py
portfolio/urls.py
stock_service/urls.py
portfolio/tests.py
```

범위:

- `GET /api/portfolio/summary/`.
- `IsAuthenticated`.
- GET only.
- DB write 없음.
- Toss API 호출 없음.

### Step J3: 화면 연결 또는 API 문서화

범위:

- template 또는 프론트에서 portfolio summary 표시.
- 평가금액, 손익, 수익률, price coverage 표시.
- "최근 종가 기준" 문구 표시.

### Step J4: Optional live quote 설계

범위:

- Toss quote optional.
- 기본 off.
- cache/rate limit/timeout/fallback 설계.
- live quote 실패 시 latest DailyPrice fallback.

### Step J5: Additional Buy Simulation 설계로 연결

범위:

- portfolio summary의 holding별 invested/market value를 기반으로
  추가매수 시뮬레이션 API 설계.
- DB write 없음.
- 주문 API 없음.
- 투자 조언 오해 방지 문구 포함.
