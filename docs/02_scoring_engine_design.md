# 02_scoring_engine_design.md

# 물타기 타이밍 판단 시스템 2단계 설계서: Scoring Engine

## 문서 목적

이 문서는 `물타기 타이밍 판단 시스템`의 2단계 구현 범위를 정의한다.

1단계인 `01_foundation_design.md`에서는 Django 프로젝트 구조, 앱 구조, 모델, serializer, admin, 기본 URL, service skeleton을 구성했다.  
2단계인 본 문서에서는 실제 물타기 판단의 핵심이 되는 **계산 엔진과 점수 산정 로직**을 상세히 정의한다.

이 문서는 다음 문서를 전제로 한다.

```text
00_overview_and_data.md
01_foundation_design.md
```

`00_overview_and_data.md`는 시스템의 목적과 판단 철학을 정의한다.  
`01_foundation_design.md`는 데이터 모델과 서비스 레이어의 기반을 정의한다.  
`02_scoring_engine_design.md`는 해당 모델과 서비스 레이어를 사용하여 실제 판단 점수를 계산하는 방법을 정의한다.

---

# 1. 2단계의 목표

## 1.1 핵심 목표

2단계의 핵심 목표는 다음과 같다.

```text
1. 가격 데이터 기반 기술적 지표 계산
2. 지지선 판단 로직 구현
3. 거래량 판단 로직 구현
4. 투자자 수급 판단 로직 구현
5. 시장 흐름 판단 로직 구현
6. 뉴스/공시 위험 이벤트 필터 구현
7. 항목별 점수 계산
8. 총점 계산
9. A/B/C/D 등급 변환
10. 판단 사유 생성
11. 추가 매수 가능 예산 계산
12. 손절 기준 가격 계산
13. 평가 결과 객체 구조 정의
```

2단계는 사용자의 요청을 받는 API 단계가 아니라, API에서 호출할 수 있는 **도메인 계산 엔진**을 만드는 단계다.

---

## 1.2 2단계 포함 범위

2단계에 포함되는 작업은 다음과 같다.

```text
1. 이동평균 계산 함수 구현
2. RSI14 계산 함수 구현
3. MACD 계산 함수 구현
4. ATR14 계산 함수 구현
5. Volume MA20 계산 함수 구현
6. Bollinger Band 계산 함수 구현
7. 최근 가격 데이터 조회 함수 구현
8. 최신 가격 조회 함수 구현
9. 지지선 탐색 함수 구현
10. 추세 점수 계산 함수 구현
11. 지지선 점수 계산 함수 구현
12. 거래량 점수 계산 함수 구현
13. 수급 점수 계산 함수 구현
14. 시장 점수 계산 함수 구현
15. 위험 이벤트 필터 함수 구현
16. 위험 이벤트 감점 함수 구현
17. 총점 계산 함수 구현
18. 점수 보정 함수 구현
19. 등급 변환 함수 구현
20. 판단 사유 생성 함수 구현
21. 추가 매수 예산 계산 함수 구현
22. 손절 기준 가격 계산 함수 구현
23. 평가 결과 dataclass 또는 dict 구조 정의
24. 단위 테스트 작성
```

---

## 1.3 2단계 제외 범위

2단계에서는 다음을 구현하지 않는다.

```text
1. 실제 평가 API 완성
2. POST /api/holdings/{id}/evaluate/ 완성
3. AveragingDecision 저장 플로우 완성
4. 복잡한 프론트엔드 화면
5. 외부 주식 API 연동
6. 뉴스/공시 자동 크롤링
7. 실시간 시세 연동
8. 자동 매매 기능
```

단, 3단계 API 구현에서 바로 사용할 수 있도록 계산 엔진의 함수와 반환 구조는 완성해야 한다.

---

## 1.4 2단계 완료 기준

2단계는 다음 조건을 만족하면 완료된 것으로 본다.

```text
1. 가격 리스트를 입력하면 MA, RSI, MACD, ATR, Volume MA20을 계산할 수 있다.
2. 최근 가격 데이터에서 지지선 후보를 계산할 수 있다.
3. RiskEvent 기준으로 critical risk 여부를 판단할 수 있다.
4. 추세, 지지선, 거래량, 수급, 시장, 리스크 점수를 각각 계산할 수 있다.
5. 항목별 점수와 총점을 산출할 수 있다.
6. 총점을 A/B/C/D 등급으로 변환할 수 있다.
7. 평가 결과에 판단 사유 목록이 포함된다.
8. 추가 매수 제안 예산이 등급과 사용자 위험 성향에 따라 계산된다.
9. 손절 기준 가격을 계산할 수 있다.
10. 핵심 함수에 대한 단위 테스트가 존재한다.
```

---

# 2. 전체 점수 체계

## 2.1 총점 구조

시스템의 기본 점수 구조는 다음과 같다.

```text
총점 = 추세 점수
     + 지지선 점수
     + 거래량 점수
     + 수급 점수
     + 시장 점수
     + 리스크 점수
```

각 항목의 기본 범위는 다음과 같다.

| 항목 | 점수 범위 | 설명 |
|---|---:|---|
| 추세 점수 | 0 ~ 25 | 종목의 단기·중기 추세 |
| 지지선 점수 | -20 ~ 20 | 지지선 근접, 이탈, 회복 여부 |
| 거래량 점수 | -15 ~ 20 | 거래량 증가 방향과 가격 반응 |
| 수급 점수 | -20 ~ 20 | 외국인·기관·개인 수급 |
| 시장 점수 | -25 ~ 15 | 시장 전체 흐름 |
| 리스크 점수 | -50 ~ 0 | 뉴스/공시 위험 이벤트 감점 |

