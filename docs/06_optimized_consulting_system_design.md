# 물타기 타이밍 판단 시스템 6단계 설계서: Optimized Consulting System

## 문서 목적

이 문서는 기존 `물타기 타이밍 판단 시스템`을 단순 점수 기반 판단 도구에서 **데이터 기반 물타기 컨설팅 시스템**으로 강화하기 위한 보완 설계서다.

기존 시스템은 다음 질문에 답한다.

```text
지금 이 종목을 추가 매수해도 되는 위험 구간인가?
```

5단계 Probability Engine은 다음 질문을 추가로 다룬다.

```text
특정 가격과 수량으로 물타기를 실행한다고 가정했을 때,
정해진 기간 안에 목표 회복 가격 또는 손절 기준에 먼저 도달할 추정 확률은 얼마인가?
```

본 6단계 Optimized Consulting System은 위 두 질문을 통합하여 다음 질문에 답한다.

```text
현재 보유 종목에 대해,
물타기를 검토해도 되는 상태인지,
어떤 조건이 충족되어야 하는지,
어떤 시나리오가 상대적으로 덜 위험한지,
추가 매수 예산을 어느 수준으로 제한해야 하는지,
그리고 물타기를 하지 말아야 하는 핵심 사유는 무엇인지 설명한다.
```

이 시스템은 매수·매도 추천, 수익률 보장, 자동매매 시스템이 아니다. 모든 결과는 투자 참고용 데이터 분석이며 최종 투자 판단과 책임은 사용자에게 있다.

---

# 1. 기존 시스템의 보완 필요성

## 1.1 기존 시스템의 장점

기존 문서 구조는 다음 장점을 가진다.

```text
1. 물타기를 추가 매수 추천이 아닌 위험도 판단으로 정의했다.
2. 치명적 리스크 필터를 점수보다 우선한다.
3. A/B/C/D 등급을 행동 명령이 아닌 상태 분류로 정의했다.
4. Scoring Engine, API Workflow, Quality Release, Probability Engine이 단계적으로 분리되어 있다.
5. 성공확률, 실패확률, 중립확률을 분리하여 확률 과신을 줄이려는 방향이 있다.
```

## 1.2 기존 시스템의 주요 약점

다음 약점은 6단계에서 보완한다.

```text
1. 점수 체계가 설명 가능하지만 실제 예측 성능 검증 구조가 약하다.
2. 리스크 이벤트가 active 여부 중심이라 시간 감쇠와 해소 상태를 충분히 반영하지 못한다.
3. 시장 상태가 단순 점수로 처리되어 시장 국면별 판단 차이가 부족하다.
4. 종목의 재무 품질과 구조적 안정성 판단이 약하다.
5. 확률 엔진의 결과를 단일 확률로 해석할 위험이 있다.
6. 데이터 부족 처리는 있지만 데이터 품질 자체의 점수화가 부족하다.
7. 예산 제안이 포트폴리오 손실 허용액과 충분히 연결되어 있지 않다.
8. 사용자에게 물타기 금지 사유와 재점검 조건을 충분히 설명하는 구조가 부족하다.
```

---

# 2. 6단계의 목표

## 2.1 핵심 목표

6단계의 목표는 다음이다.

```text
1. Risk Gate Engine 추가
2. Market Regime Engine 추가
3. Stock Quality Engine 추가
4. Data Quality Engine 추가
5. Scenario Comparison Engine 추가
6. Capital Allocation Engine 강화
7. Consulting Report Engine 추가
8. 기존 evaluate/probability 결과를 통합한 consult API 추가
9. 물타기 금지 사유와 재점검 조건 자동 생성
10. 향후 백테스트와 확률 보정을 위한 구조 준비
```

## 2.2 포함 범위

이번 단계에서 구현할 범위는 다음이다.

```text
1. 별도 DB 모델 추가 없이 service layer 중심으로 구현
2. 기존 UserHolding, DailyPrice, InvestorFlow, MarketIndex, RiskEvent, AveragingDecision 모델 재사용
3. 재무 데이터 모델이 없을 경우 StockQualityEngine은 데이터 부족 상태로 안전하게 동작
4. Probability Engine이 존재하면 호출하고, 없거나 실패하면 graceful degradation 처리
5. POST /api/holdings/{id}/consult/ API 추가
6. consult response serializer 또는 plain dict response 구현
7. 단위 테스트와 API 테스트 추가
```

