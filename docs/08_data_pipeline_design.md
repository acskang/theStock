# 08_data_pipeline_design.md

# 물타기 컨설팅 시스템 8단계 설계서: Data Pipeline & Data Quality Automation

---

# 0. 문서 목적

이 문서는 `물타기 컨설팅 시스템`의 8단계 구현 범위를 정의한다.

1~7단계까지 시스템은 다음 기능을 갖추었다.

```text
1. Django Foundation
2. Scoring Engine
3. API Workflow
4. Quality & Release
5. Probability Engine
6. Optimized Consulting System
7. Consulting Screen
```

하지만 현재 상태의 가장 큰 한계는 다음이다.

```text
기능과 화면은 존재하지만, 실제 판단에 필요한 시장/종목/가격/수급/리스크/재무 데이터가 자동으로 수집·검증·갱신되지 않으면 실사용 서비스가 될 수 없다.
```

따라서 8단계의 목적은 다음이다.

```text
1. 종목 마스터 데이터 자동 수집
2. 일봉 OHLCV 데이터 자동 수집
3. 투자자별 수급 데이터 자동 수집
4. 시장지수/환율/미국지수 보조 데이터 자동 수집
5. 뉴스/공시 기반 RiskEvent 수집 구조 구현
6. 재무 데이터 수집 구조 구현
7. 데이터 품질 검증 및 Data Quality Score 자동 갱신
8. 수집 실패 로그와 재시도 구조 구현
9. management command 기반 수동/스케줄 실행 구조 구현
10. 향후 Celery/cron 확장 가능한 구조 마련
```

이 단계는 매매 추천 기능이 아니다.  
이 단계는 기존 컨설팅 API와 화면이 신뢰할 수 있는 데이터를 기반으로 작동하도록 만드는 **데이터 기반 운영 자동화 단계**다.

---

# 1. 핵심 원칙

## 1.1 데이터가 판단보다 먼저다

물타기 판단은 데이터 품질이 낮으면 의미가 없다.

따라서 8단계 이후 모든 컨설팅 판단은 다음 순서를 따라야 한다.

```text
1. 데이터 최신성 확인
2. 데이터 누락 확인
3. 데이터 이상치 확인
4. Data Quality Score 계산
5. Data Quality Score에 따라 consult 결과 신뢰도 보정
6. 컨설팅 결과 반환
```

---

## 1.2 자동 수집은 판단 로직과 분리한다

수집 로직은 Scoring Engine, Probability Engine, Consulting Engine 안에 넣지 않는다.

```text
금지:
- consult API 실행 중 외부 API를 직접 호출
- evaluate_averaging_timing 내부에서 외부 데이터 수집
- serializer에서 외부 API 호출
- view에서 데이터 수집/정제/검증 로직 직접 구현
```

허용:

```text
- management command로 데이터 수집
- service layer에서 수집/정제/저장
- API에서는 이미 저장된 데이터를 읽어서 판단
- 데이터가 부족하면 consult 결과에 warning 표시
```

---

## 1.3 외부 데이터 제공자는 교체 가능해야 한다

운영 기준의 1순위 provider는 토스증권 OpenAPI다.

토스증권 OpenAPI에서 제공하는 데이터는 `TossOpenApiProvider`를 먼저 사용하고, 토스에서 제공하지 않거나 장애/인증 실패/rate limit 등으로 사용할 수 없는 데이터만 fallback provider를 사용한다.

초기 구현 또는 local/test 환경에서는 실제 외부 API가 확정되지 않았거나 credential이 없을 수 있다.

따라서 provider 인터페이스를 분리한다.

```text
data_pipeline/providers/
 ├── base.py
 ├── toss_openapi_provider.py
 ├── mock_provider.py
 ├── krx_provider.py
 ├── finance_provider.py
 ├── disclosure_provider.py
 └── financial_statement_provider.py
```

`mock_provider.py`, pykrx, OPENDART, 수동 입력 provider는 제거하지 않고 fallback으로 유지한다.  
운영 provider 우선순위는 설정값으로 제어한다.

```env
THESTOCK_PROVIDER_PRIORITY=toss,pykrx,opendart,manual,mock
THESTOCK_DATA_PROVIDER=toss
```

권장 우선순위:

```text
1. TossOpenApiProvider: Toss가 공식 제공하는 시세/종목/환율/시장/계좌/보유/주문 조회 데이터
2. PykrxDataProvider: Toss 미제공 KRX 보강 데이터 또는 장애 시 보조 시세 데이터
3. OpenDartDataProvider: 재무제표와 공시 상세
4. ManualDataProvider: 운영자가 검증한 리스크 이벤트 또는 예외 데이터
5. MockDataProvider: local/test 전용
```

