# 13_market_data_normalization_design.md

# theStock 시장 데이터 정규화 설계서

---

# 0. 문서 목적

`theStock`의 판단 품질은 시장 데이터 품질에 크게 의존한다.

주식 데이터는 단순히 날짜, 시가, 고가, 저가, 종가, 거래량만 저장하면 충분하지 않다.  
다음 이벤트가 반영되지 않으면 점수, 이동평균, 손익률, 목표가, 손절가, 백테스트 결과가 왜곡된다.

```text
1. 액면분할
2. 액면병합
3. 무상증자
4. 유상증자
5. 배당락
6. 권리락
7. 거래정지
8. 상장폐지
9. 종목코드 변경
10. 우선주/ETF/ETN/스팩 구분
11. 휴장일
12. 수정주가/비수정주가 기준 차이
```

이 문서는 `theStock`의 시장 데이터 정규화 기준을 정의한다.

---

# 1. 최상위 원칙

## 1.1 원본 데이터와 정규화 데이터 분리

수집한 원본 데이터와 정규화된 데이터는 구분해야 한다.

```text
RawMarketData: provider에서 받은 원본
NormalizedMarketData: 내부 판단 엔진이 사용하는 정규화 데이터
```

원본을 보관하면 provider 변경, 오류 검증, 재처리가 가능하다.

## 1.2 판단 엔진은 정규화 데이터 사용

Scoring Engine, Probability Engine, Backtest Engine은 정규화 데이터를 사용한다.

```text
1. 이동평균
2. RSI
3. 변동성
4. 손익률
5. 목표가/손절가
6. 지지/저항
7. 백테스트
```

단, 화면에는 사용자가 이해하기 쉬운 현재 가격 기준을 보여준다.

## 1.3 정규화 기준 명시

모든 가격 데이터에는 기준을 명시한다.

```text
price_adjustment_policy=ADJUSTED_CLOSE_BASED
또는
price_adjustment_policy=RAW_CLOSE_BASED
```

---

# 2. 수정주가 정책

## 2.1 수정주가가 필요한 이유

액면분할 예:

```text
분할 전 종가: 100,000원
분할 후 종가: 20,000원
5:1 액면분할
```

비수정주가로 이동평균을 계산하면 가격이 80% 폭락한 것처럼 보인다.  
이 경우 기술적 지표와 백테스트가 모두 왜곡된다.

## 2.2 내부 기준

권장:

```text
기술적 분석과 백테스트는 수정주가 기준을 사용한다.
```

저장 필드 예:

```text
raw_open
raw_high
raw_low
raw_close
adjusted_open
adjusted_high
adjusted_low
adjusted_close
adjustment_factor
adjustment_reason
```

## 2.3 수정 계수

수정 계수는 다음 이벤트를 반영한다.

```text
1. 액면분할
2. 액면병합
3. 무상증자
4. 배당락
5. 권리락
```

provider가 수정주가를 직접 제공하면 해당 기준을 문서화한다.  
provider가 제공하지 않으면 corporate action 데이터를 이용해 내부 계산한다.

---

# 3. Corporate Action 모델

권장 모델:

```text
CorporateAction
```

필드:

```text
stock
action_type
ex_date
record_date
effective_date
ratio_before
ratio_after
cash_dividend
stock_dividend_ratio
rights_issue_price
source_provider
raw_payload
created_at
updated_at
```

`action_type` 후보:

```text
SPLIT
REVERSE_SPLIT
CASH_DIVIDEND
STOCK_DIVIDEND
BONUS_ISSUE
RIGHTS_ISSUE
MERGER
SPIN_OFF
CODE_CHANGE
DELISTING
TRADING_SUSPENSION
```

---

# 4. 거래정지 처리

## 4.1 거래정지의 의미

거래정지는 일반적인 가격 하락과 다르다.  
물타기 판단에서 매우 중요한 리스크 이벤트다.

## 4.2 처리 원칙

거래정지 상태에서는 다음 정책을 적용한다.

```text
1. 추가 매수 판단 제공 금지
2. 컨설팅 결과에 강한 경고 노출
3. Probability Engine confidence 하향 또는 계산 중단
4. RiskEvent에 거래정지 상태 기록
```

## 4.3 데이터 표현

거래정지일에는 가격 데이터가 없을 수 있다.

금지:

```text
거래정지일 가격을 0으로 저장
```

권장:

```text
DailyPrice row 없음 또는 trading_status=SUSPENDED
```

---

# 5. 상장폐지 및 종목 상태

## 5.1 Stock 상태값

`Stock` 모델에 상태를 명확히 둔다.

```text
ACTIVE
SUSPENDED
MANAGED
WARNING
DELISTING_RISK
DELISTED
UNKNOWN
```

## 5.2 컨설팅 처리

| 상태 | 컨설팅 처리 |
|---|---|
| ACTIVE | 정상 판단 |
| SUSPENDED | 판단 중단 |
| MANAGED | 강한 경고 |
| WARNING | 강한 경고 |
| DELISTING_RISK | 추가 매수 부적합 |
| DELISTED | 판단 불가 |
| UNKNOWN | 데이터 확인 필요 |

---

# 6. 종목코드 변경

## 6.1 문제

회사명 변경, 합병, 분할 등으로 종목코드나 이름이 바뀔 수 있다.

## 6.2 모델

권장 모델:

```text
StockIdentifierHistory
```

필드:

```text
stock
identifier_type
identifier_value
valid_from
valid_to
source_provider
```

예:

```text
identifier_type=KRX_CODE
identifier_value=123456
valid_from=2020-01-01
valid_to=2024-05-01
```

