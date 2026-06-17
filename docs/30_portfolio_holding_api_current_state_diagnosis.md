# Portfolio and Holding API Current State Diagnosis

## 1. 목적

이 문서는 현재 theStock의 Portfolio / Holding / Decision / Indicator /
MarketData 화면과 API 구조를 진단한다.

이번 단계의 목적은 기능 추가가 아니라, 이미 Toss OpenAPI로 저장된
`UserHolding`과 `DailyPrice`를 사용자 가치 기능으로 연결하기 전에 현재
구조, 가능한 흐름, 부족한 부분, 다음 구현 후보를 명확히 정리하는 것이다.

이번 문서는 코드, 설정, migration, DB schema, scheduler, 운영 데이터를
변경하지 않는다. 실제 Toss API 호출, no-network command 실행, 저장 command
실행, 주문 API 호출도 하지 않는다.

## 2. 현재 데이터 기반 상태

마지막 수동 검증 및 이번 진단 중 안전 조회 기준 상태:

| 항목 | 상태 |
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

현재 저장된 `UserHolding` 대표 row:

| 필드 | 값 |
|---|---|
| `user_id` | 6 |
| `stock_code` | 035250 |
| `stock_name` | 강원랜드 |
| `quantity` | 2 |
| `average_price` | 15116.50 |
| `is_active` | true |

현재 검증된 데이터 흐름:

- Toss holdings -> `UserHolding` 저장/skip/update 성공.
- Toss candle -> `DailyPrice` 저장/skip/update 성공.
- DailyPrice batch dry-run 성공.
- `DataIngestionLog` 기록 성공.
- 주문 API는 미구현/비활성.
- 자동매매 없음.

주의:

- `DailyPrice`는 아직 2건뿐이라 지표/확률/컨설팅 품질에는 부족하다.
- `UserHolding`은 1건뿐이라 portfolio summary는 제한적으로만 의미가 있다.
- `DataIngestionLog`는 운영 DB row이므로 no-network command도 이번 진단에서는
  실행하지 않았다.

## 3. 앱/파일 구조 요약

### holdings

주요 파일:

- `holdings/models.py`
- `holdings/serializers.py`
- `holdings/views.py`
- `holdings/urls.py`
- `holdings/admin.py`
- `holdings/services/sync_service.py`
- `holdings/services/stock_resolution_service.py`
- `holdings/management/commands/sync_transactions_to_holdings.py`
- `holdings/tests.py`

역할:

- 현재 사용자별 보유 원장인 `UserHolding`을 관리한다.
- DRF `UserHoldingViewSet`과 holding별 evaluate/probability/consult API를 제공한다.
- legacy `portfolio.Transaction`을 `UserHolding`으로 동기화하는 서비스가 있다.

### portfolio

주요 파일:

- `portfolio/models.py`
- `portfolio/views.py`
- `portfolio/admin.py`
- `portfolio/services.py`
- `portfolio/forms.py`
- `portfolio/templates/portfolio/*.html`
- `portfolio/static/portfolio/js/holding_consult.js`
- `portfolio/tests.py`

없는 파일:

- `portfolio/serializers.py`
- `portfolio/urls.py`

역할:

- Django template 기반 화면을 제공한다.
- legacy 거래 내역(`Transaction`)과 종목 매핑(`StockSymbol`)을 관리한다.
- `/consulting/holdings/`와 `/consulting/holdings/<pk>/` 화면에서 `UserHolding`
  기반 컨설팅 UI를 제공한다.
- portfolio app 자체 DRF API는 없다. URL은 `stock_service/urls.py`에 직접 등록된다.

### decisions

주요 파일:

- `decisions/models.py`
- `decisions/serializers.py`
- `decisions/views.py`
- `decisions/urls.py`
- `decisions/services/*.py`
- `decisions/tests.py`

없는 파일:

- `decisions/services.py`

역할:

- 추가매수/물타기 판단, 확률 계산, 컨설팅 리포트, 리스크 이벤트를 담당한다.
- `UserHolding`을 입력으로 받아 `AveragingDecision`,
  `AveragingProbabilityRecord`, `HoldingConsultRecord`를 생성할 수 있다.