---

## 1.4 데이터 수집 실패는 조용히 묻지 않는다

수집 실패는 반드시 기록한다.

```text
1. 어떤 provider에서 실패했는지
2. 어떤 symbol 또는 market에서 실패했는지
3. 실패 원인이 무엇인지
4. 언제 실패했는지
5. 재시도 가능 여부
6. 마지막 성공 시각
```

---

## 1.5 중복 저장을 방지한다

가격, 수급, 시장지수 데이터는 날짜 기준으로 중복 저장되면 안 된다.

기존 모델의 unique constraint를 활용하고, 저장 시 `update_or_create`를 기본으로 사용한다.

---

# 2. 구현 범위

## 2.1 포함 범위

8단계에서 구현할 범위는 다음이다.

```text
1. data_pipeline 앱 생성
2. provider interface 정의
3. 수집 결과 dataclass 정의
4. 종목 마스터 수집 서비스
5. 일봉 가격 수집 서비스
6. 투자자별 수급 수집 서비스
7. 시장지수 수집 서비스
8. RiskEvent 수집 서비스
9. 재무 데이터 수집 구조
10. DataQualitySnapshot 모델
11. DataIngestionLog 모델
12. DataProviderStatus 모델
13. 데이터 검증 함수
14. Data Quality Score 계산 함수
15. management command 구현
16. 테스트 구현
```

---

## 2.2 제외 범위

8단계에서는 다음을 구현하지 않는다.

```text
1. 자동 매매
2. 매수/매도 추천
3. 실시간 websocket 시세
4. 초단타 분봉 수집
5. 복잡한 ML 학습
6. 백테스트 엔진
7. 사용자 알림 시스템
8. 포트폴리오 리스크 화면
```

백테스트는 9단계에서 구현한다.

---

# 3. 권장 앱 구조

새 앱 이름은 `data_pipeline`으로 한다.

```text
project_root/
 ├── data_pipeline/
 │   ├── __init__.py
 │   ├── admin.py
 │   ├── apps.py
 │   ├── models.py
 │   ├── serializers.py
 │   ├── views.py
 │   ├── urls.py
 │   ├── dataclasses.py
 │   ├── validators.py
 │   ├── providers/
 │   │   ├── __init__.py
 │   │   ├── base.py
 │   │   ├── mock_provider.py
 │   │   ├── krx_provider.py
 │   │   ├── finance_provider.py
 │   │   ├── disclosure_provider.py
 │   │   └── financial_statement_provider.py
 │   ├── services/
 │   │   ├── __init__.py
 │   │   ├── ingestion_log_service.py
 │   │   ├── stock_master_ingestion_service.py
 │   │   ├── price_ingestion_service.py
 │   │   ├── investor_flow_ingestion_service.py
 │   │   ├── market_index_ingestion_service.py
 │   │   ├── risk_event_ingestion_service.py
 │   │   ├── financial_data_ingestion_service.py
 │   │   ├── data_quality_service.py
 │   │   └── pipeline_orchestrator.py
 │   ├── management/
 │   │   └── commands/
 │   │       ├── ingest_stock_master.py
 │   │       ├── ingest_daily_prices.py
 │   │       ├── ingest_investor_flows.py
 │   │       ├── ingest_market_indices.py
 │   │       ├── ingest_risk_events.py
 │   │       ├── ingest_financial_data.py
 │   │       ├── update_data_quality.py
 │   │       └── run_daily_pipeline.py
 │   └── tests/
 │       ├── test_validators.py
 │       ├── test_data_quality_service.py
 │       ├── test_ingestion_services.py
 │       └── test_management_commands.py
```

---

# 4. 모델 설계

## 4.1 DataIngestionLog

### 목적

데이터 수집 실행 이력을 저장한다.

### 위치

```text
data_pipeline/models.py
```

### 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| job_name | CharField | 실행 작업명 |
| provider | CharField | 데이터 제공자 |
| target_type | CharField | stock, price, flow, market, risk, financial |
| target_code | CharField | 종목코드 또는 시장코드 |
| status | CharField | started, success, partial, failed |
| started_at | DateTimeField | 시작 시각 |
| finished_at | DateTimeField | 종료 시각 |
| total_count | PositiveIntegerField | 처리 대상 수 |
| success_count | PositiveIntegerField | 성공 수 |
| failed_count | PositiveIntegerField | 실패 수 |
| skipped_count | PositiveIntegerField | 스킵 수 |
| error_message | TextField | 대표 에러 메시지 |
| details | JSONField | 상세 로그 |
| created_at | DateTimeField | 생성 시각 |

