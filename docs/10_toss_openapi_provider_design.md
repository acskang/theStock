# 10_toss_openapi_provider_design.md

# theStock Toss OpenAPI Provider 설계서

---

# 0. 문서 목적

이 문서는 `theStock`의 데이터 파이프라인에 Toss OpenAPI를 실제 데이터 provider로 연결하기 위한 설계서다.

기존 `08_data_pipeline_design.md`는 provider 추상화, 수집 로그, 데이터 품질 구조를 정의한다.  
하지만 실제 Toss OpenAPI를 어떤 내부 모델에 어떻게 매핑하고, 인증/토큰/장애/스케줄/보안을 어떻게 처리할지에 대한 별도 설계가 필요하다.

이 문서의 목적은 다음이다.

```text
1. Toss OpenAPI 인증 정보를 안전하게 관리한다.
2. Toss API 응답을 theStock 내부 모델에 매핑한다.
3. provider 장애가 서비스 전체 장애로 번지지 않게 한다.
4. 수집 로그와 데이터 품질 리포트를 남긴다.
5. 운영 스케줄과 retry 정책을 정리한다.
6. 기존 MockDataProvider 구조와 충돌하지 않게 한다.
```

---

# 1. 보안 원칙

## 1.1 API Key / Secret 저장 금지

다음 정보는 문서, Git, 코드, 테스트 fixture에 저장하지 않는다.

```text
1. Toss API Key
2. Toss Client ID
3. Toss Client Secret
4. Access Token
5. Refresh Token
6. Authorization header 원문
```

허용되는 위치:

```text
1. 운영 서버의 .env
2. 배포 시스템의 secret manager
3. CI/CD secret store
```

문서에는 이름만 기록한다.

```env
TOSS_INVEST_CLIENT_ID=
TOSS_INVEST_CLIENT_SECRET=
TOSS_INVEST_BASE_URL=
TOSS_INVEST_TOKEN_URL=
```

## 1.2 로그 마스킹

로그에 인증 관련 값이 포함되면 안 된다.

마스킹 예:

```text
client_id=tos_****1234
access_token=***masked***
Authorization=Bearer ***masked***
```

## 1.3 키 노출 사고 대응

API key 또는 secret이 노출되면 다음 절차를 따른다.

```text
1. 즉시 해당 key 폐기
2. 새 key 발급
3. 운영 .env 갱신
4. 서비스 재시작
5. Git history 노출 여부 확인
6. 접근 로그 확인
7. 사고 기록 작성
```

---

## 1.4 Toss OpenAPI 우선 provider 정책

`theStock` 운영 환경에서는 Toss OpenAPI가 제공하는 데이터를 1순위 provider로 사용한다.

Toss 우선 사용 대상:

```text
1. 국내/미국 주식 현재가와 시세
2. 호가, 최근 체결, 가격 제한, 캔들
3. 종목 마스터와 종목 경고/주의 정보
4. USD/KRW 등 환율
5. 국내/미국 시장 캘린더
6. 계좌 목록과 보유주식
7. 주문 가능 금액, 매도 가능 수량, 수수료
8. 주문 목록과 주문 상세 조회
```

Toss가 제공하지 않거나 제공 범위가 부족한 데이터는 fallback provider를 사용한다.

```text
1. 재무제표와 공시 상세: OPENDART 우선
2. 뉴스/리스크 이벤트: 기존 news/risk provider 또는 수동 입력
3. 투자자별 수급: Toss 제공 여부 확인 전까지 pykrx 등 보조 provider
4. local/test 데이터: MockDataProvider
```

provider 우선순위는 설정값으로 제어한다.

```env
THESTOCK_PROVIDER_PRIORITY=toss,pykrx,opendart,manual,mock
THESTOCK_DATA_PROVIDER=toss
```

컨설팅 엔진은 provider 종류를 몰라도 되도록 기존 도메인 모델과 service interface를 유지한다.

---

# 2. Provider 구조

## 2.1 기존 구조와의 관계