- read-only decision history API와 risk event API를 제공한다.

### indicators

주요 파일:

- `indicators/models.py`
- `indicators/serializers.py`
- `indicators/views.py`
- `indicators/urls.py`
- `indicators/services/indicator_service.py`
- `indicators/tests.py`

없는 파일:

- `indicators/services.py`

역할:

- `TechnicalIndicator` 저장 모델과 indicator 계산 helper를 제공한다.
- moving average, RSI, MACD, ATR, volume MA, Bollinger Band 계산 함수가 있다.
- DRF `TechnicalIndicatorViewSet`이 있다.

### marketdata

주요 파일:

- `marketdata/models.py`
- `marketdata/serializers.py`
- `marketdata/views.py`
- `marketdata/urls.py`
- `marketdata/services/*.py`
- `marketdata/tests.py`

없는 파일:

- `marketdata/services.py`

역할:

- `DailyPrice`, `InvestorFlow`, `MarketIndex`, `StockDataCollectionStatus`를 관리한다.
- `get_latest_price`, `get_recent_prices` helper가 있다.
- DailyPrice/InvestorFlow/MarketIndex API를 제공한다.

### stocks

주요 파일:

- `stocks/models.py`
- `stocks/serializers.py`
- `stocks/views.py`
- `stocks/urls.py`
- `stocks/services/stock_quality_service.py`
- `stocks/tests.py`

역할:

- `Stock`과 `FinancialSnapshot`을 관리한다.
- stock master API와 stock quality 평가 service를 제공한다.

## 4. 모델 구조 분석

### Stock

모델: `stocks.models.Stock`

필드:

- `code`: `CharField(max_length=20, unique=True, db_index=True)`
- `name`: `CharField(max_length=100, db_index=True)`
- `market`: KOSPI/KOSDAQ/KONEX/ETF/ETN choices
- `sector`: optional text
- `is_active`
- `created_at`, `updated_at`

제약:

- `code` unique.
- 기본 ordering은 `code`.

진단:

- Toss 기반 DailyPrice/UserHolding 저장은 기존 `Stock` row가 있어야 한다.
- 현재 정책상 `Stock` 자동 생성은 금지되어 있다.

### DailyPrice

모델: `marketdata.models.DailyPrice`

필드:

- `stock` FK -> `stocks.Stock`
- `date`
- `open_price`
- `high_price`
- `low_price`
- `close_price`
- `volume`
- `change_rate`
- `created_at`, `updated_at`

제약:

- `(stock, date)` unique constraint: `unique_stock_daily_price`.
- index: `(stock, -date)`.
- 기본 ordering은 `-date`.

조회 helper:

- `marketdata.services.price_service.get_latest_price(stock)`
- `marketdata.services.price_service.get_recent_prices(stock, limit=120, ascending=True)`
- `extract_close_prices`, `extract_volumes`

진단:

- Portfolio summary의 latest close, 평가금액, 손익률 계산에 바로 사용할 수 있다.
- 지표/확률/컨설팅에는 최근 20~120개 이상의 가격 row가 필요하므로 현재 2건은 부족하다.

### UserHolding

모델: `holdings.models.UserHolding`

필드:

- `user` FK
- `stock` FK
- `average_price`
- `quantity`
- `is_active`
- `max_additional_budget`
- `risk_level`
- `memo`
- `created_at`, `updated_at`

제약:

- `(user, stock)` unique constraint: `unique_user_stock_holding`.
- 기본 ordering은 `-updated_at`, `-id`.

현재 입력/수정 방식:

- `/api/holdings/` DRF CRUD.
- Toss holdings sync command의 guarded commit path.
- legacy transaction sync service.
- Django admin.

진단:

- 현재 schema는 KR/KRW 정수 수량 보유에 적합하다.
- `currency`, `account`, `provider/source`, fractional quantity 필드가 없다.
- US/USD/소수점 수량/다중 계좌 holdings는 현 모델에 직접 반영하기 어렵다.

### Portfolio

모델:

- `portfolio.Transaction`
- `portfolio.StockSymbol`

연결:

