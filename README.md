# Stock Workbench

Django + SQLite 기반 주식 거래 관리 및 물타기 판단 API 서비스입니다.

현재 범위:
- 기존 `portfolio` UI: CSV 업로드, 거래 조회/수정, 시세 보드, 보유/실현손익 분석
- 사용자 UI: 로그인, 보유 종목 컨설팅 목록, 컨설팅 상세 화면
- DRF API: 보유 종목, 시장 데이터, 기술 지표, 위험 이벤트, 물타기 평가/이력 조회, 성공/실패 확률 계산, 종합 컨설팅
- legacy `Transaction` → `UserHolding` 동기화 브리지

## 주요 기능
- 거래내역 CSV 업로드 및 관리
- 종목명 ↔ 티커 매핑 관리
- 현재 보유분/실현손익 분석
- 물타기 판단 scoring engine
- legacy 거래원장과 `UserHolding` 자동 동기화
- 평가 결과 저장 및 이력 조회 API
- 성공/실패 확률 계산 API
- 종합 컨설팅 API
- 보유 종목 컨설팅 화면
- Django Admin

## 설치
```bash
chmod +x install.sh
./install.sh
source .venv/bin/activate
python manage.py runserver
```

## settings 구조
- 개발 기본값: `stock_service.settings.dev`
- 운영 기본값: `stock_service.settings.prod`
- 예시 환경 변수: [.env.example](/home/cskang/ganzskang/theStock/.env.example:1)

개발 서버:
```bash
python manage.py runserver
```

운영 설정 확인 예시:
```bash
DJANGO_SETTINGS_MODULE=stock_service.settings.prod python manage.py check
```

운영 보안 확인 예시:
```bash
source /home/cskang/miniconda3/etc/profile.d/conda.sh
conda activate dj5
DJANGO_SETTINGS_MODULE=stock_service.settings.prod python manage.py check --deploy
```

## 운영 배포
- 인증은 `https://peach.thesysm.com` 기반 Peach SSO relying-party 방식입니다.
- 브라우저 로그인 화면은 `GET /accounts/login/` 이며, 로그인 검증은 서버가 Peach API로 relay 합니다.
- 운영 배포 자산은 `deploy/production/` 아래에 있습니다.
- 권장 배포 토폴로지: `Cloudflare Tunnel -> Nginx -> Gunicorn -> Django`

배포 스크립트:
```bash
bash deploy/production/install_thestock.sh
bash deploy/production/validate_thestock.sh
```