### status choices

```text
started
success
partial
failed
```

### 인덱스

```text
job_name, -started_at
provider, -started_at
status, -started_at
target_type, target_code
```

---

## 4.2 DataProviderStatus

### 목적

provider별 마지막 성공/실패 상태를 저장한다.

### 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| provider | CharField | provider 이름 |
| data_type | CharField | stock_master, daily_price, investor_flow 등 |
| is_active | BooleanField | 사용 여부 |
| last_success_at | DateTimeField | 마지막 성공 시각 |
| last_failed_at | DateTimeField | 마지막 실패 시각 |
| last_error_message | TextField | 마지막 에러 |
| consecutive_failures | PositiveIntegerField | 연속 실패 횟수 |
| average_latency_ms | PositiveIntegerField | 평균 응답 시간 |
| updated_at | DateTimeField | 수정 시각 |

### unique constraint

```text
provider + data_type unique
```

---

## 4.3 DataQualitySnapshot

### 목적

종목별 데이터 품질 상태를 저장한다.

### 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| stock | ForeignKey(Stock) | 종목 |
| as_of_date | DateField | 기준일 |
| price_data_days | PositiveIntegerField | 보유 가격 데이터 수 |
| latest_price_date | DateField | 최신 가격 일자 |
| latest_price_age_days | PositiveIntegerField | 최신 가격 지연 일수 |
| investor_flow_days | PositiveIntegerField | 수급 데이터 수 |
| latest_flow_date | DateField | 최신 수급 일자 |
| market_data_available | BooleanField | 시장 데이터 존재 여부 |
| risk_event_checked_at | DateTimeField | 리스크 이벤트 확인 시각 |
| financial_data_available | BooleanField | 재무 데이터 존재 여부 |
| missing_fields | JSONField | 누락 데이터 목록 |
| anomaly_flags | JSONField | 이상치 목록 |
| overall_score | DecimalField | 0~1 데이터 품질 점수 |
| quality_grade | CharField | A, B, C, D |
| created_at | DateTimeField | 생성 시각 |
| updated_at | DateTimeField | 수정 시각 |

### unique constraint

```text
stock + as_of_date unique
```

### quality_grade 기준

| overall_score | grade | 의미 |
|---:|---|---|
| 0.80 이상 | A | 판단 신뢰도 높음 |
| 0.60 ~ 0.7999 | B | 판단 가능 |
| 0.40 ~ 0.5999 | C | 제한적 판단 |
| 0.40 미만 | D | 판단 신뢰도 낮음 |

---

## 4.4 FinancialSnapshot

기존 프로젝트에 재무 모델이 없다면 `data_pipeline` 또는 별도 `fundamentals` 앱에 구현한다.

### 목적

Stock Quality Engine에서 사용할 재무 데이터를 저장한다.

### 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| stock | ForeignKey(Stock) | 종목 |
| fiscal_year | PositiveIntegerField | 회계연도 |
| quarter | PositiveIntegerField | 분기, 연간이면 0 |
| revenue | DecimalField | 매출액 |
| operating_profit | DecimalField | 영업이익 |
| net_income | DecimalField | 순이익 |
| total_assets | DecimalField | 자산총계 |
| total_liabilities | DecimalField | 부채총계 |
| total_equity | DecimalField | 자본총계 |
| operating_cash_flow | DecimalField | 영업현금흐름 |
| debt_ratio | DecimalField | 부채비율 |
| roe | DecimalField | ROE |
| per | DecimalField | PER |
| pbr | DecimalField | PBR |
| source | CharField | 데이터 출처 |
| created_at | DateTimeField | 생성일 |
| updated_at | DateTimeField | 수정일 |

### unique constraint

```text
stock + fiscal_year + quarter unique
```

---

# 5. Provider Interface 설계

## 5.1 BaseDataProvider

### 위치

```text
data_pipeline/providers/base.py
```

### 역할

외부 데이터 provider의 공통 인터페이스를 정의한다.

