# theStock Technical Architecture and Toss User Credential Design

## 1. 문서 목적

이 문서는 `theStock`의 중장기 기술 아키텍처와 사용자별 Toss증권 credential 1:1 연결 구조를 정의한다.

목적은 다음과 같다.

- theStock의 최종 기술 스택 방향을 정리한다.
- theStock user와 Toss증권 security/API user credential의 1:1 연결 구조를 기준으로 삼는다.
- 기존 전역 `.env` Toss credential 구조를 일반 사용자 기능에서 제거하기 위한 기준을 정한다.
- DB 파일 암호화와 credential column 암호화의 역할을 분리한다.
- Django Template 기반 UI와 향후 Android API 방향을 함께 정리한다.
- 후속 구현 전 보안 원칙, 단계별 구현 계획, 검증 기준을 제공한다.

이 문서는 구현 문서가 아니다. 이번 단계에서는 Python/Django code, settings, model, migration, template, static asset, dependency, DB schema, `.env`, 배포 파일을 변경하지 않는다.

Phase 1 보안 기반 조사는 [docs/55_security_foundation_research_report.md](55_security_foundation_research_report.md)에 정리되어 있다. 본 문서는 아키텍처 기준 문서이고, docs/55는 encrypted credential 저장 방식, SQLCipher 적용 가능성, Toss 인증 모델 로컬 판정을 다룬 상세 조사 보고서다. 2026-06-17 이후 사용자별 Toss credential 관련 구현 판단은 docs/55의 결론을 이 문서에 반영한 기준을 따른다.

## 2. 현재 프로젝트 기준 상태

- Backend: Django 5.x + Django REST Framework.
- Frontend: Django Template + static CSS/JS.
- DB: local 기본은 SQLite, 운영은 `POSTGRES_*` 설정이 모두 있으면 PostgreSQL로 전환 가능한 구조.
- Auth: Django 기본 `auth.User`, `UserProfile` 1:1 확장.
- `UserProfile`: 스마트폰 번호 등 사용자 프로필 확장 역할로 유지.
- Toss: 현재 settings/`.env` 기반 전역 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT_ID` 구조.
- 사용자별 Toss credential DB 저장 구조 없음.
- Toss order history/reconciliation/customer info는 staff-only read-only 기능.
- 주문 생성/정정/취소 API와 자동매매는 금지 상태.
- `UserHolding`과 Portfolio Summary는 `request.user` owner scope 기반.

기존 staff-only read-only 기능은 현재 구현 상태로 유지한다. 일반 사용자용 Toss 연동은 이 문서의 보안 전제와 후속 phase가 완료되기 전까지 코드에 반영하지 않는다.

## 3. 최종 기술 스택

| 영역 | 기준 |
|---|---|
| Backend | Django 5.x, Django REST Framework |
| Frontend | Django Template, HTMX, Alpine.js, Tailwind CSS |
| Grid/Table | AG Grid Community |
| Data Visualization | D3.js |
| Local DB | SQLite + SQLCipher 검토/도입 |
| Production DB | PostgreSQL 가능 구조 유지 |
| Credential field encryption | application-level encrypted fields |
| Secret source | `.env` 또는 Secret Manager |
| Android Future | Kotlin + Jetpack |
| LLM Future | Ollama |

React, Next.js, Vue SPA 전환은 현재 기본 방향이 아니다. 복잡도가 실제로 Django Template + HTMX + Alpine.js 범위를 넘는 경우에만 별도 검토한다.

## 4. Backend Architecture

- Django 5.x + Django REST Framework 구조를 유지한다.
- 서버 렌더링 화면과 DRF API를 병행한다.
- 향후 Android 앱을 고려해 DRF API를 점진적으로 정리한다.
- `UserProfile`에는 Toss credential 또는 Toss account mapping을 넣지 않는다.
- 새 앱 후보는 `integrations` 또는 `user_integrations`다.
- 권장 앱명은 `integrations`다.

앱 책임 분리는 다음과 같다.

- `data_pipeline`: provider, ingestion, read-only data retrieval, operational diagnostics.
- `integrations`: 사용자-외부서비스 연결, credential 저장, ownership, audit.
- `holdings`: 사용자 보유 종목 domain.
- `portfolio`: 포트폴리오 요약, 시뮬레이션, 화면 domain.
- `platform_auth`: 로그인/회원가입, 사용자 프로필 확장.

Toss provider 호출은 최종적으로 사용자별 credential resolver를 통과하도록 진화한다.

```text
request.user
  -> integrations credential resolver
  -> decrypted credential in application memory
  -> TossOpenApiClient
  -> read-only Toss API
  -> sanitized response
  -> user-scoped domain/service
