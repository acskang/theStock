# 05_codex_prompt.md

# Codex 실행 프롬프트: 5단계 Probability Engine 구현

## 사용 방법

이 파일은 Codex에 그대로 전달하기 위한 5단계 실행 프롬프트다.

Codex에게 이 파일과 함께 다음 문서를 반드시 참조하게 한다.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
docs/03_api_workflow_design.md
docs/04_quality_release_design.md
docs/05_probability_engine_design.md
```

이번 단계의 직접 기준 문서는 다음이다.

```text
docs/05_probability_engine_design.md
```

---

# 실행 프롬프트 본문

너는 Django REST Framework 기반 백엔드 서비스에 확률 계산 엔진을 추가하는 개발 에이전트다.

이번 작업은 `물타기 타이밍 판단 시스템`의 **5단계 Probability Engine 구현**이다.

기존 시스템은 다음 질문에 답한다.

```text
지금 이 종목을 추가 매수해도 되는 위험 구간인가?
```

이번 단계에서 추가할 Probability Engine은 다음 질문에 답한다.

```text
특정 가격과 수량으로 물타기를 실행한다고 가정했을 때,
정해진 기간 안에 목표 회복 가격에 먼저 도달할 추정 확률은 얼마인가?
반대로 손절 또는 위험 기준에 먼저 도달할 추정 확률은 얼마인가?
```

이 확률은 미래를 보장하는 값이 아니다.  
과거 데이터, 현재 점수, 변동성, 위험 이벤트를 기반으로 계산한 **조건부 추정 확률**이다.

---

# 1. 반드시 참조할 문서

아래 문서를 기준으로 구현하라.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
docs/03_api_workflow_design.md
docs/04_quality_release_design.md
docs/05_probability_engine_design.md
```

문서 우선순위는 다음과 같다.

```text
1. 00_overview_and_data.md
   - 시스템 철학
   - 투자 참고용 원칙
   - 매수/매도 추천 금지

2. 05_probability_engine_design.md
   - 이번 단계의 직접 구현 기준
   - 확률 공식
   - dataclass
   - service 함수
   - API 확장

3. 02_scoring_engine_design.md
   - 기존 Scoring Engine 호출 기준
   - evaluate_averaging_timing
   - score, grade, score_breakdown 구조

4. 03_api_workflow_design.md
   - 인증, 권한, holding owner 제한
   - API 응답 구조 원칙

5. 04_quality_release_design.md
   - 테스트, 품질, 로그, edge case 처리 기준
```

---

# 2. 이번 작업의 목표

이번 단계의 목표는 다음이다.

```text
1. 물타기 시나리오 입력 구조 구현
2. 새 평균단가 계산
3. 목표 가격 계산
4. 손절 기준 가격 계산
5. Historical Component 구현
6. Score Component 구현
7. Volatility Component 구현
8. Risk Hard Override 구현
9. 세 component 결합 로직 구현
10. confidence 계산
11. success/failure/confidence label 계산
12. ProbabilityResult 반환 구조 구현
13. POST /api/holdings/{id}/probability/ API 추가
14. 권한 처리
15. 테스트 작성
```

---

# 3. 이번 단계의 구현 범위

이번 단계에서는 **확률 계산 API를 추가하되 DB 저장은 하지 않는다.**

즉, 다음은 구현한다.

```text
1. decisions/services/probability_service.py
2. decisions/services/probability_dataclasses.py
3. decisions/services/probability_labels.py
4. decisions/services/probability_components.py
5. probability request serializer
6. probability response serializer
7. POST /api/holdings/{id}/probability/ API
8. 단위 테스트 및 API 테스트
```

다음은 구현하지 않는다.

```text
1. AveragingProbabilityResult DB 모델 생성
2. 확률 계산 결과 DB 저장
3. migration 생성
4. 외부 주식 API 연동
5. 뉴스/공시 크롤러
6. 자동 매매
7. 프론트엔드 화면
```

단, 이미 프로젝트에 확률 결과 저장 모델이 존재한다면 건드리지 말고, 이번 단계에서는 계산과 API 응답만 구현한다.

---

# 4. 절대 하지 말아야 할 것

```text
1. 확률을 수익 보장처럼 표현하지 말 것
2. success_probability만 반환하지 말 것
3. failure_probability를 단순히 1 - success_probability로 계산하지 말 것
4. neutral_probability를 누락하지 말 것
5. critical risk를 일반 점수로 희석하지 말 것
6. 다른 사용자의 holding을 조회하지 말 것
7. View에서 수학 계산 로직을 직접 작성하지 말 것
8. Serializer에서 수학 계산 로직을 직접 작성하지 말 것
9. 기존 Scoring Engine을 임의로 대체하지 말 것
10. 데이터 부족을 조용히 숨기지 말 것
```

