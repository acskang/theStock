# Codex 실행 프롬프트: 물타기 컨설팅 화면 구현

## 사용 방법

이 파일은 Codex에 그대로 전달하기 위한 실행 프롬프트다.

Codex에게 다음 문서를 함께 제공하라.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
docs/03_api_workflow_design.md
docs/04_quality_release_design.md
docs/05_probability_engine_design.md
docs/06_optimized_consulting_system_design.md
docs/07_consulting_screen_design.md
```

이번 작업의 직접 기준 문서는 다음이다.

```text
docs/07_consulting_screen_design.md
```

---

# 실행 프롬프트 본문

너는 기존 Django REST Framework 기반 `물타기 타이밍 판단 시스템`에 프론트엔드 화면을 구현하는 개발 에이전트다.

백엔드에는 이미 다음 기능이 구현되어 있다.

```text
1. Data Quality Engine
2. Risk Gate Engine
3. Market Regime Engine
4. Stock Quality Engine
5. Scenario Comparison Engine
6. Capital Allocation Engine
7. Consulting Report Engine
8. POST /api/holdings/{id}/consult/ API
9. main_blockers / recheck_conditions 생성
10. Probability Engine 실패 시 graceful degradation 처리
```

이번 작업은 위 기능을 사용할 수 있는 **물타기 컨설팅 화면**을 구현하는 것이다.

---

# 1. 반드시 지킬 원칙

이 시스템은 매수/매도 추천 서비스가 아니다.

화면에서도 다음 표현을 절대 사용하지 마라.

```text
지금 매수하세요
지금 매도하세요
무조건 오릅니다
수익이 예상됩니다
손실 회복이 보장됩니다
바닥입니다
안전합니다
```

허용되는 표현은 다음이다.

```text
추가 매수 가능성을 검토할 수 있는 구간입니다.
관찰이 필요한 구간입니다.
물타기 금지 구간입니다.
손절 또는 비중 축소 기준 점검이 필요한 구간입니다.
본 결과는 투자 참고용 데이터 분석입니다.
```

---

# 2. 구현 목표

이번 작업의 목표는 다음이다.

```text
1. 보유 종목 상세 컨설팅 화면 구현
2. POST /api/holdings/{id}/consult/ API 호출
3. 최종 등급과 컨설팅 상태 표시
4. Data Quality 표시
5. Risk Gate 표시
6. Market Regime 표시
7. Stock Quality 표시
8. 성공/실패/중립 확률 표시
9. Scenario Comparison Table 표시
10. Capital Allocation Plan 표시
11. main_blockers 표시
12. recheck_conditions 표시
13. score_breakdown 표시
14. disclaimer 표시
15. Loading / Error / Empty / Partial 상태 처리
16. 반응형 UI 구현
17. 기본 테스트 작성
```

---

# 3. 구현 방식 선택

프로젝트가 React 또는 TypeScript 프론트엔드를 이미 사용하고 있다면 React 기준으로 구현하라.

프로젝트가 Django template만 사용하고 있다면 Django template + static JS/CSS로 구현하라.

기존 프로젝트 구조를 먼저 확인하고, 기존 방식과 가장 일관된 방식으로 구현하라.

절대 새로운 프론트엔드 프레임워크를 임의로 추가하지 마라.

---

# 4. React/TypeScript 프로젝트일 경우 구현 구조

다음 구조를 권장한다.

```text
src/
 ├── api/
 │   └── consultingApi.ts
 ├── pages/
 │   └── HoldingConsultPage.tsx
 ├── components/
 │   └── consulting/
 │       ├── ConsultHeader.tsx
 │       ├── FinalDecisionCard.tsx
 │       ├── DataQualityCard.tsx
 │       ├── RiskGateCard.tsx
 │       ├── MarketRegimeCard.tsx
 │       ├── StockQualityCard.tsx
 │       ├── ProbabilityCard.tsx
 │       ├── ScenarioComparisonTable.tsx
 │       ├── CapitalPlanCard.tsx
 │       ├── MainBlockersCard.tsx
 │       ├── RecheckConditionsCard.tsx
 │       ├── ScoreBreakdownCard.tsx
 │       ├── DisclaimerBox.tsx
 │       ├── LoadingSkeleton.tsx
 │       └── ErrorState.tsx
 ├── types/
 │   └── consulting.ts
 └── utils/
     ├── formatters.ts
     └── consultingLabels.ts