```

서버는 `CREDENTIAL_ENCRYPTION_KEY`로 복호화할 수 있다. 1차 목표는 DB/SQL query에서 평문 credential이 보이지 않는 구조다. user-only encryption은 후속 고도화 option으로 남긴다.

## 5. Frontend Architecture

- Django Template 기반 서버 렌더링을 유지한다.
- HTMX는 form submit, partial update, credential 등록/수정/삭제 결과 갱신에 사용한다.
- Alpine.js는 작은 상호작용, show/hide, confirm, masked/reveal UI에 사용한다.
- Tailwind CSS는 전체 UI style 기준으로 정리한다.
- React/Next/Vue SPA 전환은 현재 기본 방향이 아니다.

Credential 관련 화면은 보안 UX를 우선한다.

- 기본 표시: masked only.
- reveal: 본인 재인증 후 짧은 시간.
- staff reveal: 기본 금지. 즉, staff reveal 금지 정책을 기본값으로 둔다.
- raw credential을 DOM에 장시간 보관하지 않는다.

## 6. Grid/Table Architecture

AG Grid는 Community 기준으로만 채택한다. AG Grid Enterprise 기능은 라이선스 검토 전까지 사용하지 않는다.

기준:

- plain JavaScript integration 우선.
- Django Template 안에서 필요한 화면에만 적용.
- credential 입력/보안 화면에는 AG Grid를 남용하지 않는다.

적용 후보:

- 보유종목 목록.
- 거래내역.
- 주문내역.
- Toss 동기화 결과.
- 추가매수 후보.
- 예측 결과 ranking.
- staff-only reconciliation 화면.

## 7. Data Visualization Architecture

D3.js를 data visualization 기본 도구로 채택한다.

적용 후보:

- 포트폴리오 가치 변화.
- 종목별 비중.
- 추가매수 시뮬레이션 곡선.
- 평균단가 변화.
- 예측 알고리즘 결과.
- 리스크 이벤트 타임라인.
- 손익 곡선.

단순 표, 단순 요약 카드, credential 보안 화면에는 D3.js를 남용하지 않는다.

LLM/Ollama 결과를 시각화할 때도 raw credential, token, 계좌번호, 주문번호는 전달하지 않는다. 비식별화된 요약 지표만 사용한다.

## 8. Database and Encryption Architecture

SQLite 환경에서는 SQLCipher 도입을 목표로 검토한다.

SQLCipher의 역할:

- SQLite DB 파일 전체 암호화.
- `db.sqlite3` 파일 유출 시 방어 계층.
- local 또는 단일 서버 SQLite 운영 시 file-at-rest protection.

SQLCipher의 한계:

- SQLCipher만으로 Toss credential 보안 요건을 충족하지 않는다.
- SQLCipher는 DB 파일을 암호화하지만, 애플리케이션이 DB를 열고 credential을 평문 column에 저장하면 일반 SQL query 결과에서 평문이 노출될 수 있다.
- 따라서 SQLCipher는 credential column encryption의 대체재가 아니다.

Toss credential 저장 기준:

- Toss credential은 application-level encrypted field로 column 자체에 ciphertext를 저장한다.
- SQL query로 조회해도 encrypted blob/string만 보여야 한다.
- `client_id`, `client_secret`, `access_token`, `refresh_token` 평문 저장을 금지한다.
- encryption key는 DB에 저장하지 않는다.

Secret source:

```text
CREDENTIAL_ENCRYPTION_KEY=<REDACTED>
CREDENTIAL_HASH_PEPPER=<REDACTED>
SQLCIPHER_DATABASE_KEY=<REDACTED>
```

이 값들은 `.env` 또는 Secret Manager에서 관리한다. `.env` 파일 자체는 삭제하지 않는다. `.env`는 운영 secret 저장용으로 유지하되, 일반 사용자 기능용 전역 Toss credential은 제거 대상으로 본다.

PostgreSQL 운영 전환 시:

- SQLCipher는 적용 대상이 아니다.
- application-level encrypted field 구조는 그대로 유지한다.
- 운영 secret 관리, infra/disk/backup encryption, DB 접근 통제, key rotation 정책으로 대응한다.

Key rotation은 별도 후속 과제다.

### 2026-06-17 Security Foundation Research Update

docs/55 조사 결론에 따라 1차 Toss credential 구현에서는 SQLCipher를 blocker로 두지 않는다.

- SQLCipher는 SQLite DB 파일 보호용이다.
- SQLCipher는 별도 hardening phase에서 PoC, driver, Django backend, CI, backup/restore 검증 후 적용한다.
- credential column 보안의 핵심은 service-layer application-level encryption이다.
- SQLCipher와 credential column encryption은 대체 관계가 아니라 보완 관계다.
- PostgreSQL 운영 전환 시 SQLCipher는 적용 대상이 아니지만 credential field encryption은 유지한다.
- `CREDENTIAL_ENCRYPTION_KEY`, `CREDENTIAL_HASH_PEPPER`, `SQLCIPHER_DATABASE_KEY`는 DB에 저장하지 않는다.

## 9. Toss증권 사용자별 Credential Architecture

목표 구조:

```text
theStock user : Toss증권 security/API user credential = 1:1
user 1:1 credential mapping
```

정책:

- 일반 사용자 기능에서는 전역 `.env` Toss credential 공유를 금지한다.
- 사용자 회원가입 후 본인의 Toss API credential을 등록하는 구조를 목표로 한다.
- credential은 read-only scope 우선으로 사용한다.
- 주문 scope는 별도 phase 전까지 금지한다.
- 주문 생성/정정/취소 API, 자동매매, 주문 추천 실행은 계속 범위 밖이다.

중요한 Open Question:

- Toss증권 Open API의 `client_id`/`client_secret`이 실제로 사용자 개인별 credential인지, 서비스 앱 단위 credential인지 최종 확인이 필요하다.

설계 기준:

- 개인별 credential이 맞으면 사용자가 본인 credential을 입력하고 DB에는 application-level encryption으로 저장한다.
- 서비스 앱 단위 credential이 맞으면 사용자별 access/refresh token/account identity 구조로 보정해야 한다.
- 현재 문서는 사용자가 개인 Toss credential을 등록하는 요구사항 기준으로 설계한다.

전역 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT_ID`는 staff-only 운영 점검 또는 전환 기간에만 제한적으로 유지할 수 있다. 일반 사용자 데이터 조회에는 절대 사용하지 않는다.