## 2.3 제외 범위

이번 단계에서 하지 않는 작업은 다음이다.

```text
1. 외부 주식 API 연동
2. 뉴스/공시 크롤러 구현
3. 머신러닝 모델 학습
4. 실시간 시세 연동
5. 자동매매
6. 프론트엔드 화면 구현
7. 재무제표 자동 수집
8. 백테스트 대시보드 구현
```

단, 백테스트와 확률 보정을 향후 구현할 수 있도록 반환 구조와 service 구조는 확장 가능하게 설계한다.

---

# 3. 전체 아키텍처

## 3.1 기존 흐름

```text
Holding
 → Scoring Engine
 → AveragingDecision
 → API Response
```

## 3.2 강화 흐름

```text
Holding
 → Data Quality Engine
 → Risk Gate Engine
 → Market Regime Engine
 → Stock Quality Engine
 → Scoring Engine
 → Probability Engine
 → Scenario Comparison Engine
 → Capital Allocation Engine
 → Consulting Report Engine
 → Consult API Response
```

## 3.3 엔진별 책임

| Engine | 책임 |
|---|---|
| Data Quality Engine | 가격·수급·시장·리스크 데이터의 충분성 및 최신성 평가 |
| Risk Gate Engine | 치명적 리스크에 따른 PASS/CAUTION/BLOCK/CRITICAL 판정 |
| Market Regime Engine | 시장 국면 분류 및 등급 상한/점수 보정 제공 |
| Stock Quality Engine | 종목 재무·구조적 품질 평가. 데이터 없으면 unknown 처리 |
| Scoring Engine | 기존 A/B/C/D 판단 점수 계산 |
| Probability Engine | 특정 시나리오의 성공/실패/중립 확률 계산 |
| Scenario Comparison Engine | 보수형·기본형·공격형 물타기 시나리오 비교 |
| Capital Allocation Engine | 손실 허용액 중심의 예산 제한 계산 |
| Consulting Report Engine | 최종 등급, 핵심 사유, 금지 사유, 재점검 조건 생성 |

---

# 4. Data Quality Engine

## 4.1 목적

Data Quality Engine은 계산 결과의 신뢰도를 판단한다. 물타기 판단에서 데이터가 부족하거나 오래되었으면 좋은 점수가 나와도 신뢰하기 어렵다.

## 4.2 구현 위치

```text
decisions/services/data_quality_service.py
```

## 4.3 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class DataQualityResult:
    overall_score: Decimal
    label: str
    price_data_days: int
    latest_price_age_days: int | None
    investor_flow_days: int
    market_data_available: bool
    risk_event_available: bool
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

Python 3.9 이하 호환이 필요하면 `int | None` 대신 `Optional[int]`를 사용한다.

## 4.4 점수 기준

| 조건 | 점수 |
|---|---:|
| 가격 데이터 120거래일 이상 | +0.30 |
| 가격 데이터 60~119거래일 | +0.20 |
| 가격 데이터 30~59거래일 | +0.10 |
| 최신 가격 1영업일 이내 | +0.20 |
| 최신 가격 3영업일 이내 | +0.10 |
| 수급 데이터 20거래일 이상 | +0.15 |
| 수급 데이터 5~19거래일 | +0.08 |
| 시장 데이터 존재 | +0.15 |
| 리스크 이벤트 조회 가능 | +0.10 |
| 필수 계산 가능 상태 | +0.10 |

최종 점수는 0~1 범위로 보정한다.

## 4.5 label 기준

| overall_score | label |
|---:|---|
| 0.80 이상 | 높음 |
| 0.60 ~ 0.7999 | 보통 |
| 0.40 ~ 0.5999 | 낮음 |
| 0.40 미만 | 매우 낮음 |

## 4.6 등급 제한 룰

```text
data_quality < 0.40 → 최종 등급 최대 C
data_quality < 0.60 → 최종 등급 최대 B
data_quality >= 0.60 → 데이터 품질로 인한 등급 제한 없음
```

