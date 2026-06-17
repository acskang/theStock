# 14_portfolio_risk_engine_design.md

# theStock 포트폴리오 리스크 엔진 설계서

---

# 0. 문서 목적

현재 `theStock`의 핵심 판단은 개별 보유 종목 단위의 물타기 가능성에 초점이 맞춰져 있다.

하지만 실제 투자자에게 더 중요한 질문은 다음이다.

```text
이 종목을 더 사도 되는가?
```

이 질문은 개별 종목만 보고 답할 수 없다.

다음 질문이 함께 필요하다.

```text
1. 이 종목이 전체 포트폴리오에서 이미 너무 큰 비중인가?
2. 같은 섹터/테마에 이미 많이 노출되어 있는가?
3. 현금 여력은 충분한가?
4. 다른 손실 종목도 많은가?
5. 추가 매수 후 최악의 경우 계좌 전체 손실은 얼마인가?
6. 사용자의 위험 성향에 비해 과도한가?
```

이 문서는 개별 종목 판단을 포트폴리오 전체 리스크 판단으로 확장하기 위한 설계서다.

---

# 1. 최상위 원칙

## 1.1 개별 종목 판단만으로 추가 매수 가능 표시 금지

개별 종목 점수가 좋더라도 포트폴리오 전체 비중이 과도하면 추가 매수를 제한해야 한다.

예:

```text
삼성전자 자체 점수는 양호
하지만 이미 전체 투자금의 65%가 삼성전자
→ 추가 매수 부적합 또는 비중 축소 검토
```

## 1.2 포트폴리오 리스크는 컨설팅 결과의 상위 게이트

권장 흐름:

```text
1. 개별 종목 리스크 게이트
2. 데이터 품질 게이트
3. 포트폴리오 리스크 게이트
4. Scoring Engine
5. Probability Engine
6. Consulting Engine
```

## 1.3 사용자 위험 성향 반영

같은 포트폴리오라도 사용자 위험 성향에 따라 허용 비중이 달라질 수 있다.

위험 성향 후보:

```text
CONSERVATIVE
BALANCED
AGGRESSIVE
UNKNOWN
```

초기에는 UNKNOWN 또는 BALANCED 기본값을 사용한다.

---

# 2. 필요한 입력 데이터

## 2.1 사용자 보유 종목

```text
stock
quantity
average_price
current_price
market_value
unrealized_profit_loss
unrealized_profit_loss_rate
sector
theme
instrument_type
```

## 2.2 현금 정보

가능하면 사용자가 직접 입력한다.

```text
available_cash
monthly_income_optional
emergency_cash_required_optional
max_additional_investment_budget_optional
```

금융계좌 자동 연동이 없다면 수동 입력 기반으로 시작한다.

## 2.3 사용자 위험 성향

간단한 설문 기반으로 수집할 수 있다.

```text
1. 투자 기간
2. 최대 감내 손실률
3. 추가 투자 가능 금액
4. 손실 시 대응 방식
5. 안정성/수익성 선호도
```

---

# 3. 리스크 지표

## 3.1 단일 종목 집중도

```text
single_stock_weight = stock_market_value / total_portfolio_market_value
```

권장 기준:

| 위험 성향 | 주의 | 위험 | 차단 |
|---|---:|---:|---:|
| CONSERVATIVE | 15% | 25% | 35% |
| BALANCED | 20% | 35% | 50% |
| AGGRESSIVE | 30% | 50% | 65% |

## 3.2 추가 매수 후 집중도

```text
post_buy_weight = (stock_market_value + additional_buy_amount) / (total_market_value + additional_buy_amount)
```

컨설팅 결과는 현재 비중뿐 아니라 추가 매수 후 비중을 기준으로 제한해야 한다.

## 3.3 섹터 집중도

```text
sector_weight = sector_market_value / total_portfolio_market_value
```

예:

```text
반도체 55%
바이오 40%
2차전지 60%
```

섹터 집중도가 높으면 개별 종목이 좋아도 추가 매수 제한이 필요하다.