### 2026-06-17 Security Foundation Research Update

1차 encrypted credential 저장 방식은 `cryptography.Fernet` 또는 `MultiFernet` 기반 service-layer encryption 직접 구현을 우선 검토/채택한다.

- 일반 `TextField`에는 ciphertext만 저장한다.
- 모델 필드 자동 복호화 또는 admin 자동 복호화 방식은 1차 권장안이 아니다.
- decrypt는 명시적인 service 함수에서만 수행한다.
- `client_id`/`client_secret` reveal은 본인 비밀번호 재확인 후 짧은 시간 동안만 허용한다.
- `access_token`/`refresh_token`은 사용자 본인에게도 화면 reveal 금지다.
- staff/admin/superuser는 모든 secret/token 평문 reveal 금지다.
- 복호화 실패, key mismatch, key 손망실, 사용자 분실 문의는 운영자 복구 없이 `reset_required` + 초기화 후 사용자 재등록으로 처리한다.
- raw Toss response, Authorization header, account 원문, order id 원문은 저장하지 않는다.

## 10. 사용자별 Toss Credential 모델 초안

이번 문서에서는 실제 모델을 구현하지 않는다.

권장 모델:

```text
integrations.models.TossInvestCredential
```

필드 후보:

- `id`
- `user`: `OneToOneField(settings.AUTH_USER_MODEL, on_delete=CASCADE)`
- `provider`: 기본값 `toss_invest`
- `client_id_ciphertext`
- `client_secret_ciphertext`
- `access_token_ciphertext`, nullable
- `refresh_token_ciphertext`, nullable
- `encryption_key_version`
- `client_id_fingerprint`
- `account_hash`, nullable
- `account_masked`, nullable
- `external_user_hash`, nullable
- `scopes`: safe JSON 또는 text
- `status`: `pending_verification` / `active` / `disconnected` / `revoked` / `reset_required` / `error`
- `last_verified_at`, nullable
- `last_used_at`, nullable
- `disconnected_at`, nullable
- `error_code` 또는 `error_summary`, nullable
- `created_at`
- `updated_at`