---

# 5. Risk Gate Engine

## 5.1 목적

Risk Gate Engine은 점수 계산보다 먼저 실행되어 치명적 리스크를 행동 가능성에서 분리한다.

## 5.2 구현 위치

```text
decisions/services/risk_gate_service.py
```

## 5.3 dataclass

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RiskGateResult:
    status: str
    grade_cap: str | None
    score_multiplier: float
    critical_events: list
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 5.4 status 정의

| status | 의미 | 처리 |
|---|---|---|
| PASS | 치명적 위험 없음 | 정상 평가 |
| CAUTION | 주의 필요 | 최종 등급 최대 B |
| BLOCK | 물타기 차단 권장 | 최종 등급 최대 C |
| CRITICAL | 치명적 위험 | 최종 등급 D 고정 |

## 5.5 리스크 이벤트 매핑

| 이벤트 | 기본 status | 설명 |
|---|---|---|
| 거래정지 | CRITICAL | 정상 매매 불가 |
| 상장폐지 위험 | CRITICAL | 원금 회수 위험 |
| 감사의견 거절 | CRITICAL | 회계 신뢰성 훼손 |
| 관리종목 지정 | CRITICAL | 시장 위험 종목 |
| 회생절차 | CRITICAL | 구조적 위험 |
| 자본잠식 심화 | CRITICAL | 재무 안정성 훼손 |
| 감자 | BLOCK | 주주가치 훼손 가능성 |
| 대규모 유상증자 | BLOCK | 희석 및 수급 악화 |
| 횡령·배임 | BLOCK 또는 CRITICAL | 규모와 영향에 따라 분류 |
| 영업손실 지속 | CAUTION 또는 BLOCK | 구조적 악화 가능성 |
| 고점 대비 -60% 이상 | CAUTION 또는 BLOCK | 단순 조정이 아닐 가능성 |

## 5.6 시간 감쇠 보정

RiskEvent 모델에 event_date가 있는 경우 다음 감쇠를 적용한다.

```text
0~7일: 1.00
8~30일: 0.80
31~90일: 0.60
91~180일: 0.40
181일 이상: 0.25
```

단, critical 이벤트는 해소 여부가 명확하지 않으면 시간 감쇠로 PASS 처리하지 않는다.

---

# 6. Market Regime Engine

## 6.1 목적

시장 전체 환경을 단순 점수가 아닌 국면으로 판단한다. 같은 기술적 반등 신호라도 시장 국면에 따라 신뢰도가 달라진다.

## 6.2 구현 위치

```text
marketdata/services/market_regime_service.py
```

## 6.3 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class MarketRegimeResult:
    regime: str
    score_adjustment: int
    score_multiplier: Decimal
    grade_cap: str | None
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 6.4 regime 정의

| regime | 의미 | multiplier | grade_cap |
|---|---|---:|---|
| risk_on | 상승 우호 국면 | 1.10 | None |
| pullback | 상승 추세 내 조정 | 1.00 | None |
| sideways | 박스권 | 0.95 | A |
| risk_off | 위험 회피 하락장 | 0.75 | B |
| capitulation | 투매장 | 0.60 | C |
| rebound | 초기 반등장 | 1.00 | B |
| unknown | 판단 불가 | 0.90 | B |

## 6.5 판단 기준 1차 구현

MarketIndex 데이터에서 KOSPI, KOSDAQ 또는 대표 지수를 사용한다.

```text
1. 최근 20거래일 수익률
2. 최근 60거래일 수익률
3. 20일 이동평균과 60일 이동평균 관계
4. 최근 5거래일 급락 여부
5. 지수 변동성
```

1차 구현 규칙:

```text
20일 수익률 > 3% and 60일 수익률 > 5% → risk_on
20일 수익률 < -8% or 최근 5일 -6% 이하 → risk_off
20일 수익률 < -12% or 최근 5일 -10% 이하 → capitulation
60일 수익률 > 3% and 20일 수익률 -5~0% → pullback
20일 수익률 -3~3% and 60일 수익률 -5~5% → sideways
20일 수익률 > 5% and 60일 수익률 < 0 → rebound
데이터 부족 → unknown
```

---