```

기존 프로젝트에 다른 경로 규칙이 있으면 기존 규칙을 우선한다.

---

# 5. Django template 프로젝트일 경우 구현 구조

다음 구조를 권장한다.

```text
templates/
 └── consulting/
     └── holding_consult.html

static/
 └── consulting/
     ├── consulting.css
     └── holding_consult.js
```

Django view는 다음 경로를 제공한다.

```text
/holdings/<id>/consult/
```

템플릿은 JS에서 다음 API를 호출한다.

```http
POST /api/holdings/{id}/consult/
```

---

# 6. API 클라이언트 구현

다음 API를 호출하는 함수를 작성하라.

```http
POST /api/holdings/{id}/consult/
```

React 예시:

```ts
export async function fetchHoldingConsulting(holdingId: string | number): Promise<ConsultingResponse> {
  const response = await fetch(`/api/holdings/${holdingId}/consult/`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    credentials: "include",
  });

  if (!response.ok) {
    throw new Error(`Consulting API failed: ${response.status}`);
  }

  return response.json();
}
```

Django 세션 인증과 CSRF가 필요한 경우 기존 프로젝트의 CSRF 처리 방식을 따라 `X-CSRFToken`을 포함하라.

---

# 7. TypeScript 타입 정의

React/TypeScript인 경우 다음 타입을 구현하라.

```ts
export interface ConsultingResponse {
  stock?: StockSummary;
  holding?: HoldingSummary;
  final_grade?: string;
  consulting_status?: string;
  decision_summary?: string;
  data_quality?: DataQuality;
  risk_gate?: RiskGate;
  market_regime?: MarketRegime;
  stock_quality?: StockQuality;
  probability?: ProbabilitySummary | null;
  scenario_table?: ScenarioRow[];
  capital_plan?: CapitalPlan;
  main_blockers?: string[];
  recheck_conditions?: string[];
  score_breakdown?: Record<string, number | string>;
  disclaimer?: string;
}

export interface StockSummary {
  code?: string;
  name?: string;
  market?: string;
  sector?: string;
}

export interface HoldingSummary {
  average_price?: string;
  quantity?: number;
  current_price?: string;
  loss_rate?: string;
  max_additional_budget?: string;
}

export interface DataQuality {
  overall_score?: string;
  label?: string;
  price_data_days?: number;
  investor_flow_days?: number;
  market_data_available?: boolean;
  warnings?: string[];
}

export interface RiskGate {
  status?: string;
  label?: string;
  critical_events?: unknown[];
  warnings?: string[];
}

export interface MarketRegime {
  regime?: string;
  label?: string;
  score_adjustment?: string;
  description?: string;
  warnings?: string[];
}

export interface StockQuality {
  quality_grade?: string;
  label?: string;
  warnings?: string[];
}

export interface ProbabilitySummary {
  success_probability?: string;
  failure_probability?: string;
  neutral_probability?: string;
  confidence?: string;
  success_label?: string;
  failure_label?: string;
  confidence_label?: string;
  warnings?: string[];
}

export interface ScenarioRow {
  name?: string;
  buy_price?: string;
  buy_quantity?: number;
  additional_budget?: string;
  new_average_price?: string;
  success_probability?: string;
  failure_probability?: string;
  neutral_probability?: string;
  confidence?: string;
  status?: string;
}