- `Transaction`은 `Stock` FK가 없고 `stock_name` 문자열 기반이다.
- `StockSymbol`은 legacy 종목명을 ticker로 매핑한다.
- `holdings.services.sync_service`가 legacy 거래를 `UserHolding`으로 동기화한다.

진단:

- legacy portfolio 화면과 신규 `UserHolding` consulting 화면이 병존한다.
- legacy transaction 수정/업로드 후 sync service가 `UserHolding`을 만들거나 갱신할 수 있다.
- Toss holdings sync와 legacy sync의 소유권/우선순위 정책은 아직 통합되지 않았다.

### Decision

모델:

- `RiskEvent`
- `AveragingDecision`
- `AveragingProbabilityRecord`
- `HoldingConsultRecord`

연결:

- `AveragingDecision`, `AveragingProbabilityRecord`, `HoldingConsultRecord`는
  모두 `UserHolding` FK를 가진다.
- 판단/확률/컨설팅은 `UserHolding + DailyPrice + InvestorFlow + MarketIndex +
  RiskEvent + Stock/FinancialSnapshot` 계열 데이터를 사용한다.

저장 여부:

- evaluate/probability/consult POST API는 결과 record를 저장한다.
- decision list API는 read-only다.

### Indicator

모델:

- `TechnicalIndicator`

연결:

- `stock` FK와 `date`를 가진다.
- `(stock, date)` unique.

계산:

- `indicators.services.indicator_service`에 MA/RSI/MACD/ATR/Bollinger 계산 함수가 있다.
- decision service는 저장된 `TechnicalIndicator`보다 최근 `DailyPrice` rows로 indicator snapshot을 직접 계산한다.

진단:

- 지표 저장 API는 있으나, 현재 추가매수 판단 MVP는 저장된 indicator 없이도 `DailyPrice` 기반 계산이 가능하다.
- 가격 이력 부족 시 indicator 계산 결과가 `None`이 된다.

## 5. API/View/Serializer 구조 분석

### holdings API

등록:

- `/api/holdings/`
- `/api/holdings/<id>/evaluate/`
- `/api/holdings/<id>/decisions/`
- `/api/holdings/<id>/probability/`
- `/api/holdings/<id>/probabilities/`
- `/api/holdings/<id>/consult/`
- `/api/holdings/<id>/consults/`

특징:

- `UserHoldingViewSet`은 `ModelViewSet`이다.
- queryset은 `UserHolding.objects.filter(user=self.request.user)`로 사용자별 제한된다.
- 기본적으로 inactive row를 제외하고, `include_inactive=true` 또는 `is_active` query로 조정 가능하다.
- create 시 `serializer.save(user=self.request.user)`를 사용한다.
- serializer는 `stock_code`, `stock_name`, `stock_market`, `total_invested_amount`를 노출한다.

read/write:

- `/api/holdings/`는 CRUD 가능.
- evaluate/probability/consult POST는 계산 결과 record를 저장한다.
- history endpoint는 read-only.

### portfolio API

현황:

- `portfolio/serializers.py`, `portfolio/urls.py`가 없다.
- portfolio app 자체 DRF API는 없다.
- `stock_service/urls.py`에 template view와 `api/charts/summary/` JSON endpoint가 직접 등록된다.

기존 JSON endpoint:

- `/api/charts/summary/`: legacy `Transaction` summary용.

진단:

- 현재 의미의 `GET /api/portfolio/summary/` 또는 `GET /api/holdings/summary/`는 없다.
- Portfolio Summary API는 새로 설계/구현해야 한다.

### decisions API

등록:

- `/api/decisions/risk-events/`
- `/api/decisions/averaging-decisions/`
- `/api/decisions/probability-records/`
- `/api/decisions/consult-records/`

특징:

- `RiskEventViewSet`은 authenticated read/staff write.
- decision/probability/consult record ViewSet은 `ReadOnlyModelViewSet`.
- decision/probability/consult records는 `holding__user=self.request.user`로 owner scope가 적용된다.

read/write:

- history 조회 API는 read-only.
- 결과 생성은 `/api/holdings/<id>/.../` POST endpoint에서 수행한다.

