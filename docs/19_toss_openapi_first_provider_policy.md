# 19_toss_openapi_first_provider_policy.md

# theStock Toss OpenAPI First Provider Policy

---

# 0. 문서 목적

이 문서는 `theStock`의 운영 데이터 공급 정책을 정의한다.

운영 서비스 URL:

```text
https://stock.thesysm.com/
```

토스증권 OpenAPI가 공식 제공하는 데이터는 `TossOpenApiProvider`를 1순위 provider로 사용한다. 토스증권 OpenAPI가 제공하지 않거나 제공 범위가 부족한 데이터만 기존 provider 또는 보조 provider를 fallback으로 사용한다.

참조 문서:

```text
https://developers.tossinvest.com/llms.txt
https://openapi.tossinvest.com/openapi-docs/overview.md
https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md
https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
```

---

# 1. 기본 원칙

```text
1. Toss OpenAPI에서 제공하는 데이터는 TossOpenApiProvider를 1순위로 사용한다.
2. Toss OpenAPI에서 제공하지 않는 데이터만 기존 provider 또는 보조 provider를 사용한다.
3. MockDataProvider, pykrx, OPENDART, 수동 입력 provider는 제거하지 않고 fallback으로 유지한다.
4. provider 우선순위는 설정값으로 제어한다.
5. Toss API 장애, rate limit, 인증 실패가 서비스 전체 장애로 번지지 않게 한다.
6. 데이터 수집 실패는 DataIngestionLog 또는 운영 로그에 남긴다.
7. 컨설팅 엔진은 provider가 무엇인지 몰라도 되도록 기존 도메인 모델과 service interface를 유지한다.
8. 실제 주문 생성/정정/취소는 별도 승인 전까지 비활성화한다.
9. API Key, Secret Key, Access Token, 계좌번호는 문서나 Git에 저장하지 않는다.
```

---

# 2. Provider 우선순위

운영 기본값:

```env
THESTOCK_DATA_PROVIDER=toss
THESTOCK_PROVIDER_PRIORITY=toss,pykrx,opendart,manual,mock
TOSS_ORDER_EXECUTION_ENABLED=false
```

우선순위:

| 순위 | Provider | 사용 목적 |
|---:|---|---|
| 1 | TossOpenApiProvider | Toss가 제공하는 시세, 종목정보, 환율, 시장정보, 계좌, 보유주식, 주문 조회 데이터 |
| 2 | PykrxDataProvider | Toss 미제공 KRX 보강 데이터, 장애 시 보조 시세 데이터 |
| 3 | OpenDartDataProvider | 재무제표, 공시 상세 |
| 4 | ManualDataProvider | 운영자가 검증한 리스크 이벤트 또는 예외 데이터 |
| 5 | MockDataProvider | local/test 전용 |

---

# 3. Toss 우선 사용 데이터

| 데이터 영역 | Toss 우선 사용 | 비고 |
|---|---:|---|
| 국내 주식 현재가/시세 | 예 | Market Data |
| 미국 주식 현재가/시세 | 예 | Market Data |
| 호가/orderbook | 예 | `/api/v1/orderbook` |
| 체결/trades | 예 | `/api/v1/trades` |
| 캔들/candles | 예 | `/api/v1/candles`, 일봉/1분봉 제공 범위 확인 |
| 가격 제한/상하한가 | 예 | `/api/v1/price-limits` |
| 종목 마스터/종목정보 | 예 | `/api/v1/stocks` |
| 종목 경고/주의 정보 | 예 | `/api/v1/stocks/{symbol}/warnings` |
| 환율 | 예 | `/api/v1/exchange-rate` |
| 국내/미국 시장 캘린더 | 예 | `/api/v1/market-calendar/KR`, `/api/v1/market-calendar/US` |
| 계좌 목록 | 예 | `/api/v1/accounts` |
| 보유주식/잔고 | 예 | `/api/v1/holdings` |
| 주문 가능 금액/매수 가능 금액 | 예 | `/api/v1/buying-power` |
| 매도 가능 수량 | 예 | `/api/v1/sellable-quantity` |
| 수수료/예상 수수료 | 예 | `/api/v1/commissions` |
| 주문 목록/상세 조회 | 예 | 조회 목적만 허용 |
| 주문 생성/정정/취소 | 보류 | 별도 승인 전까지 비활성 |
| 재무제표/공시 상세 | 아니오 또는 보조 | OPENDART 유지 |
| 뉴스/공시 이벤트 | 아니오 또는 보조 | 기존 news/risk provider 유지 |
| 투자자별 수급 | 문서 확인 필요 | Toss 제공 여부 확정 전까지 보조 provider |

---

# 4. 장애 및 Fallback 정책

Toss 호출 실패 유형:

```text
1. network timeout
2. DNS/TLS 오류
3. 401/403 인증 오류
4. 429 rate limit
5. 5xx provider 오류
6. malformed response
7. partial data response
```

대응:

```text
1. DataIngestionLog에 실패를 기록한다.
2. DataProviderStatus를 UP/DEGRADED/DOWN/AUTH_FAILED/RATE_LIMITED로 갱신한다.
3. 인증 오류는 token 재발급을 1회 시도한다.
4. retry 가능한 오류는 backoff 후 재시도한다.
5. 계속 실패하면 fallback provider를 사용한다.
6. fallback도 실패하면 기존 정상 데이터를 유지하고 data quality warning을 남긴다.
7. partial response는 검증 전 active 데이터로 반영하지 않는다.
```

---

# 5. 주문 API 운영 정책

Toss OpenAPI의 주문 생성/정정/취소 API는 실제 계좌에 영향을 준다.

운영 기본값:

```env
TOSS_ORDER_EXECUTION_ENABLED=false
```

별도 승인 전 허용:

```text
1. 계좌 목록 조회
2. 보유주식 조회
3. 주문 목록 조회
4. 주문 상세 조회
5. 주문 가능 금액 조회
6. 매도 가능 수량 조회
7. 수수료 조회
```

별도 승인 전 금지:

```text
1. 주문 생성
2. 주문 정정
3. 주문 취소
4. 컨설팅 결과의 자동 주문 연결
5. 사용자의 명시 확인 없는 계좌 영향 작업
```

---

# 6. 보안 원칙

다음 값은 문서, Git, 테스트 fixture, 일반 로그에 저장하지 않는다.

```text
Toss API Key
Toss Client ID 실제 값
Toss Client Secret 실제 값
Access Token
Refresh Token 또는 token에 준하는 값
Authorization header 원문
X-Tossinvest-Account header 원문
계좌번호 또는 계좌 식별자 원문
```

`.env.example`에는 변수명만 남긴다.

```env
TOSS_INVEST_CLIENT_ID=
TOSS_INVEST_CLIENT_SECRET=
TOSS_INVEST_BASE_URL=
TOSS_INVEST_TOKEN_URL=
TOSS_ORDER_EXECUTION_ENABLED=false
THESTOCK_PROVIDER_PRIORITY=toss,pykrx,opendart,manual,mock
```

---

# 7. 관련 문서

```text
docs/08_data_pipeline_design.md
docs/10_toss_openapi_provider_design.md
docs/15_operations_runbook.md
docs/16_observability_and_alerting_design.md
docs/18_privacy_and_financial_data_policy.md
docs/20_toss_openapi_mapping_table.md
docs/21_toss_openapi_security_checklist.md
```