최종 점수는 0~100 범위로 보정한다.

```python
final_score = max(0, min(100, raw_score))
```

---

## 2.2 critical risk 우선 원칙

`critical` 위험 이벤트가 존재하면 기술적 점수 계산 결과와 상관없이 D 등급으로 처리한다.

예시 critical risk:

```text
거래정지
상장폐지 위험
감사의견 거절
관리종목 지정
회생절차
자본잠식 심화
```

처리 방식:

```text
1. active RiskEvent 중 risk_level == critical 여부 확인
2. critical risk가 있으면 점수 계산을 조기 종료
3. score = 0
4. grade = D
5. decision = 손절 또는 비중 축소 기준 점검 구간
6. reason_summary에 critical risk 내용을 포함
```

---

## 2.3 등급 기준

| 최종 점수 | 등급 | 상태 | 설명 |
|---:|---|---|---|
| 75 이상 | A | 추가 매수 가능성 검토 구간 | 조건이 비교적 우호적 |
| 55 ~ 74 | B | 관찰 구간 | 반등 가능성은 있으나 확인 필요 |
| 35 ~ 54 | C | 물타기 금지 구간 | 리스크가 크거나 추세 확인 부족 |
| 34 이하 | D | 손절 또는 비중 축소 기준 점검 구간 | 위험 신호가 강함 |

등급 문구는 매수/매도 추천으로 표현하지 않는다.

---

# 3. 데이터 입력 구조

## 3.1 계산 엔진이 사용하는 모델

2단계 계산 엔진은 1단계에서 정의한 다음 모델을 사용한다.

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

2단계에서는 주로 다음 모델을 읽는다.

```text
UserHolding
DailyPrice
InvestorFlow
MarketIndex
RiskEvent
```

그리고 필요에 따라 다음 모델에 계산 결과를 저장할 수 있다.

```text
TechnicalIndicator
```

단, 2단계에서는 저장보다 계산 함수의 정확성을 우선한다.

---

## 3.2 최소 필요 데이터 수량

각 계산에 필요한 최소 데이터 수량은 다음과 같다.

| 계산 항목 | 최소 데이터 | 권장 데이터 |
|---|---:|---:|
| MA5 | 5거래일 | 20거래일 이상 |
| MA20 | 20거래일 | 60거래일 이상 |
| MA60 | 60거래일 | 120거래일 이상 |
| MA120 | 120거래일 | 240거래일 이상 |
| RSI14 | 15거래일 이상 | 30거래일 이상 |
| MACD | 35거래일 이상 | 60거래일 이상 |
| ATR14 | 15거래일 이상 | 30거래일 이상 |
| Volume MA20 | 20거래일 | 60거래일 이상 |
| 지지선 | 30거래일 이상 | 60거래일 이상 |
| 수급 | 5거래일 | 20거래일 |
| 시장 | 20거래일 | 60거래일 |

데이터가 부족한 경우에는 다음 원칙을 따른다.

```text
1. 계산 가능한 항목만 계산한다.
2. 부족한 항목은 중립 점수 또는 보수적 감점을 적용한다.
3. reason에 데이터 부족 사실을 포함한다.
4. 데이터 부족을 숨기지 않는다.
```

---

# 4. 기술적 지표 계산 설계

## 4.1 가격 데이터 정렬 원칙

지표 계산 함수는 가격 데이터가 오래된 날짜에서 최신 날짜 순으로 정렬되어 있다고 가정한다.

```text
oldest → newest
```

DB에서 가져올 때 최신순으로 조회했다면 계산 전 반드시 역순으로 정렬한다.

```python
prices = sorted(prices, key=lambda item: item.date)
```

---

## 4.2 이동평균 계산

### 4.2.1 정의

이동평균은 최근 N일 종가의 평균이다.

```text
MA_N = 최근 N거래일 종가 합계 / N
```

### 4.2.2 함수 시그니처

```python
def calculate_moving_average(close_prices, window):
    """Calculate simple moving average from close prices."""
```

### 4.2.3 입력

```text
close_prices: Decimal 또는 float 리스트
window: 이동평균 기간
```

### 4.2.4 반환

```text
계산 가능한 경우: Decimal 또는 float
데이터 부족 시: None
```

### 4.2.5 예외 처리

```text
close_prices가 비어 있으면 None
len(close_prices) < window이면 None
window <= 0이면 ValueError
```

---

## 4.3 RSI14 계산

### 4.3.1 정의

RSI는 일정 기간 동안의 평균 상승폭과 평균 하락폭을 이용해 과매수·과매도 상태를 판단하는 지표다.

```text
RS = average_gain / average_loss
RSI = 100 - (100 / (1 + RS))
```

### 4.3.2 함수 시그니처

```python
def calculate_rsi(close_prices, period=14):
    """Calculate RSI using close prices."""
```

### 4.3.3 입력

```text
close_prices: 종가 리스트
period: 기본 14
```

### 4.3.4 반환

```text
RSI 값
데이터 부족 시 None
```

### 4.3.5 계산 원칙

기본 구현은 단순 평균 방식으로 시작한다.