필드명은 구현 전 초안이다. 기존 `_encrypted` 명명과 docs/55의 `_ciphertext` 명명 중 최종 이름은 구현 phase에서 확정한다. 1차 권장 방향은 column에 ciphertext만 저장된다는 사실을 명확히 하기 위해 `_ciphertext` 명명을 우선 검토한다.

제약:

- user는 기본 1:1.
- 활성 credential은 사용자당 1개만 허용.
- raw account number 저장 금지.
- raw account sequence 저장 금지.
- raw order id 저장 금지.
- raw external user id 저장 금지.
- raw client secret 저장 금지.
- raw token 저장 금지.
- raw account number, raw account sequence, raw order id, raw external user id, raw token 저장 금지.
- unique constraint와 검색/중복 확인은 encrypted field 자체가 아니라 fingerprint/hash에 적용.
- 화면 표시용 계좌번호는 `account_masked`만 사용.
- `client_secret`은 기본 마스킹 표시만 허용.

보조 모델 후보:

- `IntegrationAuditLog`
- `TossCredentialAccessLog`
- `UserExternalAccountLink`

## 10.1 Fingerprint/Hash 설계

1차 구현에서는 복호화 가능한 credential ciphertext와 별도로, 중복 확인과 감사 로그 표시를 위한 fingerprint/hash를 저장한다.

필드 후보:

- `client_id_fingerprint`
- `account_hash`
- `external_user_hash`
- `actor_ref_hash`
- `target_user_ref_hash`

정책:

- `CREDENTIAL_HASH_PEPPER` 기반 HMAC-SHA256을 사용한다.
- pepper는 DB에 저장하지 않는다.
- hash 입력은 provider, identifier type, normalized value를 포함하는 형태로 표준화한다.
- normalization 정책이 필요하다. 예: trim, 대소문자 처리, provider prefix 포함 여부, account type 포함 여부.
- active 또는 `pending_verification` 상태의 `client_id_fingerprint` 중복 등록을 금지한다.
- active 상태의 `account_hash` 중복 등록을 금지한다.
- pepper rotation은 기존 hash와 신규 hash 비교를 깨뜨릴 수 있으므로 `hash_version` 또는 `pepper_version`과 controlled rehash 절차가 필요하다.
- raw credential/account/order identifier를 hash 계산 후 저장하거나 로그에 남기지 않는다.

## 11. Credential 보안 정책

- DB 평문 저장 금지.
- 로그 평문 출력 금지.
- Django admin에서 encrypted field 원문 표시 금지.
- 기본 화면은 마스킹 표시.
- 본인 재인증 후 짧은 시간 동안만 reveal 허용.
- 재인증 방식 후보: 비밀번호 재확인, 2FA, PIN.
- credential 조회/복호화 이벤트는 audit log 기록.
- staff/admin/superuser는 사용자 secret/token 평문 reveal 금지.
- 운영자도 손망실, 복호화 실패, 사용자 분실 문의를 복구하지 않는다. 해당 credential은 `reset_required`로 전환하고 초기화 후 사용자 재등록으로 처리한다.
- 암호화 키는 DB에 저장하지 않음.
- key rotation은 별도 과제.
- 탈퇴/연동해제 시 credential 삭제 또는 crypto-shredding 정책 필요.
- backup에 남은 credential 처리 정책 필요.
- dump/export 시 credential ciphertext도 민감정보로 취급.
- 테스트 fixture에 실제 credential 금지.
- 문서/Git에 실제 credential 금지.