## 3.4 테마 집중도

테마는 섹터보다 더 위험할 수 있다.

예:

```text
AI 테마
2차전지 테마
원전 테마
로봇 테마
정치 테마
```

테마 정보는 초기에는 수동/관리자 입력 또는 외부 데이터 provider를 통해 보강한다.

## 3.5 손실 종목 비율

```text
losing_position_ratio = losing_positions_count / total_positions_count
```

손실 종목이 많은 상태에서 추가 물타기는 전체 계좌 리스크를 키울 수 있다.

## 3.6 계좌 최대 손실 시나리오

종목별 손절가 또는 스트레스 하락률을 적용한다.

```text
portfolio_loss_if_stop = sum(position_loss_to_stop)
portfolio_loss_rate_if_stop = portfolio_loss_if_stop / total_portfolio_value
```

## 3.7 현금 소진 위험

```text
cash_after_buy = available_cash - additional_buy_amount
cash_buffer_ratio = cash_after_buy / total_portfolio_value
```

현금이 거의 없어지는 추가 매수는 위험하다.

---

# 4. PortfolioRiskScore

## 4.1 점수 구성

```text
single_stock_concentration_score
sector_concentration_score
theme_concentration_score
cash_buffer_score
loss_cluster_score
stress_loss_score
liquidity_score
```

최종:

```text
portfolio_risk_score = weighted_sum(...)
```

점수 범위:

```text
0 = 낮은 리스크
100 = 매우 높은 리스크
```

## 4.2 등급

```text
LOW
MODERATE
HIGH
CRITICAL
```

처리:

| 등급 | 컨설팅 처리 |
|---|---|
| LOW | 개별 종목 판단 진행 |
| MODERATE | 주의 문구 표시 |
| HIGH | 추가 매수 한도 축소 |
| CRITICAL | 추가 매수 부적합 또는 판단 중단 |

---

# 5. 추가 매수 한도 조정

기존 capital_plan은 개별 종목 기준 한도를 계산한다.

포트폴리오 리스크 엔진은 이 한도를 조정한다.

```text
final_additional_buy_limit = min(
    individual_stock_limit,
    single_stock_weight_limit,
    sector_weight_limit,
    cash_buffer_limit,
    stress_loss_limit
)
```

결과 표현:

```text
개별 종목 기준으로는 1,000,000원까지 검토 가능하지만,
전체 포트폴리오 비중을 고려하면 350,000원 이하로 제한하는 것이 보수적입니다.
```

주의:

```text
추천 매수 금액이 아니라 참고 한도라고 표현한다.
```

---

# 6. 데이터 모델

## 6.1 PortfolioSnapshot

```text
user
snapshot_date
total_market_value
total_cost_basis
total_unrealized_pnl
total_unrealized_pnl_rate
available_cash
risk_profile
created_at
```

## 6.2 PortfolioPositionSnapshot

```text
portfolio_snapshot
stock
quantity
average_price
current_price
market_value
cost_basis
unrealized_pnl
unrealized_pnl_rate
sector
theme
weight
```

## 6.3 PortfolioRiskAssessment

```text
user
holding
portfolio_snapshot
risk_score
risk_grade
single_stock_weight
post_buy_weight
sector_weight
theme_weight
cash_after_buy
stress_loss_amount
stress_loss_rate
warnings_json
limits_json
created_at
```

---

# 7. API 설계

## 7.1 포트폴리오 요약 API

```http
GET /api/portfolio/summary/
```

응답 예:

```json
{
  "total_market_value": 12000000,
  "available_cash": 3000000,
  "position_count": 8,
  "largest_position": {
    "stock_code": "005930",
    "weight": 0.42
  },
  "sector_weights": [
    {"sector": "반도체", "weight": 0.55}
  ],
  "risk_grade": "HIGH"
}
```

## 7.2 포트폴리오 리스크 평가 API

```http
POST /api/holdings/{id}/portfolio-risk/
```

요청:

```json
{
  "additional_buy_amount": 500000,
  "available_cash": 3000000
}
```