```text
1. 각 날짜의 종가 변화량 계산
2. 상승분과 하락분 분리
3. 최근 period 구간의 평균 상승폭 계산
4. 최근 period 구간의 평균 하락폭 계산
5. RSI 계산
```

평균 하락폭이 0이면 RSI는 100으로 처리한다.  
평균 상승폭과 평균 하락폭이 모두 0이면 RSI는 50으로 처리한다.

---

## 4.4 MACD 계산

### 4.4.1 정의

MACD는 단기 EMA와 장기 EMA의 차이다.

```text
MACD = EMA(12) - EMA(26)
Signal = EMA(MACD, 9)
Histogram = MACD - Signal
```

### 4.4.2 함수 시그니처

```python
def calculate_macd(close_prices, short_period=12, long_period=26, signal_period=9):
    """Calculate MACD, signal, and histogram."""
```

### 4.4.3 반환 구조

```python
{
    "macd": value,
    "signal": value,
    "histogram": value
}
```

데이터가 부족하면 다음을 반환한다.

```python
{
    "macd": None,
    "signal": None,
    "histogram": None
}
```

### 4.4.4 EMA 계산

EMA는 다음 공식으로 계산한다.

```text
multiplier = 2 / (period + 1)
EMA_today = (price_today - EMA_yesterday) * multiplier + EMA_yesterday
```

초기 EMA는 해당 기간의 단순 이동평균으로 시작한다.

---

## 4.5 ATR14 계산

### 4.5.1 정의

ATR은 평균 실제 변동폭이다.

True Range는 다음 세 값 중 최대값이다.

```text
1. high - low
2. abs(high - previous_close)
3. abs(low - previous_close)
```

ATR은 최근 N일 True Range의 평균이다.

### 4.5.2 함수 시그니처

```python
def calculate_atr(price_rows, period=14):
    """Calculate ATR from rows containing high, low, close."""
```

### 4.5.3 입력

`price_rows`는 다음 값을 가진 객체 또는 dict 리스트다.

```text
high_price
low_price
close_price
```

### 4.5.4 반환

```text
ATR 값
데이터 부족 시 None
```

---

## 4.6 Volume MA20 계산

### 4.6.1 정의

최근 20거래일 평균 거래량이다.

```text
Volume_MA20 = 최근 20일 거래량 합계 / 20
```

### 4.6.2 함수 시그니처

```python
def calculate_volume_ma(volumes, window=20):
    """Calculate average volume."""
```

### 4.6.3 반환

```text
평균 거래량
데이터 부족 시 None
```

---

## 4.7 Bollinger Band 계산

### 4.7.1 정의

Bollinger Band는 이동평균과 표준편차를 이용해 가격의 상대적 위치와 변동성을 판단한다.

```text
middle = MA20
upper = MA20 + 2 * standard_deviation
lower = MA20 - 2 * standard_deviation
```

### 4.7.2 함수 시그니처

```python
def calculate_bollinger_bands(close_prices, window=20, num_std=2):
    """Calculate Bollinger Bands."""
```

### 4.7.3 반환 구조

```python
{
    "upper": value,
    "middle": value,
    "lower": value
}
```

데이터 부족 시 모든 값을 None으로 반환한다.

---

# 5. 가격 서비스 설계

## 5.1 get_latest_price

### 목적

종목의 최신 일봉 데이터를 반환한다.

### 함수 시그니처

```python
def get_latest_price(stock):
    """Return the latest DailyPrice for the given stock."""
```

### 반환

```text
DailyPrice 객체
없으면 None
```

---

## 5.2 get_recent_prices

### 목적

종목의 최근 가격 데이터를 반환한다.

### 함수 시그니처

```python
def get_recent_prices(stock, limit=120, ascending=True):
    """Return recent DailyPrice records."""
```

### 반환

```text
DailyPrice 리스트
ascending=True이면 오래된 날짜 → 최신 날짜
ascending=False이면 최신 날짜 → 오래된 날짜
```

---

## 5.3 extract_close_prices

### 목적

DailyPrice 리스트에서 종가 리스트를 추출한다.

### 함수 시그니처

```python
def extract_close_prices(price_rows):
    """Extract close prices from DailyPrice rows."""
```

---

# 6. 추세 점수 설계

## 6.1 추세 판단 목적

추세 점수는 종목의 가격 흐름이 하락 지속인지, 하락 둔화인지, 반등 초기인지 판단한다.

최대 점수는 25점이다.

---

## 6.2 추세 점수 항목

| 조건 | 점수 |
|---|---:|
| 현재가 > MA5 | +5 |
| MA5가 상승 전환 | +5 |
| 현재가가 MA20 이상 또는 MA20 근처 회복 | +5 |
| 최근 저점이 이전 저점보다 높음 | +5 |
| MA20 하락 기울기 둔화 | +5 |

감점 조건은 다음과 같다.

| 조건 | 점수 |
|---|---:|
| 현재가 < MA5 < MA20 < MA60 | -10 |
| 최근 저점 계속 갱신 | -10 |
| MA20과 MA60 모두 하락 중 | -5 |

최종 추세 점수는 0~25 범위로 보정한다.

---

## 6.3 함수 시그니처

```python
def calculate_trend_score(price_rows, indicators=None):
    """Calculate trend score from prices and indicators."""
```

### 입력

```text
price_rows: DailyPrice 리스트
indicators: 최신 TechnicalIndicator 또는 dict, 선택
```