`SQLCipher`는 DB 파일 유출 방어용이고, `application-level encrypted field`가 credential column 보안의 핵심이다.

## 12. Toss Provider Refactoring Plan

현재 `data_pipeline.providers.toss_auth.py`, `toss_client.py`, `toss_provider.py`는 settings 기반 전역 credential 의존성이 있다.

후속 방향:

- provider는 사용자별 credential 객체 또는 credential resolver를 받아 동작하도록 리팩터링한다.
- 일반 사용자용 Toss 조회는 `request.user` ownership scope를 강제한다.
- staff-only 운영 화면/API와 일반 사용자 화면/API는 URL, permission, serializer, template을 분리한다.
- `data_pipeline`은 provider/ingestion 책임을 유지한다.
- `integrations`는 사용자 credential/account ownership 책임을 가진다.

read-only 조회부터 구현한다.

- 연결 상태 확인.
- 계좌 목록 조회.
- 보유종목 조회.
- 잔고 조회.
- 주문내역 조회.
- 체결내역 조회.

계속 금지:

- 주문 생성/정정/취소.
- `TOSS_ORDER_EXECUTION_ENABLED=true` 전환.
- 자동매매.
- 컨설팅 결과와 주문 API 직접 연결.

## 13. User Flow: Credential 등록/수정/삭제/조회

등록:

1. 회원가입/로그인.
2. Toss credential 등록 화면 이동.
3. `client_id`/`client_secret` 입력.
4. 서버 validation.
5. `cryptography.Fernet` 또는 `MultiFernet` 기반 service-layer encryption으로 encrypted 저장.
6. fingerprint/hash 생성.
7. 상태를 `pending_verification`으로 저장.
8. Toss read-only 인증/대표 계좌 확인.
9. 성공 시 대표 계좌를 `account_hash` + `account_masked`로만 저장.
10. 연결 상태 `active` 표시.

검증 실패:

- 네트워크 장애, timeout, rate limit은 encrypted credential을 유지하고 `pending_verification`을 유지한다.
- `invalid_client`, `invalid_secret`, `revoked`, `forbidden` 계열은 encrypted credential/token 값을 즉시 삭제하고 `reset_required`로 전환한다.
- raw Toss response, request/response header, token, account 원문, order 원문은 저장하지 않는다.

수정:

1. 본인 재인증.
2. 새 credential 입력.
3. 기존 credential 폐기 또는 재암호화.
4. 연결 확인.
5. audit log 기록.

삭제/연동해제:

1. 본인 재인증.
2. status를 `disconnected` 또는 `revoked`로 처리.
3. encrypted 값 삭제 또는 crypto-shredding.
4. active 조회에서 즉시 제외.
5. audit log 기록.

기본 화면 표시:

- `client_id`: 부분 마스킹.
- `client_secret`: 전체 마스킹.
- account: `account_masked`.

Credential reveal:

- 본인 재인증 필요.
- 짧은 시간만 표시.
- audit log 기록.
- staff/admin/superuser는 reveal 불가.
- `access_token`/`refresh_token`은 사용자 본인에게도 reveal 금지.

## 14. AuditLog / Retention / Deletion Policy

1차는 `integrations.IntegrationAuditLog`를 사용한다. 후속으로 전역 audit 앱을 검토한다.

식별자 설계:

- `actor`: nullable FK.
- `target_user`: nullable FK.
- `actor_ref_hash`: 사용자 탈퇴 또는 export 시 원문 식별자 노출을 피하기 위한 hash.
- `target_user_ref_hash`: 대상 사용자 hash.
- FK는 운영 화면 내부 추적용이며, 화면/API/export에는 hash 중심 표시를 우선한다.

감사 대상:

- credential 등록.
- credential 수정.
- credential 삭제/초기화.
- credential reveal 시도/성공/실패.
- verification 성공/실패.
- token refresh.
- Toss 계좌 조회.
- holdings sync.
- order history 조회.
- staff 민감 조회.
- permission denied.
- 복호화 실패.