---

# 5. 구현 파일 구조

다음 구조를 권장한다.

```text
decisions/
 ├── services/
 │   ├── probability_dataclasses.py
 │   ├── probability_labels.py
 │   ├── probability_components.py
 │   └── probability_service.py
 ├── serializers.py
 ├── views.py
 ├── urls.py
 └── tests/
     ├── test_probability_formulas.py
     ├── test_probability_historical.py
     ├── test_probability_score.py
     ├── test_probability_volatility.py
     ├── test_probability_service.py
     └── test_probability_api.py
```

프로젝트가 앱별 단일 `tests.py` 구조라면 기존 스타일에 맞춰도 된다.  
하지만 함수가 많아지므로 가능하면 테스트 파일을 분리하라.

---

# 6. dataclass 구현

## 6.1 AveragingScenario

파일 위치:

```text
decisions/services/probability_dataclasses.py
```

구현:

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class AveragingScenario:
    buy_price: Decimal
    buy_quantity: int
    lookahead_days: int = 20
    target_type: str = "new_average_price"
    target_profit_rate: Decimal = Decimal("0")
    stop_loss_type: str = "support_or_atr"
    stop_loss_price: Optional[Decimal] = None
    same_day_hit_policy: str = "conservative"
```

검증은 dataclass 내부보다는 service 또는 serializer에서 수행한다.

---

## 6.2 ProbabilityComponent

파일 위치:

```text
decisions/services/probability_dataclasses.py
```

구현:

```python
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class ProbabilityComponent:
    success: Decimal
    failure: Decimal
    neutral: Decimal
    weight: Decimal
    confidence: Decimal
    sample_count: int = 0
    details: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
```

---

## 6.3 HistoricalCaseOutcome

파일 위치:

```text
decisions/services/probability_dataclasses.py
```

구현:

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class HistoricalCaseOutcome:
    base_date: date
    base_close: Decimal
    target_price: Decimal
    stop_loss_price: Decimal
    outcome: str
    days_to_outcome: Optional[int]
    max_favorable_return: Decimal
    max_adverse_return: Decimal
```

`outcome` 허용값:

```text
success
failure
neutral
ambiguous
```

---

## 6.4 ProbabilityResult

파일 위치:

```text
decisions/services/probability_dataclasses.py
```

구현:

```python
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class ProbabilityResult:
    success_probability: Decimal
    failure_probability: Decimal
    neutral_probability: Decimal

    success_label: str
    failure_label: str
    confidence: Decimal
    confidence_label: str

    target_price: Decimal
    stop_loss_price: Decimal
    new_average_price: Decimal
    lookahead_days: int

    basis: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = (
        "본 결과는 과거 데이터와 현재 조건 기반의 추정 확률이며, "
        "매수·매도 추천이 아닙니다. 미래 수익 또는 손실 회피를 보장하지 않습니다."
    )
```

---

# 7. 유틸 함수 구현

파일 위치:

```text
decisions/services/probability_components.py
```

다음 함수를 구현하라.

```python
def clamp(value, min_value, max_value):
    ...


def quantize_probability(value):
    ...


def normalize_probabilities(success, failure, neutral):
    ...


def sigmoid(value):
    ...


def normal_cdf(value):
    ...
```

## 7.1 clamp

```python
def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))
```

Decimal 기준으로 처리한다.

---

## 7.2 quantize_probability

확률은 Decimal 소수점 4자리로 통일한다.

```python
from decimal import Decimal, ROUND_HALF_UP

PROBABILITY_QUANT = Decimal("0.0001")


def quantize_probability(value: Decimal) -> Decimal:
    return value.quantize(PROBABILITY_QUANT, rounding=ROUND_HALF_UP)
```

---

## 7.3 normalize_probabilities

요구사항:

```text
1. success, failure, neutral이 음수이면 0으로 보정
2. 합계가 0이면 success=0, failure=0, neutral=1 반환
3. 합계가 1이 아니면 세 값을 합계로 나누어 정규화
4. 반환값은 모두 Decimal 4자리
5. 반올림 후 합계 오차가 생기면 neutral에 보정
```

반환:

```python
{
    "success": Decimal("0.6200"),
    "failure": Decimal("0.2500"),
    "neutral": Decimal("0.1300"),
}
```

---

## 7.4 sigmoid

```python
import math
from decimal import Decimal


def sigmoid(value):
    return Decimal(str(1 / (1 + math.exp(-float(value)))))
```