### 반환 구조

```python
{
    "score": 15,
    "reasons": [
        "현재가가 MA5 위에 있습니다.",
        "최근 저점이 이전 저점보다 높습니다."
    ],
    "details": {
        "current_price": "...",
        "ma5": "...",
        "ma20": "...",
        "ma60": "..."
    }
}
```

---

## 6.4 저점 상승 판단

최근 저점이 이전 저점보다 높은지를 판단한다.

간단한 1차 구현 기준:

```text
최근 20거래일을 10일씩 두 구간으로 나눈다.
앞 10일의 최저가와 뒤 10일의 최저가를 비교한다.
뒤 10일 최저가가 앞 10일 최저가보다 높으면 저점 상승으로 본다.
```

함수 시그니처:

```python
def is_recent_low_higher(price_rows, window=20):
    """Return whether recent low is higher than previous low."""
```

---

## 6.5 MA 기울기 둔화 판단

MA20 하락 기울기 둔화는 다음처럼 판단한다.

```text
최근 MA20 변화폭이 이전 MA20 변화폭보다 덜 하락하면 둔화로 본다.
```

1차 구현에서는 다음 기준을 사용할 수 있다.

```text
최근 5일 MA20 평균 변화량 > 이전 5일 MA20 평균 변화량
```

데이터가 부족하면 판단하지 않고 중립 처리한다.

---

# 7. 지지선 점수 설계

## 7.1 지지선 판단 목적

지지선 점수는 현재가가 의미 있는 가격 방어 구간에 근접해 있는지, 지지선을 이탈했는지, 이탈 후 회복했는지를 판단한다.

점수 범위는 -20 ~ 20이다.

---

## 7.2 지지선 탐색 기본 원칙

1차 구현에서는 복잡한 패턴 인식보다 안정적인 규칙 기반으로 구현한다.

기본 아이디어:

```text
최근 60거래일 저가를 기준으로 주요 저가 구간을 찾는다.
현재가와 가까운 반복 반등 가격대를 지지선 후보로 본다.
```

---

## 7.3 지지선 계산 방법

### 7.3.1 단순 지지선

가장 단순한 지지선은 최근 60일 최저가다.

```text
support_price = min(low_price of recent 60 prices)
```

### 7.3.2 반복 반등 지지선

조금 더 나은 방법은 가격 구간을 묶어 반복적으로 저가가 형성된 구간을 찾는 것이다.

1차 구현 기준:

```text
1. 최근 60일 low_price 수집
2. 현재가 대비 ±10% 이내의 low_price만 우선 고려
3. 가격을 1% 단위 bucket으로 그룹화
4. 2회 이상 등장한 bucket을 지지선 후보로 판단
5. 현재가와 가장 가까운 후보를 support_price로 선택
6. 후보가 없으면 최근 60일 최저가를 fallback으로 사용
```

---

## 7.4 지지선 점수 항목

| 조건 | 점수 |
|---|---:|
| 현재가가 지지선 ±3% 이내 | +15 |
| 지지선 부근에서 거래량 증가 | +5 |
| 지지선을 명확히 이탈 | -20 |
| 지지선 이탈 후 회복 | +10 |
| 지지선 후보 없음 | 0 |

---

## 7.5 함수 시그니처

```python
def find_support_zone(price_rows, lookback=60):
    """Find support zone from recent price rows."""
```

반환 구조:

```python
{
    "support_price": value,
    "lower_bound": value,
    "upper_bound": value,
    "method": "bucket" 또는 "lowest_low",
    "touch_count": 2
}
```

점수 계산 함수:

```python
def calculate_support_score(price_rows):
    """Calculate support score."""
```

반환 구조:

```python
{
    "score": 10,
    "reasons": [
        "현재가가 주요 지지선 근처에 있습니다."
    ],
    "details": {
        "support_price": "...",
        "distance_rate": "..."
    }
}
```

---

# 8. 거래량 점수 설계

## 8.1 거래량 판단 목적

거래량 점수는 가격 움직임이 신뢰할 수 있는지 판단한다.

거래량은 단독으로 판단하지 않고 가격과 함께 해석한다.

점수 범위는 -15 ~ 20이다.

---

## 8.2 거래량 점수 항목

| 조건 | 점수 |
|---|---:|
| 최근 거래량이 20일 평균 대비 150% 이상 | +5 |
| 하락 중 거래량 급증 후 가격 방어 | +10 |
| 반등 시 거래량 증가 | +10 |
| 하락 시 거래량 증가 | -10 |
| 반등 시 거래량 부족 | -5 |

최종 거래량 점수는 -15~20 범위로 보정한다.

---

## 8.3 가격 방어 판단

하락 중 거래량 급증 후 가격 방어는 다음처럼 판단한다.

```text
1. 최근 거래량이 volume_ma20 대비 150% 이상
2. 당일 저가 대비 종가가 상단에 위치
3. 종가가 전일 종가 대비 크게 밀리지 않음
```

간단한 기준:

```text
close_position = (close - low) / (high - low)

close_position >= 0.6이면 장중 하락 후 방어로 해석 가능
```

high == low이면 close_position 계산이 불가능하므로 중립 처리한다.

---

## 8.4 반등 시 거래량 증가 판단

반등일은 다음처럼 정의한다.

```text
오늘 종가 > 전일 종가
```

반등 시 거래량 증가는 다음 조건으로 판단한다.

