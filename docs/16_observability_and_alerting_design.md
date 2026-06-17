# 16_observability_and_alerting_design.md

# theStock 관측성 및 알림 설계서

---

# 0. 문서 목적

`theStock`는 주식 데이터 수집, 확률 계산, 컨설팅 결과 제공, 사용자 보유 정보 관리를 수행한다.

이런 서비스에서 장애는 단순히 페이지가 안 뜨는 문제만이 아니다.

```text
1. 데이터 수집이 조용히 실패한다.
2. Toss provider 인증이 실패한다.
3. 데이터 품질이 낮아졌는데 컨설팅이 계속 제공된다.
4. 특정 API가 느려진다.
5. 사용자별 owner scope가 깨진다.
6. API key가 로그에 노출된다.
```

따라서 `theStock`에는 관측성(observability)과 알림(alerting) 설계가 필요하다.

---

# 1. 관측성 목표

```text
1. 서비스가 살아 있는지 확인한다.
2. DB와 provider 의존성이 정상인지 확인한다.
3. API 오류율과 응답 시간을 확인한다.
4. 데이터 파이프라인 성공/실패를 추적한다.
5. 데이터 품질 저하를 감지한다.
6. 보안 이벤트를 감지한다.
7. 장애 발생 시 원인을 추적할 수 있는 로그를 남긴다.
```

---

# 2. Health Check

## 2.1 healthz

목적:

```text
Django process가 살아 있는지 확인
```

확인 범위:

```text
1. app process alive
2. settings 로딩 가능
3. 기본 response 가능
```

DB 같은 외부 의존성은 포함하지 않아도 된다.

## 2.2 readyz

목적:

```text
서비스가 실제 요청을 처리할 준비가 되었는지 확인
```

확인 범위:

```text
1. DB 연결
2. migration 상태
3. cache 연결 선택
4. 필수 환경변수 존재
5. provider 필수 설정 존재
```

## 2.3 provider health

```http
GET /api/data-pipeline/provider-status/
```

응답 예:

```json
{
  "providers": [
    {
      "name": "toss",
      "status": "UP",
      "last_success_at": "2026-06-16T17:10:00+09:00",
      "consecutive_failures": 0
    }
  ]
}
```

---

# 3. Structured Logging

## 3.1 로그 형식

가능하면 JSON log를 사용한다.

필드 예:

```json
{
  "timestamp": "2026-06-16T12:00:00+09:00",
  "level": "INFO",
  "service": "thestock",
  "environment": "production",
  "event": "consult.request.completed",
  "request_id": "req_abc123",
  "user_id_hash": "u_***",
  "status_code": 200,
  "duration_ms": 321
}
```

## 3.2 request_id

모든 요청에 request_id를 부여한다.

```text
1. 외부 요청 header X-Request-ID가 있으면 사용
2. 없으면 서버에서 생성
3. 응답 header에 포함
4. 모든 로그에 포함
```

## 3.3 민감 정보 마스킹

로그 금지 항목:

```text
1. API key
2. client secret
3. access token
4. 평균 단가 원문
5. 보유 수량 원문
6. 투자금 원문
7. Authorization header
8. Cookie header
```

---

# 4. 주요 이벤트 로그

## 4.1 인증 이벤트

```text
user.login.success
user.login.failure
user.logout
user.staff_granted
user.staff_revoked
sso.callback.failed
```

## 4.2 컨설팅 이벤트

```text
consult.request.started
consult.request.completed
consult.request.failed
consult.blocked.data_quality
consult.blocked.risk_event
consult.blocked.permission
```

## 4.3 데이터 파이프라인 이벤트

```text
ingestion.job.started
ingestion.job.completed
ingestion.job.failed
provider.fallback.used
provider.auth.failed
provider.rate_limited
provider.schema_changed
provider.order_execution.blocked
data_quality.grade_changed
technical_indicator.compute.failed
toss_smoke_result
```

## 4.3.1 Toss smoke logging

다음 management command는 Python logging으로 smoke 실행 결과를 남긴다.

```text
check_toss_provider
toss_token_smoke
toss_quote_smoke
```

로그 메시지는 `toss_smoke_result` 기반이며 다음 정보를 포함할 수 있다.

```text
1. command
2. provider=toss
3. status
4. reason
5. symbol
6. market
7. endpoint
8. network_call
9. dry_run
10. commit 상태
11. order_execution_enabled 상태
```

로그 예시는 민감정보 없이 key=value 형식으로 남긴다.