# 7. Stock Quality Engine

## 7.1 목적

물타기는 구조적 부실 종목에서 가장 위험하다. Stock Quality Engine은 재무 품질, 상장 상태, 업종 안정성, 실적 흐름 등을 바탕으로 종목 품질을 평가한다.

## 7.2 구현 위치

```text
stocks/services/stock_quality_service.py
```

## 7.3 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class StockQualityResult:
    quality_grade: str
    score: Decimal
    grade_cap: str | None
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 7.4 품질 등급

| quality_grade | 의미 | 처리 |
|---|---|---|
| Q1 | 우량 | 제한 없음 |
| Q2 | 보통 | 제한 없음 |
| Q3 | 취약 | 최대 B |
| Q4 | 위험 | 최대 C |
| Q5 | 구조적 위험 | D 또는 물타기 금지 |
| UNKNOWN | 데이터 부족 | 최대 B |

## 7.5 1차 구현 원칙

현재 재무 모델이 없다면 다음처럼 동작한다.

```text
1. Stock 기본 정보와 RiskEvent만 사용한다.
2. 재무 데이터가 없으면 quality_grade = UNKNOWN.
3. UNKNOWN은 시스템 실패가 아니라 데이터 품질 경고로 처리한다.
4. 향후 FinancialSnapshot 모델을 추가할 수 있도록 details 구조를 열어둔다.
```

향후 추가 권장 모델:

```text
FinancialSnapshot
- stock
- fiscal_year
- fiscal_quarter
- revenue
- operating_profit
- net_income
- operating_cash_flow
- debt_ratio
- current_ratio
- equity
- capital_impairment_rate
- roe
- per
- pbr
```

---

# 8. Scenario Comparison Engine

## 8.1 목적

단일 확률 결과보다 여러 물타기 시나리오를 비교해야 실제 컨설팅 가치가 높아진다. 같은 종목이라도 추가 매수 수량과 목표/손절 조건에 따라 위험이 달라진다.

## 8.2 구현 위치

```text
decisions/services/scenario_comparison_service.py
```

## 8.3 기본 시나리오

사용자가 별도 시나리오를 주지 않으면 다음 3개를 자동 생성한다.

| scenario_type | buy_quantity | 의미 |
|---|---:|---|
| conservative | 현재 보유 수량의 25% | 최소 물타기 |
| base | 현재 보유 수량의 50% | 기본 물타기 |
| aggressive | 현재 보유 수량의 100% | 공격적 물타기 |

buy_price는 기본적으로 최신 종가를 사용한다. 단, request body에 buy_price가 있으면 해당 값을 사용한다.

## 8.4 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class ScenarioComparisonItem:
    scenario_type: str
    buy_price: Decimal
    buy_quantity: int
    new_average_price: Decimal
    target_price: Decimal
    stop_loss_price: Decimal
    success_probability: Decimal | None
    failure_probability: Decimal | None
    neutral_probability: Decimal | None
    confidence: Decimal | None
    efficiency_score: Decimal
    status: str
    warnings: list[str] = field(default_factory=list)
```

## 8.5 efficiency_score

성공확률만 높다고 좋은 시나리오가 아니다. 실패확률과 추가 투입금도 함께 고려한다.

```text
efficiency_score =
  success_probability
  - failure_probability * 1.3
  - capital_pressure_penalty
  + confidence * 0.1