---

## 7.5 normal_cdf

```python
import math
from decimal import Decimal


def normal_cdf(value):
    return Decimal(str(0.5 * (1 + math.erf(float(value) / math.sqrt(2)))))
```

---

# 8. 가격 공식 구현

파일 위치:

```text
decisions/services/probability_service.py
```

또는 수식이 많아지면:

```text
decisions/services/probability_components.py
```

---

## 8.1 calculate_new_average_price

구현:

```python
def calculate_new_average_price(
    current_average_price: Decimal,
    current_quantity: int,
    buy_price: Decimal,
    buy_quantity: int,
) -> Decimal:
    ...
```

공식:

```text
new_average_price =
    (current_average_price * current_quantity + buy_price * buy_quantity)
    /
    (current_quantity + buy_quantity)
```

검증:

```text
current_average_price > 0
current_quantity > 0
buy_price > 0
buy_quantity > 0
```

조건 위반 시 `ValueError`.

---

## 8.2 calculate_target_price

구현:

```python
def calculate_target_price(
    *,
    current_average_price: Decimal,
    current_quantity: int,
    buy_price: Decimal,
    buy_quantity: int,
    target_type: str,
    target_profit_rate: Decimal = Decimal("0"),
    manual_target_price: Optional[Decimal] = None,
) -> Decimal:
    ...
```

지원 target_type:

```text
new_average_price
new_average_price_plus_profit
manual
```

처리:

```text
new_average_price:
    target_price = new_average_price

new_average_price_plus_profit:
    target_price = new_average_price * (1 + target_profit_rate)

manual:
    manual_target_price 필수
```

검증:

```text
target_profit_rate >= 0
manual_target_price > 0
지원하지 않는 target_type이면 ValueError
```

---

## 8.3 calculate_probability_stop_loss_price

구현:

```python
def calculate_probability_stop_loss_price(
    *,
    current_price: Decimal,
    stop_loss_type: str,
    manual_stop_loss_price: Optional[Decimal] = None,
    support_price: Optional[Decimal] = None,
    atr14: Optional[Decimal] = None,
    fixed_rate: Decimal = Decimal("0.07"),
) -> Decimal:
    ...
```

지원 stop_loss_type:

```text
support_or_atr
manual
fixed_rate
atr
support
```

처리 우선순위:

```text
manual:
    manual_stop_loss_price 사용

support:
    support_price * 0.97

atr:
    current_price - atr14 * 1.5

fixed_rate:
    current_price * (1 - fixed_rate)

support_or_atr:
    1. support_price가 있으면 support_price * 0.97
    2. atr14가 있으면 current_price - atr14 * 1.5
    3. fallback current_price * 0.93
```

검증:

```text
current_price > 0
manual_stop_loss_price는 0보다 크고 current_price보다 작아야 함
fixed_rate는 0보다 크고 1보다 작아야 함
지원하지 않는 stop_loss_type이면 ValueError
```

---

# 9. 라벨 함수 구현

파일 위치:

```text
decisions/services/probability_labels.py
```

구현 함수:

```python
def get_success_probability_label(probability: Decimal) -> str:
    ...


def get_failure_probability_label(probability: Decimal) -> str:
    ...


def get_confidence_label(confidence: Decimal) -> str:
    ...
```

## 9.1 success label

| success_probability | label |
|---:|---|
| 0.75 이상 | 높음 |
| 0.55 ~ 0.7499 | 보통 이상 |
| 0.40 ~ 0.5499 | 중립 |
| 0.25 ~ 0.3999 | 낮음 |
| 0.25 미만 | 매우 낮음 |

---

## 9.2 failure label

| failure_probability | label |
|---:|---|
| 0.60 이상 | 매우 위험 |
| 0.40 ~ 0.5999 | 위험 |
| 0.25 ~ 0.3999 | 주의 |
| 0.25 미만 | 상대적으로 낮음 |

---

## 9.3 confidence label

| confidence | label |
|---:|---|
| 0.75 이상 | 높음 |
| 0.50 ~ 0.7499 | 보통 |
| 0.25 ~ 0.4999 | 낮음 |
| 0.25 미만 | 매우 낮음 |

---

# 10. Score Component 구현

파일 위치:

```text
decisions/services/probability_components.py
```

구현:

```python
def calculate_score_component(
    *,
    score: int,
    grade: str,
    active_risk_events=None,
) -> ProbabilityComponent:
    ...
```

## 10.1 성공확률 공식

```text
score_success = sigmoid((score - 55) / 10)
```

## 10.2 실패확률 공식

