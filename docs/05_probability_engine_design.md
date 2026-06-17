# 05_probability_engine_design.md

# 물타기 성공확률/실패확률 수학적 로직 상세설계서

## 문서 목적

이 문서는 `물타기 타이밍 판단 시스템`에 확률 계산 기능을 추가하기 위한 상세 설계서다.

기존 시스템은 다음 질문에 답한다.

```text
지금 이 종목을 추가 매수해도 되는 위험 구간인가?
```

이 문서에서 설계하는 확률 엔진은 다음 질문에 답한다.

```text
지금 특정 조건으로 물타기를 실행한다고 가정했을 때,
정해진 기간 안에 목표 회복 가격에 먼저 도달할 가능성은 얼마인가?
반대로 손절 또는 위험 기준에 먼저 도달할 가능성은 얼마인가?
```

즉, 기존 A/B/C/D 등급은 **현재 상태 판단**이고, 본 문서의 성공확률/실패확률은 **물타기 실행 시나리오의 결과 가능성 추정**이다.

이 확률은 미래를 맞히는 보장값이 아니다.  
과거 데이터, 현재 점수, 변동성, 위험 이벤트를 기반으로 한 **조건부 추정 확률**이다.

---

# 1. 핵심 개념 정의

## 1.1 성공확률의 정의

성공확률은 사용자가 특정 가격과 수량으로 물타기를 했다고 가정했을 때, 정해진 기간 안에 목표 가격에 먼저 도달할 추정 확률이다.

기본 성공 조건은 다음이다.

```text
물타기 후 새 평균단가 이상으로 가격이 회복된다.
```

예를 들어 다음 상황을 보자.

```text
기존 평균단가: 75,000원
기존 보유수량: 10주
추가 매수가: 69,000원
추가 매수수량: 5주

새 평균단가:
(75,000 * 10 + 69,000 * 5) / (10 + 5)
= 73,000원
```

이 경우 기본 성공 목표 가격은 73,000원이다.

```text
성공 = lookahead_days 안에 주가가 73,000원 이상에 먼저 도달
```

---

## 1.2 실패확률의 정의

실패확률은 물타기 후 정해진 기간 안에 손절 기준 가격 또는 위험 기준에 먼저 도달할 추정 확률이다.

기본 실패 조건은 다음 중 하나다.

```text
1. 손절 기준 가격 이하로 하락
2. 주요 지지선 재이탈
3. 추가 매수 후 허용 손실률 초과
4. critical 위험 이벤트 발생
```

가격 기반 실패 조건은 기본적으로 다음처럼 계산한다.

```text
실패 = lookahead_days 안에 주가가 stop_loss_price 이하에 먼저 도달
```

---

## 1.3 중립확률의 정의

중립확률은 정해진 기간 안에 성공 조건과 실패 조건 중 어느 것도 발생하지 않을 추정 확률이다.

```text
중립 = lookahead_days 안에 target_price도 stop_loss_price도 도달하지 않음
```

최종 확률은 다음 합이 1이 되도록 정규화한다.

```text
success_probability + failure_probability + neutral_probability = 1
```

---

## 1.4 확률 해석 원칙

허용 표현:

```text
현재 조건 기준 목표 회복 가능성 추정치는 62%입니다.
손절 기준에 먼저 도달할 위험 추정치는 25%입니다.
이 값은 과거 데이터와 현재 조건 기반의 추정값이며 미래 결과를 보장하지 않습니다.
```

금지 표현:

```text
이 종목은 62% 확률로 오릅니다.
성공확률이 높으니 매수하세요.
실패확률이 낮으니 안전합니다.
수익이 보장됩니다.
```

---

# 2. 입력 시나리오 정의

## 2.1 AveragingScenario

확률 계산은 반드시 구체적인 물타기 시나리오를 입력받아야 한다.

같은 종목이라도 추가 매수가, 추가 매수량, 목표 조건, 손절 조건에 따라 성공확률과 실패확률이 달라진다.

권장 dataclass:

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AveragingScenario:
    buy_price: Decimal
    buy_quantity: int
    lookahead_days: int = 20
    target_type: str = "new_average_price"
    target_profit_rate: Decimal = Decimal("0")
    stop_loss_type: str = "support_or_atr"
    stop_loss_price: Decimal | None = None
    same_day_hit_policy: str = "conservative"