Toss provider는 기존 DataProvider 추상화의 구현체로 추가한다.

```text
DataProvider
 ├─ MockDataProvider
 ├─ PykrxDataProvider
 ├─ OpenDartDataProvider
 └─ TossOpenApiProvider
```

기존 MockDataProvider를 제거하지 않는다.  
local/test에서는 MockDataProvider를 계속 사용할 수 있어야 한다.

## 2.2 provider 선택 정책

환경변수로 기본 provider와 fallback 우선순위를 선택한다.

```env
THESTOCK_DATA_PROVIDER=mock
THESTOCK_DATA_PROVIDER=toss
THESTOCK_PROVIDER_PRIORITY=toss,pykrx,opendart,manual,mock
```

운영 권장:

```env
THESTOCK_DATA_PROVIDER=toss
```

단, Toss 장애 시 fallback을 위해 provider registry 구조를 유지한다.

provider registry는 다음 규칙을 따른다.

```text
1. 요청 데이터 타입을 Toss가 지원하면 Toss를 먼저 호출한다.
2. Toss가 401/403을 반환하면 token 재발급을 1회 시도한다.
3. Toss가 429/5xx/network error를 반환하면 backoff 후 재시도한다.
4. 재시도 후에도 실패하면 DataIngestionLog에 실패를 남기고 fallback provider를 호출한다.
5. fallback으로 저장한 데이터는 source 필드 또는 ingestion log에 provider를 남긴다.
6. fallback도 실패하면 기존 정상 데이터를 유지하고 data quality warning을 만든다.
```

---

## 2.3 주문 API 비활성 정책

Toss OpenAPI는 주문 생성/정정/취소 API를 제공하지만, `theStock`에서는 별도 승인 전까지 실거래 주문 실행을 비활성화한다.

운영 기본값:

```env
TOSS_ORDER_EXECUTION_ENABLED=false
```

허용:

```text
1. 주문 목록 조회
2. 주문 상세 조회
3. 매수 가능 금액 조회
4. 매도 가능 수량 조회
5. 수수료 조회
```

금지:

```text
1. 사용자 동의 없는 주문 생성
2. 자동 주문 생성
3. 자동 주문 정정
4. 자동 주문 취소
5. 컨설팅 결과를 곧바로 주문 API에 연결
```

---

# 3. 인증 흐름

## 3.1 access token 발급

Toss OpenAPI 인증은 다음 흐름을 따른다.

```text
1. client_id/client_secret을 .env에서 읽는다.
2. token endpoint에 인증 요청을 보낸다.
3. access token과 만료 시간을 받는다.
4. token cache에 저장한다.
5. API 호출 시 Authorization header에 token을 사용한다.
```

## 3.2 token cache

권장 구현:

```text
1. local memory cache
2. Django cache
3. DB 저장은 지양
```

DB에 token을 저장해야 하는 경우 암호화가 필요하다.  
단순 평문 저장은 금지한다.

## 3.3 token 재발급

다음 경우 token을 재발급한다.

```text
1. token이 없을 때
2. 만료 시간이 임박했을 때
3. API 응답이 401/403 인증 오류일 때
```

만료 5분 전 재발급을 권장한다.

---

# 4. 내부 모델 매핑

## 4.1 Stock

목적:

```text
종목 마스터 정보 저장
```

매핑 후보:

| 내부 필드 | Toss 데이터 | 비고 |
|---|---|---|
| code | 종목코드 | KRX 코드 기준 |
| name | 종목명 | 한글명 |
| market | 시장구분 | KOSPI/KOSDAQ 등 |
| sector | 업종 | 제공 시 저장 |
| is_active | 거래 가능 여부 | 상장폐지/거래정지 고려 |

## 4.2 DailyPrice

목적:

```text
일봉 가격 데이터 저장
```

매핑 후보:

| 내부 필드 | Toss 데이터 | 비고 |
|---|---|---|
| stock | 종목코드 | Stock FK |
| date | 거래일 | 휴장일 제외 |
| open_price | 시가 | 숫자 정규화 |
| high_price | 고가 | 숫자 정규화 |
| low_price | 저가 | 숫자 정규화 |
| close_price | 종가 | 수정주가 기준 확인 필요 |
| volume | 거래량 | 정수 |
| trading_value | 거래대금 | 제공 시 |

중요:

```text
Toss 데이터가 수정주가인지 비수정주가인지 반드시 확인한다.
```

## 4.3 InvestorFlow

목적:

```text
투자자별 매매 동향 저장
```

매핑 후보:

| 내부 필드 | Toss 데이터 | 비고 |
|---|---|---|
| stock | 종목코드 | Stock FK |
| date | 거래일 | 일자 |
| individual_net_buy | 개인 순매수 | 단위 확인 |
| foreign_net_buy | 외국인 순매수 | 단위 확인 |
| institution_net_buy | 기관 순매수 | 단위 확인 |
| program_net_buy | 프로그램 순매수 | 제공 시 |

## 4.4 MarketIndex

목적:

```text
KOSPI/KOSDAQ/섹터/시장 지수 저장
```

매핑 후보:

| 내부 필드 | Toss 데이터 | 비고 |
|---|---|---|
| index_code | 지수 코드 | KOSPI/KOSDAQ |
| date | 거래일 | 일자 |
| close_value | 종가 | 지수값 |
| change_rate | 등락률 | 제공 시 |
| volume | 거래량 | 제공 시 |

## 4.5 TechnicalIndicator

목적:

```text
이동평균, RSI, MACD, 변동성 등 기술 지표 저장
```

Toss가 직접 제공하지 않는 경우 내부 계산한다.

입력:

```text
DailyPrice
```

산출:

```text
MA5
MA20
MA60
MA120
RSI14
MACD
volatility20
drawdown
support/resistance 후보
```

## 4.6 RiskEvent

목적:

```text
거래정지, 관리종목, 투자주의/경고/위험, 상장폐지 위험 등 저장
```

Toss API만으로 부족할 수 있다.  
KRX, DART, 수동 입력 provider와 병행할 수 있다.

## 4.7 FinancialSnapshot

목적:

```text
재무 상태 요약 저장
```

Toss에서 재무 데이터를 제공하지 않거나 부족하면 OPENDART provider와 병행한다.

---

# 5. 데이터 수집 작업 단위

## 5.1 종목 마스터 수집

Command 예:

```bash
python manage.py ingest_market_data --provider=toss --job=stock-master
```

주기:

```text
1일 1회 또는 주 1회
```

## 5.2 가격 데이터 수집

Command 예:

```bash
python manage.py ingest_market_data --provider=toss --job=daily-price --date=YYYY-MM-DD
```

주기:

```text
장마감 이후 1회
```

주의:

```text
장마감 직후 데이터가 지연될 수 있으므로 1차/2차 수집 전략을 둔다.
```

## 5.3 수급 데이터 수집

Command 예:

```bash
python manage.py ingest_market_data --provider=toss --job=investor-flow --date=YYYY-MM-DD
```

주기:

```text
장마감 이후 1회
```

## 5.4 기술 지표 계산

Command 예:

```bash
python manage.py compute_technical_indicators --date=YYYY-MM-DD
```

주기:

```text
DailyPrice 수집 후 실행
```

## 5.5 품질 리포트 생성

Command 예:

```bash
python manage.py build_data_quality_report --date=YYYY-MM-DD
```

주기:

```text
모든 수집/계산 완료 후 실행
```

---

# 6. 장애 대응 정책

## 6.1 API 호출 실패

실패 유형:

```text
1. network timeout
2. DNS failure
3. TLS error
4. 401/403 authentication error
5. 429 rate limit
6. 5xx provider error
7. malformed response
8. partial data response
```

대응:

```text
1. DataIngestionLog에 실패 기록
2. DataProviderStatus 갱신
3. 기존 정상 데이터는 삭제하지 않음
4. retry 가능한 오류는 backoff 후 재시도
5. 인증 오류는 token 1회 재발급 후 재시도
6. 계속 실패하면 provider DOWN 상태로 표시
```

