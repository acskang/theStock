# 12_backtesting_and_probability_calibration_design.md

# theStock 백테스트 및 확률 보정 설계서

---

# 0. 문서 목적

`theStock`의 Probability Engine은 목표가 도달 가능성, 손절가 도달 가능성, 기대 손익, 시나리오별 확률을 제공한다.

하지만 확률값은 단순히 그럴듯한 숫자로 제공되면 안 된다.  
사용자는 확률값을 보고 실제 투자 판단을 바꿀 수 있다.

따라서 Probability Engine은 다음 검증이 필요하다.

```text
1. 과거 데이터에서 실제로 맞았는가?
2. 70%라고 표시한 구간이 실제로 약 70% 성공했는가?
3. 상승장/하락장/횡보장/급락장에서 다르게 동작하는가?
4. 종목군별로 편향이 없는가?
5. 위험한 상황을 안전하다고 잘못 말하는 비율은 얼마인가?
```

이 문서는 백테스트와 확률 보정의 설계 기준을 정의한다.

---

# 1. 용어 정의

## 1.1 백테스트

백테스트는 과거 특정 시점의 데이터만 사용하여 당시의 판단 결과를 만들고, 이후 실제 주가 흐름과 비교하는 검증 절차다.

중요 원칙:

```text
미래 데이터를 사용하면 안 된다.
```

예:

```text
2024-03-15 기준 컨설팅 결과를 계산한다.
그 후 20거래일, 60거래일, 120거래일 동안 실제 결과를 비교한다.
```

## 1.2 확률 보정

확률 보정은 모델이 출력한 확률이 실제 빈도와 얼마나 일치하는지 확인하고 조정하는 과정이다.

예:

```text
목표가 도달 확률 70%로 예측한 케이스 1,000개 중 실제 성공이 700개에 가까운가?
```

## 1.3 False Safe

False Safe는 실제로 위험한 상황인데 시스템이 안전하다고 판단한 경우다.

`theStock`에서 가장 위험한 오류 유형이다.

예:

```text
시스템: 추가 매수 검토 가능
실제 결과: 이후 손절가 먼저 도달 또는 큰 추가 하락
```

---

# 2. 백테스트 대상

## 2.1 대상 종목군

백테스트는 종목군별로 나누어야 한다.

```text
1. KOSPI 대형주
2. KOSPI 중소형주
3. KOSDAQ 대형주
4. KOSDAQ 중소형주
5. ETF
6. 우선주
7. 거래량 부족 종목
8. 관리종목/투자주의 종목
```

초기 버전에서는 다음을 제외하는 것이 안전하다.

```text
1. 상장폐지 종목 데이터가 불완전한 경우
2. 거래정지 기간이 긴 종목
3. 가격 데이터가 연속적이지 않은 종목
4. 스팩/리츠/ETN 등 성격이 다른 상품
```

단, 제외 기준은 로그로 남긴다.

## 2.2 시장 구간

시장 국면별 검증이 필요하다.

```text
1. 상승장
2. 하락장
3. 횡보장
4. 급락장
5. 회복장
6. 고변동성 구간
```

시장 구간은 KOSPI/KOSDAQ 지수의 이동평균, drawdown, 변동성으로 정의한다.

---

# 3. 시뮬레이션 시점 생성

## 3.1 기준일 생성

각 종목에 대해 과거 거래일을 기준일로 잡는다.

예:

```text
stock_code=005930
base_date=2024-03-15
```

## 3.2 가상 보유 상태 생성

물타기 판단은 사용자의 평균 단가와 보유 수량이 필요하다.

백테스트에서는 가상 보유 상태를 만든다.

방법 A: 과거 고점 매수 가정

```text
평균 단가 = base_date 이전 n일 고점 근처
현재가 = base_date 종가
손실률 = -5%, -10%, -20%, -30% 구간 생성
```

방법 B: 실제 하락 구간 샘플링

```text
최근 60일 고점 대비 일정 비율 하락한 날짜를 base_date로 사용
```

방법 C: 사용자 실제 이력 기반

```text
운영 데이터가 충분히 쌓인 뒤 익명화하여 사용
```

초기에는 A+B를 사용하고, 운영 데이터는 충분한 개인정보 보호 설계 후 사용한다.

---

# 4. 성공/실패 정의

