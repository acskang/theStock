# Codex 실행 프롬프트: 6단계 Optimized Consulting System 구현

## 사용 방법

이 파일은 Codex에 그대로 전달하기 위한 6단계 실행 프롬프트다.

Codex에게 이 파일과 함께 다음 문서를 반드시 참조하게 하라.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
docs/03_api_workflow_design.md
docs/04_quality_release_design.md
docs/05_probability_engine_design.md
docs/06_optimized_consulting_system_design.md
```

이번 단계의 직접 기준 문서는 다음이다.

```text
docs/06_optimized_consulting_system_design.md
```

---

# 실행 프롬프트 본문

너는 Django REST Framework 기반 백엔드 서비스를 운영 가능한 수준으로 고도화하는 개발 에이전트다.

이번 작업은 `물타기 타이밍 판단 시스템`의 **6단계 Optimized Consulting System 구현**이다.

기존 시스템은 다음 기능을 가진다.

```text
1. UserHolding 기반 보유 종목 관리
2. Scoring Engine 기반 A/B/C/D 평가
3. evaluate API와 decision 이력 저장
4. Probability Engine 기반 성공/실패/중립 확률 추정
```

이번 단계에서는 기존 점수와 확률을 그대로 행동으로 연결하지 않고, 다음 엔진들을 추가하여 **데이터 기반 물타기 컨설팅 결과**를 생성한다.

```text
1. Data Quality Engine
2. Risk Gate Engine
3. Market Regime Engine
4. Stock Quality Engine
5. Scenario Comparison Engine
6. Capital Allocation Engine
7. Consulting Report Engine
8. POST /api/holdings/{id}/consult/ API
```

이 시스템은 매수·매도 추천 서비스가 아니다. 자동매매도 아니다. 모든 문구와 응답은 투자 참고용 데이터 분석으로 표현해야 한다.

---

# 1. 반드시 지켜야 할 원칙

## 1.1 투자 표현 원칙

절대 다음 표현을 사용하지 마라.

```text
지금 매수하세요.
성공확률이 높으니 물타기하세요.
안전합니다.
수익이 예상됩니다.
손실 회복이 보장됩니다.
바닥입니다.
반드시 오릅니다.
```

허용 표현은 다음이다.

```text
추가 매수 가능성을 검토할 수 있는 구간입니다.
관찰 후 제한적으로 검토할 수 있는 구간입니다.
물타기 금지 구간으로 분류됩니다.
손절 또는 비중 축소 기준 점검이 필요한 구간입니다.
현재 조건 기준 추정 확률입니다.
미래 결과를 보장하지 않습니다.
```

## 1.2 구현 원칙

```text
1. View에 비즈니스 로직을 넣지 마라.
2. Serializer에 계산 로직을 넣지 마라.
3. Service layer에 엔진별 로직을 분리하라.
4. 기존 Scoring Engine과 Probability Engine을 임의로 대체하지 마라.
5. 기존 API를 깨지 마라.
6. 기존 모델 변경과 migration 추가를 피하라.
7. 외부 API 연동을 추가하지 마라.
8. 데이터 부족은 실패가 아니라 warnings로 응답하라.
9. critical risk는 일반 점수로 희석하지 마라.
10. 다른 사용자의 holding에는 절대 접근하지 마라.
```

---

# 2. 구현 대상 파일

다음 파일을 새로 만들거나 기존 파일에 추가하라.

```text
decisions/services/data_quality_service.py
decisions/services/risk_gate_service.py
decisions/services/scenario_comparison_service.py
decisions/services/capital_allocation_service.py
decisions/services/consulting_service.py
marketdata/services/market_regime_service.py
stocks/services/stock_quality_service.py
```

기존 파일에 API와 serializer를 추가하라.

```text
holdings/views.py 또는 decisions/views.py
holdings/urls.py 또는 decisions/urls.py
decisions/serializers.py 또는 holdings/serializers.py
```

테스트는 기존 프로젝트 스타일에 맞추되, 가능하면 다음 구조로 작성하라.

```text
decisions/tests/test_data_quality_service.py
decisions/tests/test_risk_gate_service.py
decisions/tests/test_scenario_comparison_service.py
decisions/tests/test_capital_allocation_service.py
decisions/tests/test_consulting_service.py
decisions/tests/test_consult_api.py
marketdata/tests/test_market_regime_service.py
stocks/tests/test_stock_quality_service.py
```

프로젝트가 단일 `tests.py` 구조라면 해당 앱의 `tests.py`에 추가해도 된다.

---

# 3. Data Quality Engine 구현

## 3.1 파일

```text
decisions/services/data_quality_service.py
```

## 3.2 구현할 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class DataQualityResult:
    overall_score: Decimal
    label: str
    price_data_days: int
    latest_price_age_days: Optional[int]
    investor_flow_days: int
    market_data_available: bool
    risk_event_available: bool
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 3.3 구현할 함수

```python
def evaluate_data_quality(holding) -> DataQualityResult:
    ...