```

Python 3.9 이하 호환이 필요하면 `Decimal | None` 대신 `Optional[Decimal]`을 사용한다.

---

## 2.2 입력 필드 설명

| 필드 | 타입 | 설명 |
|---|---|---|
| buy_price | Decimal | 추가 매수를 가정하는 가격 |
| buy_quantity | int | 추가 매수 수량 |
| lookahead_days | int | 성공/실패를 판정할 미래 거래일 수 |
| target_type | str | 목표 가격 계산 방식 |
| target_profit_rate | Decimal | 목표 수익률을 추가로 요구할 경우 사용 |
| stop_loss_type | str | 손절 기준 계산 방식 |
| stop_loss_price | Decimal or None | 사용자가 직접 지정한 손절가 |
| same_day_hit_policy | str | 같은 날 목표가와 손절가가 모두 도달한 경우 처리 방식 |

---

## 2.3 target_type

지원할 target_type은 다음과 같다.

| 값 | 의미 |
|---|---|
| new_average_price | 물타기 후 새 평균단가를 목표 가격으로 사용 |
| new_average_price_plus_profit | 새 평균단가에 목표 수익률을 더한 가격 |
| current_price_plus_rate | 현재가 기준 특정 상승률을 목표로 사용 |
| manual | 사용자가 직접 입력한 목표 가격 사용 |

1차 구현에서는 다음 두 가지를 필수로 구현한다.

```text
new_average_price
new_average_price_plus_profit
```

---

## 2.4 stop_loss_type

지원할 stop_loss_type은 다음과 같다.

| 값 | 의미 |
|---|---|
| support_or_atr | 지지선, ATR, 비율 fallback 순서로 계산 |
| manual | 사용자가 직접 지정한 stop_loss_price 사용 |
| fixed_rate | 현재가 기준 고정 하락률 사용 |
| atr | ATR 기반 손절가 사용 |
| support | 지지선 기반 손절가 사용 |

1차 구현에서는 다음 두 가지를 필수로 구현한다.

```text
support_or_atr
manual
```

---

## 2.5 same_day_hit_policy

과거 OHLCV 데이터만 사용할 경우, 특정 거래일에 고가가 목표가 이상이고 저가가 손절가 이하일 수 있다.

이때 실제로 어느 가격에 먼저 도달했는지는 분봉 데이터 없이는 알 수 없다.

처리 정책은 다음과 같다.

| 값 | 의미 |
|---|---|
| conservative | 같은 날 둘 다 도달하면 실패로 처리 |
| optimistic | 같은 날 둘 다 도달하면 성공으로 처리 |
| neutral | 같은 날 둘 다 도달하면 중립으로 처리 |

기본값은 `conservative`다.

---

# 3. 핵심 가격 공식

## 3.1 새 평균단가 계산

```text
new_average_price =
    (current_average_price * current_quantity + buy_price * buy_quantity)
    /
    (current_quantity + buy_quantity)
```

Python 함수:

```python
def calculate_new_average_price(
    current_average_price: Decimal,
    current_quantity: int,
    buy_price: Decimal,
    buy_quantity: int,
) -> Decimal:
    ...
```

검증 조건:

```text
current_average_price > 0
current_quantity > 0
buy_price > 0
buy_quantity > 0
```

예외:

```text
조건을 만족하지 않으면 ValueError
```

---

## 3.2 목표 가격 계산

기본 목표 가격은 새 평균단가다.

```text
target_price = new_average_price
```

목표 수익률을 추가할 경우:

```text
target_price = new_average_price * (1 + target_profit_rate)
```

예:

```text
new_average_price = 73,000
target_profit_rate = 0.03

target_price = 73,000 * 1.03 = 75,190
```

Python 함수:

```python
def calculate_target_price(
    *,
    current_average_price: Decimal,
    current_quantity: int,
    buy_price: Decimal,
    buy_quantity: int,
    target_type: str,
    target_profit_rate: Decimal = Decimal("0"),
    manual_target_price: Decimal | None = None,
) -> Decimal:
    ...
```

---

## 3.3 손절 기준 가격 계산

손절 기준 가격은 다음 우선순위로 계산한다.

```text
1. manual stop_loss_price가 있으면 그대로 사용
2. 지지선이 있으면 support_price * 0.97
3. ATR14가 있으면 current_price - ATR14 * 1.5
4. 모두 없으면 current_price * 0.93
```

Python 함수:

```python
def calculate_probability_stop_loss_price(
    *,
    current_price: Decimal,
    stop_loss_type: str,
    manual_stop_loss_price: Decimal | None = None,
    support_price: Decimal | None = None,
    atr14: Decimal | None = None,
    fixed_rate: Decimal = Decimal("0.07"),
) -> Decimal:
    ...
```

검증 조건:

```text
current_price > 0
manual_stop_loss_price가 있으면 0 < manual_stop_loss_price < current_price 권장
```

manual_stop_loss_price가 current_price 이상이면 실패 기준이 현재가보다 위에 있는 비정상 상태이므로 ValueError로 처리한다.

---

# 4. 확률 계산 전체 구조

## 4.1 세 가지 확률 컴포넌트

최종 확률은 세 가지 컴포넌트를 결합한다.

```text
1. Historical Component
   과거 유사 패턴 기반 성공/실패/중립 확률

2. Score Component
   기존 Scoring Engine 점수 기반 성공/실패/중립 확률

3. Volatility Component
   변동성 기반 목표가/손절가 도달 확률