```text
오늘 종가 > 전일 종가
오늘 거래량 > volume_ma20
```

---

## 8.5 함수 시그니처

```python
def calculate_volume_score(price_rows):
    """Calculate volume score from price rows."""
```

반환 구조:

```python
{
    "score": 10,
    "reasons": [
        "최근 거래량이 20일 평균 대비 증가했습니다."
    ],
    "details": {
        "latest_volume": 12345678,
        "volume_ma20": 9876543,
        "volume_ratio": 1.25
    }
}
```

---

# 9. 수급 점수 설계

## 9.1 수급 판단 목적

수급 점수는 외국인, 기관, 개인의 순매수 흐름을 평가한다.

점수 범위는 -20 ~ 20이다.

---

## 9.2 수급 점수 항목

최근 5거래일 기준:

| 조건 | 점수 |
|---|---:|
| 외국인 순매수 3일 이상 | +5 |
| 기관 순매수 3일 이상 | +5 |
| 외국인+기관 동시 순매수 3일 이상 | +10 |
| 외국인+기관 동시 순매도 3일 이상 | -20 |
| 개인만 강한 순매수 | -5 |

---

## 9.3 개인만 강한 순매수 판단

개인만 강한 순매수는 다음 조건으로 판단한다.

```text
최근 5일 개인 순매수 합계 > 0
최근 5일 외국인 순매수 합계 < 0
최근 5일 기관 순매수 합계 < 0
```

이 경우 개인이 하락 물량을 받아내는 구조일 수 있으므로 소폭 감점한다.

---

## 9.4 함수 시그니처

```python
def calculate_investor_flow_score(flow_rows):
    """Calculate investor flow score from recent InvestorFlow rows."""
```

반환 구조:

```python
{
    "score": 10,
    "reasons": [
        "최근 5거래일 중 외국인 순매수가 3일 이상입니다."
    ],
    "details": {
        "foreign_positive_days": 3,
        "institution_positive_days": 2,
        "foreign_sum": 100000,
        "institution_sum": -50000,
        "individual_sum": -50000
    }
}
```

---

# 10. 시장 점수 설계

## 10.1 시장 판단 목적

시장 점수는 개별 종목의 판단을 시장 전체 흐름으로 보정하기 위한 점수다.

시장 전체가 급락 중이면 개별 종목이 기술적으로 좋아 보여도 등급을 낮출 수 있다.

점수 범위는 -25 ~ 15이다.

---

## 10.2 시장 점수 항목

| 조건 | 점수 |
|---|---:|
| KOSPI 또는 해당 시장 지수가 20일선 위 | +5 |
| 시장 지수가 최근 반등 중 | +5 |
| 미국 주요 지수가 안정적 | +5 |
| 시장 급락 중 | -15 |
| 환율 급등 | -5 |
| 미국 나스닥 급락 | -5 |

---

## 10.3 시장 선택 기준

종목의 market에 따라 기본 비교 지수를 다르게 선택한다.

| 종목 시장 | 기본 비교 지수 |
|---|---|
| KOSPI | KOSPI |
| KOSDAQ | KOSDAQ |
| KONEX | KOSDAQ 또는 별도 KONEX |
| ETF | 기초자산에 따라 다르지만 1차 구현은 KOSPI |
| ETN | 기초자산에 따라 다르지만 1차 구현은 KOSPI |

---

## 10.4 시장 급락 판단

시장 급락은 다음 중 하나로 판단한다.

```text
1. 최근 1일 등락률 <= -2.5%
2. 최근 5일 누적 수익률 <= -5%
3. 현재 지수 < MA20이고 MA20 하락 중
```

---

## 10.5 환율 급등 판단

USD/KRW 데이터가 있는 경우 다음 기준을 사용할 수 있다.

```text
최근 5일 상승률 >= 2%
또는 현재 환율 > 20일 이동평균 * 1.02
```

환율 데이터가 없으면 중립 처리하고 reason에 데이터 부족을 남길 수 있다.

---

## 10.6 함수 시그니처

```python
def calculate_market_score(stock, market_index_rows, fx_rows=None, global_index_rows=None):
    """Calculate market context score."""
```

반환 구조:

```python
{
    "score": 5,
    "reasons": [
        "해당 시장 지수가 20일선 위에 있습니다."
    ],
    "details": {
        "market_code": "KOSPI",
        "market_above_ma20": True,
        "market_recent_return_5d": "..."
    }
}
```

---

# 11. 리스크 이벤트 설계

## 11.1 리스크 판단 목적

뉴스/공시 기반 위험 이벤트는 기술적 점수보다 우선한다.

특히 critical risk는 점수 계산을 조기 종료하고 D 등급으로 분류한다.

---

## 11.2 active risk event 조회

### 함수 시그니처

```python
def get_active_risk_events(stock):
    """Return active risk events for the given stock."""
```

조건:

```text
stock 일치
is_active=True
```

기본 정렬:

```text
-event_date
```

---

## 11.3 critical risk 판단

### 함수 시그니처

```python
def has_critical_risk(stock):
    """Return whether active critical risk exists."""
```

판단 조건:

```text
RiskEvent.risk_level == "critical"
RiskEvent.is_active == True
```

반환 구조:

```python
{
    "has_critical": True,
    "events": [...]
}
```

---

## 11.4 리스크 감점

critical이 아닌 risk event는 감점으로 처리한다.