## 6.3 처리 원칙

```text
1. 내부 Stock PK는 유지한다.
2. 외부 종목코드 변경은 history로 관리한다.
3. 과거 가격 데이터와 현재 종목을 연결할 수 있어야 한다.
```

---

# 7. 상품 유형 구분

일반 주식과 ETF/ETN/스팩/우선주는 성격이 다르다.

`Stock` 또는 별도 instrument 모델에 다음을 둔다.

```text
instrument_type
```

후보:

```text
COMMON_STOCK
PREFERRED_STOCK
ETF
ETN
REIT
SPAC
KONEX
UNKNOWN
```

판단 엔진 정책:

```text
1. COMMON_STOCK: 기본 엔진 적용
2. PREFERRED_STOCK: 수급/거래량 리스크 강화
3. ETF: 펀더멘털 점수 대신 구성자산/지수 추적 기준 필요
4. ETN: 발행사/괴리율 리스크 필요
5. SPAC: 일반 물타기 판단 부적합
```

초기에는 COMMON_STOCK 외 상품은 제한 또는 경고 처리한다.

---

# 8. 휴장일/거래일 캘린더

## 8.1 TradingCalendar

권장 모델:

```text
TradingCalendar
```

필드:

```text
market
date
is_open
open_time
close_time
session_type
holiday_name
```

`session_type` 후보:

```text
REGULAR
HALF_DAY
CLOSED
SPECIAL
```

## 8.2 사용처

```text
1. 데이터 수집 스케줄
2. 결측 가격 판단
3. 백테스트 N거래일 계산
4. 이동평균 계산
5. 장마감 데이터 확정 여부 판단
```

---

# 9. 장중 데이터와 장마감 데이터 구분

장중 데이터는 변동성이 크고 확정 데이터가 아니다.

필드:

```text
data_timeframe
```

후보:

```text
INTRADAY
EOD_PRELIMINARY
EOD_FINAL
```

컨설팅 정책:

```text
1. EOD_FINAL 우선 사용
2. 장중 컨설팅은 별도 경고 표시
3. EOD_PRELIMINARY는 데이터 확정 전 경고 표시
```

---

# 10. 이상치 처리

## 10.1 가격 이상치

검증 항목:

```text
1. open/high/low/close <= 0
2. high < low
3. close > high
4. close < low
5. 전일 대비 ±30% 초과인데 가격제한폭/권리락 정보 없음
6. 거래량 음수
7. 거래량 0인데 가격 변동 큼
```

## 10.2 처리

```text
1. DataQualityReport에 기록
2. 해당 날짜 데이터 사용 제한
3. 컨설팅 confidence 하향
4. 심각하면 컨설팅 중단
```

---

# 11. 정규화 파이프라인

```text
1. provider 원본 수집
2. raw table 저장
3. schema validation
4. corporate action 적용
5. adjusted price 생성
6. trading calendar와 비교
7. stock status 갱신
8. 이상치 검사
9. normalized table upsert
10. technical indicator 재계산
11. data quality report 생성
```

---

# 12. 컨설팅 엔진 연동

컨설팅 엔진은 다음 데이터를 함께 확인한다.

```text
1. adjusted price 기준 기술 지표
2. raw current price 기준 사용자 손익 계산
3. stock status
4. trading status
5. data quality grade
6. corporate action recent event
```

예:

```json
{
  "data_basis": {
    "price_basis": "ADJUSTED_FOR_TECHNICAL_ANALYSIS",
    "current_price_basis": "RAW_MARKET_PRICE",
    "recent_corporate_actions": ["CASH_DIVIDEND"],
    "trading_status": "ACTIVE"
  }
}
```

---

# 13. 구현 체크리스트

```text
[ ] raw data와 normalized data 분리 검토
[ ] adjusted price 필드 추가 검토
[ ] CorporateAction 모델 추가
[ ] Stock status 필드 정리
[ ] instrument_type 필드 추가
[ ] StockIdentifierHistory 모델 추가
[ ] TradingCalendar 모델 추가
[ ] 장중/EOD 데이터 구분 필드 추가
[ ] 정규화 management command 추가
[ ] 이상치 validation 추가
[ ] TechnicalIndicator 계산 기준을 adjusted price로 통일
[ ] 백테스트 N거래일 계산에 TradingCalendar 사용
[ ] 거래정지/상장폐지 시 컨설팅 제한
```

---

# 14. Codex 작업 지시 요약

```text
theStock의 시장 데이터 정규화 체계를 보강한다.
기술적 지표와 백테스트는 수정주가 기준을 사용하도록 설계한다.
원본 데이터와 정규화 데이터를 분리하고, corporate action, trading calendar, stock status를 관리한다.
거래정지/상장폐지/관리종목/투자경고 상태에서는 컨설팅 결과를 제한하거나 강한 경고를 표시한다.
기존 데이터 파이프라인과 API를 깨지 않도록 점진적으로 추가한다.
```

---

# 15. 결론

시장 데이터 정규화는 눈에 잘 보이지 않지만 `theStock`의 판단 신뢰도를 좌우하는 핵심 기반이다.

특히 물타기 판단에서는 다음 오류가 치명적이다.

```text
1. 액면분할을 폭락으로 오인
2. 배당락을 구조적 하락으로 오인
3. 거래정지를 단순 결측으로 처리
4. 상장폐지 위험 종목에 추가 매수 가능 표시
5. 휴장일을 데이터 누락으로 오인
```

따라서 정규화 계층을 명확히 두고, 판단 엔진은 항상 정규화된 데이터와 데이터 품질 정보를 함께 사용해야 한다.