```

최종 결합:

```text
success_probability =
    historical_success * historical_weight
  + score_success * score_weight
  + volatility_success * volatility_weight

failure_probability =
    historical_failure * historical_weight
  + score_failure * score_weight
  + volatility_failure * volatility_weight

neutral_probability =
    historical_neutral * historical_weight
  + score_neutral * score_weight
  + volatility_neutral * volatility_weight
```

기본 가중치:

```text
historical_weight = 0.45
score_weight = 0.35
volatility_weight = 0.20
```

과거 유사 사례가 부족하면 historical_weight를 0으로 낮추고, 나머지 가중치를 비례 재분배한다.

---

## 4.2 최종 정규화

결합 후 다음을 보장한다.

```text
0 <= success_probability <= 1
0 <= failure_probability <= 1
0 <= neutral_probability <= 1
success_probability + failure_probability + neutral_probability = 1
```

정규화 함수:

```python
def normalize_probabilities(success: Decimal, failure: Decimal, neutral: Decimal) -> dict:
    ...
```

처리 방식:

```text
1. 음수 값은 0으로 보정
2. 합계가 0이면 중립 1.0 반환
3. 합계가 1이 아니면 각 값을 합계로 나누어 정규화
4. Decimal 소수점 4자리 또는 6자리로 반올림
```

---

# 5. Historical Component 설계

## 5.1 개념

Historical Component는 현재 상태와 유사한 과거 시점을 찾고, 그 시점에서 같은 거리의 목표가와 손절가를 설정했을 때 이후 N거래일 안에 어떤 결과가 먼저 발생했는지 계산한다.

중요한 점은 과거에는 사용자의 실제 평균단가가 없다는 것이다.

따라서 과거 시점에서는 현재 시나리오의 목표/손절 거리 비율을 적용한다.

현재 시나리오에서:

```text
target_return = (target_price - current_price) / current_price
stop_loss_return = (current_price - stop_loss_price) / current_price
```

과거 후보 시점 t에서:

```text
historical_target_price = close_t * (1 + target_return)
historical_stop_loss_price = close_t * (1 - stop_loss_return)
```

그 후 lookahead_days 동안:

```text
고가가 target 이상 먼저 도달 → success
저가가 stop 이하 먼저 도달 → failure
둘 다 미도달 → neutral
```

---

## 5.2 유사 패턴 feature 정의

현재 상태와 과거 상태를 비교할 feature는 다음이다.

| feature | 설명 |
|---|---|
| loss_rate | 현재 손익률 |
| rsi14 | RSI |
| price_to_ma20_pct | 현재가와 MA20 거리 |
| price_to_ma60_pct | 현재가와 MA60 거리 |
| support_distance_pct | 현재가와 지지선 거리 |
| volume_ratio | 최근 거래량 / 20일 평균 거래량 |
| foreign_flow_signal | 외국인 수급 신호 |
| institution_flow_signal | 기관 수급 신호 |
| market_trend_signal | 시장 흐름 신호 |
| risk_level_signal | 활성 위험 이벤트 수준 |

1차 구현에서 필수 feature:

```text
rsi14
price_to_ma20_pct
support_distance_pct
volume_ratio
market_trend_signal
```

loss_rate는 실제 사용자의 평균단가가 필요한 값이므로 현재 holding에는 존재하지만 과거 후보에는 없을 수 있다.  
과거 후보에는 target_return, stop_loss_return을 적용하기 때문에 loss_rate는 유사도 계산에서 보조 feature로만 사용한다.

---

## 5.3 feature snapshot 구조

```python
@dataclass(frozen=True)
class ProbabilityFeatureSnapshot:
    date: date
    close_price: Decimal
    rsi14: Decimal | None
    price_to_ma20_pct: Decimal | None
    price_to_ma60_pct: Decimal | None
    support_distance_pct: Decimal | None
    volume_ratio: Decimal | None
    foreign_flow_signal: int
    institution_flow_signal: int
    market_trend_signal: int
    risk_level_signal: int
