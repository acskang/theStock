# 08_codex_prompt_data_pipeline.md

# Codex 실행 프롬프트: 8단계 Data Pipeline & Data Quality Automation 구현

## 사용 방법

이 파일은 Codex에 그대로 전달하기 위한 8단계 실행 프롬프트다.

Codex에게 이 파일과 함께 다음 문서를 반드시 참조하게 한다.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
docs/03_api_workflow_design.md
docs/04_quality_release_design.md
docs/05_probability_engine_design.md
docs/06_optimized_consulting_system_design.md
docs/07_consulting_screen_design.md
docs/08_data_pipeline_design.md
```

이번 단계의 직접 기준 문서는 다음이다.

```text
docs/08_data_pipeline_design.md
```

---

# 실행 프롬프트 본문

너는 Django REST Framework 기반 백엔드 서비스를 운영 가능한 데이터 기반 서비스로 완성하는 개발 에이전트다.

이번 작업은 `물타기 컨설팅 시스템`의 **8단계 Data Pipeline & Data Quality Automation 구현**이다.

현재 시스템은 다음이 이미 구현된 상태라고 가정한다.

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
10. Probability Engine graceful degradation
11. 물타기 컨설팅 화면
```

하지만 지금은 실제 데이터 수집 자동화가 부족하다.

이번 단계의 목표는 다음이다.

```text
1. data_pipeline 앱 생성
2. provider interface 구현
3. mock provider 구현
4. 종목 마스터 수집 구현
5. 일봉 OHLCV 수집 구현
6. 투자자별 수급 수집 구현
7. 시장지수 수집 구현
8. RiskEvent 수집 구현
9. 재무 데이터 수집 구조 구현
10. DataIngestionLog 모델 구현
11. DataProviderStatus 모델 구현
12. DataQualitySnapshot 모델 구현
13. FinancialSnapshot 모델 구현
14. Data Quality Score 계산 구현
15. management command 구현
16. 운영 조회 API 구현
17. 테스트 구현
```

---

# 1. 반드시 지킬 원칙

## 1.1 매수/매도 추천 금지

이 시스템은 매수 추천, 매도 추천, 자동매매 시스템이 아니다.

다음 표현을 코드, serializer, API 응답, README, 테스트 fixture에 사용하지 마라.

```text
매수하세요
매도하세요
수익 보장
안전합니다
반드시 오릅니다
확실한 바닥입니다
```

허용 표현:

```text
데이터 품질 점검 결과입니다.
컨설팅 판단에 필요한 데이터가 갱신되었습니다.
데이터 품질이 낮아 판단 신뢰도가 제한적입니다.
본 결과는 투자 참고용 데이터 분석입니다.
```

---

## 1.2 외부 API 직접 의존 금지

이번 단계에서는 외부 API 키가 없어도 동작해야 한다.

따라서 반드시 `MockDataProvider`를 구현하라.

실제 provider 파일은 skeleton만 만들어도 된다.

```text
krx_provider.py
finance_provider.py
disclosure_provider.py
financial_statement_provider.py
```

단, mock provider로 전체 테스트와 management command가 실행되어야 한다.

---

## 1.3 consult API 안에서 수집하지 말 것

다음 구현은 금지한다.

```text
POST /api/holdings/{id}/consult/ 실행 중 외부 API 호출
Scoring Engine 내부에서 외부 API 호출
Probability Engine 내부에서 외부 API 호출
serializer 내부에서 수집 실행
view 내부에서 수집 로직 직접 작성
```

데이터 수집은 management command와 service layer에서만 실행한다.

---

## 1.4 기존 모델을 우선 재사용

기존 앱의 모델을 반드시 재사용한다.

```text
stocks.Stock
marketdata.DailyPrice
marketdata.InvestorFlow
marketdata.MarketIndex
decisions.RiskEvent
```

새로 중복 모델을 만들지 마라.

재무 데이터 모델이 없으면 `data_pipeline.models.FinancialSnapshot`을 추가한다.

---

# 2. 구현할 앱 구조

새 Django 앱을 생성하라.

```bash
python manage.py startapp data_pipeline
```

설정에 추가하라.

```python
INSTALLED_APPS = [
    ...
    "data_pipeline",
]
```