## 마이그레이션 / 테스트
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py test
```

## CI / Release Smoke
- PR / `main`, `master` push 검증: `.github/workflows/django-ci.yml`
- 수동 또는 `v*` 태그 smoke 검증: `.github/workflows/release-smoke.yml`

CI 기본 검증 항목:
- `python manage.py check`
- `python manage.py makemigrations --check`
- `python manage.py test`

## legacy 거래 동기화
- 기본 legacy owner: 환경 변수 `LEGACY_PORTFOLIO_USERNAME`
- 기본값: `demo`
- CSV 업로드, 거래 수정/삭제, 종목 매핑 수정 후 `UserHolding`를 자동 재동기화합니다.
- 청산 종목은 `UserHolding` 삭제 대신 `is_active=False`, `quantity=0`으로 보존합니다.

수동 동기화:
```bash
python manage.py sync_transactions_to_holdings
python manage.py sync_transactions_to_holdings --dry-run
python manage.py sync_transactions_to_holdings --username demo
```

## 입력 데이터 수집
08단계 mock provider 기반 파이프라인:
```bash
python manage.py ingest_stock_master --provider mock
python manage.py ingest_daily_prices --provider mock --stock-code 005930
python manage.py ingest_investor_flows --provider mock --stock-code 005930
python manage.py ingest_market_indices --provider mock
python manage.py ingest_risk_events --provider mock --stock-code 005930
python manage.py ingest_financial_data --provider mock --stock-code 005930
python manage.py update_data_quality --stock-code 005930
python manage.py run_daily_pipeline --provider mock
```

추가 운영 조회 API:
- `GET /api/data-pipeline/summary/`
- `GET /api/data-pipeline/data-quality/{stock_code}/`
- `GET /api/data-pipeline/ingestion-logs/`
- `GET /api/data-pipeline/provider-status/`

`/api/data-pipeline/summary/`는 다음을 한 번에 요약합니다.
- `health_summary`: healthy / degraded / critical
- `snapshot_summary`: 최신 스냅샷 날짜, stale 여부, grade 분포
- `provider_summary`: failing provider 목록
- `ingestion_summary`: 최신 job, 최근 실패 로그

자동 수집 파이프라인:
- `DailyPrice`: `yfinance`
- `MarketIndex`: `yfinance`
- `InvestorFlow`: `pykrx`
- `RiskEvent`: `OpenDART`
- `FinancialSnapshot`: `OpenDART`

`data_pipeline` provider 선택 기준:
- `auto`: 위 소스들을 합성해서 `run_daily_pipeline` 전체 실행
- `finance`: `DailyPrice`, `MarketIndex`
- `krx`: `StockMaster`, `InvestorFlow`
- `disclosure`: `RiskEvent`
- `financial_statement`: `FinancialSnapshot`

기본값:
- `DATA_PIPELINE_PROVIDER=auto`
- `ingest_stock_master`: `krx`
- `ingest_daily_prices`, `ingest_market_indices`: `finance`
- `ingest_investor_flows`: `krx`
- `ingest_risk_events`: `disclosure`
- `ingest_financial_data`: `financial_statement`

```bash
python manage.py collect_daily_prices
python manage.py collect_market_indices
python manage.py collect_investor_flows
python manage.py collect_risk_events
python manage.py collect_financial_snapshots
python manage.py refresh_decision_inputs
```

옵션 예시:
```bash
python manage.py collect_daily_prices --stock-code 005930 --days 240 --dry-run
python manage.py collect_market_indices --codes KOSPI KOSDAQ USDKRW NASDAQ SP500 --days 240 --dry-run
python manage.py collect_investor_flows --stock-code 005930 --days 60 --dry-run
python manage.py collect_risk_events --stock-code 005930 --days 365 --dry-run
python manage.py collect_financial_snapshots --stock-code 005930 --years 2 --dry-run
python manage.py collect_daily_prices --use-data-pipeline --provider mock --dry-run
python manage.py collect_market_indices --use-data-pipeline --provider mock --dry-run
python manage.py collect_investor_flows --use-data-pipeline --provider mock --dry-run
python manage.py collect_risk_events --use-data-pipeline --provider mock --dry-run
python manage.py collect_financial_snapshots --use-data-pipeline --provider mock --dry-run
python manage.py run_daily_pipeline --provider auto --dry-run
python manage.py refresh_decision_inputs --stock-code 005930 --index-codes KOSPI NASDAQ --dry-run
python manage.py refresh_decision_inputs --legacy --stock-code 005930 --dry-run
```

`refresh_decision_inputs`는 기본적으로 `data_pipeline` 경로를 사용합니다. 기존 collector 경로를 그대로 쓰려면 `--legacy`를 사용하세요.

현재 기본 수집 범위:
- 가격 데이터: active `UserHolding` 종목
- 시장 데이터: `KOSPI`, `KOSDAQ`, `USDKRW`, `NASDAQ`, `SP500`
- 수급 데이터: active `UserHolding` 종목의 최근 60일 순매수 금액
- 리스크 이벤트: active `UserHolding` 종목의 최근 365일 OpenDART 공시
- 재무 스냅샷: active `UserHolding` 일반 종목의 최근 2개년 OpenDART 재무 데이터

CSV importer:
```bash
python manage.py import_investor_flows --file ./data/investor_flows.csv
python manage.py import_risk_events --file ./data/risk_events.csv
python manage.py audit_decision_input_quality
python manage.py audit_decision_input_quality --only-missing
```

주의:
- `collect_risk_events`와 `refresh_decision_inputs`의 리스크 이벤트 단계는 `OPENDART_API_KEY`가 필요합니다.
- `collect_financial_snapshots`와 `refresh_decision_inputs`의 재무 스냅샷 단계도 `OPENDART_API_KEY`가 필요합니다.
- `audit_decision_input_quality`는 `flow_sync`, `risk_sync`, `financial_sync`, `stock_quality`, `missing_flow_sync`, `missing_risk_sync`, `missing_financial_sync`로 미수집 종목을 식별합니다.

수급 CSV 컬럼:
- `stock_code`
- `date`
- `foreign_net_buy`
- `institution_net_buy`
- `individual_net_buy`
- `program_net_buy`

리스크 이벤트 CSV 컬럼:
- `stock_code`
- `event_date`
- `event_type`
- `risk_level`
- `title`
- 선택: `description`, `source`, `url`, `is_active`, `source_key`

## 샘플 데이터
평가 API를 바로 테스트할 수 있는 샘플 데이터를 생성합니다.

```bash
python manage.py seed_averaging_demo
```

기본 생성 대상:
- 사용자 `demo`
- 종목 `005930` 삼성전자
- `UserHolding`
- `DailyPrice` 120건
- `InvestorFlow` 5건
- `MarketIndex` 180건 (`KOSPI`, `NASDAQ`, `USDKRW`)

## 주요 API
인증:
- 기본 브라우저 인증은 Peach SSO 기반 session authentication
- 브라우저 로그인 화면: `GET /accounts/login/`
- logout: `POST /accounts/logout/`
- signup relay: `GET|POST /accounts/signup/`

브라우저 컨설팅 화면:
- `GET /consulting/holdings/`
- `GET /consulting/holdings/{id}/`
- `GET /operations/data-pipeline/`
- `GET /operations/data-pipeline/stocks/{stock_code}/`
- `GET /operations/data-pipeline/providers/{provider}/{data_type}/`

상세 요청/응답 문서:
- [docs/api_reference.md](docs/api_reference.md)
- 자동 schema endpoint: `GET /api/schema/`
- 자동 docs page: `GET /api/docs/`

핵심 endpoint:
- `GET /api/holdings/`
- `POST /api/holdings/{id}/evaluate/`
- `GET /api/holdings/{id}/decisions/`
- `POST /api/holdings/{id}/probability/`
- `GET /api/holdings/{id}/probabilities/`
- `POST /api/holdings/{id}/consult/`
- `GET /api/holdings/{id}/consults/`
- `GET /api/stocks/`
- `GET /api/marketdata/daily-prices/`
- `GET /api/marketdata/investor-flows/`
- `GET /api/marketdata/market-indices/`
- `GET /api/indicators/technical-indicators/`
- `GET /api/decisions/risk-events/`
- `GET /api/decisions/averaging-decisions/`
- `GET /api/decisions/probability-records/`
- `GET /api/decisions/consult-records/`
- `GET /api/data-pipeline/data-quality/{stock_code}/`
- `GET /api/data-pipeline/summary/`
- `GET /api/data-pipeline/ingestion-logs/`
- `GET /api/data-pipeline/provider-status/`

기준 데이터 권한 정책:
- `stocks`, `marketdata`, `risk-events` API는 인증 사용자 조회가 가능합니다.
- `POST`, `PUT`, `PATCH`, `DELETE`는 `is_staff=True` 사용자만 허용됩니다.
- `technical-indicators` API는 현재 인증 사용자 CRUD가 가능합니다.
- `averaging-decisions` API는 현재 사용자 본인 데이터만 조회 가능한 read-only API입니다.

holding API 운영 규칙:
- `GET /api/holdings/`는 기본적으로 `is_active=True`만 반환합니다.
- `GET /api/holdings/?include_inactive=true`로 청산 보존 holding까지 함께 조회할 수 있습니다.
- `POST /api/holdings/{id}/evaluate/`는 `AveragingDecision`를 저장합니다.
- `POST /api/holdings/{id}/probability/`는 `AveragingProbabilityRecord`를 저장하고, `GET /api/holdings/{id}/probabilities/`에서 최신순 이력을 조회할 수 있습니다.
- `POST /api/holdings/{id}/consult/`는 `HoldingConsultRecord`를 저장하고, `GET /api/holdings/{id}/consults/`에서 최신순 이력을 조회할 수 있습니다.
- `GET /consulting/holdings/{id}/` 화면은 내부적으로 `POST /api/holdings/{id}/consult/`를 호출합니다.
- 타 사용자 holding 접근은 `404`, inactive holding 평가/확률/컨설팅 요청은 `400`을 반환합니다.
- 요청에 `X-Request-ID`를 넣으면 응답과 서버 로그에 같은 값을 남깁니다.

평가 실행 예시:
```bash
curl -u demo:demo12345! -X POST http://127.0.0.1:8000/api/holdings/1/evaluate/
```

이력 조회 예시:
```bash
curl -u demo:demo12345! http://127.0.0.1:8000/api/holdings/1/decisions/
```

확률 계산 예시:
```bash
curl -u demo:demo12345! \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: probability-demo-001" \
  -X POST http://127.0.0.1:8000/api/holdings/1/probability/ \
  -d '{
    "buy_price": "68000.00",
    "buy_quantity": 10,
    "lookahead_days": 20,
    "target_type": "new_average_price_plus_profit",
    "target_profit_rate": "0.0500",
    "stop_loss_type": "support_or_atr",
    "same_day_hit_policy": "conservative"
  }'