```

signal 값 기준:

```text
positive = 1
neutral = 0
negative = -1
unknown = 0
```

risk_level_signal:

```text
no active risk = 0
low = -1
medium = -2
high = -3
critical = -5
```

critical은 Historical Component 이전에 hard override로 처리하는 것이 원칙이다.

---

## 5.4 유사도 거리 계산

feature별 표준화 거리의 가중합을 사용한다.

```text
distance = Σ weight_i * normalized_distance_i
```

기본 feature weight:

| feature | weight |
|---|---:|
| rsi14 | 0.20 |
| price_to_ma20_pct | 0.20 |
| support_distance_pct | 0.20 |
| volume_ratio | 0.15 |
| market_trend_signal | 0.15 |
| foreign_flow_signal | 0.05 |
| institution_flow_signal | 0.05 |

normalized_distance 예시:

```text
rsi_distance = abs(current_rsi - past_rsi) / 100
price_to_ma20_distance = abs(current_pct - past_pct) / 0.20
support_distance = abs(current_support_pct - past_support_pct) / 0.10
volume_ratio_distance = abs(current_volume_ratio - past_volume_ratio) / 3.0
signal_distance = abs(current_signal - past_signal) / 2
```

최종 distance가 낮을수록 유사한 사례다.

---

## 5.5 유사 사례 선택 기준

기본 기준:

```text
distance <= 0.30
```

최소 사례 수:

```text
min_cases = 30
```

충분한 사례가 없으면 threshold를 단계적으로 완화한다.

```text
0.30 → 0.40 → 0.50 → 0.65
```

그래도 min_cases보다 적으면 historical component는 confidence를 낮추고, 최종 결합에서 historical weight를 줄인다.

---

## 5.6 HistoricalCaseOutcome

```python
@dataclass(frozen=True)
class HistoricalCaseOutcome:
    base_date: date
    base_close: Decimal
    target_price: Decimal
    stop_loss_price: Decimal
    outcome: str
    days_to_outcome: int | None
    max_favorable_return: Decimal
    max_adverse_return: Decimal
```

outcome 값:

```text
success
failure
neutral
ambiguous
```

ambiguous는 같은 날 target과 stop을 모두 터치한 경우다.  
기본 same_day_hit_policy가 conservative이면 ambiguous를 failure로 변환한다.

---

## 5.7 과거 결과 판정 로직

Python 함수:

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
        same_day_hit_policy에 따라 success/failure/neutral 처리

    if hit_target:
        success

    if hit_stop:
        failure

lookahead_days 안에 둘 다 없으면 neutral
```

보수적 기본 정책:

```text
같은 날 목표와 손절을 모두 터치하면 failure
```

---

## 5.8 Historical Probability 계산

```python
historical_success_probability = success_count / total_count
historical_failure_probability = failure_count / total_count
historical_neutral_probability = neutral_count / total_count
```

함수:

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

반환 구조:

```python
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

# 6. Score Component 설계

## 6.1 개념

Score Component는 기존 Scoring Engine의 점수를 확률로 변환한다.

기존 점수는 다음 의미를 가진다.

```text
높은 점수 = 추가 매수 가능성을 검토할 수 있는 상태
낮은 점수 = 위험 신호가 강한 상태
```

하지만 점수는 성공확률 그 자체가 아니므로 sigmoid 함수로 확률화한다.

---

## 6.2 성공확률 변환

```text
score_success = sigmoid((score - success_midpoint) / success_scale)
```

기본값:

```text
success_midpoint = 55
success_scale = 10
```

공식:

```text
sigmoid(x) = 1 / (1 + e^(-x))
```

예시:

| score | score_success |
|---:|---:|
| 35 | 약 0.119 |
| 45 | 약 0.269 |
| 55 | 0.500 |
| 65 | 약 0.731 |
| 75 | 약 0.881 |

---

## 6.3 실패확률 변환

실패확률은 단순히 `1 - score_success`로 계산하지 않는다.  
중립 상태도 존재하기 때문이다.

별도의 sigmoid를 사용한다.

```text
score_failure = sigmoid((failure_midpoint - score) / failure_scale)
```

기본값:

```text
failure_midpoint = 45
failure_scale = 10
```

예시:

| score | score_failure |
|---:|---:|
| 25 | 약 0.881 |
| 35 | 약 0.731 |
| 45 | 0.500 |
| 55 | 약 0.269 |
| 65 | 약 0.119 |

---

## 6.4 중립확률 계산

```text
score_neutral = 1 - score_success - score_failure
```

만약 합계가 1을 초과하면 success/failure를 정규화하고 neutral을 0으로 둔다.

---

## 6.5 함수 시그니처

```python
def calculate_score_component(
    *,
    score: int,
    grade: str,
    active_risk_events=None,
) -> ProbabilityComponent:
    ...
```

---

## 6.6 위험 이벤트 보정

critical risk는 Score Component가 아니라 전체 확률 계산의 hard override에서 처리한다.

high/medium/low risk는 Score Component에 다음 보정을 줄 수 있다.

```text
high risk:
    success *= 0.75
    failure += 0.20

medium risk:
    success *= 0.90
    failure += 0.10

low risk:
    success *= 0.95
    failure += 0.05