def get_data_quality_grade_cap(result: DataQualityResult) -> str | None:
    ...
```

Python 3.9 이하 호환이 필요하면 `str | None` 대신 `Optional[str]`를 사용하라.

## 3.4 점수 기준

다음 규칙을 구현하라.

```text
가격 데이터 120개 이상: +0.30
가격 데이터 60~119개: +0.20
가격 데이터 30~59개: +0.10
최신 가격 1일 이내: +0.20
최신 가격 3일 이내: +0.10
수급 데이터 20개 이상: +0.15
수급 데이터 5~19개: +0.08
시장 데이터 존재: +0.15
리스크 이벤트 조회 가능: +0.10
기본 필수 계산 가능 상태: +0.10
```

최종 점수는 `Decimal`로 0~1 범위에 clamp하고 소수점 4자리로 quantize하라.

## 3.5 label 기준

```text
0.80 이상: 높음
0.60 이상: 보통
0.40 이상: 낮음
0.40 미만: 매우 낮음
```

## 3.6 grade cap

```text
overall_score < 0.40 → C
overall_score < 0.60 → B
그 외 → None
```

---

# 4. Risk Gate Engine 구현

## 4.1 파일

```text
decisions/services/risk_gate_service.py
```

## 4.2 구현할 dataclass

```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class RiskGateResult:
    status: str
    grade_cap: Optional[str]
    score_multiplier: float
    critical_events: list
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 4.3 구현할 함수

```python
def evaluate_risk_gate(holding) -> RiskGateResult:
    ...


def classify_risk_event(event) -> str:
    ...
```

## 4.4 status 처리

```text
PASS → grade_cap None, multiplier 1.0
CAUTION → grade_cap B, multiplier 0.8
BLOCK → grade_cap C, multiplier 0.5
CRITICAL → grade_cap D, multiplier 0.0
```

## 4.5 이벤트 분류

RiskEvent의 `risk_level`이 critical이면 CRITICAL로 처리한다.

`event_type`, `title`, `description`에 다음 키워드가 있으면 CRITICAL로 처리한다.

```text
거래정지
상장폐지
감사의견 거절
관리종목
회생절차
자본잠식
```

다음 키워드는 BLOCK로 처리한다.

```text
감자
유상증자
횡령
배임
```

다음 키워드는 CAUTION으로 처리한다.

```text
영업손실
적자
실적 부진
투자주의
투자경고
```

키워드가 없고 risk_level이 high이면 BLOCK, medium이면 CAUTION, low이면 CAUTION으로 처리하라.

활성 이벤트가 없으면 PASS를 반환하라.

---

# 5. Market Regime Engine 구현

## 5.1 파일

```text
marketdata/services/market_regime_service.py
```

## 5.2 구현할 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class MarketRegimeResult:
    regime: str
    score_adjustment: int
    score_multiplier: Decimal
    grade_cap: Optional[str]
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 5.3 구현할 함수

```python
def evaluate_market_regime(stock=None) -> MarketRegimeResult:
    ...
```

## 5.4 구현 규칙

MarketIndex 데이터에서 다음 우선순위로 대표 지수를 찾는다.

```text
KOSPI
KOSDAQ
KS11
KQ11
그 외 가장 최근 데이터가 많은 지수
```

최근 60개 MarketIndex 데이터를 사용하라.