```

컨설팅 실행 예시:
```bash
curl -u demo:demo12345! \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: consult-demo-001" \
  -X POST http://127.0.0.1:8000/api/holdings/1/consult/ \
  -d '{
    "buy_price": "68000.00",
    "lookahead_days": 20,
    "target_profit_rate": "0.0500",
    "stop_loss_type": "support_or_atr",
    "include_scenarios": true
  }'
```

권장 API 사용 순서:
1. `seed_averaging_demo` 또는 holding 생성
2. `refresh_decision_inputs`
3. `audit_decision_input_quality`
4. `evaluate` 또는 `probability`
5. 필요 시 `consult`

자동 문서화:
```bash
curl -u demo:demo12345! http://127.0.0.1:8000/api/schema/
curl -u demo:demo12345! http://127.0.0.1:8000/api/docs/
```

## 운영 모니터링
- liveness: `GET /healthz/`
- readiness: `GET /readyz/`
- `readyz`는 기본적으로 DB 연결과 pending migration 여부를 함께 점검합니다.
- `READINESS_CHECK_MIGRATIONS=0`이면 migration readiness check를 끌 수 있습니다.

예시:
```bash
curl http://127.0.0.1:8000/healthz/
curl http://127.0.0.1:8000/readyz/
```

## CSV 형식
- 매매구분
- 종목
- 년
- 월
- 일
- 시
- 분
- 수량(주)
- 단가(원)

## 기존 UI
- 대시보드: `/`
- 거래 목록: `/transactions/`
- 시세 보드: `/prices/`
- 분석 화면: `/analysis/`
- 종목 매핑: `/symbols/`
- 관리자: `/admin/`

## 운영 메모
- 개발은 SQLite + `DEBUG=True`
- 운영은 `DEBUG=False`와 환경 변수 기반 설정을 사용합니다
- PostgreSQL 연결 정보가 환경 변수로 주어지면 `stock_service.settings.prod`에서 PostgreSQL을 사용합니다
- 운영 배포는 `dj5` conda 환경과 `deploy/production/` 스크립트를 기준으로 합니다
- 운영 인증은 Peach SSO cookie (`.thesysm.com`) 공유를 전제로 합니다
- legacy 거래 UI를 계속 쓸 경우 `LEGACY_PORTFOLIO_USERNAME` 사용자를 고정해서 운영해야 합니다
- 계산형 API와 수집 command는 `request_id`, `holding_id`, `stock_code`, `command`, `source`를 포함한 구조화 콘솔 로그를 남깁니다
- 요청에 `X-Request-ID`를 보내면 응답에도 같은 값이 반환되어 추적에 사용할 수 있습니다
- 로그 레벨은 `DJANGO_LOG_LEVEL`로 조정합니다

## 투자 고지
본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다.
최종 투자 판단과 책임은 사용자 본인에게 있습니다.