```

보정 후 반드시 정규화한다.

---

# 7. Volatility Component 설계

## 7.1 개념

Volatility Component는 현재가에서 목표 가격과 손절 가격까지의 거리를 변동성 기준으로 평가한다.

핵심 질문:

```text
lookahead_days 동안 현재 변동성으로 target_price 또는 stop_loss_price에 닿을 가능성은 어느 정도인가?
```

---

## 7.2 거리 계산

목표까지의 상승 거리:

```text
target_return = (target_price - current_price) / current_price
```

손절까지의 하락 거리:

```text
stop_loss_return = (current_price - stop_loss_price) / current_price
```

검증:

```text
target_return <= 0이면 이미 목표 가격 이상이므로 success를 높게 처리
stop_loss_return <= 0이면 손절가가 현재가 이상이므로 scenario invalid 또는 failure 높게 처리
```

---

## 7.3 일일 변동성 계산

우선순위:

```text
1. 최근 종가 로그수익률 표준편차
2. ATR14 / current_price
3. fallback 기본값 0.02
```

### 로그수익률

```text
log_return_t = ln(close_t / close_{t-1})
```

일일 변동성:

```text
daily_volatility = std(log_returns)
```

최소값 floor:

```text
daily_volatility = max(daily_volatility, 0.005)
```

너무 큰 값 cap:

```text
daily_volatility = min(daily_volatility, 0.15)
```

---

## 7.4 기간 변동성

```text
horizon_volatility = daily_volatility * sqrt(lookahead_days)
```

---

## 7.5 목표 터치 확률 근사

Brownian motion의 reflection principle을 단순화하여 사용한다.

상방 barrier 터치 확률 근사:

```text
p_touch_up = 2 * (1 - normal_cdf(target_return / horizon_volatility))
```

하방 barrier 터치 확률 근사:

```text
p_touch_down = 2 * (1 - normal_cdf(stop_loss_return / horizon_volatility))
```

범위 제한:

```text
p_touch_up = clamp(p_touch_up, 0, 0.98)
p_touch_down = clamp(p_touch_down, 0, 0.98)
```

normal_cdf 구현:

```python
import math

def normal_cdf(x):
    return Decimal(str(0.5 * (1 + math.erf(float(x) / math.sqrt(2)))))
```

---

## 7.6 상방/하방 중 먼저 도달할 비율

drift가 없다고 가정하면 두 barrier 중 상방에 먼저 도달할 확률은 다음과 같이 근사할 수 있다.

```text
barrier_success_ratio = stop_loss_return / (target_return + stop_loss_return)
barrier_failure_ratio = target_return / (target_return + stop_loss_return)
```

의미:

```text
목표가가 가까울수록 success_ratio 증가
손절가가 가까울수록 failure_ratio 증가
```

단, target_return 또는 stop_loss_return이 0 이하인 경우는 별도 처리한다.

---

## 7.7 trend drift 보정

기존 Scoring Engine의 추세 점수를 사용해 barrier_success_ratio를 보정한다.

```text
trend_adjustment = (trend_score - 12.5) / 100
```

예:

```text
trend_score = 25 → +0.125
trend_score = 0 → -0.125
```

보정:

```text
barrier_success_ratio = clamp(barrier_success_ratio + trend_adjustment, 0.05, 0.95)
barrier_failure_ratio = 1 - barrier_success_ratio
```

---

## 7.8 volatility success/failure 계산

```text
volatility_success = p_touch_up * barrier_success_ratio
volatility_failure = p_touch_down * barrier_failure_ratio
volatility_neutral = 1 - volatility_success - volatility_failure
```

합계가 1을 초과하면 정규화한다.

---

## 7.9 함수 시그니처

```python
def calculate_volatility_component(
    *,
    current_price: Decimal,
    target_price: Decimal,
    stop_loss_price: Decimal,
    price_rows,
    atr14: Decimal | None,
    lookahead_days: int,
    trend_score: int = 0,
) -> ProbabilityComponent:
    ...
```

---

# 8. Risk Hard Override 설계

## 8.1 critical risk

active critical risk가 있으면 확률 계산을 사실상 종료한다.

반환:

```text
success_probability = 0.02
failure_probability = 0.95
neutral_probability = 0.03
confidence = 0.90
```

사유:

```text
치명적 위험 이벤트가 감지되어 확률 계산보다 리스크 차단이 우선입니다.
```

critical event 예:

```text
거래정지
상장폐지 위험
감사의견 거절
관리종목
회생절차
심각한 자본잠식
```

---

## 8.2 high risk

high risk가 있으면 hard override는 아니지만 실패확률을 강하게 높인다.

보정:

```text
success *= 0.75
failure += 0.20
neutral = 1 - success - failure
정규화
```

---

## 8.3 medium/low risk

medium:

```text
success *= 0.90
failure += 0.10
```

low:

```text
success *= 0.95
failure += 0.05
```

---

# 9. 최종 결합 로직

## 9.1 기본 가중치

```python
DEFAULT_WEIGHTS = {
    "historical": Decimal("0.45"),
    "score": Decimal("0.35"),
    "volatility": Decimal("0.20"),
}
```

---

## 9.2 historical 데이터 부족 시 가중치 재분배

historical sample_count가 min_cases보다 부족하면 historical weight를 낮춘다.

```text
historical_quality = min(sample_count / min_cases, 1)
adjusted_historical_weight = default_historical_weight * historical_quality
remaining_weight = 1 - adjusted_historical_weight
score_weight : volatility_weight 비율은 0.35 : 0.20 유지
```

예:

```text
sample_count = 15
min_cases = 30
historical_quality = 0.5