## 6.2 기존 데이터 보존

수집 실패 시 기존 데이터를 지우지 않는다.

금지:

```text
1. 실패한 날짜의 기존 DailyPrice 전체 삭제
2. partial response로 정상 데이터를 덮어쓰기
3. 데이터 품질 확인 전 active 데이터로 반영
```

권장:

```text
1. staging table에 먼저 저장
2. validation 통과 후 upsert
3. 실패 시 staging 폐기
```

## 6.3 retry 정책

권장 기본값:

```text
max_retries=3
initial_delay_seconds=2
backoff_multiplier=2
timeout_seconds=10
```

429 rate limit은 더 긴 대기 시간을 사용한다.

---

# 7. Rate Limit 정책

Toss API의 호출 제한을 초과하지 않도록 다음을 적용한다.

```text
1. provider별 rate limiter
2. endpoint별 호출 간격
3. bulk 요청 가능 시 bulk 사용
4. 종목별 순차 호출 시 sleep/backoff
5. 장중 과도한 반복 수집 금지
```

환경변수 예:

```env
TOSS_RATE_LIMIT_PER_MINUTE=60
TOSS_REQUEST_TIMEOUT_SECONDS=10
TOSS_MAX_RETRIES=3
```

---

# 8. DataIngestionLog 기록

각 수집 작업마다 다음을 기록한다.

```text
provider
job_type
started_at
finished_at
status
requested_date
requested_symbol_count
success_count
failure_count
created_count
updated_count
skipped_count
error_code
error_message_masked
data_quality_summary
```

민감 정보는 기록하지 않는다.

금지:

```text
1. Authorization header
2. access token
3. client_secret
4. raw response 전체
```

---

# 9. DataProviderStatus

provider 상태를 별도 관리한다.

상태값:

```text
UP
DEGRADED
DOWN
AUTH_FAILED
RATE_LIMITED
DISABLED
```

갱신 기준:

```text
1. 최근 성공 시각
2. 최근 실패 시각
3. 연속 실패 횟수
4. 마지막 오류 유형
5. 평균 응답 시간
```

서비스 화면이나 admin에서 provider 상태를 확인할 수 있어야 한다.

---

# 10. 데이터 품질 검증

Toss provider로 수집한 데이터는 저장 전후로 품질 검증을 거친다.

검증 항목:

```text
1. 필수 필드 누락 여부
2. 가격이 음수인지 여부
3. high >= low 관계
4. high >= close >= low 범위
5. 거래량 음수 여부
6. 전일 대비 비정상 급등락
7. 휴장일 데이터 존재 여부
8. 중복 데이터 여부
9. 종목코드 유효성
10. 수정주가 기준 일관성
```

품질 등급:

```text
A: 정상
B: 경미한 누락 또는 지연
C: 일부 지표 신뢰 제한
D: 컨설팅 사용 주의
F: 컨설팅 금지 또는 강한 경고
```

---

# 11. 운영 스케줄 예시

한국 주식시장 기준 예시다.

```text
16:10 종목별 일봉 1차 수집
16:30 수급 데이터 수집
16:45 기술 지표 계산
17:00 데이터 품질 리포트 생성
17:10 provider 상태 점검
18:30 일봉/수급 2차 보정 수집
19:00 최종 품질 리포트 갱신
```

휴장일에는 수집하지 않거나 휴장일 로그만 남긴다.

---

# 12. API 응답과 컨설팅 연동

컨설팅 엔진은 데이터 품질을 반드시 확인해야 한다.

예:

```text
1. DailyPrice 품질 F → 컨설팅 금지 또는 강한 경고
2. InvestorFlow 누락 → 수급 점수 confidence 낮춤
3. FinancialSnapshot 오래됨 → 펀더멘털 점수 confidence 낮춤
4. RiskEvent provider DOWN → 리스크 판단 보수화
```

