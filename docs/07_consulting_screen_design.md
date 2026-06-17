# 물타기 컨설팅 화면 설계서

## 문서 목적

이 문서는 기존에 구현된 `물타기 컨설팅 API`를 사용자가 실제로 활용할 수 있도록 하기 위한 프론트엔드 화면 설계서다.

이미 백엔드에는 다음 기능이 구현되어 있다고 가정한다.

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

본 문서의 목표는 위 기능을 사용자가 한 화면에서 이해하고, 물타기 여부를 감정이 아니라 데이터 기준으로 판단할 수 있게 만드는 것이다.

---

# 1. 화면의 핵심 목적

## 1.1 사용자에게 답해야 할 질문

물타기 컨설팅 화면은 다음 질문에 답해야 한다.

```text
1. 지금 이 종목은 물타기 검토가 가능한 상태인가?
2. 물타기를 하면 어떤 위험이 있는가?
3. 성공확률, 실패확률, 중립확률은 어떻게 추정되는가?
4. 어떤 시나리오가 가장 안전한가?
5. 얼마까지 추가 매수해도 계좌 리스크가 과도하지 않은가?
6. 어떤 조건이 충족되면 다시 검토할 수 있는가?
7. 왜 시스템이 이런 판단을 내렸는가?
```

---

## 1.2 화면의 비목표

다음 표현과 기능은 화면에서 제공하지 않는다.