```text
데이터 부족 → unknown, multiplier 0.90, grade_cap B
20일 수익률 > 3% and 60일 수익률 > 5% → risk_on, multiplier 1.10, cap None
20일 수익률 < -12% or 최근 5일 수익률 <= -10% → capitulation, multiplier 0.60, cap C
20일 수익률 < -8% or 최근 5일 수익률 <= -6% → risk_off, multiplier 0.75, cap B
60일 수익률 > 3% and -5% <= 20일 수익률 <= 0% → pullback, multiplier 1.00, cap None
-3% <= 20일 수익률 <= 3% and -5% <= 60일 수익률 <= 5% → sideways, multiplier 0.95, cap A
20일 수익률 > 5% and 60일 수익률 < 0% → rebound, multiplier 1.00, cap B
그 외 → unknown, multiplier 0.90, cap B
```

---

# 6. Stock Quality Engine 구현

## 6.1 파일

```text
stocks/services/stock_quality_service.py
```

## 6.2 구현할 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class StockQualityResult:
    quality_grade: str
    score: Decimal
    grade_cap: Optional[str]
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 6.3 구현할 함수

```python
def evaluate_stock_quality(stock) -> StockQualityResult:
    ...
```

## 6.4 1차 구현 원칙

현재 프로젝트에 재무 모델이 없을 가능성이 높다. 재무 모델이 없으면 실패하지 말고 다음을 반환하라.

```text
quality_grade = UNKNOWN
score = Decimal("0.5000")
grade_cap = B
warnings = ["재무 품질 데이터가 없어 품질 평가는 제한적입니다."]
```

단, stock.is_active가 False이면 다음을 반환하라.

```text
quality_grade = Q5
grade_cap = D
blockers = ["비활성 종목으로 분류되어 있습니다."]
```

향후 FinancialSnapshot 모델이 있으면 확장 가능하도록 try/except 또는 optional import 구조로 작성하라.

---

# 7. Scenario Comparison Engine 구현

## 7.1 파일

```text
decisions/services/scenario_comparison_service.py
```

## 7.2 구현할 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class ScenarioComparisonItem:
    scenario_type: str
    buy_price: Decimal
    buy_quantity: int
    new_average_price: Decimal
    target_price: Decimal
    stop_loss_price: Decimal
    success_probability: Optional[Decimal]
    failure_probability: Optional[Decimal]
    neutral_probability: Optional[Decimal]
    confidence: Optional[Decimal]
    efficiency_score: Decimal
    status: str
    warnings: list[str] = field(default_factory=list)
```

## 7.3 구현할 함수

```python
def build_default_scenarios(holding, buy_price=None, lookahead_days=20):
    ...


def compare_scenarios(
    holding,
    *,
    buy_price=None,
    lookahead_days=20,
    target_profit_rate=None,
    stop_loss_type="support_or_atr",
    stop_loss_price=None,
    risk_gate_result=None,
):
    ...
