# 01_codex_prompt.md

# Codex 실행 프롬프트: 1단계 Django Foundation 구현

## 사용 방법

이 파일은 Codex에 그대로 전달하기 위한 1단계 실행 프롬프트다.

Codex에게 이 파일과 함께 다음 문서를 참조하게 한다.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
```

Codex 실행 시에는 아래 “실행 프롬프트 본문” 전체를 복사해서 전달한다.

---

# 실행 프롬프트 본문

너는 Django REST Framework 기반 백엔드 서비스를 구현하는 개발 에이전트다.

이번 작업은 `물타기 타이밍 판단 시스템`의 **1단계 Foundation 구현**이다.

이 시스템은 주식 매수 추천 서비스가 아니다.  
사용자의 보유 종목에 대해 물타기, 즉 추가 매수 가능성을 검토할 수 있는 위험 구간인지 판단하기 위한 **투자 참고용 데이터 분석 시스템**이다.

아래 문서를 반드시 기준으로 삼아라.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
```

`00_overview_and_data.md`는 시스템의 최상위 기준 문서다.  
`01_foundation_design.md`는 이번 1단계에서 구현할 상세 설계서다.

---

# 1. 이번 작업의 목표

이번 단계의 목표는 계산 엔진을 만드는 것이 아니다.

이번 단계의 목표는 다음이다.

```text
1. Django REST Framework 기반 프로젝트 골격 구축
2. 핵심 앱 생성
3. 핵심 모델 구현
4. admin 등록
5. serializer 작성
6. 기본 ViewSet 또는 APIView 골격 작성
7. 기본 URL 라우팅 구성
8. services/ 디렉터리와 함수 시그니처 준비
9. 최소 smoke test 작성
10. 다음 단계에서 계산 엔진을 구현할 수 있는 안정적인 기반 마련
```

---

# 2. 반드시 구현할 앱

다음 앱을 구현하거나, 이미 존재한다면 설계에 맞게 정리하라.

```text
stocks
holdings
marketdata
indicators
decisions
```

각 앱의 책임은 다음과 같다.

| 앱 | 책임 |
|---|---|
| stocks | 종목 기본 정보 관리 |
| holdings | 사용자 보유 종목 관리 |
| marketdata | 일봉 가격, 시장 지수, 수급 데이터 관리 |
| indicators | 기술적 지표 저장 및 계산 준비 |
| decisions | 위험 이벤트와 물타기 판단 결과 이력 관리 |

---

# 3. 이번 단계에서 구현할 모델

다음 모델을 구현하라.

```text
Stock
UserHolding
DailyPrice
InvestorFlow
MarketIndex
TechnicalIndicator
RiskEvent
AveragingDecision
```

각 모델은 `docs/01_foundation_design.md`의 필드, 제약 조건, 인덱스, 기본값, choices를 기준으로 구현한다.

---

# 4. 모델 구현 상세 요구사항

## 4.1 Stock

앱 위치:

```text
stocks/models.py
```

필수 필드:

```text
code
name
market
sector
is_active
created_at
updated_at
```

요구사항:

```text
code는 unique=True, db_index=True
name은 db_index=True
market은 choices 사용
created_at, updated_at 포함
__str__ 구현
Meta.ordering = ["code"]
```

---

## 4.2 UserHolding

앱 위치:

```text
holdings/models.py
```

필수 필드:

```text
user
stock
average_price
quantity
max_additional_budget
risk_level
memo
created_at
updated_at
```

요구사항:

```text
user는 settings.AUTH_USER_MODEL 참조
stock은 stocks.Stock 참조
average_price는 DecimalField
quantity는 PositiveIntegerField
max_additional_budget은 DecimalField
risk_level은 conservative, normal, aggressive choices 사용
기본 risk_level은 normal
같은 사용자가 같은 종목을 중복 등록하지 못하도록 UniqueConstraint 설정
__str__ 구현
```

계산 속성 또는 serializer field로 다음 값을 제공할 준비를 하라.

```text
total_invested_amount = average_price * quantity
```

---

## 4.3 DailyPrice

앱 위치:

```text
marketdata/models.py
```

필수 필드:

```text
stock
date
open_price
high_price
low_price
close_price
volume
change_rate
created_at
updated_at
```

요구사항:

```text
stock + date UniqueConstraint
stock, -date 인덱스
date db_index=True
가격 필드는 DecimalField
volume은 BigIntegerField
Meta.ordering = ["-date"]
__str__ 구현
```

---

## 4.4 InvestorFlow

앱 위치:

```text
marketdata/models.py
```

필수 필드:

```text
stock
date
foreign_net_buy
institution_net_buy
individual_net_buy
program_net_buy
created_at
updated_at
```

요구사항:

```text
stock + date UniqueConstraint
date db_index=True
순매수 값은 음수 가능해야 하므로 BigIntegerField 사용
Meta.ordering = ["-date"]
__str__ 구현
```

---

## 4.5 MarketIndex

앱 위치:

```text
marketdata/models.py
```

필수 필드:

```text
code
name
date
close_value
change_rate
created_at
updated_at
```

요구사항:

```text
code + date UniqueConstraint
code와 date에 db_index=True
close_value는 DecimalField
Meta.ordering = ["-date", "code"]
__str__ 구현
```

---

## 4.6 TechnicalIndicator

앱 위치:

```text
indicators/models.py
```

필수 필드:

```text
stock
date
ma5
ma20
ma60
ma120
rsi14
macd
macd_signal
macd_histogram
atr14
volume_ma20
bb_upper
bb_middle
bb_lower
created_at
updated_at
```

요구사항:

```text
stock + date UniqueConstraint
stock, -date 인덱스
대부분의 지표 필드는 null=True, blank=True 허용
Meta.ordering = ["-date"]
__str__ 구현
```

---

## 4.7 RiskEvent

앱 위치:

```text
decisions/models.py
```

필수 필드:

```text
stock
event_type
title
source
url
event_date
risk_level
description
is_active
created_at
updated_at
```

요구사항:

```text
risk_level은 low, medium, high, critical choices 사용
is_active 기본값 True
stock, -event_date 인덱스
risk_level, is_active 인덱스
Meta.ordering = ["-event_date"]
__str__ 구현
```

---

## 4.8 AveragingDecision

앱 위치:

```text
decisions/models.py
```

필수 필드:

```text
holding
score
grade
decision
reason_summary
reasons
score_breakdown
suggested_budget
stop_loss_price
disclaimer
created_at
```

요구사항:

```text
holding은 holdings.UserHolding 참조
grade는 A, B, C, D choices 사용
reasons는 JSONField default=list
score_breakdown은 JSONField default=dict
suggested_budget은 DecimalField
stop_loss_price는 null=True, blank=True 허용
disclaimer 기본값 포함
holding, -created_at 인덱스
grade, -created_at 인덱스
Meta.ordering = ["-created_at"]
__str__ 구현
```

반드시 포함해야 하는 disclaimer 기본값:

```text
본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다.
```

---

# 5. admin 구현 요구사항

각 앱의 `admin.py`에 모델을 등록하라.

최소한 다음 모델은 admin에서 관리 가능해야 한다.

```text
Stock
UserHolding
DailyPrice
InvestorFlow
MarketIndex
TechnicalIndicator
RiskEvent
AveragingDecision
```

admin 구현 시 다음을 포함하라.

```text
list_display
list_filter
search_fields
ordering
date_hierarchy, 날짜 필드가 있는 경우
autocomplete_fields, FK가 있는 경우
```

단, `autocomplete_fields`를 사용하려면 참조 대상 admin에 `search_fields`가 있어야 한다.

---

# 6. serializer 구현 요구사항

각 앱에 `serializers.py`를 작성하라.

필수 serializer:

```text
StockSerializer
UserHoldingSerializer
DailyPriceSerializer
InvestorFlowSerializer
MarketIndexSerializer
TechnicalIndicatorSerializer
RiskEventSerializer
AveragingDecisionSerializer
```

## 6.1 공통 serializer 원칙

```text
1. FK 입력은 기본적으로 id로 받는다.
2. 조회 응답에는 stock_code, stock_name 등 읽기 전용 보조 필드를 포함한다.
3. UserHolding의 user는 request.user로 자동 설정할 수 있게 한다.
4. total_invested_amount는 읽기 전용 계산 필드로 제공한다.
5. DecimalField 값이 JSON에서 문자열로 표현될 수 있음을 고려한다.
```

## 6.2 UserHoldingSerializer 필수 읽기 전용 필드

```text
stock_code
stock_name
stock_market
total_invested_amount
```

## 6.3 AveragingDecisionSerializer 필수 읽기 전용 필드

```text
stock_code
stock_name
disclaimer
created_at
```

---

# 7. View와 URL 구현 요구사항

1단계에서는 복잡한 평가 로직을 구현하지 않는다.

다만 API 골격은 만든다.

## 7.1 필수 endpoint

다음 endpoint가 최소한 URL 오류 없이 동작해야 한다.