AuditLog safe fields:

- `actor`, nullable FK
- `target_user`, nullable FK
- `actor_ref_hash`
- `target_user_ref_hash`
- `provider`
- `action`
- `account_hash`
- `success`
- `safe_reason`
- `created_at`

AuditLog 금지:

- username/email 원문.
- credential 원문.
- account 원문.
- token/header.
- raw response.
- order id 원문.
- Authorization header.

Retention/delete:

- 연동해제 즉시 active 조회에서 제외.
- 사용자 탈퇴 시 credential 삭제 또는 crypto-shredding.
- backup/restore 후 삭제 replay 절차 필요.
- AuditLog retention은 별도 결정.

## 15. Staff-only 기능과 일반 사용자 기능 분리

- 기존 staff-only Toss order history/reconciliation은 현재 구현 상태로 안전하게 유지한다.
- 일반 사용자용 user-scoped 기능은 별도 URL/API/template로 만든다.
- staff-only global credential과 user credential을 혼동하지 않는다.
- staff-only 기능에서 전역 credential을 쓰더라도 일반 사용자 데이터 조회에는 사용하지 않는다.
- 일반 사용자 API에서 `user_id` query로 다른 사용자 데이터 조회를 금지한다.
- `account_hash`를 URL query에 직접 노출하지 않는 것이 바람직하다.
- opaque id 또는 server-side selected account를 사용한다.

## 16. Android App Future Plan

- 백엔드 안정화 후 Android 앱을 Kotlin + Jetpack 기준으로 개발한다.
- DRF API를 점진적으로 정리한다.
- 모바일 앱은 Toss credential 평문을 저장하지 않는다.
- 모바일 앱은 theStock 서버 API로 포트폴리오/분석 결과를 조회한다.
- 모바일 인증/token/session 전략은 별도 설계한다.
- 모바일 API에서도 owner scope를 강제한다.
- 모바일 response에 credential/token/account 원문을 포함하지 않는다.

## 17. Ollama/LLM Future Plan

- 추가예측 알고리즘에는 Ollama 기반 LLM 활용을 검토한다.
- Toss credential 관리와 LLM 예측 알고리즘은 보안 경계가 다르므로 별도 phase로 분리한다.
- LLM에 raw credential, token, 계좌번호, 주문번호 등 민감정보를 전달하지 않는다.
- LLM 입력은 비식별화/요약된 포트폴리오 지표와 시장 데이터 중심으로 제한한다.
- LLM 결과는 투자 판단 보조 정보로 표시한다.
- 자동 주문 실행과 직접 연결하지 않는다.
- LLM prompt/log 저장 시 민감정보를 제거한다.

## 18. Implementation Roadmap

### Phase 0. 기술 아키텍처 문서 반영

- docs/54 생성.
- 관련 문서 링크/정책 업데이트.
- 코드 변경 없음.

### Phase 1. 보안 기반 조사 - 완료/문서화

- docs/55 생성.
- service-layer encryption 1순위 권장.
- SQLCipher는 별도 hardening phase 권장.
- Toss credential 발급 단위 공식 확인 필요.

### Phase 2. docs/54 반영 - 현재 단계

- docs/55 결론을 기준 아키텍처에 반영.
- 구현 전 blocker와 구현 가능 영역을 분리.
- SQLCipher를 1차 credential 구현 blocker가 아니라 hardening phase로 분리.
- Toss credential 발급 단위 공식 확인을 user-scoped provider 구현 전 blocker로 명시.

### Phase 3. integrations 앱 skeleton + encryption utility 설계/구현

- `integrations` 앱 생성.
- `cryptography.Fernet`/`MultiFernet` 기반 service-layer encryption.
- `TextField` ciphertext 저장.
- HMAC-SHA256 fingerprint/hash.
- unit test.
- 아직 Toss API user-scoped 호출은 하지 않음.

### Phase 4. TossInvestCredential/IntegrationAuditLog 모델 구현