```python
from abc import ABC, abstractmethod


class BaseDataProvider(ABC):
    name = "base"

    @abstractmethod
    def fetch_stock_master(self):
        pass

    def fetch_prices(self, symbols):
        """현재가 조회. provider가 지원하지 않으면 NotImplementedError를 발생시킨다."""
        raise NotImplementedError

    @abstractmethod
    def fetch_daily_prices(self, stock_code, start_date=None, end_date=None):
        pass

    def fetch_orderbook(self, symbol):
        raise NotImplementedError

    def fetch_trades(self, symbol):
        raise NotImplementedError

    def fetch_price_limits(self, symbols):
        raise NotImplementedError

    @abstractmethod
    def fetch_investor_flows(self, stock_code, start_date=None, end_date=None):
        pass

    @abstractmethod
    def fetch_market_indices(self, codes=None, start_date=None, end_date=None):
        pass

    def fetch_exchange_rate(self, base_currency="USD", quote_currency="KRW"):
        raise NotImplementedError

    def fetch_market_calendar(self, market_country, start_date=None, end_date=None):
        raise NotImplementedError

    def fetch_accounts(self):
        raise NotImplementedError

    def fetch_holdings(self, account_seq):
        raise NotImplementedError

    def fetch_buying_power(self, account_seq, symbol=None):
        raise NotImplementedError

    def fetch_sellable_quantity(self, account_seq, symbol):
        raise NotImplementedError

    def fetch_commissions(self, account_seq=None, market_country=None):
        raise NotImplementedError

    @abstractmethod
    def fetch_risk_events(self, stock_code=None, start_date=None, end_date=None):
        pass

    @abstractmethod
    def fetch_financial_snapshots(self, stock_code, fiscal_year=None):
        pass
```

---

## 5.2 TossOpenApiProvider

`TossOpenApiProvider`는 운영 기본 provider다.

역할:

```text
1. 국내/미국 주식 현재가와 캔들 조회
2. 호가, 최근 체결, 가격 제한 조회
3. 종목 마스터와 종목 경고/주의 정보 조회
4. USD/KRW 등 환율 조회
5. 국내/미국 시장 캘린더 조회
6. 계좌 목록과 보유주식 조회
7. 주문 가능 금액, 매도 가능 수량, 수수료 조회
8. 주문 목록과 상세 조회
```

실제 주문 생성/정정/취소 method는 provider 구현에 둘 수 있지만, 운영 설정에서 기본 비활성화한다.

```env
TOSS_ORDER_EXECUTION_ENABLED=false
```

수집 실패 시에는 `DataIngestionLog`와 `DataProviderStatus`에 실패를 기록하고 다음 fallback provider로 넘긴다. fallback도 실패하면 기존 정상 데이터를 삭제하지 않고 데이터 품질 경고를 남긴다.

---

## 5.3 MockDataProvider

초기 구현에서는 외부 API 없이도 테스트 가능해야 한다.

```text
data_pipeline/providers/mock_provider.py
```

역할:

```text
1. 샘플 종목 반환
2. 샘플 가격 데이터 반환
3. 샘플 수급 데이터 반환
4. 샘플 시장지수 반환
5. 샘플 리스크 이벤트 반환
6. 샘플 재무 데이터 반환
```

Mock provider는 테스트와 개발환경에서 사용한다.

---

## 5.4 실제 provider 구현 원칙

KRX, DART, 공공데이터, 증권사 API 등은 다음 원칙을 따른다.

```text
1. API key는 환경변수에서 읽는다.
2. provider 내부에서 모델 저장을 하지 않는다.
3. provider는 raw data 또는 dataclass list만 반환한다.
4. 저장은 ingestion service에서 담당한다.
5. timeout과 retry를 provider 내부 또는 wrapper에서 처리한다.
```

---

# 6. Dataclass 설계

## 6.1 위치

```text
data_pipeline/dataclasses.py
```

---

## 6.2 StockMasterRow

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class StockMasterRow:
    code: str
    name: str
    market: str
    sector: str = ""
    is_active: bool = True
```

---

## 6.3 DailyPriceRow

```python
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class DailyPriceRow:
    stock_code: str
    date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    change_rate: Decimal | None = None
```

Python 3.9 호환이 필요하면 `Decimal | None` 대신 `Optional[Decimal]`을 사용한다.

---

## 6.4 InvestorFlowRow

```python
@dataclass(frozen=True)
class InvestorFlowRow:
    stock_code: str
    date: date
    foreign_net_buy: int = 0
    institution_net_buy: int = 0
    individual_net_buy: int = 0
    program_net_buy: int = 0
```

---

## 6.5 MarketIndexRow

```python
@dataclass(frozen=True)
class MarketIndexRow:
    code: str
    name: str
    date: date
    close_value: Decimal
    change_rate: Decimal | None = None
```

---

## 6.6 RiskEventRow

```python
@dataclass(frozen=True)
class RiskEventRow:
    stock_code: str
    event_type: str
    title: str
    source: str
    url: str
    event_date: date
    risk_level: str
    description: str = ""
    is_active: bool = True