```text
/api/stocks/
/api/holdings/
/api/marketdata/daily-prices/
/api/marketdata/investor-flows/
/api/marketdata/market-indices/
/api/indicators/technical-indicators/
/api/decisions/risk-events/
/api/decisions/averaging-decisions/
/api/holdings/{id}/evaluate/
/api/holdings/{id}/decisions/
```

## 7.2 ViewSet 권장

가능하면 DRF `ModelViewSet`을 사용하라.

```text
StockViewSet
UserHoldingViewSet
DailyPriceViewSet
InvestorFlowViewSet
MarketIndexViewSet
TechnicalIndicatorViewSet
RiskEventViewSet
AveragingDecisionViewSet
```

## 7.3 UserHolding 접근 제한

`UserHoldingViewSet`은 반드시 현재 로그인 사용자 자신의 보유 종목만 반환해야 한다.

```python
def get_queryset(self):
    return UserHolding.objects.filter(user=self.request.user)
```

생성 시에는 request.user를 자동으로 주입한다.

```python
def perform_create(self, serializer):
    serializer.save(user=self.request.user)
```

## 7.4 AveragingDecision 접근 제한

`AveragingDecisionViewSet`도 반드시 현재 로그인 사용자의 holding에 연결된 결과만 반환해야 한다.

```python
def get_queryset(self):
    return AveragingDecision.objects.filter(holding__user=self.request.user)
```

---

# 8. evaluate endpoint placeholder

다음 endpoint를 만든다.

```http
POST /api/holdings/{id}/evaluate/
```

1단계에서는 실제 평가 엔진을 구현하지 않는다.

따라서 다음과 같은 placeholder 응답을 반환하라.

```json
{
  "detail": "Evaluation engine is not implemented in step 1. This endpoint will be completed in step 3.",
  "next_step": "Implement scoring engine services in step 2."
}
```

중요:

```text
이 endpoint에서 점수 계산 로직을 작성하지 말 것.
이 endpoint에서 투자 판단 결과를 만들지 말 것.
이 endpoint에서 임시로 A/B/C/D 등급을 계산하지 말 것.
```

---

# 9. holding decisions endpoint

다음 endpoint를 만든다.

```http
GET /api/holdings/{id}/decisions/
```

기능:

```text
현재 로그인 사용자의 특정 holding에 대한 AveragingDecision 이력을 최신순으로 반환한다.
다른 사용자의 holding에 접근하면 404 또는 permission denied를 반환한다.
```

---

# 10. services/ 디렉터리 구현 요구사항

1단계에서는 실제 계산 로직을 구현하지 않는다.

다만 2단계에서 사용할 파일과 함수 시그니처를 만들어 둔다.

## 10.1 marketdata/services/price_service.py

```python
def get_latest_price(stock):
    """Return the latest DailyPrice for the given stock."""
    raise NotImplementedError


def get_recent_prices(stock, limit=120):
    """Return recent DailyPrice records for the given stock."""
    raise NotImplementedError
```

## 10.2 marketdata/services/market_service.py

```python
def get_latest_market_index(code):
    """Return the latest MarketIndex by code."""
    raise NotImplementedError


def get_market_context(stock):
    """Return market context for the stock's market."""
    raise NotImplementedError
```

## 10.3 indicators/services/indicator_service.py

```python
def calculate_moving_average(prices, window):
    """Calculate simple moving average."""
    raise NotImplementedError


def calculate_rsi(prices, period=14):
    """Calculate RSI."""
    raise NotImplementedError


def calculate_macd(prices):
    """Calculate MACD values."""
    raise NotImplementedError


def calculate_atr(prices, period=14):
    """Calculate ATR."""
    raise NotImplementedError
```

## 10.4 decisions/services/risk_event_service.py

```python
def get_active_risk_events(stock):
    """Return active risk events for a stock."""
    raise NotImplementedError


def has_critical_risk(stock):
    """Return whether the stock has critical risk events."""
    raise NotImplementedError
```

## 10.5 decisions/services/scoring_service.py

```python
def calculate_total_score(*, trend_score, support_score, volume_score, flow_score, market_score, risk_score):
    """Calculate final score."""
    raise NotImplementedError


def convert_score_to_grade(score):
    """Convert score to A/B/C/D grade."""
    raise NotImplementedError
```

## 10.6 decisions/services/averaging_decision_service.py

```python
def evaluate_averaging_timing(holding):
    """Evaluate averaging down timing for a holding."""
    raise NotImplementedError


def create_decision_from_result(holding, result):
    """Persist AveragingDecision from evaluation result."""
    raise NotImplementedError
```

주의:

```text
1단계에서 위 함수 내부를 억지로 구현하지 말 것.
2단계 계산 엔진에서 구현할 수 있도록 구조만 준비할 것.
```