| risk_level | 점수 |
|---|---:|
| high | -30 |
| medium | -15 |
| low | -5 |

동일 종목에 여러 위험 이벤트가 있으면 누적하되, 리스크 점수는 -50보다 낮아지지 않게 제한한다.

```python
risk_score = max(-50, raw_risk_score)
```

---

## 11.5 함수 시그니처

```python
def calculate_risk_score(risk_events):
    """Calculate risk penalty from active risk events."""
```

반환 구조:

```python
{
    "score": -15,
    "reasons": [
        "중간 수준의 위험 이벤트가 감지되었습니다: 분기 실적 부진"
    ],
    "details": {
        "event_count": 1,
        "highest_risk_level": "medium"
    }
}
```

---

# 12. 총점 계산 설계

## 12.1 calculate_total_score

### 함수 시그니처

```python
def calculate_total_score(
    *,
    trend_score,
    support_score,
    volume_score,
    flow_score,
    market_score,
    risk_score,
):
    """Calculate final normalized score."""
```

### 계산

```python
raw_score = (
    trend_score
    + support_score
    + volume_score
    + flow_score
    + market_score
    + risk_score
)
final_score = max(0, min(100, raw_score))
```

### 반환

```python
{
    "raw_score": raw_score,
    "final_score": final_score
}
```

---

## 12.2 convert_score_to_grade

### 함수 시그니처

```python
def convert_score_to_grade(score):
    """Convert score to A/B/C/D grade."""
```

### 기준

```text
75 이상: A
55~74: B
35~54: C
34 이하: D
```

---

## 12.3 get_decision_text

### 함수 시그니처

```python
def get_decision_text(grade):
    """Return user-facing decision text for grade."""
```

### 반환

| 등급 | 문구 |
|---|---|
| A | 추가 매수 가능성 검토 구간 |
| B | 관찰 구간 |
| C | 물타기 금지 구간 |
| D | 손절 또는 비중 축소 기준 점검 구간 |

---

# 13. 판단 사유 생성 설계

## 13.1 사유 생성 원칙

판단 사유는 사용자가 결과를 이해할 수 있도록 구체적이어야 한다.

좋은 예:

```text
현재가가 MA5 위에 있어 단기 반등 신호가 일부 확인됩니다.
최근 5거래일 중 외국인 순매수가 3일 이상 확인됩니다.
현재가가 주요 지지선 대비 2.1% 이내에 있습니다.
```

나쁜 예:

```text
좋습니다.
위험합니다.
점수가 높습니다.
조건이 나쁩니다.
```

---

## 13.2 build_reason_summary

### 함수 시그니처

```python
def build_reason_summary(grade, reasons):
    """Build short summary from grade and reasons."""
```

### 예시

A 등급:

```text
기술적 지표와 수급 조건이 비교적 우호적이며, 주요 위험 이벤트가 확인되지 않았습니다. 다만 본 결과는 투자 참고용 데이터 분석입니다.
```

B 등급:

```text
일부 반등 신호는 있으나 추세 전환 확인이 충분하지 않아 관찰이 필요한 구간입니다.
```

C 등급:

```text
하락 추세 또는 리스크 요인이 있어 추가 매수는 신중해야 하는 구간입니다.
```

D 등급:

```text
위험 신호가 강해 추가 매수보다 손절 또는 비중 축소 기준 점검이 필요한 구간입니다.
```

---

# 14. 추가 매수 예산 계산 설계

## 14.1 기본 원칙

추가 매수 예산은 사용자의 `max_additional_budget`을 기준으로 계산한다.

단, 점수가 높더라도 전체 예산을 한 번에 제안하지 않는다.

---

## 14.2 등급별 예산 비율

| 등급 | 기본 제안 비율 |
|---|---:|
| A | 30% |
| B | 10% |
| C | 0% |
| D | 0% |

A 등급이라도 1차 분할 매수 기준으로 30%만 제안한다.

---

## 14.3 위험 성향 보정

| risk_level | 보정 |
|---|---:|
| conservative | 0.5배 |
| normal | 1.0배 |
| aggressive | 1.2배 |

단, C/D 등급은 위험 성향과 관계없이 0이다.

---

## 14.4 함수 시그니처

```python
def calculate_suggested_budget(holding, grade):
    """Calculate suggested budget based on grade and risk level."""
```

계산 예:

```text
max_additional_budget = 1,000,000
grade = A
risk_level = normal

suggested_budget = 1,000,000 * 0.3 * 1.0 = 300,000
```

---

# 15. 손절 기준 가격 계산 설계

## 15.1 기본 원칙

손절 기준은 “매도하라”가 아니라 “손절 기준 점검 가격”이다.

---

## 15.2 기준 우선순위

```text
1. 지지선 하단
2. ATR 기반 변동성 가격
3. 현재가 기준 비율 손절
```

---

## 15.3 계산 방식

### 지지선 기반

```text
stop_loss_price = support_price * 0.97
```

### ATR 기반

```text
stop_loss_price = current_price - (ATR14 * 1.5)
```

### 비율 기반 fallback

```text
stop_loss_price = current_price * 0.93
```

최종적으로 사용 가능한 값 중 가장 보수적인 값을 선택한다.

1차 구현에서는 다음처럼 단순화할 수 있다.

```text
support_price가 있으면 support_price * 0.97
그렇지 않고 ATR14가 있으면 current_price - ATR14 * 1.5
둘 다 없으면 current_price * 0.93
```