```text
1. 지금 매수하세요
2. 무조건 반등합니다
3. 수익이 예상됩니다
4. 손실 회복이 보장됩니다
5. 자동매매 실행
6. 목표가 보장
7. 투자 자문처럼 보이는 확정 표현
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

# 2. 화면 IA 정보 구조

물타기 컨설팅 화면은 단일 상세 페이지로 구성한다.

```text
/holdings/:id/consult
```

또는 Django template 기반일 경우:

```text
/consulting/holdings/<id>/
```

화면은 다음 영역으로 나눈다.

```text
1. Header / 종목 요약 영역
2. 최종 컨설팅 판단 카드
3. 데이터 품질 상태 카드
4. Risk Gate 카드
5. Market Regime 카드
6. Stock Quality 카드
7. 성공/실패/중립 확률 카드
8. 시나리오 비교 테이블
9. 자금 배분 계획 카드
10. 주요 금지 사유 main_blockers 영역
11. 재검토 조건 recheck_conditions 영역
12. 세부 근거/점수 breakdown 영역
13. 유의 문구 disclaimer 영역
```

---

# 3. 사용자 흐름

## 3.1 기본 흐름

```text
1. 사용자가 보유 종목 목록 화면에 들어간다.
2. 특정 종목의 “컨설팅 보기” 버튼을 누른다.
3. 프론트엔드는 POST /api/holdings/{id}/consult/ 를 호출한다.
4. 응답 데이터를 화면에 표시한다.
5. 사용자는 최종 판단, 위험 사유, 시나리오, 예산 계획을 확인한다.
6. 필요하면 “다시 분석” 버튼으로 consult API를 재호출한다.
```

---

## 3.2 API 호출 방식

컨설팅 화면 진입 시 자동 호출한다.

```http
POST /api/holdings/{id}/consult/
```

화면에 “다시 분석” 버튼을 두고 동일 API를 재호출한다.

```text
다시 분석 버튼 클릭 → POST /api/holdings/{id}/consult/
```

---

# 4. API 응답 전제 구조

프론트엔드는 다음 형태의 응답을 기준으로 구현한다.

```json
{
  "stock": {
    "code": "005930",
    "name": "삼성전자",
    "market": "KOSPI",
    "sector": "반도체"
  },
  "holding": {
    "average_price": "75000.00",
    "quantity": 10,
    "current_price": "69000.00",
    "loss_rate": "-8.00",
    "max_additional_budget": "1000000.00"
  },
  "final_grade": "B",
  "consulting_status": "관찰 후 제한 검토",
  "decision_summary": "일부 반등 신호는 있으나 거래량 확인이 부족합니다.",
  "data_quality": {
    "overall_score": "0.8100",
    "label": "양호",
    "price_data_days": 240,
    "investor_flow_days": 20,
    "market_data_available": true,
    "warnings": []
  },
  "risk_gate": {
    "status": "PASS",
    "label": "치명적 위험 없음",
    "critical_events": [],
    "warnings": []
  },
  "market_regime": {
    "regime": "pullback",
    "label": "조정장",
    "score_adjustment": "-5",
    "description": "시장 전체는 단기 조정 국면입니다."
  },
  "stock_quality": {
    "quality_grade": "Q1",
    "label": "우량",
    "warnings": []
  },
  "probability": {
    "success_probability": "0.5700",
    "failure_probability": "0.2900",
    "neutral_probability": "0.1400",
    "confidence": "0.6100",
    "success_label": "보통 이상",
    "failure_label": "주의",
    "confidence_label": "보통",
    "warnings": []
  },
  "scenario_table": [
    {
      "name": "보수형",
      "buy_price": "69000.00",
      "buy_quantity": 3,
      "new_average_price": "73500.00",
      "success_probability": "0.5100",
      "failure_probability": "0.2200",
      "neutral_probability": "0.2700",
      "confidence": "0.6200",
      "status": "관찰"
    }
  ],
  "capital_plan": {
    "max_allowed_budget": "300000.00",
    "first_entry_budget": "100000.00",
    "second_entry_condition": "20일선 회복 후",
    "third_entry_condition": "거래량 동반 전고점 돌파 후",
    "warnings": []
  },
  "main_blockers": [
    "거래량 증가가 충분하지 않습니다."
  ],
  "recheck_conditions": [
    "20일선 회복",
    "외국인 또는 기관 순매수 전환"
  ],
  "score_breakdown": {
    "trend": 15,
    "support": 10,
    "volume": 5,
    "flow": 10,
    "market": -5,
    "risk": 0,
    "final_total": 65
  },
  "disclaimer": "본 결과는 투자 참고용 데이터 분석이며 매수·매도 추천이 아닙니다."
}
```

응답 필드가 일부 누락될 수 있으므로 화면은 graceful degradation을 지원해야 한다.

---

# 5. 화면 레이아웃 설계

## 5.1 전체 레이아웃

데스크톱 기준 2단 레이아웃을 사용한다.

```text
┌──────────────────────────────────────────────┐
│ Header: 종목명 / 현재가 / 손익률 / 다시 분석 │
├──────────────────────────────────────────────┤
│ Final Decision Card                           │
├──────────────────────────────┬───────────────┤
│ Probability Card             │ Risk Gate     │
├──────────────────────────────┼───────────────┤
│ Scenario Table               │ Data Quality  │
│                              │ Market Regime │
│                              │ Stock Quality │
├──────────────────────────────┴───────────────┤
│ Capital Allocation Plan                       │
├──────────────────────────────────────────────┤
│ Main Blockers / Recheck Conditions            │
├──────────────────────────────────────────────┤
│ Score Breakdown / Detail Reasons              │
├──────────────────────────────────────────────┤
│ Disclaimer                                    │
└──────────────────────────────────────────────┘
```

모바일에서는 단일 컬럼으로 전환한다.

---

## 5.2 Header 영역

### 표시 항목

```text
종목명
종목코드
시장 구분
섹터
현재가
평균 매입가
보유 수량
현재 손익률
다시 분석 버튼
```

### 상태 표현

손익률은 색상으로 구분한다.

```text
손익률 양수: 상승 색상
손익률 음수: 위험 색상
0 근처: 중립 색상
```

단, 색상만으로 의미를 전달하지 말고 텍스트도 함께 표시한다.

---

## 5.3 Final Decision Card

화면에서 가장 중요한 카드다.

### 표시 항목

```text
최종 등급: A/B/C/D
컨설팅 상태
요약 문장
주요 판단 태그
```

### 등급별 화면 문구

| 등급 | 제목 | 설명 |
|---|---|---|
| A | 추가 매수 가능성 검토 구간 | 조건이 비교적 우호적입니다. 단, 분할 접근과 손절 기준 확인이 필요합니다. |
| B | 관찰 후 제한 검토 구간 | 일부 긍정 신호가 있으나 추가 확인이 필요합니다. |
| C | 물타기 금지 구간 | 하락 지속 또는 리스크 요인이 커 추가 매수는 신중해야 합니다. |
| D | 손절/비중 축소 기준 점검 구간 | 치명적 또는 강한 위험 신호가 확인됩니다. |

### 금지 표현

```text
매수 추천
매도 추천
목표 수익 보장
반등 확정
```

---

## 5.4 Data Quality Card

### 목적

사용자가 분석 결과의 신뢰도를 이해할 수 있게 한다.

### 표시 항목

```text
데이터 품질 점수
품질 라벨
가격 데이터 일수
수급 데이터 일수
시장 데이터 존재 여부
데이터 경고 목록
```

### 라벨 기준

```text
0.80 이상: 양호
0.60 이상: 보통
0.40 이상: 낮음
0.40 미만: 매우 낮음
```

---

## 5.5 Risk Gate Card

### 목적

치명적 위험이 있는지 가장 빠르게 보여준다.

### 표시 항목

```text
Risk Gate 상태
critical event 목록
high risk event 목록
경고 메시지
```

### 상태

```text
PASS
CAUTION
BLOCK
CRITICAL
```

### 상태별 문구

| status | 문구 |
|---|---|
| PASS | 치명적 위험 신호가 확인되지 않았습니다. |
| CAUTION | 주의가 필요한 위험 이벤트가 있습니다. |
| BLOCK | 추가 매수 판단을 제한하는 위험 이벤트가 있습니다. |
| CRITICAL | 치명적 위험 이벤트가 있어 물타기 검토가 부적절합니다. |

---

## 5.6 Market Regime Card

### 표시 항목

```text
시장 국면
시장 국면 설명
점수 보정값
관련 경고
```

### 시장 국면

```text
risk_on
pullback
sideways
risk_off
capitulation
rebound
unknown
```

---

## 5.7 Stock Quality Card

### 표시 항목

```text
품질 등급 Q1~Q5
품질 라벨
재무/종목 품질 경고
등급 제한 사유
```

### 품질 등급 문구

| 등급 | 문구 |
|---|---|
| Q1 | 우량 |
| Q2 | 보통 |
| Q3 | 취약 |
| Q4 | 위험 |
| Q5 | 구조적 위험 |

---

## 5.8 Probability Card

### 목적

성공확률 하나만 강조하지 말고, 실패확률과 중립확률을 함께 보여준다.

### 표시 항목

```text
성공확률
실패확률
중립확률
신뢰도
각 확률 라벨
확률 계산 경고
```

### 중요 원칙

```text
성공확률이 높더라도 실패확률이 높으면 위험으로 표시한다.
confidence가 낮으면 확률 숫자를 크게 강조하지 않는다.
Probability Engine 실패 시 “확률 계산 제한” 상태를 표시한다.
```

### graceful degradation 문구

```text
확률 계산에 필요한 데이터가 부족하여 성공/실패 확률을 제한적으로 표시합니다.
현재 화면에서는 리스크 게이트, 시장 국면, 주요 차단 사유를 우선 확인하세요.
```

---

## 5.9 Scenario Comparison Table

### 목적

사용자가 단일 물타기 판단이 아니라 여러 시나리오를 비교할 수 있게 한다.

### 컬럼

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

### 상태 문구

```text
관찰
제한 검토
위험
금지
```

### 정렬 기준

기본 정렬은 다음 순서로 한다.

```text
1. 실패확률 낮은 순
2. confidence 높은 순
3. 성공확률 높은 순
```

단, API 응답 순서가 의미를 갖는 경우 응답 순서를 우선한다.

---

## 5.10 Capital Allocation Plan Card

### 표시 항목

```text
최대 허용 추가 예산
1차 진입 예산
2차 진입 조건
3차 진입 조건
손절 기준 가격
예산 관련 경고
```

### 핵심 문구

```text
이 금액은 매수 추천 금액이 아니라 리스크 한도를 넘지 않기 위한 참고 예산입니다.
```

---

## 5.11 Main Blockers 영역

### 목적

왜 지금 물타기를 하면 안 되거나 조심해야 하는지 명확히 보여준다.

### 표시 방식

```text
번호 목록
강조 카드
위험 수준 뱃지
```

### 예시

```text
1. 최근 20거래일 저점이 계속 낮아지고 있습니다.
2. 외국인과 기관이 5거래일 연속 동시 순매도 중입니다.
3. 현재가가 주요 지지선을 이탈했습니다.
```

---

## 5.12 Recheck Conditions 영역

### 목적

사용자가 감정적으로 재진입하지 않고, 어떤 조건을 기다려야 하는지 알게 한다.

### 표시 방식

```text
체크리스트 형태
조건 충족 전에는 “관찰” 상태 유지
```

### 예시

```text
[ ] 20일선 회복
[ ] 외국인 또는 기관 순매수 전환
[ ] 지지선 재회복 후 3거래일 유지
[ ] 시장 국면 risk_off 해제
```

---

## 5.13 Score Breakdown 영역

### 목적

판단의 설명 가능성을 제공한다.

### 표시 항목

```text
trend
support
volume
flow
market
risk
final_total
```

막대 그래프 또는 카드형 리스트로 표시한다.

---

# 6. UI 상태 설계

## 6.1 Loading 상태

API 호출 중에는 다음을 표시한다.

```text
물타기 컨설팅 데이터를 분석 중입니다.
가격, 수급, 시장 국면, 리스크 이벤트를 확인하고 있습니다.
```

skeleton card를 사용한다.

---

## 6.2 Empty 상태

holding이 없거나 API가 404를 반환하면 다음을 표시한다.

```text
보유 종목 정보를 찾을 수 없습니다.
보유 종목 목록에서 다시 선택해 주세요.
```

---

## 6.3 Error 상태

예상치 못한 오류가 발생하면 다음을 표시한다.

```text
컨설팅 결과를 불러오지 못했습니다.
잠시 후 다시 시도하거나 보유 종목 데이터와 가격 데이터가 등록되어 있는지 확인해 주세요.
```

---

## 6.4 Partial 상태

Probability Engine이 실패했지만 Consulting Report가 생성된 경우:

```text
일부 확률 계산이 제한되었습니다.
리스크 게이트와 주요 차단 사유를 우선 확인하세요.
```

---

# 7. 컴포넌트 설계

React 기준 권장 컴포넌트 구조는 다음과 같다.

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

Django template 기반이라면 다음 구조를 권장한다.

```text
templates/
 └── consulting/
     └── holding_consult.html