응답:

```json
{
  "risk_grade": "HIGH",
  "risk_score": 78,
  "post_buy_weight": 0.48,
  "final_additional_buy_limit": 300000,
  "warnings": [
    "해당 종목 비중이 이미 높습니다.",
    "동일 섹터 비중이 50%를 초과합니다."
  ]
}
```

## 7.3 컨설팅 API 통합

기존 consult API 응답에 portfolio_risk 섹션을 추가한다.

```json
{
  "portfolio_risk": {
    "grade": "HIGH",
    "score": 78,
    "final_additional_buy_limit": 300000,
    "warnings": []
  }
}
```

하위 호환성을 위해 기존 필드는 제거하지 않는다.

---

# 8. UI 설계

컨설팅 화면에 다음 섹션을 추가한다.

```text
1. 현재 종목 비중
2. 추가 매수 후 예상 비중
3. 섹터 비중
4. 현금 잔고 영향
5. 최악 시나리오 손실
6. 포트폴리오 리스크 등급
7. 최종 참고 한도
```

표현 예:

```text
이 종목은 현재 전체 포트폴리오의 42%를 차지합니다.
추가 매수 후 비중은 48%로 증가합니다.
동일 섹터 비중도 55%로 높아, 추가 매수 한도를 보수적으로 낮추는 것이 적절합니다.
```

---

# 9. 개인정보 보호

포트폴리오 데이터는 민감한 금융정보다.

원칙:

```text
1. 본인만 조회 가능
2. staff 조회 시 감사 로그 기록
3. 로그에 총투자금/종목별 수량 직접 노출 금지
4. API 응답 캐싱 주의
5. 삭제 요청 시 보유 데이터 삭제 정책 필요
```

---

# 10. 구현 체크리스트

```text
[ ] PortfolioSnapshot 모델 추가 검토
[ ] PortfolioPositionSnapshot 모델 추가 검토
[ ] PortfolioRiskAssessment 모델 추가 검토
[ ] 사용자 현금 입력 방식 정의
[ ] 위험 성향 기본값 정의
[ ] 단일 종목 비중 계산
[ ] 추가 매수 후 비중 계산
[ ] 섹터/테마 비중 계산
[ ] cash buffer 계산
[ ] stress loss 계산
[ ] capital_plan과 최종 한도 통합
[ ] consult API에 portfolio_risk 섹션 추가
[ ] UI에 포트폴리오 리스크 카드 추가
[ ] owner scope 테스트
[ ] staff 감사 로그 추가
```

---

# 11. Codex 작업 지시 요약

```text
theStock의 개별 종목 물타기 판단에 포트폴리오 전체 리스크 엔진을 추가한다.
기존 consult API의 기존 필드는 제거하지 말고 portfolio_risk 섹션을 추가한다.
추가 매수 한도는 개별 종목 한도와 포트폴리오 비중 한도 중 더 보수적인 값을 사용한다.
단일 종목 집중도, 섹터 집중도, 현금 여력, 손실 종목 비율, 스트레스 손실을 계산한다.
모든 포트폴리오 데이터는 owner scope를 적용하고 로그에는 민감 정보를 노출하지 않는다.
```

---

# 12. 결론

물타기 판단은 개별 종목 문제가 아니라 계좌 전체 리스크 문제다.

`theStock`이 사용자에게 더 안전한 서비스를 제공하려면 다음 원칙이 필요하다.

```text
1. 좋은 종목이라도 비중이 과하면 추가 매수를 제한한다.
2. 같은 섹터/테마에 집중되어 있으면 리스크를 경고한다.
3. 현금이 부족하면 물타기보다 방어를 우선한다.
4. 추가 매수 후 최악의 계좌 손실을 보여준다.
5. 추천 금액이 아니라 리스크 한도 내 참고 금액으로 표현한다.
```

포트폴리오 리스크 엔진은 `theStock`을 단일 종목 계산기에서 계좌 전체 리스크 관리 도구로 발전시키는 핵심 기능이다.