```

---

## 6.7 FinancialSnapshotRow

```python
@dataclass(frozen=True)
class FinancialSnapshotRow:
    stock_code: str
    fiscal_year: int
    quarter: int
    revenue: Decimal | None = None
    operating_profit: Decimal | None = None
    net_income: Decimal | None = None
    total_assets: Decimal | None = None
    total_liabilities: Decimal | None = None
    total_equity: Decimal | None = None
    operating_cash_flow: Decimal | None = None
    debt_ratio: Decimal | None = None
    roe: Decimal | None = None
    per: Decimal | None = None
    pbr: Decimal | None = None
    source: str = ""
```

---

# 7. 데이터 검증 설계

## 7.1 validators.py

### 위치

```text
data_pipeline/validators.py
```

---

## 7.2 가격 데이터 검증

함수:

```python
def validate_daily_price_row(row):
    ...
```

검증 규칙:

```text
1. open_price > 0
2. high_price > 0
3. low_price > 0
4. close_price > 0
5. high_price >= low_price
6. high_price >= open_price
7. high_price >= close_price
8. low_price <= open_price
9. low_price <= close_price
10. volume >= 0
11. date is not None
12. stock_code is not empty
```

오류 발생 시 `ValueError`.

---

## 7.3 수급 데이터 검증

함수:

```python
def validate_investor_flow_row(row):
    ...
```

검증 규칙:

```text
1. date is not None
2. stock_code is not empty
3. 순매수 값은 음수 가능
4. None 값은 0으로 보정 가능
```

---

## 7.4 시장지수 검증

함수:

```python
def validate_market_index_row(row):
    ...
```

검증 규칙:

```text
1. code is not empty
2. name is not empty
3. close_value > 0
4. date is not None
```

---

## 7.5 RiskEvent 검증

함수:

```python
def validate_risk_event_row(row):
    ...
```

검증 규칙:

```text
1. stock_code is not empty
2. event_type is not empty
3. title is not empty
4. event_date is not None
5. risk_level in low, medium, high, critical
6. source is not empty
```

---

# 8. Ingestion Service 설계

## 8.1 공통 결과 구조

각 ingestion service는 다음 dict를 반환한다.

```python
{
    "total_count": 100,
    "success_count": 98,
    "failed_count": 2,
    "skipped_count": 0,
    "errors": [
        {"code": "005930", "message": "..."}
    ],
}
```

---

## 8.2 stock_master_ingestion_service.py

### 함수

```python
def ingest_stock_master(provider):
    ...
```

### 처리 흐름

```text
1. provider.fetch_stock_master() 호출
2. 각 row 검증
3. Stock.update_or_create(code=row.code)
4. count 집계
5. DataIngestionLog 저장
6. DataProviderStatus 갱신
```

---

## 8.3 price_ingestion_service.py

### 함수

```python
def ingest_daily_prices(provider, stock_codes=None, start_date=None, end_date=None):
    ...
```

### 처리 흐름

```text
1. 대상 stock_codes 결정
2. 각 stock_code에 대해 provider.fetch_daily_prices 호출
3. validate_daily_price_row 실행
4. Stock 조회
5. DailyPrice.update_or_create(stock, date)
6. success/failed 집계
7. ingestion log 저장
8. provider status 갱신
```

### 주의

```text
- consult API에서 직접 호출하지 않는다.
- 가격 저장 후 DataQualitySnapshot은 별도 command에서 갱신한다.
- 대량 데이터는 bulk_create/update를 고려할 수 있으나 1차 구현은 update_or_create 허용.
```

---

## 8.4 investor_flow_ingestion_service.py

### 함수

```python
def ingest_investor_flows(provider, stock_codes=None, start_date=None, end_date=None):
    ...
```

### 저장 대상

```text
marketdata.models.InvestorFlow
```

### 처리 원칙

```text
stock + date 기준 update_or_create
None 값은 0으로 보정 가능
```

---

## 8.5 market_index_ingestion_service.py

### 함수

```python
def ingest_market_indices(provider, codes=None, start_date=None, end_date=None):
    ...
```

### 기본 codes

```text
KOSPI
KOSDAQ
S&P500
NASDAQ
USD_KRW
```

프로젝트 모델이 `MarketIndex`에 code/name/date/close_value/change_rate를 가지고 있으므로 그대로 저장한다.

---

## 8.6 risk_event_ingestion_service.py

### 함수

```python
def ingest_risk_events(provider, stock_codes=None, start_date=None, end_date=None):
    ...