```

## 7.4 기본 시나리오

```text
conservative: max(1, holding.quantity * 25% 반올림)
base: max(1, holding.quantity * 50% 반올림)
aggressive: max(1, holding.quantity * 100%)
```

buy_price가 없으면 최신 DailyPrice.close_price를 사용하라. 최신 가격이 없으면 빈 리스트와 warning을 반환하라.

## 7.5 Probability Engine 연동

기존 Probability Engine이 있다면 다음 함수를 찾아서 사용하라.

```text
decisions.services.probability_service
```

가능한 함수명이 프로젝트와 다를 수 있으므로, 구현된 함수명을 확인하고 가장 적절한 public service 함수를 사용하라.

없는 경우에는 실패하지 말고 다음처럼 처리하라.

```text
success_probability = None
failure_probability = None
neutral_probability = None
confidence = None
warnings에 "Probability Engine을 사용할 수 없어 시나리오 확률 계산을 생략했습니다." 추가
```

## 7.6 efficiency_score

확률이 있으면 다음 공식으로 계산하라.

```text
efficiency_score = success_probability - failure_probability * 1.3 - capital_pressure_penalty + confidence * 0.1
```

확률이 없으면 `Decimal("0.0000")`으로 둔다.

capital_pressure_penalty:

```text
additional_amount / max_additional_budget * 0.2
```

max_additional_budget이 0이면 penalty는 0.2로 처리하라.

## 7.7 status

```text
risk_gate CRITICAL/BLOCK → 금지
failure_probability >= 0.45 → 위험
success_probability >= 0.55 and failure_probability < 0.30 and confidence >= 0.50 → 제한 검토
confidence < 0.40 → 신뢰도 낮음
확률 없음 → 관찰
그 외 → 관찰
```

---

# 8. Capital Allocation Engine 구현

## 8.1 파일

```text
decisions/services/capital_allocation_service.py
```

## 8.2 구현할 dataclass

```python
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class CapitalPlanResult:
    max_allowed_budget: Decimal
    first_entry_budget: Decimal
    second_entry_budget: Decimal
    third_entry_budget: Decimal
    first_entry_condition: str
    second_entry_condition: str
    third_entry_condition: str
    stop_loss_price: Optional[Decimal]
    estimated_max_loss: Optional[Decimal]
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
```

## 8.3 구현할 함수

```python
def build_capital_plan(
    holding,
    *,
    risk_gate_result,
    market_regime_result,
    data_quality_result,
    scenario_items=None,
) -> CapitalPlanResult:
    ...
```

## 8.4 budget multiplier

```text
RiskGate PASS: 1.00
RiskGate CAUTION: 0.50
RiskGate BLOCK: 0.00
RiskGate CRITICAL: 0.00

Market risk_on: 1.00
Market pullback: 0.80
Market sideways: 0.60
Market risk_off: 0.30
Market capitulation: 0.00
Market unknown: 0.50

DataQuality 높음: 1.00
DataQuality 보통: 0.80
DataQuality 낮음: 0.50
DataQuality 매우 낮음: 0.00
```

```text
max_allowed_budget = holding.max_additional_budget * risk_multiplier * market_multiplier * data_quality_multiplier
```

소수점 2자리 Decimal로 quantize하라.

## 8.5 분할 예산

```text
first_entry_budget = max_allowed_budget * 0.40
second_entry_budget = max_allowed_budget * 0.30
third_entry_budget = max_allowed_budget * 0.30
```

RiskGate가 CAUTION이면 second/third budget은 0으로 두고 조건부 재점검 문구를 넣어라.

## 8.6 조건 문구

```text
first_entry_condition: "현재 조건이 유지되고 치명적 리스크가 없을 때만 검토"
second_entry_condition: "20일 이동평균 회복 후 2거래일 이상 유지"
third_entry_condition: "거래량 증가와 함께 직전 고점 돌파 확인"
```

BLOCK/CRITICAL이면 모든 budget은 0이고 조건은 다음으로 둔다.

```text
"현재 리스크 조건에서는 추가 매수 검토를 중단하고 재평가 조건 충족 여부를 확인"
```

---

# 9. Consulting Report Engine 구현

## 9.1 파일

```text
decisions/services/consulting_service.py
```

## 9.2 구현할 dataclass

```python
from dataclasses import dataclass, field
from typing import Optional


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
    probability: Optional[dict]
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

## 9.3 구현할 함수

```python
def cap_grade(grade: str, cap: str | None) -> str:
    ...


def get_consulting_status(final_grade: str) -> str:
    ...


def consult_holding(
    holding,
    *,
    buy_price=None,
    lookahead_days=20,
    target_profit_rate=None,
    stop_loss_type="support_or_atr",
    stop_loss_price=None,
    include_scenarios=True,
) -> ConsultingResult:
    ...
```

## 9.4 cap_grade 규칙

등급 순서는 다음이다.

```text
A > B > C > D
```

cap이 B이면 A만 B로 낮추고 B/C/D는 유지한다.
cap이 C이면 A/B는 C로 낮추고 C/D는 유지한다.
cap이 D이면 항상 D다.
cap이 None이면 원래 grade를 유지한다.

## 9.5 consulting_status

```text
A → 추가 매수 가능성 검토 구간
B → 관찰 후 제한 검토 구간
C → 물타기 금지 구간
D → 손절 또는 비중 축소 기준 점검 구간
```