```text
score_failure = sigmoid((45 - score) / 10)
```

## 10.3 중립확률

```text
score_neutral = 1 - score_success - score_failure
```

정규화:

```text
normalize_probabilities(score_success, score_failure, score_neutral)
```

## 10.4 risk event 보정

critical risk는 여기서 처리하지 말고 main service hard override에서 처리한다.

high risk:

```text
success *= 0.75
failure += 0.20
```

medium risk:

```text
success *= 0.90
failure += 0.10
```

low risk:

```text
success *= 0.95
failure += 0.05
```

보정 후 반드시 정규화한다.

---

# 11. Volatility Component 구현

파일 위치:

```text
decisions/services/probability_components.py
```

구현:

```python
def calculate_volatility_component(
    *,
    current_price: Decimal,
    target_price: Decimal,
    stop_loss_price: Decimal,
    price_rows,
    atr14: Optional[Decimal],
    lookahead_days: int,
    trend_score: int = 0,
) -> ProbabilityComponent:
    ...
```

## 11.1 target_return

```text
target_return = (target_price - current_price) / current_price
```

## 11.2 stop_loss_return

```text
stop_loss_return = (current_price - stop_loss_price) / current_price
```

## 11.3 daily volatility

우선순위:

```text
1. 최근 종가 로그수익률 표준편차
2. ATR14 / current_price
3. fallback Decimal("0.02")
```

로그수익률:

```text
log_return_t = ln(close_t / close_{t-1})
```

floor/cap:

```text
daily_volatility = max(daily_volatility, Decimal("0.005"))
daily_volatility = min(daily_volatility, Decimal("0.15"))
```

## 11.4 horizon volatility

```text
horizon_volatility = daily_volatility * sqrt(lookahead_days)
```

## 11.5 barrier touch probability

```text
p_touch_up = 2 * (1 - normal_cdf(target_return / horizon_volatility))
p_touch_down = 2 * (1 - normal_cdf(stop_loss_return / horizon_volatility))
```

clamp:

```text
0 <= p_touch_up <= 0.98
0 <= p_touch_down <= 0.98
```

## 11.6 barrier success/failure ratio

```text
barrier_success_ratio = stop_loss_return / (target_return + stop_loss_return)
barrier_failure_ratio = target_return / (target_return + stop_loss_return)
```

trend 보정:

```text
trend_adjustment = (trend_score - 12.5) / 100
barrier_success_ratio = clamp(barrier_success_ratio + trend_adjustment, 0.05, 0.95)
barrier_failure_ratio = 1 - barrier_success_ratio
```

## 11.7 최종 volatility 확률

```text
volatility_success = p_touch_up * barrier_success_ratio
volatility_failure = p_touch_down * barrier_failure_ratio
volatility_neutral = 1 - volatility_success - volatility_failure
```

반드시 정규화한다.

---

# 12. Historical Component 구현

파일 위치:

```text
decisions/services/probability_components.py
```

또는 길어지면:

```text
decisions/services/probability_historical.py
```

---

## 12.1 determine_historical_outcome

구현:

```python
def determine_historical_outcome(
    *,
    future_price_rows,
    target_price: Decimal,
    stop_loss_price: Decimal,
    same_day_hit_policy: str = "conservative",
) -> HistoricalCaseOutcome:
    ...
```

판정 순서:

```text
for day_index, row in enumerate(future_price_rows, start=1):
    hit_target = row.high_price >= target_price
    hit_stop = row.low_price <= stop_loss_price

    if hit_target and hit_stop:
        same_day_hit_policy에 따라 처리

    if hit_target:
        success

    if hit_stop:
        failure

lookahead_days 안에 둘 다 없으면 neutral
```

same_day_hit_policy:

```text
conservative → failure
optimistic → success
neutral → neutral
```

---

## 12.2 calculate_historical_probabilities

구현:

```python
def calculate_historical_probabilities(
    *,
    stock,
    current_snapshot,
    target_return: Decimal,
    stop_loss_return: Decimal,
    lookahead_days: int,
    max_lookback_days: int = 720,
    min_cases: int = 30,
    same_day_hit_policy: str = "conservative",
) -> ProbabilityComponent:
    ...
```

1차 구현에서 historical snapshot이 복잡하면 다음 pragmatic fallback을 사용한다.

```text
1. stock의 최근 max_lookback_days 가격 데이터를 가져온다.
2. 각 과거 시점을 후보로 삼는다.
3. 후보 시점 이후 lookahead_days 데이터가 있는 경우만 사용한다.
4. 현재 target_return, stop_loss_return을 후보 close_price에 적용한다.
5. determine_historical_outcome으로 success/failure/neutral 판정한다.
6. sample_count가 min_cases보다 작으면 confidence와 weight를 낮춘다.
```