```

### 중복 방지 기준

RiskEvent 모델에 unique constraint가 없다면 다음 기준으로 중복 여부를 판단한다.

```text
stock + event_type + title + event_date + source
```

중복이면 update, 신규면 create.

### risk_level 매핑

provider마다 risk label이 다를 수 있으므로 normalize 함수가 필요하다.

```python
def normalize_risk_level(raw_level):
    ...
```

허용 값:

```text
low
medium
high
critical
```

---

## 8.7 financial_data_ingestion_service.py

### 함수

```python
def ingest_financial_snapshots(provider, stock_codes=None, fiscal_year=None):
    ...
```

### 저장 대상

```text
FinancialSnapshot
```

### 처리 원칙

```text
1. 재무 데이터가 없으면 실패가 아니라 skipped 처리 가능
2. stock quality engine은 재무 데이터가 없으면 quality confidence를 낮춘다
3. 재무 데이터는 분기 단위와 연간 단위를 모두 수용한다
```

---

# 9. Data Quality Service 설계

## 9.1 목적

Data Quality Service는 종목별 데이터 상태를 점수화한다.

컨설팅 결과가 아무리 좋더라도 데이터 품질이 낮으면 신뢰도를 낮춰야 한다.

---

## 9.2 함수 목록

위치:

```text
data_pipeline/services/data_quality_service.py
```

함수:

```python
def calculate_price_data_score(stock, as_of_date=None):
    ...


def calculate_flow_data_score(stock, as_of_date=None):
    ...


def calculate_market_data_score(as_of_date=None):
    ...


def calculate_risk_event_data_score(stock, as_of_date=None):
    ...


def calculate_financial_data_score(stock, as_of_date=None):
    ...


def calculate_overall_data_quality(stock, as_of_date=None):
    ...


def update_data_quality_snapshot(stock, as_of_date=None):
    ...


def update_all_data_quality_snapshots(as_of_date=None):
    ...
```

---

## 9.3 점수 범위

각 항목은 0~1 Decimal로 계산한다.

```text
price_score
flow_score
market_score
risk_event_score
financial_score
```

최종 점수:

```text
overall_score =
  price_score * 0.35
+ flow_score * 0.15
+ market_score * 0.20
+ risk_event_score * 0.15
+ financial_score * 0.15
```

---

## 9.4 price_score 계산

기준:

```text
최근 가격 데이터 최신성 + 충분한 일봉 수
```

점수:

```text
price_days_score:
  240일 이상 = 1.0
  120일 이상 = 0.8
  60일 이상 = 0.6
  30일 이상 = 0.4
  30일 미만 = 0.2
  0일 = 0

latest_age_score:
  1일 이내 = 1.0
  3일 이내 = 0.8
  7일 이내 = 0.5
  14일 이내 = 0.2
  14일 초과 = 0
```

```text
price_score = price_days_score * 0.6 + latest_age_score * 0.4
```

---

## 9.5 flow_score 계산

기준:

```text
최근 20거래일 이상 수급 데이터가 있으면 충분
```

점수:

```text
20일 이상 = 1.0
10일 이상 = 0.7
5일 이상 = 0.4
1일 이상 = 0.2
없음 = 0
```

---

## 9.6 market_score 계산

기준:

```text
KOSPI/KOSDAQ 중 최소 하나 이상 최신 시장 데이터 존재
```

권장:

```text
KOSPI, KOSDAQ, NASDAQ, S&P500, USD_KRW 중 존재 비율로 계산
```

---

## 9.7 risk_event_score 계산

기준:

```text
최근 리스크 이벤트 확인 시각이 얼마나 최신인지
```

점수:

```text
1일 이내 = 1.0
3일 이내 = 0.8
7일 이내 = 0.5
14일 이내 = 0.2
없음 = 0.3
```

리스크 이벤트 데이터가 없다는 것이 반드시 안전을 의미하지 않는다.  
따라서 확인 기록이 없으면 0이 아니라 0.3으로 둔다.

---

## 9.8 financial_score 계산

기준:

```text
최근 연간 또는 분기 재무 데이터 존재 여부
```

점수:

```text
최근 분기 데이터 있음 = 1.0
최근 연간 데이터 있음 = 0.8
2년 이내 데이터 있음 = 0.5
오래된 데이터 있음 = 0.2
없음 = 0
```

---

## 9.9 quality_grade 변환

```python
def convert_data_quality_grade(score):
    if score >= Decimal("0.80"):
        return "A"
    if score >= Decimal("0.60"):
        return "B"
    if score >= Decimal("0.40"):
        return "C"
    return "D"