static/
 └── consulting/
     ├── consulting.css
     └── holding_consult.js
```

---

# 8. TypeScript 타입 정의

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

# 9. API 클라이언트 설계

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

CSRF가 필요한 Django 세션 인증 환경에서는 `X-CSRFToken`을 포함한다.

---

# 10. 디자인 스타일 가이드

## 10.1 화면 톤

```text
차분한 금융 대시보드
위험을 과장하지 않되 명확하게 표시
매수 유도 느낌 금지
결과보다 근거 중심
```

---

## 10.2 색상 의미

```text
A / 우호: 초록 계열
B / 관찰: 파랑 또는 노랑 계열
C / 주의: 주황 계열
D / 위험: 빨강 계열
중립/데이터 없음: 회색 계열
```

색상 이름은 프로젝트의 기존 CSS 변수 또는 Tailwind theme를 따른다.

---

## 10.3 접근성

```text
색상만으로 상태를 전달하지 않는다.
상태 텍스트와 아이콘을 함께 표시한다.
테이블은 모바일에서 가로 스크롤을 허용한다.
버튼에는 명확한 aria-label을 둔다.
```

---

# 11. 테스트 기준

## 11.1 단위 테스트

```text
formatPercent 정상 동작
formatMoney 정상 동작
등급 라벨 매핑 정상 동작
누락 필드 fallback 정상 동작
```

---

## 11.2 컴포넌트 테스트

```text
FinalDecisionCard가 A/B/C/D 등급을 정상 표시
ProbabilityCard가 probability null 상태를 정상 표시
ScenarioComparisonTable이 빈 배열을 정상 표시
MainBlockersCard가 빈 배열이면 “주요 차단 사유 없음” 표시
RecheckConditionsCard가 체크리스트 표시
```

---

## 11.3 통합 테스트

```text
페이지 진입 시 consult API 호출
다시 분석 버튼 클릭 시 consult API 재호출
API 실패 시 ErrorState 표시
partial response에서도 페이지 렌더링 유지
```

---

# 12. 완료 기준

```text
1. 사용자가 보유 종목별 컨설팅 화면에 접근할 수 있다.
2. POST /api/holdings/{id}/consult/ 응답을 화면에 표시한다.
3. 최종 등급, 확률, 시나리오, 예산 계획, 차단 사유, 재검토 조건이 보인다.
4. 확률 계산 실패 시에도 화면이 깨지지 않는다.
5. 데이터 누락 시 fallback 문구가 표시된다.
6. 모바일에서도 주요 정보 확인이 가능하다.
7. 매수/매도 추천처럼 보이는 문구가 없다.
8. 테스트가 통과한다.
```

---

# 13. 핵심 요약

물타기 컨설팅 화면은 “매수 버튼을 누르게 하는 화면”이 아니다.

이 화면의 핵심은 다음이다.

```text
1. 위험을 먼저 보여준다.
2. 확률을 성공/실패/중립으로 나누어 보여준다.
3. 단일 판단이 아니라 시나리오를 비교하게 한다.
4. 감정적 물타기를 막기 위해 차단 사유와 재검토 조건을 명확히 보여준다.
5. 사용자가 손실 확대를 피할 수 있도록 예산 한도와 손절 기준을 함께 제시한다.
```