---

## 15.4 함수 시그니처

```python
def calculate_stop_loss_price(current_price, support_price=None, atr14=None):
    """Calculate stop-loss review price."""
```

반환:

```text
Decimal 가격
```

---

# 16. 평가 결과 구조

## 16.1 EvaluationResult dataclass

2단계에서는 API 저장 이전에 사용할 평가 결과 구조를 정의한다.

```python
from dataclasses import dataclass, field
from decimal import Decimal

@dataclass
class EvaluationResult:
    score: int
    grade: str
    decision: str
    reason_summary: str
    reasons: list[str] = field(default_factory=list)
    score_breakdown: dict = field(default_factory=dict)
    suggested_budget: Decimal = Decimal("0")
    stop_loss_price: Decimal | None = None
    disclaimer: str = "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다."
```

Python 버전 호환성을 위해 `Decimal | None` 대신 `Optional[Decimal]`을 사용할 수도 있다.

---

## 16.2 score_breakdown 구조

```python
{
    "trend": 15,
    "support": 10,
    "volume": 5,
    "flow": 10,
    "market": 5,
    "risk": -15,
    "raw_total": 30,
    "final_total": 30
}
```

---

# 17. evaluate_averaging_timing 설계

## 17.1 함수 목적

`evaluate_averaging_timing`은 2단계 계산 엔진의 중심 함수다.

이 함수는 `UserHolding`을 받아 해당 종목의 물타기 판단 결과를 계산한다.

3단계 API에서는 이 함수를 호출하고, 반환된 결과를 `AveragingDecision`에 저장한다.

---

## 17.2 함수 시그니처

```python
def evaluate_averaging_timing(holding):
    """Evaluate averaging-down timing for the given holding."""
```

---

## 17.3 처리 흐름

```text
1. holding.stock 확인
2. latest price 조회
3. recent prices 조회
4. active risk events 조회
5. critical risk 여부 확인
6. critical이면 즉시 D 결과 반환
7. technical indicators 계산
8. trend score 계산
9. support score 계산
10. volume score 계산
11. investor flow score 계산
12. market score 계산
13. risk score 계산
14. total score 계산
15. grade 변환
16. decision text 생성
17. reason summary 생성
18. suggested budget 계산
19. stop loss price 계산
20. EvaluationResult 반환
```

---

## 17.4 critical risk 처리 예시

```python
critical_result = has_critical_risk(stock)
if critical_result["has_critical"]:
    return EvaluationResult(
        score=0,
        grade="D",
        decision="손절 또는 비중 축소 기준 점검 구간",
        reason_summary="치명적 위험 이벤트가 감지되어 추가 매수 검토보다 리스크 점검이 우선입니다.",
        reasons=[
            f"치명적 위험 이벤트가 감지되었습니다: {event.title}"
            for event in critical_result["events"]
        ],
        score_breakdown={
            "trend": 0,
            "support": 0,
            "volume": 0,
            "flow": 0,
            "market": 0,
            "risk": -50,
            "raw_total": 0,
            "final_total": 0,
        },
        suggested_budget=Decimal("0"),
        stop_loss_price=None,
    )
```

---

# 18. 데이터 부족 처리

## 18.1 데이터 부족 기본 원칙

데이터가 부족하다고 시스템이 실패하면 안 된다.

다음 원칙을 따른다.

```text
1. 계산 가능한 항목은 계산한다.
2. 계산 불가능한 항목은 중립 또는 보수적 점수를 적용한다.
3. 데이터 부족 사유를 reasons에 포함한다.
4. critical risk 판단은 데이터가 있으면 반드시 우선 적용한다.
5. latest price가 없으면 평가 불가 결과를 반환한다.
```

---

## 18.2 최신 가격이 없는 경우

최신 가격이 없으면 평가가 불가능하다.

반환 예:

```text
grade = D
score = 0
decision = 데이터 부족으로 평가 불가
reason_summary = 최신 가격 데이터가 없어 평가할 수 없습니다.
suggested_budget = 0
```

단, 이 경우 D 등급이 투자 위험 D와 혼동될 수 있으므로 `decision` 문구를 명확히 한다.

---

## 18.3 최근 가격 데이터 부족

예:

```text
최근 가격 데이터가 20거래일 미만이면 MA20, Volume MA20 계산 불가
최근 가격 데이터가 60거래일 미만이면 지지선 신뢰도 낮음
```

처리:

```text
계산 불가 항목은 0점
reasons에 데이터 부족 표시
```

---

# 19. 파일별 구현 위치

## 19.1 indicators/services/indicator_service.py

구현 함수:

```text
calculate_moving_average
calculate_rsi
calculate_ema
calculate_macd
calculate_atr
calculate_volume_ma
calculate_bollinger_bands
```

---

## 19.2 marketdata/services/price_service.py

구현 함수:

```text
get_latest_price
get_recent_prices
extract_close_prices
extract_volumes
```

---

## 19.3 marketdata/services/market_service.py

구현 함수:

```text
get_latest_market_index
get_recent_market_indices
calculate_market_score
```

---

## 19.4 decisions/services/support_service.py

구현 함수:

```text
find_support_zone
calculate_support_score
```

---

## 19.5 decisions/services/volume_service.py

구현 함수:

```text
calculate_volume_score
```

---

## 19.6 decisions/services/investor_flow_service.py

