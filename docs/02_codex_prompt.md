# 02_codex_prompt.md

# Codex 실행 프롬프트: 2단계 Scoring Engine 구현

## 사용 방법

이 파일은 Codex에 그대로 전달하는 실행 프롬프트다.

반드시 아래 설계서를 함께 참고하게 하라.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
```

---

# 실행 프롬프트 본문

너는 Django 기반 백엔드 서비스의 비즈니스 로직을 구현하는 개발 에이전트다.

이번 작업은 `물타기 타이밍 판단 시스템`의 **2단계 Scoring Engine 구현**이다.

이 단계에서는 API를 완성하지 않는다.  
대신 **계산 엔진과 점수 산정 로직을 완성**한다.

---

# 1. 목표

이번 단계의 목표:

```text
1. 기술적 지표 계산 함수 구현
2. 지지선 탐색 로직 구현
3. 거래량 분석 로직 구현
4. 수급 분석 로직 구현
5. 시장 흐름 분석 로직 구현
6. 리스크 이벤트 필터 구현
7. 항목별 점수 계산
8. 총점 계산
9. 등급 변환
10. EvaluationResult 반환 구조 구현
```

---

# 2. 절대 하지 말 것

```text
1. API endpoint 완성
2. AveragingDecision DB 저장 로직 완성
3. 외부 API 연동
4. 프론트엔드 구현
```

---

# 3. 구현 위치

다음 파일에 구현하라:

```text
indicators/services/indicator_service.py
marketdata/services/price_service.py
marketdata/services/market_service.py
decisions/services/support_service.py
decisions/services/volume_service.py
decisions/services/investor_flow_service.py
decisions/services/risk_event_service.py
decisions/services/scoring_service.py
decisions/services/averaging_decision_service.py
```

---

# 4. 핵심 구현 함수

## indicator_service.py

```python
calculate_moving_average
calculate_rsi
calculate_macd
calculate_atr
calculate_volume_ma
calculate_bollinger_bands
```

## price_service.py

```python
get_latest_price
get_recent_prices
extract_close_prices
```

## support_service.py

```python
find_support_zone
calculate_support_score
```

## volume_service.py

```python
calculate_volume_score
```

## investor_flow_service.py

```python
calculate_investor_flow_score
```

## risk_event_service.py

```python
get_active_risk_events
has_critical_risk
calculate_risk_score
```

## scoring_service.py

```python
calculate_trend_score
calculate_total_score
convert_score_to_grade
get_decision_text
build_reason_summary
calculate_suggested_budget
calculate_stop_loss_price
```

## averaging_decision_service.py

```python
evaluate_averaging_timing
```

---

# 5. 핵심 로직 요구사항

## 5.1 critical risk 우선 처리

```text
critical risk 존재 → 즉시 D 등급 반환
```

## 5.2 점수 계산

```text
trend + support + volume + flow + market + risk
```

최종 점수:

```python
final_score = max(0, min(100, raw_score))
```

## 5.3 등급 변환

```text
75+ → A
55~74 → B
35~54 → C
34↓ → D
```

---

# 6. EvaluationResult 구조

```python
@dataclass
class EvaluationResult:
    score: int
    grade: str
    decision: str
    reason_summary: str
    reasons: list
    score_breakdown: dict
    suggested_budget: Decimal
    stop_loss_price: Decimal | None
    disclaimer: str
```

---

# 7. evaluate_averaging_timing 흐름

```text
1. latest price 조회
2. recent prices 조회
3. risk event 조회
4. critical risk 확인
5. indicator 계산
6. 각 점수 계산
7. total score 계산
8. grade 변환
9. decision 생성
10. summary 생성
11. budget 계산
12. stop loss 계산
13. EvaluationResult 반환
```

---

# 8. 테스트 필수 항목

```text
MA 계산 정상 동작
RSI 극단값 테스트
MACD 구조 반환 테스트
ATR 계산 테스트
지지선 계산 테스트
거래량 점수 테스트
수급 점수 테스트
critical risk 테스트
등급 변환 테스트
evaluate_averaging_timing 전체 테스트
```

---

# 9. 품질 규칙

```text
1. 함수는 작게 나눠라
2. 한 함수 = 하나 책임
3. views.py에 로직 넣지 마라
4. Decimal 사용 유지
5. 이유(reasons)를 반드시 생성
```

---

# 10. 완료 보고 형식

```text
2단계 Scoring Engine 구현 완료

구현한 파일:
- ...

구현한 함수:
- ...

테스트:
- pytest 또는 manage.py test

다음 단계:
03_api_workflow_design.md 진행
```

---

# 11. 실행 시작

지금 바로 구현하라.

설계서 기준을 반드시 유지하고,  
뒤로 갈수록 품질이 떨어지면 멈추고 다음 단계로 나누어라.