---

# 11. 테스트 구현 요구사항

1단계에서는 최소 smoke test와 모델 기본 테스트를 작성한다.

## 11.1 필수 테스트

다음 테스트를 작성하라.

```text
Stock 생성 가능
Stock code 중복 불가
UserHolding 생성 가능
같은 사용자가 같은 종목 중복 등록 불가
다른 사용자는 같은 종목 등록 가능
DailyPrice stock+date 중복 불가
InvestorFlow stock+date 중복 불가
TechnicalIndicator stock+date 중복 불가
RiskEvent critical 생성 가능
AveragingDecision 생성 시 disclaimer 포함
UserHolding API는 자기 데이터만 반환
evaluate endpoint placeholder 응답 확인
```

## 11.2 테스트 방식

기존 프로젝트가 pytest를 사용하면 pytest 기준으로 작성한다.  
그렇지 않으면 Django 기본 `TestCase`를 사용한다.

테스트 실행 명령어를 README 또는 작업 완료 메시지에 포함하라.

예:

```bash
python manage.py test
```

또는

```bash
pytest
```

---

# 12. 마이그레이션 요구사항

모델 구현 후 다음 명령어가 정상 실행되어야 한다.

```bash
python manage.py makemigrations
python manage.py migrate
```

마이그레이션 파일이 생성되어야 한다.

---

# 13. README 또는 작업 메모에 포함할 내용

작업 완료 후 다음 내용을 정리하라.

```text
1. 생성/수정한 앱 목록
2. 생성/수정한 모델 목록
3. 생성/수정한 serializer 목록
4. 생성/수정한 endpoint 목록
5. 마이그레이션 실행 방법
6. 테스트 실행 방법
7. 아직 구현하지 않은 항목
8. 다음 단계에서 해야 할 작업
```

---

# 14. 절대 하지 말아야 할 것

이번 단계에서 다음을 하지 마라.

```text
1. 실제 점수 계산 로직 구현
2. 실제 RSI/MACD/ATR 계산 구현
3. 외부 주식 API 연동
4. 뉴스 크롤러 구현
5. 공시 크롤러 구현
6. 자동 매매 기능 구현
7. 매수/매도 추천 문구 작성
8. views.py에 복잡한 비즈니스 로직 작성
9. 임의로 설계서의 모델 필드를 크게 축소
10. 오류를 숨기기 위해 테스트를 제거
```

---

# 15. 투자 참고용 고지 문구

모든 판단 결과와 관련된 모델 또는 응답에는 다음 문구를 기준으로 사용한다.

```text
본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다.
```

1단계에서는 `AveragingDecision.disclaimer` 기본값에 반드시 포함한다.

---

# 16. 품질 유지 규칙

작업이 길어져 품질이 떨어질 것 같으면 무리해서 모든 내용을 한 번에 끝내지 마라.

그럴 경우 다음 형식으로 멈춰라.

```text
현재까지 완료한 작업:
- ...

아직 남은 작업:
- ...

다음 단계에서 이어서 구현할 항목:
- ...
```

뒤로 갈수록 코드 품질이나 설명 밀도가 떨어지는 방식으로 작성하지 마라.

---

# 17. 최종 완료 응답 형식

작업이 끝나면 다음 형식으로 보고하라.

```text
1단계 Foundation 구현 완료

생성/수정한 파일:
- ...

구현한 모델:
- ...

구현한 API:
- ...

마이그레이션:
- python manage.py makemigrations
- python manage.py migrate

테스트:
- python manage.py test

아직 구현하지 않은 것:
- 실제 지표 계산
- 실제 점수 계산
- 실제 평가 API 로직
- 외부 데이터 연동

다음 단계:
02_scoring_engine_design.md 기준으로 계산 엔진을 구현한다.
```

---

# 18. 지금 바로 수행할 작업

이제 다음 순서로 작업하라.

```text
1. 현재 프로젝트 구조를 확인한다.
2. 필요한 앱이 없으면 생성한다.
3. settings.py에 앱과 DRF를 등록한다.
4. 모델을 구현한다.
5. admin을 구현한다.
6. serializer를 구현한다.
7. 기본 ViewSet과 URL을 구현한다.
8. evaluate placeholder endpoint를 구현한다.
9. holding decisions endpoint를 구현한다.
10. service skeleton 파일을 만든다.
11. 테스트를 작성한다.
12. makemigrations, migrate, test 실행이 가능하도록 정리한다.
13. 완료 보고를 작성한다.
```

반드시 `docs/00_overview_and_data.md`와 `docs/01_foundation_design.md`의 원칙을 따르라.