구조는 다음을 기준으로 한다.

```text
data_pipeline/
 ├── __init__.py
 ├── admin.py
 ├── apps.py
 ├── models.py
 ├── serializers.py
 ├── views.py
 ├── urls.py
 ├── dataclasses.py
 ├── validators.py
 ├── providers/
 │   ├── __init__.py
 │   ├── base.py
 │   ├── mock_provider.py
 │   ├── krx_provider.py
 │   ├── finance_provider.py
 │   ├── disclosure_provider.py
 │   └── financial_statement_provider.py
 ├── services/
 │   ├── __init__.py
 │   ├── ingestion_log_service.py
 │   ├── stock_master_ingestion_service.py
 │   ├── price_ingestion_service.py
 │   ├── investor_flow_ingestion_service.py
 │   ├── market_index_ingestion_service.py
 │   ├── risk_event_ingestion_service.py
 │   ├── financial_data_ingestion_service.py
 │   ├── data_quality_service.py
 │   └── pipeline_orchestrator.py
 ├── management/
 │   └── commands/
 │       ├── ingest_stock_master.py
 │       ├── ingest_daily_prices.py
 │       ├── ingest_investor_flows.py
 │       ├── ingest_market_indices.py
 │       ├── ingest_risk_events.py
 │       ├── ingest_financial_data.py
 │       ├── update_data_quality.py
 │       └── run_daily_pipeline.py
 └── tests/
     ├── test_validators.py
     ├── test_data_quality_service.py
     ├── test_ingestion_services.py
     └── test_management_commands.py
```

---

# 3. 모델 구현

위치:

```text
data_pipeline/models.py
```

---

## 3.1 DataIngestionLog

다음 모델을 구현하라.

필드:

```text
job_name
provider
target_type
target_code
status
started_at
finished_at
total_count
success_count
failed_count
skipped_count
error_message
details
created_at
```

요구사항:

```text
status choices: started, success, partial, failed
target_code는 blank 허용
details는 JSONField default=dict
count 필드는 default=0
finished_at은 null=True, blank=True
error_message는 blank=True
```

인덱스:

```text
job_name, -started_at
provider, -started_at
status, -started_at
target_type, target_code
```

---

## 3.2 DataProviderStatus

필드:

```text
provider
data_type
is_active
last_success_at
last_failed_at
last_error_message
consecutive_failures
average_latency_ms
updated_at
```

요구사항:

```text
provider + data_type UniqueConstraint
is_active default=True
consecutive_failures default=0
average_latency_ms null=True, blank=True
last_success_at null=True, blank=True
last_failed_at null=True, blank=True
last_error_message blank=True
```

---

## 3.3 DataQualitySnapshot

필드:

```text
stock
as_of_date
price_data_days
latest_price_date
latest_price_age_days
investor_flow_days
latest_flow_date
market_data_available
risk_event_checked_at
financial_data_available
missing_fields
anomaly_flags
overall_score
quality_grade
created_at
updated_at
```

요구사항:

```text
stock은 stocks.Stock FK
stock + as_of_date UniqueConstraint
overall_score는 DecimalField(max_digits=5, decimal_places=4)
quality_grade choices: A, B, C, D
missing_fields JSONField default=list
anomaly_flags JSONField default=list
latest_price_date null=True, blank=True
latest_flow_date null=True, blank=True
risk_event_checked_at null=True, blank=True
```

---

## 3.4 FinancialSnapshot

기존 프로젝트에 재무 모델이 없다면 구현하라.

필드:

```text
stock
fiscal_year
quarter
revenue
operating_profit
net_income
total_assets
total_liabilities
total_equity
operating_cash_flow
debt_ratio
roe
per
pbr
source
created_at
updated_at
```

요구사항:

```text
stock + fiscal_year + quarter UniqueConstraint
금액/비율 필드는 DecimalField, null=True, blank=True
quarter는 PositiveSmallIntegerField, 연간 데이터는 0 허용
source blank=True
```

---

# 4. admin 구현

`data_pipeline/admin.py`에 다음 모델을 등록하라.

```text
DataIngestionLog
DataProviderStatus
DataQualitySnapshot
FinancialSnapshot
```

각 admin은 최소한 다음을 포함한다.