```

capital_pressure_penalty:

```text
additional_amount / max_additional_budget * 0.2
```

max_additional_budget이 0이거나 없으면 penalty는 0.2로 보수 처리한다.

## 8.6 status 기준

| 조건 | status |
|---|---|
| RiskGate CRITICAL | 금지 |
| RiskGate BLOCK | 금지 |
| failure_probability >= 0.45 | 위험 |
| success_probability >= 0.55 and failure_probability < 0.30 and confidence >= 0.50 | 제한 검토 |
| confidence < 0.40 | 신뢰도 낮음 |
| 그 외 | 관찰 |

---

# 9. Capital Allocation Engine

## 9.1 목적

물타기의 핵심은 “얼마를 더 살 수 있는가”가 아니라 “추가 하락이 와도 계좌가 망가지지 않는가”다.

## 9.2 구현 위치

```text
decisions/services/capital_allocation_service.py
```

## 9.3 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class CapitalPlanResult:
    max_allowed_budget: Decimal
    first_entry_budget: Decimal
    second_entry_budget: Decimal
    third_entry_budget: Decimal
    first_entry_condition: str
    second_entry_condition: str
    third_entry_condition: str
    stop_loss_price: Decimal | None
    estimated_max_loss: Decimal | None
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 9.4 기본 예산 계산

```text
max_allowed_budget = min(
    holding.max_additional_budget,
    risk_gate_budget_cap,
    market_regime_budget_cap,
    data_quality_budget_cap
)
```

## 9.5 보정 계수

| 조건 | budget multiplier |
|---|---:|
| RiskGate PASS | 1.00 |
| RiskGate CAUTION | 0.50 |
| RiskGate BLOCK | 0.00 |
| RiskGate CRITICAL | 0.00 |
| Market risk_on | 1.00 |
| Market pullback | 0.80 |
| Market sideways | 0.60 |
| Market risk_off | 0.30 |
| Market capitulation | 0.00 |
| DataQuality 낮음 | 0.50 |
| DataQuality 매우 낮음 | 0.00 |

## 9.6 분할 매수 구조

```text
first_entry_budget = max_allowed_budget * 0.40
second_entry_budget = max_allowed_budget * 0.30
third_entry_budget = max_allowed_budget * 0.30
```

단, RiskGate가 CAUTION이면 1차만 허용하고 2차·3차는 조건부로 둔다.

## 9.7 진입 조건 예시

```text
1차: 현재 조건이 유지되고 RiskGate가 PASS일 때만 검토
2차: 20일 이동평균 회복 후 2거래일 이상 유지
3차: 거래량 증가와 함께 직전 고점 돌파 확인
```

---

# 10. Consulting Report Engine

## 10.1 목적

Consulting Report Engine은 여러 엔진 결과를 통합해 사용자가 이해할 수 있는 결과를 만든다.

## 10.2 구현 위치

```text
decisions/services/consulting_service.py
```

## 10.3 dataclass

```python
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConsultingResult:
    final_grade: str
    consulting_status: str
    summary: str
    risk_gate: dict
    data_quality: dict
    market_regime: dict
    stock_quality: dict
    base_decision: dict
    probability: dict | None
    scenario_table: list[dict]
    capital_plan: dict
    main_blockers: list[str] = field(default_factory=list)
    positive_factors: list[str] = field(default_factory=list)
    recheck_conditions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = (
        "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. "
        "미래 수익 또는 손실 회피를 보장하지 않습니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다."
    )
```

## 10.4 최종 등급 보정 순서

```text
1. Scoring Engine의 base grade를 가져온다.
2. RiskGate grade_cap을 적용한다.
3. MarketRegime grade_cap을 적용한다.
4. StockQuality grade_cap을 적용한다.
5. DataQuality grade_cap을 적용한다.
6. Probability failure risk가 높으면 한 단계 낮춘다.
7. 최종 등급을 final_grade로 반환한다.
```

등급 제한 함수:

```python
def cap_grade(grade: str, cap: str | None) -> str:
    # A > B > C > D 순서
    # cap이 B이면 A는 B로 낮추고 B/C/D는 유지