## 4.1 목표가 도달 성공

성공 조건 예:

```text
base_date 이후 N거래일 안에 목표가 이상 도달
```

N 후보:

```text
20거래일
60거래일
120거래일
250거래일
```

목표가 후보:

```text
1. 평균 단가 회복
2. 평균 단가 -5% 회복
3. 현재가 대비 +5%
4. 현재가 대비 +10%
5. 시스템 산출 목표가
```

## 4.2 손절가 도달 실패

실패 조건 예:

```text
base_date 이후 N거래일 안에 손절가 먼저 도달
```

손절가 후보:

```text
1. 현재가 대비 -5%
2. 현재가 대비 -10%
3. 최근 지지선 이탈
4. 시스템 산출 손절가
```

## 4.3 목표가/손절가 순서

중요한 것은 둘 중 무엇이 먼저 발생했는지다.

```text
성공: 목표가 먼저 도달
실패: 손절가 먼저 도달
미결: 기간 내 둘 다 미도달
```

## 4.4 최대 낙폭

추가 매수 판단에는 최대 낙폭도 중요하다.

```text
max_drawdown_after_base_date
```

목표가에 도달했더라도 중간에 -30% 하락했다면 사용자가 버티기 어려웠을 수 있다.

---

# 5. 백테스트 실행 흐름

```text
1. 기준 종목군 선택
2. 기준 기간 선택
3. 기준일 생성
4. 가상 보유 상태 생성
5. base_date 기준 과거 데이터만 로딩
6. Scoring Engine 실행
7. Probability Engine 실행
8. Consulting Engine 실행
9. 이후 실제 가격 경로 로딩
10. 목표가/손절가/최대낙폭/기간수익률 계산
11. 예측과 실제 비교
12. 결과 저장
13. 리포트 생성
```

절대 금지:

```text
base_date 이후 데이터를 점수 계산에 사용하는 것
```

---

# 6. 백테스트 결과 모델

권장 모델:

```text
BacktestRun
BacktestCase
BacktestOutcome
ProbabilityCalibrationBucket
```

## 6.1 BacktestRun

```text
id
name
started_at
finished_at
status
period_start
period_end
market_scope
stock_count
case_count
config_json
summary_json
```

## 6.2 BacktestCase

```text
run
stock
base_date
virtual_avg_price
virtual_quantity
current_price
loss_rate_at_base
decision_code
score_summary
probability_summary
consulting_summary
```

## 6.3 BacktestOutcome

```text
case
time_horizon_days
target_price
stop_loss_price
target_hit
stop_loss_hit
first_hit_type
days_to_target
days_to_stop_loss
max_drawdown
return_at_horizon
outcome_code
```

## 6.4 ProbabilityCalibrationBucket

```text
run
probability_type
bucket_min
bucket_max
case_count
actual_success_count
actual_success_rate
brier_score
```

---

# 7. 주요 평가 지표

## 7.1 Hit Ratio

```text
목표가 먼저 도달한 케이스 / 전체 케이스
```

## 7.2 Stop First Ratio

```text
손절가 먼저 도달한 케이스 / 전체 케이스
```

## 7.3 False Safe Rate

```text
시스템이 검토 가능 또는 긍정 판단을 했지만 실제로 손절가 먼저 도달한 비율
```

가장 중요하게 관리해야 한다.

## 7.4 False Warning Rate

```text
시스템이 위험하다고 했지만 실제로 목표가 먼저 도달한 비율
```

서비스가 너무 보수적인지 확인하는 지표다.

## 7.5 Brier Score

확률 예측의 정확도를 평가한다.

```text
예측 확률과 실제 결과의 평균 제곱 오차
```

낮을수록 좋다.

## 7.6 Calibration Curve

예측 확률 구간별 실제 성공률을 비교한다.

예:

| 예측 구간 | 케이스 수 | 실제 성공률 |
|---|---:|---:|
| 0~10% | 120 | 8% |
| 10~20% | 240 | 17% |
| 20~30% | 310 | 25% |
| 70~80% | 180 | 62% |
| 80~90% | 90 | 69% |

예측 80% 구간이 실제 69%라면 과신하고 있는 것이다.

---

# 8. 확률 보정 방법

초기에는 단순하고 설명 가능한 방식을 사용한다.

## 8.1 Bucket Calibration