```text
list_display
list_filter
search_fields
ordering
date_hierarchy 가능한 경우 적용
autocomplete_fields 가능한 경우 적용
```

---

# 5. Dataclass 구현

위치:

```text
data_pipeline/dataclasses.py
```

다음 dataclass를 구현하라.

```python
StockMasterRow
DailyPriceRow
InvestorFlowRow
MarketIndexRow
RiskEventRow
FinancialSnapshotRow
```

Python 3.9 호환성을 고려하여 가능하면 `Optional`을 사용하라.

---

# 6. Provider 구현

## 6.1 BaseDataProvider

위치:

```text
data_pipeline/providers/base.py
```

다음 abstract method를 구현하라.

```python
fetch_stock_master
fetch_daily_prices
fetch_investor_flows
fetch_market_indices
fetch_risk_events
fetch_financial_snapshots
```

---

## 6.2 MockDataProvider

위치:

```text
data_pipeline/providers/mock_provider.py
```

요구사항:

```text
1. name = "mock"
2. fetch_stock_master는 최소 3개 샘플 종목 반환
3. fetch_daily_prices는 120일 이상의 DailyPriceRow 반환
4. fetch_investor_flows는 20일 이상의 InvestorFlowRow 반환
5. fetch_market_indices는 KOSPI, KOSDAQ, NASDAQ, S&P500, USD_KRW 샘플 반환
6. fetch_risk_events는 low/medium/high 샘플을 반환하되 critical은 기본적으로 반환하지 않음
7. fetch_financial_snapshots는 FinancialSnapshotRow 반환
```

샘플 데이터는 deterministic해야 한다. 테스트마다 값이 바뀌면 안 된다.

---

## 6.3 provider factory

다음 함수를 구현하라.

위치:

```text
data_pipeline/providers/__init__.py
```

```python
def get_provider(provider_name="mock"):
    ...
```

지원:

```text
mock
krx
finance
disclosure
financial_statement
```

실제 provider가 구현되지 않았으면 `NotImplementedError` 또는 skeleton class를 반환하되 mock은 반드시 동작해야 한다.

---

# 7. Validator 구현

위치:

```text
data_pipeline/validators.py
```

다음 함수를 구현하라.

```python
validate_daily_price_row
validate_investor_flow_row
validate_market_index_row
validate_risk_event_row
validate_financial_snapshot_row
```

검증 실패 시 `ValueError`를 발생시켜라.

DailyPrice 검증:

```text
open_price > 0
high_price > 0
low_price > 0
close_price > 0
high_price >= low_price
high_price >= open_price
high_price >= close_price
low_price <= open_price
low_price <= close_price
volume >= 0
stock_code 필수
date 필수
```

RiskEvent 검증:

```text
risk_level in low, medium, high, critical
stock_code 필수
title 필수
event_type 필수
event_date 필수
source 필수
```

---

# 8. Ingestion Log Service 구현

위치:

```text
data_pipeline/services/ingestion_log_service.py
```

함수:

```python
def start_ingestion_log(job_name, provider, target_type, target_code="", details=None):
    ...


def finish_ingestion_log(log, status, total_count=0, success_count=0, failed_count=0, skipped_count=0, error_message="", details=None):
    ...


def update_provider_status_success(provider, data_type, latency_ms=None):
    ...


def update_provider_status_failure(provider, data_type, error_message="", latency_ms=None):
    ...
```

---

# 9. Ingestion Service 구현

## 9.1 stock_master_ingestion_service.py

함수:

```python
def ingest_stock_master(provider):
    ...
```

저장 대상:

```text
stocks.models.Stock
```

저장 방식:

```python
Stock.objects.update_or_create(
    code=row.code,
    defaults={
        "name": row.name,
        "market": row.market,
        "sector": row.sector,
        "is_active": row.is_active,
    },
)
```

---

## 9.2 price_ingestion_service.py

함수:

```python
def ingest_daily_prices(provider, stock_codes=None, start_date=None, end_date=None, limit=None):
    ...
```

저장 대상:

```text
marketdata.models.DailyPrice
```

주의:

```text
stock이 없으면 failed 처리
중복 실행 시 update_or_create로 갱신
validate_daily_price_row 사용
```