## 9.6 consult_holding 처리 흐름

다음 순서를 반드시 지켜라.

```text
1. Data Quality Engine 실행
2. Risk Gate Engine 실행
3. Market Regime Engine 실행
4. Stock Quality Engine 실행
5. 기존 evaluate_averaging_timing(holding) 호출
6. base_decision dict 생성
7. include_scenarios가 true이면 Scenario Comparison Engine 실행
8. 가능한 경우 대표 probability 추출
9. Capital Allocation Engine 실행
10. base grade에 RiskGate, MarketRegime, StockQuality, DataQuality grade cap 적용
11. failure_probability가 0.40 이상이면 한 단계 하향
12. main_blockers 생성
13. positive_factors 생성
14. recheck_conditions 생성
15. ConsultingResult 반환
```

## 9.7 Probability Engine 실패 처리

Probability Engine 또는 Scenario Comparison에서 예외가 발생해도 consult_holding 전체를 실패시키지 마라.

```text
warnings에 오류 요약 추가
probability = None
scenario_table = []
나머지 컨설팅 결과는 정상 반환
```

## 9.8 main_blockers 생성

다음 조건을 blockers에 추가하라.

```text
RiskGate BLOCK/CRITICAL 사유
MarketRegime risk_off/capitulation
DataQuality 낮음/매우 낮음
StockQuality Q4/Q5/UNKNOWN
Probability failure_probability >= 0.40
base_decision grade C/D
```

## 9.9 recheck_conditions 생성

항상 최소 3개 이상을 반환하라.

기본값:

```text
20일 이동평균 회복 후 2거래일 유지
주요 지지선 재회복 여부 확인
외국인 또는 기관 순매수 전환 확인
거래량 증가를 동반한 반등 확인
시장 국면 risk_off 해제 확인
```

---

# 10. Consult API 구현

## 10.1 Endpoint

다음 endpoint를 추가하라.

```http
POST /api/holdings/{id}/consult/
```

## 10.2 Request serializer

가능하면 serializer를 구현하라.

```python
class HoldingConsultRequestSerializer(serializers.Serializer):
    buy_price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    lookahead_days = serializers.IntegerField(required=False, min_value=5, max_value=120, default=20)
    target_profit_rate = serializers.DecimalField(max_digits=8, decimal_places=4, required=False, default=Decimal("0"))
    stop_loss_type = serializers.ChoiceField(
        choices=["support_or_atr", "manual", "fixed_rate", "atr", "support"],
        required=False,
        default="support_or_atr",
    )
    stop_loss_price = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)
    include_scenarios = serializers.BooleanField(required=False, default=True)
```

## 10.3 View 구현

권장 위치는 `holdings/views.py`다.

```python
class HoldingConsultAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        holding = get_object_or_404(
            UserHolding.objects.select_related("stock"),
            id=pk,
            user=request.user,
        )

        request_serializer = HoldingConsultRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)

        result = consult_holding(holding, **request_serializer.validated_data)
        return Response(build_consult_response(holding, result), status=200)
```

`build_consult_response`는 service 또는 serializer helper로 구현하라. dataclass는 `dataclasses.asdict`를 사용해 dict로 변환해도 된다. Decimal은 DRF가 처리할 수 있도록 문자열 또는 Decimal 그대로 반환해도 된다.

## 10.4 URL 추가

다음 endpoint가 동작해야 한다.

```text
/api/holdings/{id}/consult/
```

기존 `/evaluate/`, `/decisions/`, `/probability/` endpoint를 깨지 마라.

## 10.5 로깅

성공 시:

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

예외 시에는 `logger.exception`을 사용하라.

---

# 11. 응답 구조

응답은 최소 다음 필드를 포함해야 한다.

```json
{
  "stock": {
    "code": "005930",
    "name": "삼성전자"
  },
  "final_grade": "B",
  "consulting_status": "관찰 후 제한 검토 구간",
  "summary": "일부 반등 신호는 있으나 제한적 관찰이 필요합니다.",
  "risk_gate": {},
  "data_quality": {},
  "market_regime": {},
  "stock_quality": {},
  "base_decision": {},
  "probability": null,
  "scenario_table": [],
  "capital_plan": {},
  "main_blockers": [],
  "positive_factors": [],
  "recheck_conditions": [],
  "warnings": [],
  "disclaimer": "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. 미래 수익 또는 손실 회피를 보장하지 않습니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다."
}
```