historical_weight = 0.45 * 0.5 = 0.225
remaining = 0.775

score_weight = 0.775 * (0.35 / (0.35 + 0.20)) = 0.493
volatility_weight = 0.775 * (0.20 / (0.35 + 0.20)) = 0.282
```

---

## 9.3 컴포넌트 결합 함수

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

# 10. Confidence 설계

## 10.1 confidence 목적

확률값만 보여주면 사용자가 과신할 수 있다.

따라서 확률과 함께 confidence를 제공한다.

```text
probability = 계산된 성공/실패/중립 추정치
confidence = 이 추정치를 얼마나 신뢰할 수 있는지에 대한 데이터 품질 점수
```

---

## 10.2 confidence 구성 요소

```text
confidence =
    sample_quality * 0.45
  + data_quality * 0.35
  + component_agreement * 0.20
```

---

## 10.3 sample_quality

```text
sample_quality = min(historical_sample_count / min_cases, 1)
```

---

## 10.4 data_quality

필수 데이터 충족률:

| 데이터 | 가중치 |
|---|---:|
| latest price | 0.20 |
| 60일 가격 데이터 | 0.25 |
| ATR 또는 volatility | 0.15 |
| RSI/MA 지표 | 0.15 |
| 수급 데이터 | 0.10 |
| 시장 데이터 | 0.10 |
| risk event 데이터 | 0.05 |

합산하여 0~1 값으로 계산한다.

---

## 10.5 component_agreement

세 컴포넌트가 비슷한 방향을 가리키면 confidence가 높다.

예:

```text
historical_success = 0.60
score_success = 0.65
volatility_success = 0.58
→ agreement 높음
```

계산:

```text
success_values = [historical.success, score.success, volatility.success]
std = standard_deviation(success_values)
component_agreement = max(0, 1 - std / 0.30)
```

---

## 10.6 confidence label

| confidence | label |
|---:|---|
| 0.75 이상 | 높음 |
| 0.50 ~ 0.74 | 보통 |
| 0.25 ~ 0.49 | 낮음 |
| 0.25 미만 | 매우 낮음 |

---

# 11. ProbabilityResult 설계

## 11.1 dataclass

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

## 11.2 basis 구조

```python
basis = {
    "scenario": {
        "buy_price": "69000.00",
        "buy_quantity": 5,
        "lookahead_days": 20,
        "target_type": "new_average_price",
        "stop_loss_type": "support_or_atr"
    },
    "prices": {
        "current_price": "69000.00",
        "new_average_price": "73000.00",
        "target_price": "73000.00",
        "stop_loss_price": "65000.00",
        "target_return": "0.0580",
        "stop_loss_return": "0.0580"
    },
    "components": {
        "historical": {
            "success": "0.5800",
            "failure": "0.2500",
            "neutral": "0.1700",
            "sample_count": 42,
            "confidence": "0.8000"
        },
        "score": {
            "success": "0.6900",
            "failure": "0.2100",
            "neutral": "0.1000",
            "score": 63,
            "grade": "B"
        },
        "volatility": {
            "success": "0.4300",
            "failure": "0.2600",
            "neutral": "0.3100",
            "daily_volatility": "0.0260",
            "horizon_volatility": "0.1163"
        }
    },
    "weights": {
        "historical": "0.4500",
        "score": "0.3500",
        "volatility": "0.2000"
    }
}
```

---

# 12. 라벨링 설계

## 12.1 success_label

| success_probability | label |
|---:|---|
| 0.75 이상 | 높음 |
| 0.55 ~ 0.7499 | 보통 이상 |
| 0.40 ~ 0.5499 | 중립 |
| 0.25 ~ 0.3999 | 낮음 |
| 0.25 미만 | 매우 낮음 |

---

## 12.2 failure_label

| failure_probability | label |
|---:|---|
| 0.60 이상 | 매우 위험 |
| 0.40 ~ 0.5999 | 위험 |
| 0.25 ~ 0.3999 | 주의 |
| 0.25 미만 | 상대적으로 낮음 |

---

## 12.3 label 함수

```python
def get_success_probability_label(probability: Decimal) -> str:
    ...


def get_failure_probability_label(probability: Decimal) -> str:
    ...


def get_confidence_label(confidence: Decimal) -> str:
    ...
```

---

# 13. 메인 서비스 함수 설계

## 13.1 파일 위치

권장 위치:

```text
decisions/services/probability_service.py
```

이 파일에 확률 계산 로직을 모은다.

---

## 13.2 메인 함수

```python
def calculate_averaging_success_failure_probability(
    *,
    holding,
    scenario: AveragingScenario,
) -> ProbabilityResult:
    ...