```

## 10.5 consulting_status 기준

| final_grade | status |
|---|---|
| A | 추가 매수 가능성 검토 구간 |
| B | 관찰 후 제한 검토 구간 |
| C | 물타기 금지 구간 |
| D | 손절 또는 비중 축소 기준 점검 구간 |

## 10.6 main_blockers 생성 기준

다음 조건을 blocker로 넣는다.

```text
1. RiskGate BLOCK 또는 CRITICAL 사유
2. MarketRegime risk_off 또는 capitulation
3. DataQuality 낮음 또는 매우 낮음
4. StockQuality Q4/Q5/UNKNOWN
5. Probability failure_probability >= 0.40
6. Scoring Engine의 주요 부정 reason
7. 지지선 이탈
8. 외국인·기관 동시 순매도
```

## 10.7 recheck_conditions 생성 기준

예시:

```text
1. 20일 이동평균 회복 후 2거래일 유지
2. 주요 지지선 재회복
3. 외국인 또는 기관 순매수 전환
4. 거래량 증가를 동반한 반등 확인
5. 시장 국면 risk_off 해제
6. critical 또는 high risk event 해소 확인
7. 데이터 품질 보강 후 재평가
```

---

# 11. Consult API 설계

## 11.1 Endpoint

```http
POST /api/holdings/{id}/consult/
```

## 11.2 Request Body

모든 필드는 선택값이다.

```json
{
  "buy_price": "69000.00",
  "lookahead_days": 20,
  "target_profit_rate": "0.00",
  "stop_loss_type": "support_or_atr",
  "stop_loss_price": null,
  "include_scenarios": true
}
```

## 11.3 Response

```json
{
  "stock": {
    "code": "005930",
    "name": "삼성전자"
  },
  "final_grade": "B",
  "consulting_status": "관찰 후 제한 검토 구간",
  "summary": "일부 반등 신호는 있으나 시장 국면과 데이터 신뢰도를 함께 고려해 제한적 관찰이 필요합니다.",
  "risk_gate": {
    "status": "PASS",
    "grade_cap": null,
    "blockers": []
  },
  "data_quality": {
    "overall_score": "0.8100",
    "label": "높음",
    "warnings": []
  },
  "market_regime": {
    "regime": "pullback",
    "score_multiplier": "1.00",
    "grade_cap": null,
    "reasons": []
  },
  "stock_quality": {
    "quality_grade": "UNKNOWN",
    "grade_cap": "B",
    "warnings": ["재무 품질 데이터가 없어 품질 평가는 제한적입니다."]
  },
  "base_decision": {
    "score": 68,
    "grade": "B",
    "decision": "관찰 구간",
    "reason_summary": "일부 반등 신호 존재"
  },
  "probability": {
    "success_probability": "0.5700",
    "failure_probability": "0.2900",
    "neutral_probability": "0.1400",
    "confidence": "0.6100"
  },
  "scenario_table": [
    {
      "scenario_type": "conservative",
      "buy_price": "69000.00",
      "buy_quantity": 3,
      "new_average_price": "73800.00",
      "success_probability": "0.5100",
      "failure_probability": "0.2200",
      "confidence": "0.6000",
      "status": "관찰"
    }
  ],
  "capital_plan": {
    "max_allowed_budget": "300000.00",
    "first_entry_budget": "120000.00",
    "second_entry_condition": "20일 이동평균 회복 후 2거래일 이상 유지",
    "third_entry_condition": "거래량 증가와 함께 직전 고점 돌파 확인"
  },
  "main_blockers": [],
  "positive_factors": [],
  "recheck_conditions": [
    "20일 이동평균 회복 후 2거래일 유지",
    "외국인 또는 기관 순매수 전환"
  ],
  "warnings": [],
  "disclaimer": "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. 미래 수익 또는 손실 회피를 보장하지 않습니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다."
}
```

## 11.4 권한 처리

기존 API와 동일하게 반드시 request.user 기준으로 holding을 조회한다.

```python
holding = get_object_or_404(
    UserHolding.objects.select_related("stock"),
    id=pk,
    user=request.user,
)
```

---

# 12. 구현 파일 구조

권장 파일 구조:

```text
decisions/
 ├── services/
 │   ├── data_quality_service.py
 │   ├── risk_gate_service.py
 │   ├── scenario_comparison_service.py
 │   ├── capital_allocation_service.py
 │   └── consulting_service.py
 ├── serializers.py
 ├── views.py
 ├── urls.py
 └── tests/
     ├── test_data_quality_service.py
     ├── test_risk_gate_service.py
     ├── test_scenario_comparison_service.py
     ├── test_capital_allocation_service.py
     ├── test_consulting_service.py
     └── test_consult_api.py

marketdata/
 └── services/
     └── market_regime_service.py

stocks/
 └── services/
     └── stock_quality_service.py
