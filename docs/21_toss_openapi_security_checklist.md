# 21_toss_openapi_security_checklist.md

# Toss OpenAPI Security Checklist

---

# 0. 문서 목적

이 문서는 `theStock`에서 Toss OpenAPI를 사용할 때 지켜야 할 보안 점검표다.

실제 API Key, Secret Key, Access Token, 계좌번호, `accountSeq` 원문은 이 문서와 Git에 저장하지 않는다.

---

# 1. Secret 관리

```text
[ ] Toss Client ID 실제 값을 Git에 저장하지 않는다.
[ ] Toss Client Secret 실제 값을 Git에 저장하지 않는다.
[ ] Access Token을 Git, 문서, fixture에 저장하지 않는다.
[ ] Refresh Token 또는 token에 준하는 값을 Git, 문서, fixture에 저장하지 않는다.
[ ] 계좌번호 또는 accountSeq 원문을 Git, 문서, fixture에 저장하지 않는다.
[ ] .env.example에는 변수명만 남긴다.
[ ] 운영 값은 운영 서버 .env 또는 secret manager에서만 관리한다.
[ ] CI/CD에는 secret store를 사용한다.
[ ] secret rotation 절차를 운영 Runbook에 연결한다.
```

기존 전역 `.env` Toss credential은 staff-only 운영 점검 또는 transition 용도에 한해 제한적으로 유지할 수 있다. 일반 사용자 기능에서는 전역 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT_ID`를 공유 credential로 사용하지 않는다.

허용되는 예:

```env
TOSS_INVEST_CLIENT_ID=
TOSS_INVEST_CLIENT_SECRET=
TOSS_INVEST_BASE_URL=
TOSS_INVEST_TOKEN_URL=
TOSS_ORDER_EXECUTION_ENABLED=false
```

사용자별 credential 구조 추가 체크:

```text
[ ] 사용자별 Toss client_id/client_secret은 평문 DB 저장 금지.
[ ] encrypted field ciphertext 저장을 확인한다.
[ ] SQL query로 client_id/client_secret/token 평문이 조회되지 않는지 확인한다.
[ ] CREDENTIAL_ENCRYPTION_KEY는 DB에 저장하지 않는다.
[ ] CREDENTIAL_HASH_PEPPER는 DB에 저장하지 않는다.
[ ] SQLCIPHER_DATABASE_KEY는 SQLite DB file encryption 용도이며 credential column encryption 대체재가 아니다.
[ ] SQLCipher만으로 credential 보안 충분하다고 판단하지 않는다.
[ ] Django admin에서 secret 평문 표시 금지.
[ ] credential reveal은 본인 재인증과 audit log가 필요하다.
[ ] AG Grid/D3/LLM 화면/API에 민감정보 원문 전달 금지.
```

## 1.1 Phase 1 security foundation 조사 반영

상세 조사 보고서는 `docs/55_security_foundation_research_report.md`를 기준으로 한다.

요약:

```text
[ ] 1차 encrypted credential 저장은 cryptography.Fernet/MultiFernet 기반 service-layer encryption을 우선한다.
[ ] 일반 TextField에는 ciphertext만 저장하고 decrypt는 service 함수에서만 수행한다.
[ ] SQLCipher는 SQLite DB 파일 보호 계층이며 credential column encryption 대체재가 아니다.
[ ] SQLCipher는 1차 credential 구현 blocker가 아니라 별도 hardening phase에서 검증한다.
[ ] staff/admin/superuser는 사용자 secret/token 평문 reveal 금지.
[ ] access_token/refresh_token은 사용자 본인에게도 화면 reveal 금지.
[ ] 복호화 실패, key mismatch, 손망실, 분실 문의는 reset_required + 초기화 후 사용자 재등록으로 처리한다.
```

---

# 2. 로그 마스킹

로그 금지:

```text
[ ] Authorization header 원문
[ ] X-Tossinvest-Account header 원문
[ ] client_secret 원문
[ ] access_token 원문
[ ] accountSeq 원문
[ ] 계좌번호 원문
[ ] 보유 수량 원문
[ ] 평균 단가 원문
[ ] 총 투자금 원문
```

권장 마스킹:

```text
client_id=tos_****1234
access_token=***masked***
Authorization=Bearer ***masked***
X-Tossinvest-Account=***masked***
accountSeq=acct_****1234
```

---

# 3. 인증/토큰 처리

```text
[ ] OAuth2 Client Credentials Grant로 access token을 발급한다.
[ ] token endpoint 호출 실패를 DataIngestionLog 또는 운영 로그에 기록한다.
[ ] token은 local memory cache 또는 Django cache에 저장한다.
[ ] token DB 평문 저장은 금지한다.
[ ] 만료 5분 전 재발급을 권장한다.
[ ] 401/403 응답 시 token 재발급을 1회만 시도한다.
[ ] 반복 인증 실패는 provider status를 AUTH_FAILED로 전환한다.
```

---

# 4. 계좌/자산 API 보호

```text
[ ] 계좌 API 호출은 사용자 명시 동의 이후에만 수행한다.
[ ] `X-Tossinvest-Account` 헤더 값은 사용자 금융정보에 준해 보호한다.
[ ] 계좌 목록은 본인 계정 scope 안에서만 조회한다.
[ ] 보유주식 동기화 결과는 UserHolding owner scope를 적용한다.
[ ] staff 화면에서는 계좌/보유 민감 필드를 기본 마스킹한다.
[ ] 계좌 연동 해제 시 token/cache/account mapping 제거 절차를 둔다.
[ ] consult/probability/portfolio API에는 `Cache-Control: no-store`를 적용한다.
```

---

# 5. 주문 API 차단

운영 기본값:

```env
TOSS_ORDER_EXECUTION_ENABLED=false
```

점검:

```text
[ ] 주문 생성 API는 기본 비활성화한다.
[ ] 주문 정정 API는 기본 비활성화한다.
[ ] 주문 취소 API는 기본 비활성화한다.
[ ] 컨설팅 결과를 주문 API에 자동 연결하지 않는다.
[ ] 주문 실행 활성화는 별도 승인, 사용자 확인 UX, 감사 로그, rollback 불가 고지 이후에만 검토한다.
[ ] 운영에서 주문 실행 API 호출 시도를 P0 보안/안전 이벤트로 기록한다.
```

---

# 6. Provider 장애 대응

```text
[ ] Toss API timeout을 설정한다.
[ ] 429 rate limit 발생 시 backoff를 적용한다.
[ ] 5xx provider 오류 시 기존 정상 데이터를 삭제하지 않는다.
[ ] malformed response는 provider.schema_changed 이벤트로 기록한다.
[ ] fallback provider 사용 시 provider.fallback.used 이벤트를 기록한다.
[ ] fallback 데이터 source를 DataIngestionLog에 남긴다.
[ ] partial response는 검증 전 active 데이터로 반영하지 않는다.
[ ] provider DOWN 상태에서도 consult API가 전체 중단되지 않게 한다.
```

---

# 7. Repository 점검

배포 전 또는 secret 사고 의심 시 실행한다.

```bash
git grep -n "TOSS_INVEST_CLIENT_SECRET"
git grep -n "Authorization: Bearer"
git grep -n "X-Tossinvest-Account"
git grep -n "access_token"
git grep -n "client_secret"
git grep -n "CREDENTIAL_ENCRYPTION_KEY"
git grep -n "CREDENTIAL_HASH_PEPPER"
git grep -n "SQLCIPHER_DATABASE_KEY"
```

Git repo가 아닌 문서 작업 디렉터리에서는 다음을 사용한다.

```bash
rg -n "TOSS_INVEST_CLIENT_SECRET|Authorization: Bearer|X-Tossinvest-Account|access_token|client_secret|CREDENTIAL_ENCRYPTION_KEY|CREDENTIAL_HASH_PEPPER|SQLCIPHER_DATABASE_KEY" .
```

검색 결과에 실제 secret 값이 있으면 즉시 폐기/재발급 절차를 따른다. 변수명만 존재하는 것은 허용되지만, 실제 값은 출력하거나 보고서에 붙여 넣지 않는다.

---

# 8. Smoke 구현 보안 체크

1차 smoke 구현은 설정 점검, token 발급 smoke, 현재가 조회 smoke까지만 포함한다. DB 저장, provider registry 등록, 주문 생성/정정/취소 API는 포함하지 않는다.

```text
[ ] .env.example에 실제 client_id/client_secret/account id가 없는가
[ ] deploy/production/thestock.env.example에 실제 secret이 없는가
[ ] TOSS_ORDER_EXECUTION_ENABLED=false가 기본값인가
[ ] check_toss_provider가 네트워크 호출 없이 동작하는가
[ ] toss_token_smoke --no-network가 네트워크 호출 없이 동작하는가
[ ] toss_quote_smoke --symbol=005930 --market=KR --no-network가 네트워크 호출 없이 동작하는가
[ ] toss_token_smoke가 access token 원문을 출력하지 않는가
[ ] toss_quote_smoke가 Authorization header를 출력하지 않는가
[ ] check_toss_provider가 client_secret 원문을 출력하지 않는가
[ ] account id는 마스킹되거나 missing/configured로만 표시되는가
[ ] request body/header가 로그에 남지 않는가
[ ] raw API response 전체가 로그에 남지 않는가
[ ] provider registry에 Toss provider가 아직 등록되지 않았는가
[ ] 주문 생성/정정/취소 API가 구현되어 있지 않은가
[ ] DataIngestionLog에 token/secret/account 원문이 저장되지 않는가
```

검증 command:

```bash
python manage.py check_toss_provider
python manage.py toss_token_smoke --no-network
python manage.py toss_quote_smoke --symbol=005930 --market=KR --no-network
```

위 command는 운영자 점검에서도 네트워크 호출 없이 먼저 실행한다.

## 8.1 실제 smoke 실행 전 확인

실제 token endpoint 또는 현재가 endpoint를 호출하기 전 다음을 확인한다.

```text
[ ] 운영자가 실제 네트워크 호출 발생 가능성을 이해했는가
[ ] Toss API key/secret이 운영 .env 또는 secret manager에만 있는가
[ ] 화면 공유/터미널 녹화 중 secret이 노출되지 않도록 했는가
[ ] python manage.py toss_token_smoke 실행 후 token 원문이 출력되지 않는지 확인했는가
[ ] python manage.py toss_quote_smoke --symbol=005930 --market=KR 실행 후 DB 저장이 발생하지 않는지 확인했는가
[ ] 주문 API 호출 경로가 없음을 확인했는가
```

실제 smoke command:

```bash
python manage.py toss_token_smoke
python manage.py toss_quote_smoke --symbol=005930 --market=KR
```

주의:

```text
1. 위 두 command는 운영 환경변수가 설정된 경우 실제 네트워크 호출을 수행할 수 있다.
2. toss_quote_smoke는 GET /api/v1/prices 현재가 조회만 수행한다.
3. quote smoke는 DB 저장하지 않는다.
4. quote smoke는 계좌 API가 아니므로 X-Tossinvest-Account header를 사용하지 않는다.
5. 주문 생성/정정/취소 API는 구현되어 있지 않아야 한다.
```

---

# 9. 사고 대응

API key 또는 계좌 식별자 노출이 의심되면 다음 순서로 대응한다.

```text
1. 노출 범위를 기록한다.
2. 노출된 key/token을 즉시 폐기한다.
3. 새 key를 발급한다.
4. 운영 .env 또는 secret manager 값을 갱신한다.
5. 서비스를 재시작한다.
6. Git history와 로그 저장소를 확인한다.
7. 의심 API 호출 기록을 확인한다.
8. 사고 기록을 남기고 재발 방지 작업을 등록한다.
```

사용자별 Toss credential 사고 대응:

```text
1. 특정 사용자 credential leak 의심 시 해당 credential을 revoke/delete 처리한다.
2. CREDENTIAL_ENCRYPTION_KEY leak 의심 시 전체 사용자 credential 사고로 격상한다.
3. SQLCIPHER_DATABASE_KEY leak은 DB 파일 유출 방어 계층 사고로 분류하되, credential encryption key와 별도로 대응한다.
4. audit log에서 reveal/access/token refresh/조회 이벤트를 확인한다.
5. key rotation과 credential 재등록 절차를 별도 incident task로 등록한다.
```

---

# 10. 관련 문서

```text
docs/10_toss_openapi_provider_design.md
docs/15_operations_runbook.md
docs/16_observability_and_alerting_design.md
docs/18_privacy_and_financial_data_policy.md
docs/19_toss_openapi_first_provider_policy.md
docs/20_toss_openapi_mapping_table.md
```