```text
toss_smoke_result command=toss_quote_smoke status=skipped provider=toss reason=no-network symbol=005930 market=KR endpoint=/api/v1/prices network_call=false dry_run=true
```

민감정보 로그 금지 항목:

```text
1. client_secret 원문
2. access_token 원문
3. account id 원문
4. Authorization header
5. X-Tossinvest-Account header
6. request body
7. request headers
8. raw API response 전체
```

`toss_token_smoke` 성공 시에도 access token 원문은 로그에 남기지 않는다. stdout에는 마스킹된 token만 표시할 수 있다.

## 4.3.2 DataIngestionLog 보류

현재 smoke command 결과는 Python logging으로만 남긴다.  
DataIngestionLog 기록은 보류했다.

보류 사유:

```text
1. target_type choices가 health/auth/smoke를 자연스럽게 표현하지 못한다.
2. status choices에 skipped가 없다.
3. migration 없이 억지 매핑하면 운영 데이터 의미가 흐려질 수 있다.
4. smoke command는 아직 실제 수집 job이 아니며 DB 저장도 수행하지 않는다.
```

추후 DataIngestionLog 확장 시 고려할 필드:

```text
job_type
provider_name
status success/failed/skipped
target_symbol
endpoint_name
network_call
dry_run
duration_ms
error_code
safe_reason
metadata JSONField
```

## 4.4 보안 이벤트

```text
security.permission.denied
security.owner_scope.violation_attempt
security.admin.access
security.secret.masking.detected
security.suspicious_bulk_access
```

---

# 5. Metrics

## 5.1 API metrics

```text
http_requests_total
http_request_duration_seconds
http_5xx_total
http_4xx_total
consult_requests_total
consult_failures_total
probability_requests_total
```

## 5.2 데이터 파이프라인 metrics

```text
ingestion_jobs_total
ingestion_failures_total
ingestion_duration_seconds
provider_consecutive_failures
provider_last_success_age_seconds
provider_fallback_used_total
provider_auth_failures_total
provider_rate_limited_total
data_quality_grade_count
technical_indicator_compute_duration_seconds
```

## 5.3 비즈니스 안전 metrics

```text
consult_blocked_by_data_quality_total
consult_blocked_by_risk_event_total
high_risk_consult_results_total
false_safe_backtest_rate
probability_calibration_error
```

## 5.4 시스템 metrics

```text
cpu_usage
memory_usage
disk_usage
db_connection_count
db_query_duration
```

---

# 6. 알림 기준

## 6.1 P0 알림

즉시 확인이 필요한 알림이다.

```text
1. 사이트 healthz 실패 3회 연속
2. readyz 실패 3회 연속
3. consult API 500 오류율 5분간 5% 초과
4. DB 연결 실패
5. API key/secret 로그 노출 의심
6. owner scope 위반 의심
7. provider 인증 실패 지속
8. 운영에서 주문 생성/정정/취소 API 호출 시도 감지
9. TOSS_ORDER_EXECUTION_ENABLED=true 감지
```

## 6.2 P1 알림

운영자가 빠르게 확인해야 한다.

```text
1. data ingestion job 실패
2. provider status DOWN
3. 데이터 품질 F 종목 급증
4. Toss rate limit 반복
5. slow API 증가
6. DB backup 실패
7. disk usage 85% 초과
8. Toss-first 대상 데이터가 fallback provider로 반복 수집됨
9. toss_token_smoke failed
10. toss_quote_smoke failed
11. authentication failed 반복
12. rate limit exceeded 반복
13. provider enabled인데 credentials missing
14. logs에 secret/token/account 원문 패턴 감지
```

TOSS_ORDER_EXECUTION_ENABLED=true는 주문 API 구현 전까지 경고 대상이다. 현재 주문 실행 API는 구현되어 있지 않아야 한다.

## 6.3 P2 알림

정기 점검 수준이다.

```text
1. 데이터 품질 C 이하 비율 증가
2. 특정 종목 데이터 누락
3. 백테스트 calibration 악화
4. warning log 증가
5. provider 응답 시간 증가
```

---

# 7. 알림 채널

초기 권장:

```text
1. 이메일
2. Telegram/Slack/Discord 중 하나
3. 관리자 화면 알림 배너
```

운영자 개인 메신저에 직접 붙이기보다, 서비스별 운영 채널을 만드는 것이 좋다.

알림 메시지 예:

```text
[theStock][P1] Data ingestion failed
provider=toss
job=daily-price
date=2026-06-16
error=RATE_LIMITED
last_success_at=2026-06-15 17:02 KST
runbook=docs/15_operations_runbook.md#데이터-파이프라인-장애-대응
```