export interface CapitalPlan {
  max_allowed_budget?: string;
  first_entry_budget?: string;
  second_entry_condition?: string;
  third_entry_condition?: string;
  stop_loss_price?: string;
  warnings?: string[];
}
```

---

# 8. 페이지 구현 요구사항

## 8.1 HoldingConsultPage

페이지는 URL parameter에서 holding id를 가져와야 한다.

예시:

```text
/holdings/:id/consult
```

페이지 진입 시 자동으로 consult API를 호출한다.

상태는 다음을 관리한다.

```text
loading
error
data
isRefreshing
```

다시 분석 버튼을 클릭하면 consult API를 재호출한다.

---

## 8.2 필수 표시 영역

다음 컴포넌트를 반드시 화면에 표시하라.

```text
ConsultHeader
FinalDecisionCard
DataQualityCard
RiskGateCard
MarketRegimeCard
StockQualityCard
ProbabilityCard
ScenarioComparisonTable
CapitalPlanCard
MainBlockersCard
RecheckConditionsCard
ScoreBreakdownCard
DisclaimerBox
```

---

# 9. 컴포넌트 상세 요구사항

## 9.1 ConsultHeader

표시 항목:

```text
종목명
종목코드
시장
섹터
현재가
평균 매입가
보유 수량
현재 손익률
다시 분석 버튼
```

누락 데이터는 `-`로 표시한다.

---

## 9.2 FinalDecisionCard

표시 항목:

```text
final_grade
consulting_status
decision_summary
```

등급별 문구:

```text
A: 추가 매수 가능성 검토 구간
B: 관찰 후 제한 검토 구간
C: 물타기 금지 구간
D: 손절/비중 축소 기준 점검 구간
```

---

## 9.3 DataQualityCard

표시 항목:

```text
overall_score
label
price_data_days
investor_flow_days
market_data_available
warnings
```

warnings가 비어 있으면 다음 문구를 표시한다.

```text
데이터 품질 관련 주요 경고가 없습니다.
```

---

## 9.4 RiskGateCard

표시 항목:

```text
status
label
critical_events
warnings
```

status가 CRITICAL이면 화면 상단 FinalDecisionCard 근처에도 위험 배지를 표시하라.

---

## 9.5 MarketRegimeCard

표시 항목:

```text
regime
label
score_adjustment
description
warnings
```

---

## 9.6 StockQualityCard

표시 항목:

```text
quality_grade
label
warnings
```

---

## 9.7 ProbabilityCard

표시 항목:

```text
success_probability
failure_probability
neutral_probability
confidence
success_label
failure_label
confidence_label
warnings
```

probability가 null이거나 주요 필드가 없으면 다음 문구를 표시한다.

```text
확률 계산에 필요한 데이터가 부족하여 성공/실패 확률을 제한적으로 표시합니다.
현재 화면에서는 리스크 게이트와 주요 차단 사유를 우선 확인하세요.
```

성공확률만 크게 강조하지 마라. 실패확률과 중립확률을 같은 수준으로 보여라.

---

## 9.8 ScenarioComparisonTable

컬럼:

```text
시나리오명
추가 매수가
추가 수량
추가 예산
새 평균단가
성공확률
실패확률
중립확률
신뢰도
상태
```

scenario_table이 비어 있으면 다음 문구를 표시한다.

```text
비교 가능한 물타기 시나리오가 없습니다.
```

모바일에서는 가로 스크롤을 허용하라.

---

## 9.9 CapitalPlanCard

표시 항목:

```text
max_allowed_budget
first_entry_budget
second_entry_condition
third_entry_condition
stop_loss_price
warnings
```

반드시 다음 문구를 포함하라.

```text
이 금액은 매수 추천 금액이 아니라 리스크 한도를 넘지 않기 위한 참고 예산입니다.
```

---

## 9.10 MainBlockersCard

main_blockers를 번호 목록으로 표시한다.

비어 있으면 다음 문구를 표시한다.

```text
현재 응답 기준 주요 차단 사유가 없습니다.
```

---

## 9.11 RecheckConditionsCard

recheck_conditions를 체크리스트 형태로 표시한다.

비어 있으면 다음 문구를 표시한다.

```text
현재 응답 기준 별도 재검토 조건이 없습니다.
```

체크박스는 UI 표시용이며 서버 상태를 변경하지 않는다.

---

## 9.12 ScoreBreakdownCard

score_breakdown의 key/value를 표시한다.

가능하면 막대형 UI를 사용하되, 라이브러리를 추가하지 말고 기본 CSS로 구현하라.

---

## 9.13 DisclaimerBox

disclaimer가 있으면 표시한다.

없으면 다음 기본 문구를 표시한다.

```text
본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다.
```

---

# 10. 포맷터 구현

다음 유틸 함수를 구현하라.

```ts
formatMoney(value?: string | number | null): string
formatPercent(value?: string | number | null): string
formatProbability(value?: string | number | null): string
formatNumber(value?: string | number | null): string
safeText(value?: unknown, fallback = "-"): string
```

확률 값은 `0.5700` 형식이면 `57.0%`처럼 표시한다.

---

# 11. 스타일 요구사항

## 11.1 레이아웃

데스크톱:

```text
상단 Header
FinalDecisionCard full width
본문 2 column grid
하단 detail full width
```

모바일:

```text
single column
scenario table horizontal scroll
cards stacked
```

---

## 11.2 디자인 톤

```text
금융 대시보드 스타일
카드 기반 레이아웃
과도한 애니메이션 금지
위험 정보는 명확하게 표시
매수 유도 느낌 금지
```

---

# 12. 상태 처리

## 12.1 Loading

API 호출 중에는 skeleton 또는 loading card를 표시한다.

문구:

```text
물타기 컨설팅 데이터를 분석 중입니다.
가격, 수급, 시장 국면, 리스크 이벤트를 확인하고 있습니다.
```

---

## 12.2 Error

API 실패 시 ErrorState를 표시한다.

문구:

```text
컨설팅 결과를 불러오지 못했습니다.
잠시 후 다시 시도하거나 보유 종목 데이터와 가격 데이터가 등록되어 있는지 확인해 주세요.
```

다시 시도 버튼을 제공한다.

---

## 12.3 Partial

probability가 null이거나 probability warnings가 있더라도 페이지 전체가 깨지면 안 된다.

가능한 데이터는 모두 표시하고, 부족한 영역에만 제한 문구를 표시하라.

---

# 13. 라우팅 연결

기존 라우터 구조에 맞게 컨설팅 페이지 경로를 연결하라.

React Router 예시:

```tsx
<Route path="/holdings/:id/consult" element={<HoldingConsultPage />} />
```

Django URL 예시:

```python
path("holdings/<int:pk>/consult/", HoldingConsultPageView.as_view(), name="holding-consult")
```

보유 종목 목록 화면이 있다면 각 보유 종목 row에 다음 버튼을 추가하라.

```text
컨설팅 보기
```

링크:

```text
/holdings/{id}/consult
```

기존 보유 종목 목록 화면이 없으면 이 버튼 추가는 생략하고, 컨설팅 상세 화면만 구현하라.

---

# 14. 테스트 구현

프로젝트에 테스트 환경이 있다면 다음 테스트를 추가하라.

## 14.1 유틸 테스트

```text
formatMoney 정상 동작
formatPercent 정상 동작
formatProbability 정상 동작
safeText fallback 정상 동작
```

## 14.2 컴포넌트 테스트

```text
FinalDecisionCard가 등급과 상태를 표시한다.
ProbabilityCard가 probability null 상태를 표시한다.
ScenarioComparisonTable이 빈 배열 상태를 표시한다.
MainBlockersCard가 목록을 표시한다.
RecheckConditionsCard가 체크리스트를 표시한다.
```

## 14.3 페이지 테스트

```text
페이지 진입 시 consult API가 호출된다.
API 성공 시 주요 카드가 표시된다.
API 실패 시 ErrorState가 표시된다.
다시 분석 버튼 클릭 시 API가 재호출된다.
```

기존 프로젝트에 프론트엔드 테스트 환경이 없다면 테스트 파일 생성은 최소화하고, 수동 확인 절차를 README 또는 구현 보고에 남겨라.

---

# 15. 구현 시 주의사항

```text
1. API 응답 필드가 일부 없어도 화면이 깨지면 안 된다.
2. 확률 계산 실패가 전체 화면 실패로 이어지면 안 된다.
3. 모든 금액과 확률은 포맷터를 통해 표시한다.
4. 매수/매도 추천처럼 보이는 문구를 사용하지 않는다.
5. View 또는 컴포넌트에서 비즈니스 계산을 새로 만들지 않는다.
6. 백엔드 응답을 화면에 설명 가능하게 표시하는 데 집중한다.
7. 새 라이브러리 추가는 최소화한다.
8. 기존 디자인 시스템이 있으면 기존 컴포넌트를 우선 사용한다.
```

---

# 16. 완료 기준

다음 조건을 만족하면 완료다.

```text
1. /holdings/:id/consult 또는 대응 경로에서 컨설팅 화면 접근 가능
2. POST /api/holdings/{id}/consult/ API 호출 성공
3. 최종 등급, 확률, 시나리오, 예산 계획, 차단 사유, 재검토 조건 표시
4. loading/error/partial 상태 처리
5. 모바일 화면에서 주요 정보 확인 가능
6. 매수/매도 추천성 문구 없음
7. 가능한 테스트 또는 수동 검증 완료
```

---

# 17. 완료 보고 형식

작업 완료 후 다음 형식으로 보고하라.

```text
물타기 컨설팅 화면 구현 완료

구현한 파일:
- ...

구현한 화면:
- ...

연결한 API:
- POST /api/holdings/{id}/consult/

상태 처리:
- Loading
- Error
- Partial
- Empty

테스트 또는 검증:
- ...

주의사항:
- 본 화면은 투자 참고용 데이터 분석 화면이며 매수·매도 추천 화면이 아님
```

---

# 18. 지금 바로 수행

기존 프로젝트 구조를 확인한 뒤, 가장 적절한 방식으로 물타기 컨설팅 화면을 구현하라.

구현 중 모호한 부분이 있으면 `docs/07_consulting_screen_design.md`를 우선 기준으로 삼아라.