---

## 9.3 investor_flow_ingestion_service.py

함수:

```python
def ingest_investor_flows(provider, stock_codes=None, start_date=None, end_date=None, limit=None):
    ...
```

저장 대상:

```text
marketdata.models.InvestorFlow
```

---

## 9.4 market_index_ingestion_service.py

함수:

```python
def ingest_market_indices(provider, codes=None, start_date=None, end_date=None):
    ...
```

저장 대상:

```text
marketdata.models.MarketIndex
```

---

## 9.5 risk_event_ingestion_service.py

함수:

```python
def normalize_risk_level(raw_level):
    ...


def ingest_risk_events(provider, stock_codes=None, start_date=None, end_date=None, limit=None):
    ...
```

저장 대상:

```text
decisions.models.RiskEvent
```

중복 기준:

```text
stock + event_type + title + event_date + source
```

---

## 9.6 financial_data_ingestion_service.py

함수:

```python
def ingest_financial_snapshots(provider, stock_codes=None, fiscal_year=None, limit=None):
    ...
```

저장 대상:

```text
data_pipeline.models.FinancialSnapshot
```

---

# 10. Data Quality Service 구현

위치:

```text
data_pipeline/services/data_quality_service.py
```

다음 함수를 구현하라.

```python
calculate_price_data_score
calculate_flow_data_score
calculate_market_data_score
calculate_risk_event_data_score
calculate_financial_data_score
calculate_overall_data_quality
convert_data_quality_grade
update_data_quality_snapshot
update_all_data_quality_snapshots
```

점수 공식은 `08_data_pipeline_design.md`를 기준으로 구현하라.

최종 가중치:

```text
price_score * 0.35
flow_score * 0.15
market_score * 0.20
risk_event_score * 0.15
financial_score * 0.15
```

Decimal을 사용하고 최종 overall_score는 소수점 4자리로 저장하라.

---

# 11. Pipeline Orchestrator 구현

위치:

```text
data_pipeline/services/pipeline_orchestrator.py
```

함수:

```python
def run_daily_pipeline(provider, stock_codes=None, start_date=None, end_date=None, limit=None):
    ...
```

처리 순서:

```text
1. ingest_stock_master
2. ingest_daily_prices
3. ingest_investor_flows
4. ingest_market_indices
5. ingest_risk_events
6. ingest_financial_snapshots
7. update_all_data_quality_snapshots
```

하나가 실패해도 전체를 즉시 중단하지 말고 partial 결과를 반환하라.

반환 예시:

```python
{
    "status": "partial",
    "steps": {
        "stock_master": {...},
        "daily_prices": {...},
        "investor_flows": {...},
        "market_indices": {...},
        "risk_events": {...},
        "financial_data": {...},
        "data_quality": {...},
    },
    "errors": [],
}
```

---

# 12. Management Command 구현

다음 command를 구현하라.

```text
ingest_stock_master
ingest_daily_prices
ingest_investor_flows
ingest_market_indices
ingest_risk_events
ingest_financial_data
update_data_quality
run_daily_pipeline
```

공통 옵션:

```text
--provider
--start-date
--end-date
--stock-code
--dry-run
--limit
```

모든 command는 stdout에 요약을 출력하라.

예:

```text
Data ingestion completed: success_count=120, failed_count=0
```

`dry-run`이 구현하기 어렵다면 최소한 옵션은 받아들이되 실제 저장을 막거나, 명확히 NotImplementedError 없이 warning을 출력하라.

---

# 13. Serializer / API 구현

## 13.1 serializers.py

다음 serializer를 구현하라.

```python
DataIngestionLogSerializer
DataProviderStatusSerializer
DataQualitySnapshotSerializer
```

DataQualitySnapshotSerializer는 다음 읽기 전용 필드를 포함한다.

```text
stock_code
stock_name
```

---

## 13.2 views.py

다음 API를 구현하라.

```http
GET /api/data-pipeline/data-quality/{stock_code}/
GET /api/data-pipeline/ingestion-logs/
GET /api/data-pipeline/provider-status/
```

권한은 기존 프로젝트 정책에 맞춰 `IsAuthenticated`를 기본으로 한다.

---

## 13.3 urls.py