### indicators API

등록:

- `/api/indicators/`

특징:

- `TechnicalIndicatorViewSet`은 `ModelViewSet`.
- serializer는 stock, stock_code, stock_name, date, MA/RSI/MACD/ATR/Bollinger fields를 노출한다.

주의:

- viewset에 명시적 permission class가 보이지 않는다.
- 프로젝트 기본 DRF permission에 의존한다면 안전하지만, 기본값 변경 시 쓰기 노출 위험을 검토해야 한다.

### marketdata API

등록:

- `/api/marketdata/daily-prices/`
- `/api/marketdata/investor-flows/`
- `/api/marketdata/market-indices/`

특징:

- 각 ViewSet은 `ModelViewSet`.
- `AuthenticatedReadOnlyOrStaffWrite` permission이 적용된다.
- 일반 인증 사용자는 read-only, staff만 write 가능 구조다.

### stocks API

등록:

- `/api/stocks/`

특징:

- `StockViewSet`은 `ModelViewSet`.
- `AuthenticatedReadOnlyOrStaffWrite` permission이 적용된다.

### owner scope / 민감정보

owner scope:

- `UserHolding` 및 decision record 계열은 사용자별 scope가 적용되어 있다.
- marketdata/stocks/indicators는 공용 시장 데이터 성격이라 사용자별 scope가 아니다.

민감정보:

- 현재 모델/serializer에는 Toss accountNo/accountSeq/token/header 같은 민감정보 필드가 없다.
- `UserHolding`에는 계좌 식별자를 저장하지 않는다.

## 6. URL/화면 구조 분석

프론트엔드 구조:

- Django template 기반이다.
- React/Vue/Next/Vite/package.json 구조는 확인되지 않았다.
- 정적 JS/CSS는 `portfolio/static/portfolio/`와 `staticfiles/portfolio/`에 있다.

주요 화면:

- `/`: landing.
- `/workspace/`: legacy dashboard.
- `/transactions/`: legacy transaction list.
- `/upload/`: CSV upload.
- `/prices/`: price board.
- `/analysis/`: legacy transaction 기반 회고 분석.
- `/consulting/holdings/`: `UserHolding` 기반 컨설팅 목록.
- `/consulting/holdings/<pk>/`: `UserHolding` 기반 컨설팅 상세.
- `/operations/data-pipeline/`: 운영 데이터 파이프라인 현황.

중요 화면 동작:

- `portfolio/static/portfolio/js/holding_consult.js`는 컨설팅 상세 페이지 로드 시
  `POST /api/holdings/<id>/consult/`를 자동 호출한다.
- 따라서 컨설팅 상세 페이지는 read-only 화면처럼 보이지만 consult record를 생성할 수 있다.

## 7. 현재 데이터 흐름 진단

| 흐름 | 상태 | 설명 |
|---|---|---|
| Toss holdings -> UserHolding 저장 | 가능 | 실제 save/skip/update 검증 완료 |
| Toss candle -> DailyPrice 저장 | 가능 | single-symbol save/skip/update 검증 완료 |
| UserHolding + DailyPrice -> 현재 평가금액 | 부분 가능 | latest DailyPrice가 있으면 계산 가능. 현재 가격 row가 적음 |
| UserHolding + quote -> 실시간 평가금액 | 필요 구현 | Toss quote 경로는 검증됐지만 화면/API 연결은 없음 |
| UserHolding + indicators -> 추가매수 판단 | 부분 가능 | `DailyPrice` 이력이 충분하면 service에서 계산 가능. 현재 이력 부족 |
| UserHolding + decisions -> 물타기/추가매수 리포트 | 가능하지만 기록 생성 | consult/evaluate/probability POST 구현됨. 호출 시 record 저장 |
| Portfolio summary API | 불가능 | 전용 API 미구현 |
| Legacy Transaction -> UserHolding | 가능 | legacy sync service 존재 |

## 8. Portfolio Summary 가능성

후보 API:

- `GET /api/portfolio/summary/`
- `GET /api/holdings/summary/`

현재 모델만으로 가능한 항목:

- user 기준 `UserHolding` 목록.
- stock code/name/market/sector.
- quantity.
- average_price.
- invested_amount = `average_price * quantity`.
- risk_level.
- max_additional_budget.
- is_active.

`DailyPrice`만으로 가능한 항목:

- latest close.
- latest close date.
- market_value = latest close * quantity.
- profit_loss_amount = market_value - invested_amount.
- profit_loss_rate.

추가 API 호출이 필요한 항목:

- 실시간 현재가 기반 평가금액.
- 장중 price 변동 반영.
- Toss quote rate-limit 고려가 필요한 live quote.

지금 바로 read-only API로 만들 수 있는 항목:

- DB의 `UserHolding + latest DailyPrice` 기반 portfolio summary.
- Toss API 호출 없음.
- DB 저장 없음.
- 민감정보 없음.
- owner scope는 `request.user` 기준으로 적용 가능.

위험 요소:

- `DailyPrice`가 없는 holding은 평가금액/손익률이 `null` 또는 데이터 없음이 된다.
- 현재 `DailyPrice` count가 2라 많은 종목이 최신가 없음 상태일 가능성이 높다.
- 실시간 quote를 섞으면 rate limit, 실패 fallback, 캐시 정책이 필요하다.

## 9. 추가매수/물타기 판단 리포트 가능성

후보 API:

- `GET /api/decisions/additional-buy-report/`
- 또는 holding 단위 `POST /api/holdings/<id>/additional-buy-simulation/`

입력 후보:

- user.
- holding/stock.
- additional_budget.
- optional target_price.

현재 모델만으로 가능한 계산:

- 현재 보유 수량.
- 현재 평균단가.
- 투입 원금.
- 추가매수 가능 수량: `additional_budget / 기준가`.
- 추가매수 후 총 수량.
- 추가매수 후 평균단가.
- 손익분기점.
- 목표 회복가 대비 필요 상승률.

`DailyPrice`가 필요한 계산:

- latest close 기반 현재 손익률.
- latest close 기반 추가매수 가능 수량.
- latest close 기반 평가금액.

quote가 필요한 계산:

- 실시간 현재가 기반 평가금액.
- 실시간 현재가 기반 추가매수 가능 수량.

indicators가 필요한 계산:

- MA/RSI/MACD/ATR/Bollinger 기반 기술적 상태 요약.
- 지지/저항, 추세, 변동성 기반 보수적 판단.

백테스트/확률 보정이 필요한 계산:

- 성공/실패/중립 확률.
- scenario comparison.
- historical similar-case 기반 설명.
- confidence 산출.

현재 구현된 판단 로직:

- `evaluate_averaging_timing(holding)`은 `DailyPrice`, investor flow, market
  context, risk event를 종합해 score/grade/decision/suggested_budget을 만든다.
- `/api/holdings/<id>/evaluate/`는 `AveragingDecision`을 저장한다.
- `/api/holdings/<id>/probability/`는 probability record를 저장한다.
- `/api/holdings/<id>/consult/`는 종합 consulting record를 저장한다.

지금 바로 구현 가능한 MVP 범위:

- DB 저장 없는 read-only 추가매수 시뮬레이션 API.
- `UserHolding + latest DailyPrice` 기반 평균단가/손익분기/필요상승률 계산.
- 주문 실행 없음.
- Toss API 호출 없음.
- 결과 record 저장 없음.

위험 요소:

- 사용자가 리포트를 매수 권유로 오해하지 않도록 disclaimer가 필요하다.
- sparse DailyPrice 상태에서는 latest close가 없을 수 있다.
- 실제 주문 API와 연결하지 않는다는 정책을 명확히 유지해야 한다.

## 10. 부족한 부분과 위험 요소