```

---

# 13. 테스트 설계

## 13.1 Unit Test

```text
DataQualityResult 점수 계산
RiskGate CRITICAL 처리
RiskGate CAUTION 처리
MarketRegime risk_on/risk_off/capitulation 분류
StockQuality UNKNOWN 처리
ScenarioComparison 기본 3개 시나리오 생성
CapitalPlan RiskGate BLOCK 시 예산 0 처리
cap_grade 함수 정상 동작
```

## 13.2 Service Test

```text
consult_holding 정상 응답
critical risk → final_grade D
data_quality 매우 낮음 → 최대 C
market risk_off → 최대 B
stock_quality UNKNOWN → 최대 B
probability 실패 시에도 consult 정상 응답
```

## 13.3 API Test

```text
POST /api/holdings/{id}/consult/ → 200
다른 사용자 holding 접근 → 404
응답 schema 검증
include_scenarios=false 시 scenario_table 빈 배열 또는 생략 정책 검증
데이터 부족 상황에서도 200 + warnings 포함
```

---

# 14. 로깅

consult 실행 시 다음 로그를 남긴다.

```python
logger.info({
    "event": "consult_holding",
    "user_id": request.user.id,
    "holding_id": holding.id,
    "stock_code": holding.stock.code,
    "final_grade": result.final_grade,
    "risk_gate": result.risk_gate.get("status"),
    "market_regime": result.market_regime.get("regime"),
})
```

예외 발생 시:

```python
logger.exception({
    "event": "consult_holding_failed",
    "user_id": request.user.id,
    "holding_id": pk,
})
```

---

# 15. 안전 문구 원칙

## 15.1 금지 표현

```text
지금 매수하세요.
성공확률이 높으니 물타기하세요.
안전합니다.
수익이 예상됩니다.
손실 회복이 보장됩니다.
바닥입니다.
```

## 15.2 허용 표현

```text
추가 매수 가능성을 검토할 수 있는 구간입니다.
관찰 후 제한적으로 검토할 수 있는 구간입니다.
물타기 금지 구간으로 분류됩니다.
손절 또는 비중 축소 기준 점검이 필요한 구간입니다.
현재 조건 기준 추정 확률입니다.
미래 결과를 보장하지 않습니다.
```

---

# 16. 완료 기준

6단계는 다음 조건을 만족하면 완료로 본다.

```text
1. POST /api/holdings/{id}/consult/ API가 동작한다.
2. RiskGate, DataQuality, MarketRegime, StockQuality 결과가 응답에 포함된다.
3. 기존 Scoring Engine 결과가 base_decision으로 포함된다.
4. Probability Engine이 존재하면 probability와 scenario_table이 생성된다.
5. Probability Engine이 없거나 실패해도 consult API는 warnings와 함께 정상 응답한다.
6. final_grade가 grade cap 규칙에 따라 보정된다.
7. capital_plan이 생성된다.
8. main_blockers와 recheck_conditions가 생성된다.
9. 권한 테스트가 통과한다.
10. 데이터 부족 상황에서도 정상 응답한다.
```

---

# 17. 향후 확장

6단계 이후 확장할 수 있는 기능은 다음이다.

```text
1. Backtesting Framework
2. Probability Calibration
3. Event Study Engine
4. FinancialSnapshot 기반 Stock Quality 고도화
5. Portfolio Risk Engine
6. Sector Regime Engine
7. 공매도·대차잔고 반영
8. 뉴스 감성 분석
9. ML 기반 유사 패턴 검색
10. 컨설팅 리포트 PDF/HTML 생성
```

---

# 18. 핵심 요약

6단계의 핵심은 다음이다.

```text
점수 기반 판단을 그대로 행동으로 연결하지 않는다.
Risk Gate와 Market Regime으로 먼저 위험을 제한한다.
Data Quality로 결과 신뢰도를 표시한다.
Stock Quality로 구조적 부실 위험을 제한한다.
Probability와 Scenario Comparison으로 물타기 조건별 위험을 비교한다.
Capital Allocation으로 추가 매수 예산을 제한한다.
Consulting Report로 금지 사유와 재점검 조건을 명확히 제시한다.
```

이 구조를 적용하면 시스템은 단순한 “물타기 점수 계산기”가 아니라, 사용자의 감정적 추가 매수를 막고 조건부 의사결정을 돕는 **물타기 리스크 컨설팅 시스템**으로 발전한다.