`data_pipeline/urls.py`를 만들고, 프로젝트 root urls에 include하라.

```python
path("api/data-pipeline/", include("data_pipeline.urls"))
```

---

# 14. Consulting API 연동

가능하면 기존 `POST /api/holdings/{id}/consult/` 응답에 최신 DataQualitySnapshot을 포함하라.

추가 필드:

```json
"data_quality": {
  "overall_score": "0.8600",
  "quality_grade": "A",
  "latest_price_age_days": 1,
  "missing_fields": [],
  "anomaly_flags": []
}
```

DataQualitySnapshot이 없으면 graceful degradation 처리한다.

```json
"data_quality": {
  "overall_score": null,
  "quality_grade": "UNKNOWN",
  "warning": "Data quality snapshot is not available."
}
```

기존 consult API를 깨뜨리지 마라.

---

# 15. 테스트 구현

다음 테스트를 작성하라.

## 15.1 validators 테스트

```text
정상 DailyPriceRow 통과
high_price < low_price이면 ValueError
volume < 0이면 ValueError
stock_code 누락이면 ValueError
RiskEvent risk_level 오류이면 ValueError
```

## 15.2 ingestion service 테스트

```text
Mock provider로 Stock 생성
Mock provider로 DailyPrice 저장
중복 실행 시 row 수 증가하지 않음
InvestorFlow 저장
MarketIndex 저장
RiskEvent 저장
FinancialSnapshot 저장
DataIngestionLog 저장
DataProviderStatus 갱신
```

## 15.3 data quality 테스트

```text
가격 데이터 충분하면 price_score 높음
최신 가격이 오래되면 price_score 낮음
수급 데이터 없으면 flow_score 낮음
overall_score 계산 정확
quality_grade 변환 정확
DataQualitySnapshot 생성/갱신 정상
```

## 15.4 management command 테스트

```text
ingest_stock_master --provider mock 성공
ingest_daily_prices --provider mock 성공
update_data_quality --all 성공
run_daily_pipeline --provider mock 성공 또는 partial 정상 처리
```

## 15.5 API 테스트

```text
GET data-quality 정상
GET ingestion-logs 정상
GET provider-status 정상
인증 정책 정상
```

---

# 16. 로깅 구현

각 service에 logger를 추가하라.

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
validation error
provider error
data quality updated
```

---

# 17. 마이그레이션

모델 구현 후 migration을 생성하라.

```bash
python manage.py makemigrations data_pipeline
python manage.py migrate
```

---

# 18. 실행 확인

다음 명령이 동작해야 한다.

```bash
python manage.py ingest_stock_master --provider mock
python manage.py ingest_daily_prices --provider mock --limit 3
python manage.py ingest_investor_flows --provider mock --limit 3
python manage.py ingest_market_indices --provider mock
python manage.py ingest_risk_events --provider mock --limit 3
python manage.py ingest_financial_data --provider mock --limit 3
python manage.py update_data_quality --all
python manage.py run_daily_pipeline --provider mock --limit 3
python manage.py test
```

---

# 19. 완료 보고 형식

구현 완료 후 다음 형식으로 보고하라.

```text
8단계 Data Pipeline 구현 완료

구현한 주요 파일:
- data_pipeline/models.py
- data_pipeline/providers/base.py
- data_pipeline/providers/mock_provider.py
- data_pipeline/services/...
- data_pipeline/management/commands/...

구현한 기능:
- Mock provider 기반 데이터 수집
- DataIngestionLog 저장
- DataProviderStatus 갱신
- DataQualitySnapshot 계산
- management command 실행
- 운영 조회 API

테스트:
- python manage.py test 결과

주의사항:
- 실제 외부 provider는 skeleton이며, mock provider로 검증 완료

다음 단계:
- 09 Backtesting Engine 구현
```

---

# 20. 지금 구현 시작

지금 바로 구현하라.

중요:

```text
1. 기존 consult API를 깨뜨리지 마라.
2. 기존 모델을 중복 생성하지 마라.
3. mock provider로 전체 pipeline이 반드시 동작해야 한다.
4. 데이터 수집 실패는 로그와 DataIngestionLog에 남겨라.
5. 데이터 품질이 낮은 상황을 숨기지 마라.
```