현재 snapshot의 세밀한 feature 유사도는 `05_probability_engine_design.md`에 정의된 대로 구현하는 것이 이상적이다.  
단, 한 번에 구현 품질이 떨어질 경우 pragmatic fallback으로 먼저 구현하고 TODO를 남긴다.

하지만 다음은 반드시 지켜야 한다.

```text
1. 과거 결과 판정은 lookahead_days 기준으로 해야 한다.
2. target_return과 stop_loss_return을 과거 close_price에 적용해야 한다.
3. success/failure/neutral을 모두 계산해야 한다.
4. sample_count와 warnings를 반환해야 한다.
```

---

# 13. Risk Hard Override 구현

파일 위치:

```text
decisions/services/probability_service.py
```

critical risk가 있으면 확률 계산을 사실상 종료한다.

반환값:

```text
success_probability = 0.0200
failure_probability = 0.9500
neutral_probability = 0.0300
confidence = 0.9000
success_label = 매우 낮음
failure_label = 매우 위험
confidence_label = 높음
```

warnings:

```text
치명적 위험 이벤트가 감지되어 확률 계산보다 리스크 차단이 우선입니다.
```

critical 판단은 기존 risk_event_service의 함수를 사용한다.

```python
from decisions.services.risk_event_service import has_critical_risk, get_active_risk_events
```

기존 함수 반환 구조가 다르면 프로젝트의 실제 구현에 맞게 어댑터를 작성하라.

---

# 14. Component 결합 구현

파일 위치:

```text
decisions/services/probability_components.py
```

구현:

```python
def combine_probability_components(
    *,
    historical: ProbabilityComponent,
    score: ProbabilityComponent,
    volatility: ProbabilityComponent,
    min_historical_cases: int = 30,
) -> dict:
    ...
```

기본 가중치:

```python
historical_weight = Decimal("0.45")
score_weight = Decimal("0.35")
volatility_weight = Decimal("0.20")
```

historical sample 부족 시:

```text
historical_quality = min(sample_count / min_cases, 1)
adjusted_historical_weight = 0.45 * historical_quality
remaining = 1 - adjusted_historical_weight
score_weight = remaining * (0.35 / (0.35 + 0.20))
volatility_weight = remaining * (0.20 / (0.35 + 0.20))
```

최종:

```text
success =
    historical.success * historical_weight
  + score.success * score_weight
  + volatility.success * volatility_weight
```

failure/neutral도 동일.

반드시 정규화한다.

반환:

```python
{
    "success": Decimal("0.6200"),
    "failure": Decimal("0.2500"),
    "neutral": Decimal("0.1300"),
    "weights": {
        "historical": Decimal("0.4500"),
        "score": Decimal("0.3500"),
        "volatility": Decimal("0.2000"),
    }
}
```

---

# 15. Confidence 계산 구현

파일 위치:

```text
decisions/services/probability_components.py
```

구현:

```python
def calculate_probability_confidence(
    *,
    historical: ProbabilityComponent,
    score: ProbabilityComponent,
    volatility: ProbabilityComponent,
    data_quality: Decimal,
    min_historical_cases: int = 30,
) -> Decimal:
    ...
```

공식:

```text
confidence =
    sample_quality * 0.45
  + data_quality * 0.35
  + component_agreement * 0.20
```

sample_quality:

```text
min(historical.sample_count / min_historical_cases, 1)
```

component_agreement:

```text
success_values = [historical.success, score.success, volatility.success]
std = standard_deviation(success_values)
component_agreement = max(0, 1 - std / 0.30)
```

반환값은 0~1 범위로 clamp 후 Decimal 4자리.

---

# 16. Data Quality 계산 구현

파일 위치:

```text
decisions/services/probability_service.py
```

또는:

```text
decisions/services/probability_components.py
```

구현:

```python
def calculate_data_quality(
    *,
    latest_price,
    price_rows,
    atr14,
    indicators_available: bool,
    flow_rows=None,
    market_rows=None,
    risk_events=None,
) -> Decimal:
    ...
```

가중치:

| 데이터 | 가중치 |
|---|---:|
| latest price | 0.20 |
| 60일 가격 데이터 | 0.25 |
| ATR 또는 volatility | 0.15 |
| RSI/MA 지표 | 0.15 |
| 수급 데이터 | 0.10 |
| 시장 데이터 | 0.10 |
| risk event 데이터 | 0.05 |

기준:

```text
latest_price가 있으면 0.20
len(price_rows) >= 60이면 0.25, 20 이상이면 0.15
atr14가 있거나 로그수익률 계산 가능하면 0.15
indicator 계산 가능하면 0.15
flow_rows 있으면 0.10
market_rows 있으면 0.10
risk_events 조회가 성공하면 0.05
```

---

# 17. 메인 서비스 구현

파일 위치:

```text
decisions/services/probability_service.py
```

구현:

```python
def calculate_averaging_success_failure_probability(
    *,
    holding,
    scenario: AveragingScenario,
) -> ProbabilityResult:
    ...
```

## 17.1 처리 순서

```text
1. scenario validation
2. stock = holding.stock
3. latest_price 조회
4. recent price rows 조회
5. latest_price가 없으면 계산 불가 ProbabilityResult 반환
6. current_price = latest_price.close_price
7. new_average_price 계산
8. target_price 계산
9. support_price 계산
10. ATR14 계산 또는 조회
11. stop_loss_price 계산
12. active risk events 조회
13. critical risk 확인
14. critical risk가 있으면 hard override result 반환
15. 기존 evaluate_averaging_timing(holding) 호출 또는 scoring 함수 호출
16. score, grade, score_breakdown 확보
17. target_return 계산
18. stop_loss_return 계산
19. Historical Component 계산
20. Score Component 계산
21. Volatility Component 계산
22. Component 결합
23. data_quality 계산
24. confidence 계산
25. success/failure/confidence label 계산
26. basis 구성
27. warnings 구성
28. ProbabilityResult 반환
```

---

## 17.2 latest_price가 없는 경우

반환:

```text
success_probability = 0.0000
failure_probability = 0.0000
neutral_probability = 1.0000
confidence = 0.0000
success_label = 매우 낮음
failure_label = 상대적으로 낮음
confidence_label = 매우 낮음
warnings = ["최신 가격 데이터가 없어 확률을 계산할 수 없습니다."]
```

target_price, stop_loss_price, new_average_price는 계산 가능한 경우 계산하고, 불가능하면 Decimal("0")을 사용한다.

---

## 17.3 기존 Scoring Engine 호출

가능하면 기존 함수를 사용한다.

```python
from decisions.services.averaging_decision_service import evaluate_averaging_timing
```

```python
evaluation_result = evaluate_averaging_timing(holding)
score = evaluation_result.score
grade = evaluation_result.grade
score_breakdown = evaluation_result.score_breakdown
```

이 호출이 DB 저장을 하지 않는 순수 계산 함수여야 한다.  
만약 현재 프로젝트에서 `evaluate_averaging_timing`이 저장까지 수행한다면, 저장 없는 평가 함수로 분리하거나 별도 score 계산 함수를 사용하라.

절대 확률 계산 API 호출만으로 AveragingDecision이 저장되면 안 된다.

---

## 17.4 basis 구성

ProbabilityResult.basis에는 다음 구조를 넣는다.

```python
basis = {
    "scenario": {
        "buy_price": str(scenario.buy_price),
        "buy_quantity": scenario.buy_quantity,
        "lookahead_days": scenario.lookahead_days,
        "target_type": scenario.target_type,
        "target_profit_rate": str(scenario.target_profit_rate),
        "stop_loss_type": scenario.stop_loss_type,
        "same_day_hit_policy": scenario.same_day_hit_policy,
    },
    "prices": {
        "current_price": str(current_price),
        "new_average_price": str(new_average_price),
        "target_price": str(target_price),
        "stop_loss_price": str(stop_loss_price),
        "target_return": str(target_return),
        "stop_loss_return": str(stop_loss_return),
    },
    "components": {
        "historical": historical.details,
        "score": score_component.details,
        "volatility": volatility.details,
    },
    "weights": combined["weights"],
    "score_context": {
        "score": score,
        "grade": grade,
        "score_breakdown": score_breakdown,
    },
}
```

JSON 직렬화 가능하도록 Decimal은 문자열로 변환하거나 serializer에서 처리하라.

---

# 18. Serializer 구현

파일 위치:

```text
decisions/serializers.py
```

기존 serializer 파일에 추가하라.

---

## 18.1 AveragingProbabilityScenarioSerializer

구현:

```python
class AveragingProbabilityScenarioSerializer(serializers.Serializer):
    buy_price = serializers.DecimalField(max_digits=14, decimal_places=2)
    buy_quantity = serializers.IntegerField(min_value=1)
    lookahead_days = serializers.IntegerField(min_value=5, max_value=120, default=20)
    target_type = serializers.ChoiceField(
        choices=["new_average_price", "new_average_price_plus_profit", "manual"],
        default="new_average_price",
    )
    target_profit_rate = serializers.DecimalField(
        max_digits=6,
        decimal_places=4,
        default=Decimal("0"),
        min_value=Decimal("0"),
    )
    manual_target_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    stop_loss_type = serializers.ChoiceField(
        choices=["support_or_atr", "manual", "fixed_rate", "atr", "support"],
        default="support_or_atr",
    )
    stop_loss_price = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
        required=False,
        allow_null=True,
    )
    same_day_hit_policy = serializers.ChoiceField(
        choices=["conservative", "optimistic", "neutral"],
        default="conservative",
    )
```

검증:

```text
target_type == manual이면 manual_target_price 필수
stop_loss_type == manual이면 stop_loss_price 필수
buy_price > 0
buy_quantity > 0
target_profit_rate >= 0
```

---

## 18.2 AveragingProbabilityResultSerializer

dataclass를 dict로 변환하기 위한 serializer를 구현한다.

필수 응답 필드:

```text
success_probability
failure_probability
neutral_probability
success_label
failure_label
confidence
confidence_label
target_price
stop_loss_price
new_average_price
lookahead_days
basis
warnings
disclaimer
```

DRF Serializer 또는 직접 Response dict 변환 중 하나를 선택할 수 있다.  
단, Decimal 값은 JSON 응답에서 문자열로 안정적으로 반환되도록 한다.

---

# 19. API View 구현

파일 위치:

```text
holdings/views.py
```

또는 기존 프로젝트의 구조상 적절한 View 파일.

---

## 19.1 Endpoint

```http
POST /api/holdings/{id}/probability/
```

---

## 19.2 권한

반드시 인증 필요.

```python
permission_classes = [IsAuthenticated]
```

holding 조회는 반드시 request.user 기준.

```python
holding = get_object_or_404(
    UserHolding.objects.select_related("stock"),
    id=pk,
    user=request.user,
)
```

---

## 19.3 View 구현 흐름

```python
class HoldingProbabilityAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        holding = get_object_or_404(
            UserHolding.objects.select_related("stock"),
            id=pk,
            user=request.user,
        )

        serializer = AveragingProbabilityScenarioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        scenario = AveragingScenario(**serializer.validated_data)

        result = calculate_averaging_success_failure_probability(
            holding=holding,
            scenario=scenario,
        )

        response_serializer = AveragingProbabilityResultSerializer(result)
        return Response(response_serializer.data, status=200)
```

만약 dataclass serializer가 복잡하면 `result_to_dict(result)` helper를 만들어 Response에 넘겨도 된다.

---

# 20. URL 라우팅

파일 위치:

```text
holdings/urls.py
```

추가:

```python
path("<int:pk>/probability/", HoldingProbabilityAPIView.as_view(), name="holding-probability")
```

최종 endpoint:

```text
POST /api/holdings/{id}/probability/
```

---

# 21. API 응답 예시

```json
{
  "success_probability": "0.6200",
  "failure_probability": "0.2500",
  "neutral_probability": "0.1300",
  "success_label": "보통 이상",
  "failure_label": "주의",
  "confidence": "0.7200",
  "confidence_label": "보통",
  "target_price": "73000.00",
  "stop_loss_price": "65000.00",
  "new_average_price": "73000.00",
  "lookahead_days": 20,
  "basis": {
    "scenario": {
      "buy_price": "69000.00",
      "buy_quantity": 5,
      "lookahead_days": 20
    },
    "components": {
      "historical": {
        "success": "0.5800",
        "failure": "0.2500",
        "neutral": "0.1700",
        "sample_count": 42
      },
      "score": {
        "success": "0.6900",
        "failure": "0.2100",
        "neutral": "0.1000"
      },
      "volatility": {
        "success": "0.4300",
        "failure": "0.2600",
        "neutral": "0.3100"
      }
    }
  },
  "warnings": [
    "확률은 과거 데이터와 현재 조건 기반의 추정값입니다.",
    "미래 수익을 보장하지 않습니다."
  ],
  "disclaimer": "본 결과는 과거 데이터와 현재 조건 기반의 추정 확률이며, 매수·매도 추천이 아닙니다. 미래 수익 또는 손실 회피를 보장하지 않습니다."
}
```

---

# 22. 테스트 구현

## 22.1 가격 공식 테스트

필수 테스트:

```text
new_average_price 계산 정확성
buy_quantity가 0이면 ValueError
buy_price가 0 이하이면 ValueError
target_price new_average_price 정상
target_price new_average_price_plus_profit 정상
manual target price 누락 시 validation error
manual stop_loss_price 검증
support 기반 stop_loss 계산
ATR 기반 stop_loss 계산
fallback stop_loss 계산
```

---

## 22.2 Score Component 테스트

필수 테스트:

```text
score 55 → success 약 0.5
score 75 → success가 score 55보다 큼
score 35 → failure가 높음
success + failure + neutral 합계 1
high risk 보정 시 failure 증가
critical risk는 score component가 아니라 hard override에서 처리
```

---

## 22.3 Volatility Component 테스트

필수 테스트:

```text
target_price가 가까우면 success 증가
stop_loss_price가 가까우면 failure 증가
변동성이 높으면 touch probability 증가
price_rows가 부족하면 ATR fallback 사용
ATR도 없으면 기본 volatility 0.02 사용
lookahead_days가 길면 touch probability 증가
success + failure + neutral 합계 1
```

---

## 22.4 Historical Component 테스트

필수 테스트:

```text
target 먼저 도달 → success
stop 먼저 도달 → failure
둘 다 미도달 → neutral
같은 날 둘 다 도달 + conservative → failure
같은 날 둘 다 도달 + optimistic → success
같은 날 둘 다 도달 + neutral → neutral
유사 사례 부족 시 warning 생성
sample_count가 min_cases보다 작으면 historical weight 감소
```

---

## 22.5 Main Service 테스트

필수 테스트:

```text
latest price 없으면 neutral 1.0 반환
critical risk 있으면 success 0.02, failure 0.95, neutral 0.03
정상 데이터이면 ProbabilityResult 반환
basis에 scenario/prices/components/weights 포함
warnings 포함
disclaimer 포함
confidence_label 정상
```

---

## 22.6 API 테스트

필수 테스트:

```text
POST /api/holdings/{id}/probability/ 정상 응답
다른 사용자의 holding 접근 차단
buy_price 누락 시 400
buy_quantity 0이면 400
manual stop_loss_type인데 stop_loss_price 없으면 400
manual target_type인데 manual_target_price 없으면 400
응답에 success_probability, failure_probability, neutral_probability 포함
응답에 disclaimer 포함
확률 결과 호출만으로 AveragingDecision이 생성되지 않음
```

---

# 23. 로깅

가능하면 probability API 호출 시 로그를 남겨라.

```python
logger.info(
    "Averaging probability calculated",
    extra={
        "user_id": request.user.id,
        "holding_id": holding.id,
        "stock_code": holding.stock.code,
        "success_probability": str(result.success_probability),
        "failure_probability": str(result.failure_probability),
        "confidence": str(result.confidence),
    },
)
```

프로젝트 로깅 설정이 없다면 다음만 추가한다.

```python
import logging
logger = logging.getLogger(__name__)
```

---

# 24. 완료 후 실행할 명령

이번 단계는 기본적으로 DB 모델을 추가하지 않으므로 migration이 없어야 정상이다.

테스트 실행:

```bash
python manage.py test
```

프로젝트가 pytest를 사용한다면:

```bash
pytest
```

---

# 25. 완료 보고 형식

작업 완료 후 다음 형식으로 보고하라.

```text
5단계 Probability Engine 구현 완료

구현/수정한 파일:
- ...

구현한 핵심 기능:
- AveragingScenario
- ProbabilityResult
- 새 평균단가 계산
- 목표가 계산
- 손절가 계산
- Historical Component
- Score Component
- Volatility Component
- Risk Hard Override
- Confidence 계산
- POST /api/holdings/{id}/probability/

테스트:
- ...

중요 확인:
- success/failure/neutral 합계 1
- critical risk hard override 동작
- 다른 사용자의 holding 접근 차단
- 확률 계산만으로 AveragingDecision 저장되지 않음
- disclaimer 포함

아직 구현하지 않은 것:
- 확률 결과 DB 저장
- 확률 이력 조회
- 프론트엔드 UI
- 외부 데이터 연동
```

---

# 26. 지금 바로 수행할 작업

지금 바로 다음 순서로 구현하라.

```text
1. docs/05_probability_engine_design.md 읽기
2. 기존 decisions/services 구조 확인
3. probability dataclass 파일 생성
4. probability utility/component 함수 구현
5. probability main service 구현
6. serializer 추가
7. HoldingProbabilityAPIView 추가
8. URL 추가
9. 테스트 작성
10. 테스트 실행
11. 완료 보고 작성
```

반드시 기존 1~4단계 구조를 깨지 말고, 이번 확률 기능은 독립적인 확장 모듈로 구현하라.