- `DailyPrice`가 아직 2건뿐이라 지표 계산에는 부족하다.
- `UserHolding`이 1건뿐이라 portfolio summary는 제한적이다.
- quote 실시간 조회를 화면에서 매번 호출할지, command/API에서 캐시할지 결정이 필요하다.
- DailyPrice batch commit은 아직 미구현이다.
- UserHolding 대량 commit은 아직 보류 상태다.
- US/fractional holdings는 현재 `UserHolding` 모델에 맞지 않는다.
- `UserHolding`에 currency 필드가 없다.
- `UserHolding`에 account/provider/source 필드가 없다.
- scheduler 자동화는 실제 등록하지 않았다.
- 컨설팅 상세 화면은 자동 POST로 `HoldingConsultRecord`를 생성할 수 있다.
- legacy transaction 기반 화면과 `UserHolding` 기반 화면이 아직 완전히 통합되지 않았다.
- 주문 API는 계속 금지해야 한다.

## 11. 다음 구현 후보

### 후보 1. Read-only Portfolio Summary API

내용:

- `UserHolding + latest DailyPrice` 기반.
- Toss API 호출 없음.
- DB 저장 없음.
- 민감정보 없음.
- owner scope는 `request.user`.

장점:

- 사용자 가치가 즉시 높다.
- 구현 위험이 낮다.
- 현재 저장된 Toss holdings와 DailyPrice를 화면/API 가치로 연결한다.

추천 상태:

- 1순위.

### 후보 2. Portfolio Summary + live quote optional

내용:

- `UserHolding + Toss quote` 기반 실시간 평가금액 옵션.

장점:

- 실시간성이 높다.

주의:

- 네트워크 호출, rate limit, 장애 fallback, 캐시 정책이 필요하다.
- 기본 API는 DB 기반 read-only로 두고 live quote는 명시 옵션으로 분리하는 것이 안전하다.

추천 상태:

- 2순위 또는 1순위 구현 후 확장.

### 후보 3. Additional Buy Simulation API

내용:

- `UserHolding` 기반 평균단가/손익분기/필요상승률 시뮬레이션.
- 주문 실행 없음.
- DB 저장 없는 read-only 계산.

장점:

- 사용자 가치가 매우 높다.
- 현재 `UserHolding` 모델만으로도 MVP 가능하다.

주의:

- 투자 권유가 아니라 참고용 계산임을 명확히 해야 한다.
- 실시간 quote 없이 latest DailyPrice만 사용하면 기준일 표시가 필요하다.

추천 상태:

- 3순위이지만 제품 가치가 높아 Portfolio Summary 직후 진행 가능.

### 후보 4. DailyPrice batch commit 설계

내용:

- batch dry-run 결과를 기반으로 guarded commit 설계.

장점:

- 분석/컨설팅 품질을 직접 개선한다.

주의:

- 저장 리스크가 있다.
- symbol limit, rollback, partial failure, DataIngestionLog counts 정책이 필요하다.

추천 상태:

- 화면/API MVP 이후 진행 추천.

## 12. 추천 다음 단계

추천 순서:

1. `Read-only Portfolio Summary API` 설계.
2. `Read-only Portfolio Summary API` 구현.
3. Portfolio Summary 화면 또는 기존 holdings list에 summary 표시.
4. `Additional Buy Simulation API` 설계.
5. `Additional Buy Simulation API` 구현.
6. DailyPrice batch commit 설계.

권장 MVP:

```text
GET /api/portfolio/summary/
```

초기 응답 범위:

- holding id.
- stock code/name/market.
- quantity.
- average_price.
- invested_amount.
- latest_close_price.
- latest_price_date.
- market_value.
- profit_loss_amount.
- profit_loss_rate.
- risk_level.
- max_additional_budget.
- data_status: `ok` / `missing_daily_price`.

초기 정책:

- read-only.
- DB 저장 없음.
- Toss API 호출 없음.
- owner scope는 `request.user`.
- 주문 API 없음.
- 자동매매 없음.

## 13. 보류/금지 항목

보류:

- Portfolio Summary live quote 자동 호출.
- DailyPrice batch commit.
- UserHolding 대량 commit.
- US/fractional holdings schema 확장.
- multi-account holdings model.
- scheduler commit profile.

금지:

- 주문 생성/정정/취소 API 구현 또는 호출.
- Order API / Order History API / Order Info API 호출.
- 자동매매.
- accountNo/accountSeq/token/header/raw response 저장 또는 출력.
- `UserHolding` owner scope 약화.
- `Stock` 자동 생성 기반 portfolio summary.