---

# 8. Dashboard

운영 dashboard에는 다음이 필요하다.

```text
1. 서비스 상태
2. provider 상태
3. 최근 ingestion job 목록
4. 데이터 품질 등급 분포
5. 최근 500 오류
6. consult API 요청 수
7. 평균 응답 시간
8. 느린 API 목록
9. 최근 보안 이벤트
10. DB backup 상태
```

초기에는 Django admin 또는 staff 전용 dashboard로 시작할 수 있다.

---

# 9. Slow Query / Slow API

## 9.1 slow API 기준

권장:

```text
consult API > 2초
probability API > 2초
portfolio summary > 1초
data pipeline summary > 1초
```

## 9.2 대응

```text
1. query count 확인
2. select_related/prefetch_related 확인
3. index 추가 검토
4. cache 적용 검토
5. 비동기 계산 검토
```

---

# 10. 데이터 품질 알림

## 10.1 grade 변화 알림

종목 데이터 품질이 급격히 악화되면 알림을 보낸다.

예:

```text
A -> F
B -> D
```

## 10.2 시장 전체 이상 알림

```text
전체 종목의 30% 이상이 데이터 품질 D/F
```

이 경우 provider 장애 또는 정규화 오류일 가능성이 높다.

## 10.3 Toss-first fallback 알림

Toss OpenAPI가 제공하는 데이터가 fallback provider로 반복 수집되면 알림을 보낸다.

예:

```text
provider.fallback.used_total{primary="toss", fallback="pykrx", data_type="daily_price"} > 3
provider.auth_failures_total{provider="toss"} > 0
provider.rate_limited_total{provider="toss"} 증가
```

fallback 사용은 장애 대응으로 허용하지만, 운영 기준이 Toss-first에서 벗어난 상태이므로 원인을 확인한다.

---

# 11. 보안 관측성

다음 패턴은 보안 이벤트로 기록한다.

```text
1. 동일 IP에서 로그인 실패 반복
2. 일반 사용자의 다른 사용자 holding 접근 시도
3. staff가 짧은 시간에 많은 사용자 데이터 조회
4. Authorization header가 error log에 찍힘
5. API key 패턴이 로그에서 감지됨
```

API key 패턴 감지는 정규식 기반으로 시작할 수 있다.

---

# 12. 보관 기간

권장:

| 로그 유형 | 보관 기간 |
|---|---:|
| application log | 30~90일 |
| access log | 30~90일 |
| security audit log | 1년 이상 검토 |
| data ingestion log | 1년 이상 권장 |
| consulting result log | 개인정보 정책에 따름 |

금융정보와 연결되는 로그는 개인정보/금융정보 보호 정책과 맞춰야 한다.

---

# 13. 구현 체크리스트

```text
[ ] request_id middleware 추가
[ ] JSON structured logging 설정
[ ] 민감 정보 마스킹 filter 추가
[ ] healthz/readyz 점검 강화
[ ] provider status endpoint 정리
[ ] ingestion metrics 기록
[ ] consult API duration logging
[ ] data quality grade change logging
[ ] P0/P1/P2 alert 기준 구현
[ ] 알림 채널 설정
[ ] staff 운영 dashboard 추가
[ ] secret 노출 감지 스크립트 추가
[ ] DB backup 성공/실패 알림 추가
```

---

# 14. Codex 작업 지시 요약

```text
theStock에 운영 관측성과 알림 체계를 추가한다.
모든 요청에 request_id를 부여하고 JSON structured logging을 적용한다.
API key, token, 사용자 투자 정보는 로그에서 마스킹한다.
healthz/readyz/provider-status를 분리하고, consult API 오류율, 데이터 수집 실패, provider 인증 실패, 데이터 품질 F 급증, DB backup 실패를 알림 대상으로 만든다.
기존 기능과 API 응답 구조는 깨지지 않도록 운영 보강 레이어로 추가한다.
```

---

# 15. 결론

관측성은 운영 후에 붙이는 부가 기능이 아니다.  
`theStock`처럼 데이터와 판단 결과가 중요한 서비스에서는 핵심 안정성 기능이다.

가장 먼저 감지해야 할 것은 다음이다.

```text
1. 서비스 다운
2. consult API 장애
3. provider 인증 실패
4. 데이터 수집 실패
5. 데이터 품질 급락
6. 사용자 데이터 접근 이상
7. secret 로그 노출
```

이 설계에 따라 운영자가 문제를 빠르게 발견하고, Runbook에 따라 안전하게 대응할 수 있어야 한다.