```

---

# 10. Pipeline Orchestrator 설계

## 10.1 목적

개별 ingestion command를 한 번에 실행하는 daily pipeline을 제공한다.

위치:

```text
data_pipeline/services/pipeline_orchestrator.py
```

함수:

```python
def run_daily_pipeline(provider, stock_codes=None, start_date=None, end_date=None):
    ...
```

흐름:

```text
1. stock master 수집
2. daily prices 수집
3. investor flows 수집
4. market indices 수집
5. risk events 수집
6. financial data 수집 또는 필요 시 skip
7. data quality snapshot 갱신
8. 전체 결과 반환
```

---

## 10.2 graceful degradation

하나의 수집 단계가 실패해도 전체 pipeline을 즉시 중단하지 않는다.

```text
예:
- 가격 수집 성공
- 수급 수집 실패
- 시장지수 성공
- 리스크 이벤트 partial
- data quality 갱신 성공
→ pipeline status = partial
```

---

# 11. Management Command 설계

## 11.1 공통 옵션

모든 command는 다음 옵션을 지원한다.

```text
--provider mock
--start-date YYYY-MM-DD
--end-date YYYY-MM-DD
--stock-code 005930
--dry-run
--limit 100
```

필요 없는 옵션은 무시해도 된다.

---

## 11.2 ingest_stock_master

```bash
python manage.py ingest_stock_master --provider mock
```

역할:

```text
종목 마스터 수집
```

---

## 11.3 ingest_daily_prices

```bash
python manage.py ingest_daily_prices --provider mock --stock-code 005930 --start-date 2025-01-01 --end-date 2025-12-31
```

역할:

```text
일봉 가격 수집
```

---

## 11.4 ingest_investor_flows

```bash
python manage.py ingest_investor_flows --provider mock --stock-code 005930
```

---

## 11.5 ingest_market_indices

```bash
python manage.py ingest_market_indices --provider mock
```

---

## 11.6 ingest_risk_events

```bash
python manage.py ingest_risk_events --provider mock --stock-code 005930
```

---

## 11.7 ingest_financial_data

```bash
python manage.py ingest_financial_data --provider mock --stock-code 005930 --fiscal-year 2025
```

---

## 11.8 update_data_quality

```bash
python manage.py update_data_quality --stock-code 005930
python manage.py update_data_quality --all
```

---

## 11.9 run_daily_pipeline

```bash
python manage.py run_daily_pipeline --provider mock
```

역할:

```text
전체 pipeline 실행
```

---

# 12. API 설계

8단계는 운영용 조회 API만 추가한다.  
데이터 수집 실행은 원칙적으로 management command 또는 관리자 기능에서 수행한다.

---

## 12.1 Data Quality 조회 API

```http
GET /api/data-pipeline/data-quality/{stock_code}/
```

응답 예시:

```json
{
  "stock_code": "005930",
  "stock_name": "삼성전자",
  "as_of_date": "2026-04-30",
  "price_data_days": 240,
  "latest_price_date": "2026-04-29",
  "latest_price_age_days": 1,
  "investor_flow_days": 20,
  "market_data_available": true,
  "risk_event_checked_at": "2026-04-30T08:00:00+09:00",
  "financial_data_available": true,
  "missing_fields": [],
  "anomaly_flags": [],
  "overall_score": "0.8600",
  "quality_grade": "A"
}
```

---

## 12.2 Ingestion Log 조회 API

```http
GET /api/data-pipeline/ingestion-logs/
```

query:

```text
?status=failed
?job_name=ingest_daily_prices
?provider=mock
```

---

## 12.3 Provider Status 조회 API

```http
GET /api/data-pipeline/provider-status/
```

---

# 13. 기존 Consulting API와의 연동

8단계 이후 `POST /api/holdings/{id}/consult/`는 가능하면 DataQualitySnapshot을 읽어 결과에 포함한다.

## 13.1 consult response 추가 필드

```json
{
  "data_quality": {
    "overall_score": "0.8600",
    "quality_grade": "A",
    "latest_price_age_days": 1,
    "missing_fields": [],
    "anomaly_flags": []
  }
}
```

---

## 13.2 등급 상한 보정

Data Quality가 낮으면 최종 등급을 제한한다.

```text
data_quality_grade = D → final_grade 최대 C
data_quality_grade = C → final_grade 최대 B
data_quality_grade = A/B → 정상 허용
```

단, critical risk가 있으면 Data Quality와 관계없이 D가 우선이다.

---

## 13.3 문구 보정

Data Quality가 C 또는 D이면 consult 결과에 warning을 추가한다.

```text
데이터 품질이 낮아 판단 신뢰도가 제한적입니다. 최신 가격·수급·리스크 이벤트 데이터를 갱신한 뒤 다시 확인하는 것이 좋습니다.
```

---

# 14. 테스트 설계

## 14.1 Validator 테스트

```text
정상 DailyPriceRow 통과
high < low이면 ValueError
volume < 0이면 ValueError
stock_code 누락이면 ValueError
RiskEvent risk_level 잘못되면 ValueError
```

---

## 14.2 Ingestion Service 테스트

```text
Mock provider로 Stock 생성
Mock provider로 DailyPrice 저장
중복 실행 시 중복 row 생성 안 됨
잘못된 row는 failed_count 증가
DataIngestionLog 저장됨
DataProviderStatus 갱신됨
```

---

## 14.3 Data Quality 테스트

```text
가격 데이터 240일 이상이면 price_score 높음
최신 가격이 오래되면 price_score 낮음
수급 데이터 없으면 flow_score 낮음
재무 데이터 없으면 financial_score 낮음
overall_score 계산 정확
quality_grade 변환 정확
DataQualitySnapshot update_or_create 정상
```

---

## 14.4 Management Command 테스트

```text
ingest_stock_master command 실행 성공
ingest_daily_prices command 실행 성공
update_data_quality command 실행 성공
run_daily_pipeline partial failure 처리 정상
```

---

## 14.5 API 테스트

```text
GET data-quality 정상
GET ingestion-logs 정상
GET provider-status 정상
인증 필요 여부는 기존 프로젝트 정책에 맞춤
```

---

# 15. 로깅 설계

모든 ingestion service는 logger를 사용한다.

```python
import logging
logger = logging.getLogger(__name__)
```

필수 로그:

```text
ingestion started
ingestion success
ingestion partial
ingestion failed
provider error
validation error
data quality updated
```

로그 예시:

```python
logger.info({
    "event": "ingest_daily_prices",
    "provider": provider.name,
    "stock_code": stock_code,
    "success_count": success_count,
    "failed_count": failed_count,
})
```

---

# 16. 환경 설정

## 16.1 settings.py

`INSTALLED_APPS`에 추가한다.

```python
INSTALLED_APPS = [
    ...
    "data_pipeline",
]
```

---

## 16.2 환경변수

실제 provider 사용 시 다음 환경변수를 사용할 수 있게 한다.

```text
DATA_PROVIDER=mock
KRX_API_KEY=
DART_API_KEY=
FINANCE_API_KEY=
DATA_PIPELINE_TIMEOUT_SECONDS=10
DATA_PIPELINE_RETRY_COUNT=3
```

---

# 17. 운영 스케줄 권장

초기에는 cron 또는 수동 command로 실행한다.

```bash
# 장 마감 후 가격/수급/시장 데이터 갱신
python manage.py run_daily_pipeline --provider mock