---

# 12. 테스트 구현

## 12.1 Data Quality 테스트

```text
가격 데이터 충분 → label 높음 또는 보통
가격 데이터 없음 → label 매우 낮음, warning 포함
get_data_quality_grade_cap 정상 동작
```

## 12.2 Risk Gate 테스트

```text
active critical RiskEvent → CRITICAL, cap D
유상증자 키워드 → BLOCK, cap C
리스크 없음 → PASS
```

## 12.3 Market Regime 테스트

```text
상승 데이터 → risk_on
급락 데이터 → risk_off 또는 capitulation
데이터 부족 → unknown, cap B
```

## 12.4 Stock Quality 테스트

```text
재무 모델 없음 → UNKNOWN, cap B, warning 포함
stock.is_active=False → Q5, cap D
```

## 12.5 Scenario Comparison 테스트

```text
기본 3개 시나리오 생성
RiskGate BLOCK이면 모든 시나리오 status 금지
Probability Engine 부재/실패 시에도 빈 확률로 정상 반환
```

## 12.6 Capital Allocation 테스트

```text
PASS + risk_on + data 높음 → 예산 유지
BLOCK → 예산 0
data 매우 낮음 → 예산 0
CAUTION → 2차/3차 예산 0 또는 조건부 제한
```

## 12.7 Consulting Service 테스트

```text
정상 데이터 → ConsultingResult 반환
critical risk → final_grade D
market risk_off → final_grade 최대 B
data_quality 매우 낮음 → final_grade 최대 C
probability 실패 → warnings 포함 + 정상 반환
recheck_conditions 최소 3개 이상
```

## 12.8 API 테스트

```text
POST /api/holdings/{id}/consult/ → 200
다른 사용자 holding 접근 → 404
응답 필수 필드 포함
include_scenarios=false → scenario_table 빈 배열 또는 생략 정책 검증
데이터 부족 → 200 + warnings 포함
```

---

# 13. 완료 기준

다음 조건을 모두 만족하면 6단계 구현 완료다.

```text
1. POST /api/holdings/{id}/consult/ API가 동작한다.
2. View에 계산 로직이 없다.
3. DataQuality, RiskGate, MarketRegime, StockQuality 결과가 응답에 포함된다.
4. 기존 evaluate_averaging_timing 결과가 base_decision으로 포함된다.
5. Probability Engine이 있으면 scenario_table에 확률이 포함된다.
6. Probability Engine이 없거나 실패해도 consult API는 warnings와 함께 정상 응답한다.
7. final_grade가 grade cap 규칙에 따라 보정된다.
8. capital_plan이 생성된다.
9. main_blockers와 recheck_conditions가 생성된다.
10. 권한 테스트가 통과한다.
11. 데이터 부족 상황에서도 정상 응답한다.
12. 금지 표현이 코드와 테스트 데이터에 포함되지 않는다.
```

---

# 14. 완료 보고 형식

작업 완료 후 다음 형식으로 보고하라.

```text
6단계 Optimized Consulting System 구현 완료

구현한 파일:
- ...

구현한 기능:
- Data Quality Engine
- Risk Gate Engine
- Market Regime Engine
- Stock Quality Engine
- Scenario Comparison Engine
- Capital Allocation Engine
- Consulting Report Engine
- POST /api/holdings/{id}/consult/

테스트:
- 실행 명령: ...
- 결과: ...

주의 사항:
- Probability Engine이 없는 경우 graceful degradation 처리됨
- 재무 데이터 모델이 없는 경우 StockQuality는 UNKNOWN으로 처리됨

다음 단계 제안:
- Backtesting Framework
- Probability Calibration
- FinancialSnapshot 모델
- Event Study Engine
```

---

# 15. 지금 수행

이제 위 설계에 따라 바로 구현하라.

반드시 기존 문서의 원칙을 유지하고, 기존 API를 깨지 말고, 비즈니스 로직은 service layer에 분리하라.