컨설팅 응답에는 데이터 기준 시각을 포함한다.

```json
{
  "data_basis": {
    "price_date": "2026-06-15",
    "provider": "toss",
    "data_quality_grade": "B",
    "warnings": ["수급 데이터가 일부 지연되었습니다."]
  }
}
```

---

# 13. 테스트 전략

## 13.0 1차 Smoke 구현 현황

2026-06 기준 1차 smoke 범위는 운영 데이터 파이프라인 자동 편입이 아니라, 인증/요청/설정 점검을 안전하게 검증하는 최소 구현이다.

구현 완료 파일:

```text
data_pipeline/providers/toss_exceptions.py
data_pipeline/providers/toss_masking.py
data_pipeline/providers/toss_order_guard.py
data_pipeline/providers/toss_auth.py
data_pipeline/providers/toss_client.py
data_pipeline/providers/toss_provider.py
```

구현 완료 command:

```bash
python manage.py check_toss_provider
python manage.py toss_token_smoke --no-network
python manage.py toss_quote_smoke --symbol=005930 --market=KR --no-network
```

실제 네트워크 호출 가능 command:

```bash
python manage.py toss_token_smoke
python manage.py toss_quote_smoke --symbol=005930 --market=KR
```

실제 네트워크 호출은 운영자가 `TOSS_INVEST_PROVIDER_ENABLED`, `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET` 등 운영 환경변수를 설정하고 명시적으로 실행할 때만 수행한다.

현재 구현 범위:

```text
1. Toss auth skeleton 구현 완료
2. Toss client skeleton 구현 완료
3. Toss provider skeleton 구현 완료
4. check_toss_provider command 구현 완료
5. toss_token_smoke command 구현 완료
6. toss_quote_smoke command 구현 완료
7. smoke command Python logging 적용 완료
8. DataIngestionLog 기록은 보류
9. provider registry 등록은 보류
10. 실제 데이터 파이프라인 자동 편입은 보류
11. DailyPrice 저장은 보류
12. holdings sync는 보류
13. 주문 API는 미구현 및 비활성
```

공식 문서 기준 endpoint mapping:

| 구분 | 기준 |
|---|---|
| Base API server | `https://openapi.tossinvest.com` |
| Token | `POST /oauth2/token` |
| Token content type | `application/x-www-form-urlencoded` |
| Token grant_type | `client_credentials` |
| Token Authorization header | 사용하지 않음 |
| Access token 사용 | 이후 API에서 Authorization Bearer header로 사용 |
| Refresh token | 제공되지 않음. 만료 시 token endpoint로 재발급 |
| Current price | `GET /api/v1/prices` |
| Current price query parameter | `symbols` |

현재가 API는 Market Data API이며 계좌 header 없이 access token으로 호출할 수 있다. 계좌, 자산, 주문 관련 API는 access token 외에 `X-Tossinvest-Account` header가 필요하다.

`toss_quote_smoke`는 단일 symbol만 허용한다. 공식 API는 `symbols` 콤마 구분 다건 조회를 지원하지만, 1차 smoke command는 안전한 최소 범위로 단일 symbol만 처리한다.

1차 smoke 보안 기준:

```text
1. access token 원문 출력 금지
2. client_secret 원문 출력 금지
3. account id 원문 출력 금지
4. Authorization header 출력 금지
5. request body/header 로그 금지
6. token은 stdout에서만 mask_secret으로 마스킹 출력 가능
7. client_secret은 configured/missing으로만 표시
8. account id는 mask_account_id로만 표시
9. TOSS_ORDER_EXECUTION_ENABLED=false 기본값 유지
```

현재 한계:

```text
1. TossOpenApiProvider는 아직 registry에 등록되지 않았다.
2. BaseDataProvider 호환 skeleton은 있으나 실제 get_*_rows 연동은 미구현이다.
3. get_quote는 아직 provider method로 직접 조회를 수행하지 않는다.
4. quote smoke command는 command 단위 smoke이며 DB 저장하지 않는다.
5. DataIngestionLog는 schema/choices 보강 전까지 보류한다.
6. 실제 운영 데이터 수집 scheduler 연동은 미구현이다.
7. holdings sync는 미구현이다.
8. 주문 생성/정정/취소는 미구현이다.
```