- `TossInvestCredential` 모델.
- `IntegrationAuditLog` 모델.
- migration.
- admin 마스킹.
- no auto decrypt.
- status lifecycle.

### Phase 5. Credential 등록/수정/삭제/reveal 화면

- Django Template + HTMX + Alpine.js + Tailwind CSS.
- 본인 credential 등록/수정/삭제.
- 마스킹 표시.
- 본인 비밀번호 재확인.
- `client_id`/`client_secret` 제한 reveal.
- token reveal 금지.
- AuditLog.

### Phase 6. Toss 인증 모델 공식 확인 후 provider 리팩터링

- 개인별 credential인지 서비스 앱 credential인지 확정.
- credential resolver 설계 보정.
- read-only user-scoped provider 연결.
- 전역 settings credential 의존성 제거 또는 staff-only 경로로 격리.
- owner scope 강제.

### Phase 7. SQLCipher hardening PoC

- SQLite 개발/운영 환경에 적용 가능성 검증.
- CI/backup/restore/driver 검증.
- PostgreSQL 운영 전환과 역할 분리.

### Phase 8. 사용자별 portfolio/holdings sync

- 사용자별 Toss 계좌에서 holdings/balance/order history 조회.
- raw account/order 식별자 저장 금지.
- hash/masked 저장.
- 동기화 로그와 오류 처리.

### Phase 9. UI 고도화

- AG Grid Community.
- D3.js.
- Tailwind 정리.
- 모바일 가독성.

### Phase 10. Android/API 준비

- DRF API 정리.
- 모바일 인증 전략.
- Kotlin + Jetpack 앱 연동 준비.

### Phase 11. Ollama 예측 알고리즘

- 민감정보 제거 데이터만 사용.
- 예측 결과 설명/근거/주의사항.
- 자동주문과 분리.

## 19. Non-goals

- 이번 단계에서 코드 구현 안 함.
- 이번 단계에서 모델/migration 생성 안 함.
- 이번 단계에서 settings/`.env` 변경 안 함.
- 이번 단계에서 SQLCipher 실제 적용 안 함.
- 이번 단계에서 requirements 변경 안 함.
- 이번 단계에서 AG Grid/D3/HTMX/Alpine/Tailwind 실제 설치 안 함.
- 이번 단계에서 Toss API 호출 안 함.
- 이번 단계에서 주문 API 구현 안 함.
- staff/admin reveal 없음.
- token reveal 없음.
- Toss credential 발급 단위 확정 전 user-scoped provider 구현 금지.
- SQLCipher를 credential column encryption 대체재로 사용 금지.
- 자동매매 금지.
- 매수/매도 추천 실행 금지.
- 수익 보장 표현 금지.
- SQLCipher만으로 credential 보안 충분하다고 주장 금지.
- `.env` 파일 자체 삭제 주장 금지.

## 20. Open Questions

- Toss증권 Open API의 `client_id`/`client_secret`이 실제로 사용자 개인별 credential인지, 서비스 앱 단위 credential인지 최종 확인 필요.
- 로컬 코드 기준 현재는 OAuth2 client credentials + settings 전역 `TOSS_INVEST_*` 구조다.
- credential 발급 단위는 로컬 근거만으로 확정 불가이며, 구현 전 Toss증권 Open API 공식 문서 또는 발급 정책 확인이 필요하다.
- 이 항목은 일반 사용자 credential 기반 user-scoped provider 구현 전 blocker다.
- 단, `integrations` 앱 skeleton, service-layer encryption utility, model skeleton 설계는 이 blocker를 Open Question으로 남긴 채 진행 가능하다.
- SQLCipher를 Django 5.x + 현재 SQLite 환경에서 어떤 패키지/드라이버로 적용할지 검증 필요.
- application-level encrypted field 패키지 선정 필요. docs/55 기준 1차 권장안은 `cryptography.Fernet`/`MultiFernet` service-layer encryption 직접 구현이다.
- `CREDENTIAL_ENCRYPTION_KEY` 생성/보관/회전 정책 확정 필요.
- `CREDENTIAL_HASH_PEPPER` 회전 시 기존 fingerprint/hash 처리 정책 필요.
- `SQLCIPHER_DATABASE_KEY` 보관/백업/복구 정책 필요.
- production PostgreSQL 전환 시 credential encryption/key rotation 운영 방안 확정 필요.
- 본인 재인증 방식: 비밀번호 재확인만 할지, 2FA/PIN을 추가할지 결정 필요.
- staff가 사용자 credential reveal을 절대 못 하게 할지, 최고 관리자 승인 예외를 둘지 결정 필요.
- Android 앱 인증 방식 결정 필요.
- Ollama 예측 알고리즘 입력 데이터 스키마 결정 필요.
- 탈퇴/연동해제/backup deletion replay 정책 확정 필요.
- user-only encryption을 장기 목표로 둘지, 서버 복호화 가능한 application-level encryption을 유지할지 결정 필요.