확률 구간별 실제 성공률을 계산하여 보정한다.

예:

```text
원래 확률: 0.78
해당 bucket 실제 성공률: 0.64
보정 확률: 0.64 또는 가중 평균
```

## 8.2 Isotonic Regression

데이터가 충분하면 사용할 수 있다.

장점:

```text
비선형 보정 가능
단조성 유지
```

단점:

```text
데이터가 적으면 과적합 가능
```

## 8.3 Platt Scaling

모델 점수를 로지스틱 함수로 보정하는 방식이다.

초기 룰 기반 엔진에는 bucket calibration이 더 단순하다.

---

# 9. 리포트 구성

백테스트 리포트는 다음을 포함한다.

```text
1. 실행 기간
2. 종목군
3. 케이스 수
4. 시장 구간 분포
5. decision_code별 성과
6. 예측 확률 구간별 실제 성공률
7. False Safe Rate
8. False Warning Rate
9. 최대 낙폭 분포
10. 종목군별 성과
11. 개선 필요 threshold
```

---

# 10. 운영 반영 정책

백테스트 결과가 나왔다고 즉시 운영 threshold를 바꾸면 안 된다.

권장 절차:

```text
1. 백테스트 실행
2. 리포트 검토
3. threshold 후보 생성
4. staging에서 검증
5. 기존 결과와 diff 비교
6. 운영 반영
7. 반영 버전 기록
```

threshold 버전 관리:

```text
SCORING_RULE_VERSION=2026-06-v1
PROBABILITY_CALIBRATION_VERSION=2026-06-v1
```

컨설팅 결과에도 버전을 기록한다.

---

# 11. 데이터 누수 방지

백테스트에서 가장 위험한 오류는 미래 데이터 누수다.

금지:

```text
1. base_date 이후 이동평균 사용
2. base_date 이후 재무 데이터 사용
3. base_date 이후 공시 이벤트 사용
4. 미래 상장폐지 여부를 사전 리스크로 사용
5. 전체 기간 기준 정규화값 사용
```

검증:

```text
1. 모든 feature에 as_of_date를 적용
2. query filter에 date <= base_date 강제
3. 테스트로 미래 데이터 접근 차단 확인
```

---

# 12. 구현 체크리스트

```text
[ ] BacktestRun 모델 추가
[ ] BacktestCase 모델 추가
[ ] BacktestOutcome 모델 추가
[ ] calibration bucket 저장 구조 추가
[ ] 기준일 생성기 구현
[ ] 가상 보유 상태 생성기 구현
[ ] as_of_date 기반 scoring 실행
[ ] 미래 데이터 누수 방지 테스트
[ ] 목표가/손절가 first hit 계산
[ ] max drawdown 계산
[ ] false safe/warning 지표 계산
[ ] calibration curve 데이터 생성
[ ] 백테스트 admin/list/detail 화면 추가
[ ] management command 추가
[ ] 리포트 생성 기능 추가
```

---

# 13. Codex 작업 지시 요약

```text
theStock Probability Engine의 신뢰도를 검증하기 위한 백테스트 기능을 추가한다.
base_date 이후 데이터가 scoring/probability 계산에 들어가지 않도록 as_of_date 원칙을 강제한다.
목표가 먼저 도달, 손절가 먼저 도달, 미결 상태를 구분한다.
False Safe Rate를 핵심 지표로 계산한다.
예측 확률 구간별 실제 성공률을 계산해 calibration curve를 만든다.
기존 컨설팅 API 응답 구조는 깨지지 않게 하고, 백테스트 기능은 별도 admin/management command 중심으로 추가한다.
```

---

# 14. 결론

`theStock`의 확률값은 서비스 신뢰도를 크게 높일 수 있지만, 검증되지 않은 확률은 오히려 위험하다.

따라서 Probability Engine은 다음 기준을 만족해야 한다.

```text
1. 과거 데이터에서 검증된다.
2. 미래 데이터 누수가 없다.
3. 시장 국면별 성능이 확인된다.
4. 확률 구간과 실제 성공률이 비교된다.
5. 위험한 상황을 안전하다고 말하는 비율을 최소화한다.
```

백테스트와 확률 보정은 theStock이 단순 계산기에서 신뢰 가능한 투자 보조 시스템으로 발전하기 위한 핵심 단계다.