```

---

## 13.3 처리 순서

```text
1. scenario validation
2. holding.stock 조회
3. latest price 조회
4. recent price rows 조회
5. 최신 가격이 없으면 평가 불가 result 반환
6. new_average_price 계산
7. target_price 계산
8. support_price 계산
9. ATR14 계산 또는 조회
10. stop_loss_price 계산
11. active risk events 조회
12. critical risk 확인
13. critical risk 있으면 hard override result 반환
14. 기존 evaluate_averaging_timing 또는 scoring 함수로 score/grade/score_breakdown 확보
15. historical component 계산
16. score component 계산
17. volatility component 계산
18. risk 보정 적용
19. component 결합
20. confidence 계산
21. label 계산
22. ProbabilityResult 반환
```

---

## 13.4 최신 가격이 없는 경우

가격 데이터가 없으면 성공/실패 계산 자체가 불가능하다.

반환:

```text
success_probability = 0
failure_probability = 0
neutral_probability = 1
confidence = 0
warnings = ["최신 가격 데이터가 없어 확률을 계산할 수 없습니다."]
```

이 경우 API에서는 200 OK로 반환할 수 있지만, 사용자는 계산 불가 상태임을 명확히 알아야 한다.

---

## 13.5 critical risk hard override

```python
if critical_risk_exists:
    return ProbabilityResult(
        success_probability=Decimal("0.0200"),
        failure_probability=Decimal("0.9500"),
        neutral_probability=Decimal("0.0300"),
        success_label="매우 낮음",
        failure_label="매우 위험",
        confidence=Decimal("0.9000"),
        confidence_label="높음",
        ...
        warnings=[
            "치명적 위험 이벤트가 감지되어 확률 계산보다 리스크 차단이 우선입니다."
        ],
    )
```

---

# 14. API 확장 설계

## 14.1 Endpoint

확률 계산 API를 추가할 경우 다음 endpoint를 권장한다.

```http
POST /api/holdings/{id}/probability/
```

---

## 14.2 Request Body

```json
{
  "buy_price": "69000.00",
  "buy_quantity": 5,
  "lookahead_days": 20,
  "target_type": "new_average_price",
  "target_profit_rate": "0.00",
  "stop_loss_type": "support_or_atr",
  "stop_loss_price": null,
  "same_day_hit_policy": "conservative"
}
```

---

## 14.3 Response Body

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

## 14.4 Serializer

권장 serializer:

```text
AveragingProbabilityScenarioSerializer
AveragingProbabilityResultSerializer
```

입력 serializer 검증:

```text
buy_price > 0
buy_quantity > 0
lookahead_days는 5~120 사이 권장
target_profit_rate >= 0
stop_loss_price는 stop_loss_type이 manual일 때 필수
same_day_hit_policy는 conservative/optimistic/neutral 중 하나
```

---

# 15. 선택적 DB 저장 모델

## 15.1 저장이 필요한 경우

확률 계산 결과를 이력으로 남기고 싶다면 별도 모델을 추가한다.

모델명:

```text
AveragingProbabilityResult
```

---

## 15.2 모델 설계

```python
class AveragingProbabilityResult(models.Model):
    holding = models.ForeignKey(
        "holdings.UserHolding",
        on_delete=models.CASCADE,
        related_name="probability_results",
    )

    buy_price = models.DecimalField(max_digits=14, decimal_places=2)
    buy_quantity = models.PositiveIntegerField()
    lookahead_days = models.PositiveIntegerField(default=20)
    target_type = models.CharField(max_length=50, default="new_average_price")
    stop_loss_type = models.CharField(max_length=50, default="support_or_atr")

    success_probability = models.DecimalField(max_digits=6, decimal_places=4)
    failure_probability = models.DecimalField(max_digits=6, decimal_places=4)
    neutral_probability = models.DecimalField(max_digits=6, decimal_places=4)

    success_label = models.CharField(max_length=50)
    failure_label = models.CharField(max_length=50)
    confidence = models.DecimalField(max_digits=6, decimal_places=4)
    confidence_label = models.CharField(max_length=50)

    target_price = models.DecimalField(max_digits=14, decimal_places=2)
    stop_loss_price = models.DecimalField(max_digits=14, decimal_places=2)
    new_average_price = models.DecimalField(max_digits=14, decimal_places=2)

    basis = models.JSONField(default=dict, blank=True)
    warnings = models.JSONField(default=list, blank=True)
    disclaimer = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["holding", "-created_at"]),
        ]