구현 함수:

```text
get_recent_investor_flows
calculate_investor_flow_score
```

---

## 19.7 decisions/services/risk_event_service.py

구현 함수:

```text
get_active_risk_events
has_critical_risk
calculate_risk_score
```

---

## 19.8 decisions/services/scoring_service.py

구현 함수:

```text
calculate_trend_score
calculate_total_score
convert_score_to_grade
get_decision_text
build_reason_summary
calculate_suggested_budget
calculate_stop_loss_price
```

---

## 19.9 decisions/services/averaging_decision_service.py

구현 함수:

```text
evaluate_averaging_timing
```

`create_decision_from_result`는 3단계 API 저장 흐름에서 완성한다.

---

# 20. 테스트 설계

## 20.1 기술적 지표 테스트

반드시 테스트할 항목:

```text
MA5 계산
데이터 부족 시 MA 반환 None
RSI 상승만 있는 경우 100
RSI 변동 없는 경우 50
MACD 데이터 부족 시 None 구조 반환
ATR 계산
Volume MA20 계산
Bollinger Band 계산
```

---

## 20.2 점수 계산 테스트

반드시 테스트할 항목:

```text
현재가 > MA5이면 추세 가산
저점 상승이면 추세 가산
하락 배열 현재가 < MA5 < MA20 < MA60이면 감점
지지선 ±3% 이내이면 가산
지지선 이탈이면 감점
거래량 급증 후 가격 방어이면 가산
하락 시 거래량 증가이면 감점
외국인 순매수 3일 이상이면 가산
기관 순매수 3일 이상이면 가산
외국인+기관 동시 순매도이면 감점
시장 급락이면 감점
critical risk 있으면 D 등급
high risk는 감점
총점 75 이상 A
총점 55~74 B
총점 35~54 C
총점 34 이하 D
```

---

## 20.3 evaluate_averaging_timing 테스트

필수 테스트:

```text
최신 가격이 없으면 평가 불가 결과 반환
critical risk가 있으면 D 등급 조기 반환
충분한 데이터가 있으면 EvaluationResult 반환
score_breakdown에 모든 항목 포함
disclaimer 포함
C/D 등급이면 suggested_budget 0
A 등급이면 max_additional_budget의 일부 반환
```

---

# 21. 구현 시 주의사항

## 21.1 투자 표현 주의

다음 표현을 사용하지 않는다.

```text
매수 추천
지금 매수
무조건 반등
수익 보장
손실 회복 가능
```

허용 표현:

```text
추가 매수 가능성 검토 구간
관찰 구간
물타기 금지 구간
손절 또는 비중 축소 기준 점검 구간
투자 참고용 데이터 분석
```

---

## 21.2 숫자 타입 주의

가격, 금액, 예산은 Decimal을 사용한다.

```text
float 사용으로 인한 오차를 피한다.
```

단, 일부 지표 계산 중간값은 float으로 계산한 뒤 Decimal로 변환할 수 있다.  
이 경우 변환 시 반올림 규칙을 명확히 한다.

---

## 21.3 함수 책임 분리

나쁜 구조:

```python
def evaluate_averaging_timing(holding):
    # DB 조회
    # RSI 계산
    # 지지선 계산
    # 점수 계산
    # 저장
    # 응답 생성
    # 모두 한 함수에 작성
```

좋은 구조:

```text
DB 조회 함수
지표 계산 함수
점수 계산 함수
등급 변환 함수
사유 생성 함수
평가 orchestration 함수
저장 함수
```

2단계에서는 저장 함수보다 계산 함수 완성에 집중한다.

---

# 22. 2단계 산출물

2단계 완료 후 산출물은 다음과 같아야 한다.

```text
1. indicator_service.py 구현
2. price_service.py 구현
3. market_service.py 일부 구현
4. support_service.py 구현
5. volume_service.py 구현
6. investor_flow_service.py 구현
7. risk_event_service.py 구현
8. scoring_service.py 구현
9. averaging_decision_service.py 계산 엔진 구현
10. EvaluationResult 구조
11. 단위 테스트
12. 3단계 API 연결을 위한 사용 예시
```

---

# 23. 다음 단계 연결

2단계가 완료되면 3단계에서 다음을 구현한다.

```text
03_api_workflow_design.md
```

3단계 주요 작업은 다음과 같다.

```text
1. POST /api/holdings/{id}/evaluate/ 실제 구현
2. evaluate_averaging_timing 호출
3. EvaluationResult를 AveragingDecision으로 저장
4. 판단 결과 JSON 응답 구성
5. 판단 이력 조회 API 완성
6. 권한 처리 강화
7. API 테스트 작성
```

---

# 24. 최종 요약

2단계의 핵심은 “점수 계산 엔진”이다.

1단계에서 만든 모델과 service skeleton 위에 다음을 구현한다.

```text
1. 기술적 지표 계산
2. 위험 이벤트 우선 필터
3. 추세·지지선·거래량·수급·시장 점수 계산
4. 총점 계산
5. 등급 변환
6. 판단 사유 생성
7. 제안 예산 계산
8. 손절 기준 가격 계산
9. EvaluationResult 반환
```

이 단계가 정확해야 3단계 API가 신뢰할 수 있는 결과를 반환할 수 있다.

모든 결과는 다음 원칙을 지킨다.

```text
본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아니다.
최종 투자 판단과 책임은 사용자 본인에게 있다.
```