# 데이터 품질만 재계산
python manage.py update_data_quality --all
```

향후 Celery beat로 확장 가능하다.

권장 스케줄:

```text
종목 마스터: 매일 1회 또는 주 1회
일봉 가격: 장 마감 후 1회
수급 데이터: 장 마감 후 1회
시장지수: 장 마감 후 1회
RiskEvent: 하루 2~4회
재무 데이터: 분기 실적 시즌 또는 주 1회
DataQualitySnapshot: pipeline 종료 후 매번
```

---

# 18. 완료 기준

8단계 완료 기준은 다음이다.

```text
1. data_pipeline 앱이 존재한다.
2. provider interface가 존재한다.
3. mock provider로 전체 pipeline을 실행할 수 있다.
4. Stock/DailyPrice/InvestorFlow/MarketIndex/RiskEvent/FinancialSnapshot 저장이 가능하다.
5. DataIngestionLog가 저장된다.
6. DataProviderStatus가 갱신된다.
7. DataQualitySnapshot이 계산된다.
8. data quality API가 동작한다.
9. run_daily_pipeline management command가 동작한다.
10. 핵심 테스트가 통과한다.
```

---

# 19. 다음 단계

8단계 이후 권장 단계는 다음이다.

```text
09_backtesting_engine_design.md
09_codex_prompt_backtesting_engine.md
```

9단계에서는 실제로 A/B/C/D 등급과 성공확률/실패확률이 과거 데이터에서 얼마나 맞았는지 검증한다.

---

# 20. 핵심 요약

```text
8단계 = 데이터 자동 수집 + 데이터 품질 자동 검증 + 운영 가능한 데이터 기반 마련
```

현재 시스템은 기능과 화면이 완성되어 있다.  
8단계가 완료되면 컨설팅 화면이 실제 데이터로 움직이기 시작한다.