```

1차 구현에서는 DB 저장 없이 계산 결과만 반환해도 된다.  
하지만 운영 서비스에서 사용자의 과거 확률 시나리오를 비교하려면 저장 모델을 추가하는 것이 좋다.

---

# 16. 테스트 설계

## 16.1 가격 공식 테스트

필수 테스트:

```text
new_average_price 계산 정확성
buy_quantity가 0이면 ValueError
buy_price가 0 이하이면 ValueError
target_price 계산 정확성
manual stop_loss_price 검증
support 기반 stop_loss 계산
ATR 기반 stop_loss 계산
fallback stop_loss 계산
```

---

## 16.2 Historical Component 테스트

필수 테스트:

```text
과거 target 먼저 도달 → success
과거 stop 먼저 도달 → failure
둘 다 미도달 → neutral
같은 날 둘 다 도달 + conservative → failure
같은 날 둘 다 도달 + optimistic → success
같은 날 둘 다 도달 + neutral → neutral
유사 사례 부족 시 warning 생성
sample_count가 min_cases보다 작으면 historical weight 감소
```

---

## 16.3 Score Component 테스트

필수 테스트:

```text
score 55 → success 약 0.5
score 75 → success 높음
score 35 → failure 높음
success + failure + neutral 합계 1
high risk 보정 시 failure 증가
critical risk는 여기서 처리하지 않고 hard override에서 처리
```

---

## 16.4 Volatility Component 테스트

필수 테스트:

```text
target_price가 가까우면 success 증가
stop_loss_price가 가까우면 failure 증가
변동성이 높으면 터치 확률 증가
변동성이 0이면 floor 적용
lookahead_days가 길면 터치 확률 증가
success + failure + neutral 합계 1
```

---

## 16.5 최종 결합 테스트

필수 테스트:

```text
세 component 결합 후 합계 1
historical sample 부족 시 weight 재분배
critical risk 있으면 success 0.02 / failure 0.95 / neutral 0.03
latest price 없으면 neutral 1
warnings 포함
disclaimer 포함
confidence label 정상
```

---

## 16.6 API 테스트

API를 구현할 경우 필수 테스트:

```text
POST /api/holdings/{id}/probability/ 정상 응답
다른 사용자의 holding 접근 차단
buy_price 누락 시 400
buy_quantity 0이면 400
manual stop_loss_type인데 stop_loss_price 없으면 400
response에 success_probability, failure_probability, neutral_probability 포함
disclaimer 포함
```

---

# 17. 구현 파일 구조

권장 파일 구조:

```text
decisions/
 ├── services/
 │   ├── probability_service.py
 │   ├── probability_components.py
 │   ├── probability_dataclasses.py
 │   └── probability_labels.py
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

단순 구현에서는 `probability_service.py` 하나로 시작해도 된다.  
하지만 함수가 길어지면 위 구조처럼 분리한다.

---

# 18. Codex 구현 지시 요약

Codex가 구현할 때 다음 순서를 따른다.

```text
1. probability dataclass 정의
2. scenario validation 구현
3. new_average_price, target_price, stop_loss_price 계산 함수 구현
4. normal_cdf, sigmoid, clamp, normalize 유틸 함수 구현
5. score component 구현
6. volatility component 구현
7. historical outcome 판정 함수 구현
8. historical similar case 탐색 함수 구현
9. risk hard override 구현
10. component combine 구현
11. confidence 계산 구현
12. main probability service 구현
13. 선택적으로 API serializer/view/url 구현
14. 테스트 작성
```

---

# 19. 구현 시 금지 사항

```text
1. 확률을 수익 보장처럼 표현하지 말 것
2. success_probability만 반환하지 말고 failure/neutral도 함께 반환할 것
3. 실패확률을 단순히 1 - 성공확률로 계산하지 말 것
4. historical sample이 부족한데 높은 confidence를 반환하지 말 것
5. critical risk를 일반 점수로 희석하지 말 것
6. 같은 날 목표/손절 동시 도달 상황을 무시하지 말 것
7. Decimal과 float을 무분별하게 섞지 말 것
8. 데이터 부족을 조용히 숨기지 말 것
```

---

# 20. 최종 요약

본 확률 엔진은 다음 세 가지 정보를 결합한다.

```text
1. 과거 유사 패턴에서 실제로 목표/손절 중 무엇에 먼저 도달했는가
2. 현재 Scoring Engine 점수상 추가 매수 검토 조건이 얼마나 우호적인가
3. 현재 변동성 기준 목표 가격과 손절 가격이 얼마나 가까운가
```

최종 결과는 다음 세 확률로 반환한다.

```text
success_probability
failure_probability
neutral_probability
```

그리고 반드시 다음 보조 정보를 함께 반환한다.

```text
confidence
confidence_label
target_price
stop_loss_price
new_average_price
basis
warnings
disclaimer
```

이 확률 엔진은 기존 시스템을 다음 수준으로 확장한다.

```text
기존:
지금 물타기를 검토해도 되는 상태인가?

확장:
이 조건으로 물타기를 실행했을 때 목표 회복과 손절 위험 중 어느 쪽 가능성이 더 큰가?
```

최종 사용자 표현은 항상 다음 원칙을 따른다.

```text
본 결과는 과거 데이터와 현재 조건 기반의 추정 확률이며,
매수·매도 추천이 아닙니다.
미래 수익 또는 손실 회피를 보장하지 않습니다.
```