## 21. Verification Checklist

- [ ] docs/54 문서가 생성되었는가.
- [ ] docs/54에 docs/55 링크가 있는가.
- [ ] docs/00_current_state_entrypoint.md에서 docs/54가 현재 문서 세트 또는 후속 기준 문서로 연결되었는가.
- [ ] service-layer encryption 1순위 권장안이 반영되었는가.
- [ ] SQLCipher가 blocker가 아니라 hardening phase로 정리되었는가.
- [ ] Toss credential 발급 단위 공식 확인 필요가 blocker로 명시되었는가.
- [ ] staff/admin reveal 금지가 반영되었는가.
- [ ] token reveal 금지가 반영되었는가.
- [ ] `reset_required` + 초기화 후 사용자 재등록 정책이 반영되었는가.
- [ ] `CREDENTIAL_ENCRYPTION_KEY`, `CREDENTIAL_HASH_PEPPER`, `SQLCIPHER_DATABASE_KEY` 정책이 반영되었는가.
- [ ] docs/52_user_account_mapping_design.md가 새 사용자별 credential 1:1 방향을 반영하는가.
- [ ] docs/18_privacy_and_financial_data_policy.md가 사용자별 Toss credential과 암호화 정책을 반영하는가.
- [ ] docs/21_toss_openapi_security_checklist.md가 application-level encrypted field, SQLCipher 역할 분리, `CREDENTIAL_ENCRYPTION_KEY`, `CREDENTIAL_HASH_PEPPER`, `SQLCIPHER_DATABASE_KEY`를 반영하는가.
- [ ] docs/10_toss_openapi_provider_design.md가 provider 리팩터링 방향을 반영하는가.
- [ ] docs/29_next_feature_priority_decision.md가 기존 DailyPrice batch 우선순위와 새 credential architecture 우선순위의 관계를 설명하는가.
- [ ] docs/53_implementation_closure_report.md가 기존 closure 결과를 훼손하지 않고 후속 architecture 문서를 참조하는가.
- [ ] 주문 API/자동매매 금지 정책이 유지되는가.
- [ ] AG Grid Enterprise 금지 정책이 명시되었는가.
- [ ] LLM/Ollama 민감정보 전달 금지 정책이 명시되었는가.

## 22. 관련 문서

- [docs/00_current_state_entrypoint.md](00_current_state_entrypoint.md)
- [docs/10_auth_policy_design.md](10_auth_policy_design.md)
- [docs/10_toss_openapi_provider_design.md](10_toss_openapi_provider_design.md)
- [docs/18_privacy_and_financial_data_policy.md](18_privacy_and_financial_data_policy.md)
- [docs/21_toss_openapi_security_checklist.md](21_toss_openapi_security_checklist.md)
- [docs/29_next_feature_priority_decision.md](29_next_feature_priority_decision.md)
- [docs/52_user_account_mapping_design.md](52_user_account_mapping_design.md)
- [docs/53_implementation_closure_report.md](53_implementation_closure_report.md)
- [docs/55_security_foundation_research_report.md](55_security_foundation_research_report.md)
- [docs/toss_OpenAPI_guide/0.toss security-api.txt](toss_OpenAPI_guide/0.toss%20security-api.txt)
- [docs/toss_OpenAPI_guide/1.auth.txt](toss_OpenAPI_guide/1.auth.txt)