참고 공식 문서:

```text
https://developers.tossinvest.com/docs
https://developers.tossinvest.com/llms.txt
https://openapi.tossinvest.com/openapi-docs/latest/openapi.json
```

## 13.1 unit test

```text
1. token 발급 성공
2. token 만료 전 재사용
3. token 만료 후 재발급
4. 401 후 1회 재발급
5. 429 retry/backoff
6. malformed response 처리
7. 내부 모델 매핑
8. 로그 마스킹
```

## 13.2 integration test

```text
1. Toss sandbox 또는 mock server 연동
2. 종목 마스터 수집
3. 가격 데이터 수집
4. 수급 데이터 수집
5. 기술 지표 계산
6. 품질 리포트 생성
```

## 13.3 production smoke test

```text
1. python manage.py check_toss_provider 실행
2. python manage.py toss_token_smoke --no-network 실행
3. python manage.py toss_quote_smoke --symbol=005930 --market=KR --no-network 실행
4. 운영 환경변수 설정 후 운영자가 명시적으로 toss_token_smoke 실행
5. 운영 환경변수 설정 후 운영자가 명시적으로 toss_quote_smoke 실행
6. API key, client_secret, access token, account id 로그 노출 없음 확인
```

1차 smoke 단계에서는 DataIngestionLog 생성 확인을 요구하지 않는다. 현재 smoke 결과는 Python logging으로만 남긴다.

---

# 14. 구현 체크리스트

```text
[x] TossOpenApiProvider skeleton 추가
[x] 환경변수 로딩 추가
[x] auth skeleton 추가
[x] 인증 정보 로그 마스킹 추가
[x] check_toss_provider command 추가
[x] toss_token_smoke command 추가
[x] toss_quote_smoke command 추가
[x] smoke command logging 추가
[ ] stock master 매핑 구현
[ ] daily price 매핑 구현
[ ] investor flow 매핑 구현
[ ] provider status 모델 또는 관리 구조 연결
[ ] DataIngestionLog 기록 연결
[ ] retry/backoff 구현
[ ] rate limit 구현
[ ] data quality validation 연결
[ ] management command에 --provider=toss 옵션 추가
[x] production .env.example 업데이트
[x] 테스트 작성
[x] 운영 smoke 문서 업데이트
```

DataIngestionLog 기록 연결은 `target_type`과 `status` choices가 smoke/auth/health 결과를 자연스럽게 표현할 수 있도록 보강한 뒤 진행한다.

---

# 15. Codex 작업 지시 요약

```text
Toss OpenAPI를 theStock의 DataProvider 구조에 추가한다.
기존 MockDataProvider와 기존 API 응답 구조는 깨지지 않아야 한다.
API key, client secret, token은 코드/문서/test fixture에 절대 저장하지 않는다.
모든 인증값은 환경변수에서 읽고 로그에서는 마스킹한다.
수집 실패 시 기존 정상 데이터를 삭제하지 않는다.
DataIngestionLog, DataProviderStatus, DataQualityReport와 연결한다.
429/5xx/timeout에 대한 retry/backoff를 구현한다.
운영에서 사용할 수 있는 management command와 smoke test를 제공한다.
```

---

# 16. 결론

Toss OpenAPI provider는 단순 API 호출 기능이 아니다.

운영 서비스 관점에서는 다음이 함께 구현되어야 한다.

```text
1. 안전한 인증 정보 관리
2. 내부 모델 매핑
3. 장애 격리
4. 수집 로그
5. 데이터 품질 검증
6. rate limit 대응
7. 운영 스케줄
8. 컨설팅 엔진과 품질 등급 연동
```

이 원칙을 지켜야 `theStock`의 컨설팅 결과가 안정적인 실제 시장 데이터 위에서 동작할 수 있다.
