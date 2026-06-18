# Security Foundation Research Report

조사일: 2026-06-17

## 1. 목적

이 문서는 사용자별 Toss증권 credential 1:1 연동을 실제 구현하기 전에 필요한 보안 기반을 조사한 보고서다. 조사 범위는 application-level encrypted field 후보, SQLCipher 적용 가능성, 현재 Toss 인증 흐름의 로컬 근거, secret/key 관리 방향이다.

이번 단계는 구현 전 조사 문서이며 Python/Django 코드, settings, models, migration, requirements, .env, DB schema는 변경하지 않는다. 실제 Toss API 호출, SQLCipher 적용, dependency 설치도 수행하지 않는다.

## 2. 결론 요약

- Encrypted field 권장안: 1차는 `cryptography.Fernet` 또는 `MultiFernet` 기반 service-layer encryption 직접 구현을 권장한다. DB field는 일반 `TextField` ciphertext 저장으로 두고, 복호화는 권한 검사를 통과한 service 함수에서만 수행한다.
- SQLCipher 권장안: 1차 credential 모델 구현의 선행 조건으로 두지 않고 별도 phase에서 검증한다. SQLCipher는 SQLite DB 파일 유출 방어 계층이며 credential column encryption의 대체재가 아니다.
- Toss 인증 모델 로컬 판정: 현재 코드와 로컬 가이드는 OAuth2 client credentials 흐름, settings 기반 전역 `TOSS_INVEST_CLIENT_ID` / `TOSS_INVEST_CLIENT_SECRET` / `TOSS_INVEST_ACCOUNT_ID`, `X-Tossinvest-Account` 계좌 header 사용을 확인시켜 준다. 다만 client_id/client_secret이 사용자 개인별 credential인지 서비스 앱 단위 credential인지는 로컬 근거만으로 확정할 수 없다.
- 구현 전 반드시 확인할 사항: Toss증권 Open API credential 발급 단위, encrypted field 최종 구현 방식, key format/rotation, SQLCipher driver/backend 선택, admin 마스킹과 reveal session 정책.
- 다음 Codex 단계 권고: docs/54에 docs/55 결론 반영 후 integrations 앱 skeleton 및 암호화 유틸 구현 설계로 진행한다.

## 3. 확정된 아키텍처 결정 요약

- 목표 구조는 theStock user : Toss credential : selected Toss account = 1:1:1이다.
- 1차 앱 위치는 `integrations`로 한다.
- Toss credential column은 application-level encrypted field 또는 service-layer encryption으로 ciphertext만 저장한다.
- SQL query로 `client_id`, `client_secret`, token 평문이 보이면 안 된다.
- 서버는 `CREDENTIAL_ENCRYPTION_KEY`로 복호화 가능하되, 사용자 화면 reveal은 본인 비밀번호 재확인 후 짧은 시간만 허용한다.
- `access_token`과 `refresh_token`은 사용자 본인에게도 화면 reveal 금지다.
- staff, superuser, 운영자는 사용자 secret/token 평문 reveal 불가다.
- 손망실, 복호화 실패, 사용자 분실 문의는 운영자 복구 없이 초기화 후 사용자 재등록 정책으로 처리한다.
- 최초 credential 등록 후 상태는 `pending_verification`이며 read-only Toss 인증/계좌 확인 성공 후 `active`가 된다.
- 인증 실패, invalid secret, revoked, forbidden 계열은 encrypted 값 즉시 삭제 후 `reset_required`로 전환한다.
- 네트워크 장애, timeout, rate limit은 encrypted credential 유지와 `pending_verification` 상태를 허용한다.
- 중복 등록은 1차에서 금지한다. `client_id_fingerprint` 또는 `account_hash`가 active/pending 상태의 다른 사용자와 충돌하면 막는다.
- 대표 Toss 계좌는 1개만 연결한다. 다계좌는 후속 phase다.
- AuditLog는 1차에서 `integrations.IntegrationAuditLog`로 구현한다.
- 주문 생성/정정/취소 API, 자동매매, 주문 추천 실행은 계속 범위 밖이다.

## 4. 현재 프로젝트 로컬 조사 결과

- Django/DRF 버전: Django 5.2.14, Django REST Framework 3.15.2.
- Python 버전: Python 3.13.9.
- 의존성: `requirements.txt`는 Django, DRF, django-filter, gunicorn, pandas, psycopg, pykrx, yfinance, openpyxl 중심이다. encrypted field 또는 SQLCipher 관련 dependency는 없다.
- 설치 확인: `cryptography`는 현재 환경에 설치되어 있다. `encrypted_fields`, `fernet_fields`, `django_cryptography`, `encrypted_model_fields`, `pysqlcipher3`, `sqlcipher3`는 설치되어 있지 않다.
- DB 구조: 기본은 `BASE_DIR / "db.sqlite3"` SQLite다. 운영 설정은 `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`가 모두 있을 때 PostgreSQL로 전환한다.
- Auth/User 구조: `INSTALLED_APPS`에 `platform_auth`가 있고, 프로젝트 전제상 Django 기본 `auth.User`와 `platform_auth.models.UserProfile` 1:1 확장 구조를 사용한다. Toss credential은 UserProfile에 섞지 않고 별도 `integrations` 앱으로 분리한다.
- Toss 관련 코드 위치: `data_pipeline/providers/toss_auth.py`, `toss_client.py`, `toss_provider.py`, `toss_masking.py`, `toss_order_guard.py`와 관련 management command가 존재한다.
- 현재 전역 `TOSS_INVEST_*` 사용 방식: settings에서 env 기반 전역 값을 읽고 provider/client/auth 계층에서 token 발급, account header, provider enable/timeout/order execution flag에 사용한다.
- docs/54 존재 여부: `docs/54_technical_architecture_and_toss_credential_design.md`가 존재한다.
- 코드 변경 없음 확인: 이번 조사 단계에서 코드 파일, requirements, settings, migration은 변경하지 않는다.

## 5. Toss 인증 모델 로컬 조사

조사한 파일:

- `docs/toss_OpenAPI_guide/`
- `data_pipeline/providers/toss_auth.py`
- `data_pipeline/providers/toss_client.py`
- `data_pipeline/providers/toss_provider.py`
- `stock_service/settings/base.py`
- `deploy/production/thestock.env.example`
- `data_pipeline/management/commands/` 관련 Toss command

현재 token 발급 흐름:

- `toss_auth.py`는 OAuth2 Client Credentials Grant를 사용한다.
- token 요청에는 `grant_type=client_credentials`, settings 기반 `client_id`, `client_secret`이 사용된다.
- 현재 로컬 코드에는 Toss refresh token 흐름이 보이지 않는다.

settings 기반 credential 사용 위치:

- `stock_service/settings/base.py`에서 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT_ID`를 env에서 읽는다.
- `TossOpenApiProvider.from_settings()`와 `issue_toss_access_token()`이 이 settings 값을 사용한다.
- 현재 구조는 사용자별 DB credential이 아니라 앱 전역 credential 구조다.

`X-Tossinvest-Account` 또는 account header 사용 여부:

- `toss_client.py`의 header builder는 account-required 요청에서 계좌 reference를 `X-Tossinvest-Account` header로 넣는다.
- `toss_provider.py`는 명시 account, settings의 `TOSS_INVEST_ACCOUNT_ID`, accounts API 단일 계좌 fallback 순서로 holdings account를 resolve한다.

로컬 문서 기준 client_id/client_secret 발급 단위 판정:

- 로컬 Toss 가이드는 client credentials 흐름과 access token, account list, account header 사용을 설명한다.
- 가이드의 표현만으로 client_id/client_secret이 사용자 개인별 credential인지 서비스 앱 단위 credential인지 확정하기 어렵다.
- 구현 전 공식 Toss증권 Open API 문서 또는 운영 콘솔에서 credential 발급 단위를 확인해야 한다.

위험한 가정:

- 사용자 개인별 credential이라고 확정하지 않은 상태에서 일반 사용자에게 client_id/client_secret 입력을 요구하면 안 된다.
- 서비스 앱 credential이라면 사용자별 access/refresh token 또는 계좌 identity 구조로 설계를 수정해야 한다.
- 전역 `TOSS_INVEST_*` credential을 일반 사용자 데이터 조회에 공유하면 안 된다.

## 6. Application-level Encrypted Field 후보 비교

| 후보 | 방식 | Django 5.x 호환성 | SQLite/PostgreSQL 호환성 | 자동 복호화 위험 | key rotation | 유지보수 상태 | 장점 | 단점 | theStock 적합도 |
|---|---|---|---|---|---|---|---|---|---|
| `cryptography.Fernet/MultiFernet` 직접 구현 | service-layer encryption + `TextField` ciphertext | Django field 의존 낮음. Python 3.13 환경에서 `cryptography` 설치 확인 | DB 독립적 | 낮음. service에서만 decrypt 가능 | `MultiFernet`과 key version 설계 가능 | `cryptography`는 널리 쓰이는 기반 라이브러리 | staff reveal 금지, token reveal 금지, audit 강제에 유리 | 직접 테스트/유틸 구현 필요 | 높음 |
| `django-fernet-encrypted-fields` | Django encrypted field | 추가 검증 필요 | 일반 Django field로 동작 | 중간. model/admin 접근 시 자동 복호화 가능성 검토 필요 | `SALT_KEY` list와 `SECRET_KEY_FALLBACKS` 문서화 | Jazzband 계열, PyPI 확인 | Django field 형태로 빠르게 적용 가능 | admin/forms/serializer 노출 제어가 까다로울 수 있음 | 중간 |
| `django-fernet-fields` | `BinaryField` 기반 Fernet field | PyPI release가 2019년이고 문서상 Python 3.7/Django 1.11 이후 중심 | PostgreSQL/SQLite/MySQL tested로 문서화 | 중간 | 제한적 검토 필요 | 오래된 패키지 | 단순한 Fernet field | Django 5/Python 3.13 검증 부담 | 낮음 |
| `django-encrypted-model-fields` | 표준 Django field wrapper | PyPI classifier는 Django 4.0까지, release 2022년 | DB 독립 가능성 | 중간 | 제한적 검토 필요 | 최근성이 낮음 | settings 기반 key, 12-factor 방향 | 자동 복호화와 유지보수 확인 필요 | 중간 이하 |
| `django-cryptography` | `encrypt()` wrapper | Django 5.x 직접 검증 필요 | DB 독립 가능성 | 높음. model field 접근 시 복호화 | 제한적 검토 필요 | PyPI/문서 확인 가능하나 최신 Django 검증 필요 | API가 간단 | secret reveal 금지 정책과 충돌 가능성 큼 | 낮음 |
| 외부 패키지 + service wrapper | package field 또는 일반 TextField + service access | 패키지에 따라 다름 | 패키지에 따라 다름 | wrapper로 완화 가능 | 패키지에 따라 다름 | 패키지 의존 | 구현량 절감 가능 | 패키지 자동 복호화를 완전히 막기 어려움 | 후보 |

후보별 상세 평가:

- `cryptography.Fernet/MultiFernet` 직접 구현은 Django model field 자동 복호화를 피할 수 있어 theStock 정책과 가장 잘 맞는다. `TossInvestCredential`에는 ciphertext 문자열만 저장하고, service 계층에서 본인 재인증, token reveal 금지, audit log 기록을 강제할 수 있다.
- `django-fernet-encrypted-fields`는 key rotation 문서가 있고 Django field 형태라 편하지만, 모델 인스턴스 접근만으로 평문이 복호화될 수 있는 구조라 admin/detail/serializer 노출 제어를 별도로 강하게 막아야 한다.
- `django-fernet-fields`는 PostgreSQL/SQLite/MySQL 테스트가 문서화되어 있으나 release와 지원 Python 범위가 오래되어 Django 5.2/Python 3.13 기준 1차 후보로 두기 어렵다.
- `django-encrypted-model-fields`는 cryptography 기반 field wrapper지만 Django 5.x 호환성, maintenance, 자동 복호화 노출을 추가 검증해야 한다.
- `django-cryptography`는 사용법이 간단하지만 field 접근 시 평문을 돌려주는 모델은 staff reveal 금지와 token reveal 금지 정책에 맞지 않는다.

## 7. Service-layer Encryption 직접 구현 검토

1차 구현 권장 구조:

- `client_id_encrypted`, `client_secret_encrypted`, `access_token_encrypted`, `refresh_token_encrypted`는 `TextField` 또는 nullable `TextField`에 Fernet token 문자열만 저장한다.
- encryption/decryption은 `integrations` service 함수에서만 수행한다.
- model property, Django admin, serializer에서 자동 복호화를 제공하지 않는다.
- client_id/client_secret reveal은 본인 비밀번호 재확인과 짧은 timeout session을 통과한 경우에만 service가 허용한다.
- access_token/refresh_token reveal은 service에서도 화면용 API를 제공하지 않는다.
- 복호화 실패는 raw 예외를 사용자에게 노출하지 않고 `reset_required` 전환 후보로 처리한다.

`cryptography.Fernet` 또는 `MultiFernet`:

- Fernet은 symmetric authenticated encryption을 제공한다.
- MultiFernet은 여러 key로 decrypt를 시도하고 첫 번째 key로 encrypt/rotate할 수 있어 key rotation 설계에 유리하다.
- key rotation을 운영하려면 `key_version` 또는 `encryption_key_id` 필드와 controlled re-encryption job이 필요하다.

장점:

- 자동 복호화 위험이 낮다.
- staff/admin reveal 금지 정책을 코드 구조로 강제하기 쉽다.
- token reveal 금지 정책과 잘 맞는다.
- DB unique/index 제약과 분리해서 fingerprint/hash를 설계할 수 있다.
- 현재 환경에 `cryptography`가 이미 설치되어 있어 새 dependency 부담이 낮다.

단점:

- 직접 구현이므로 단위 테스트와 misuse 방지 테스트가 필수다.
- field validation, admin masking, serializer masking을 별도로 구현해야 한다.
- key rotation, key loss, reset_required 처리 정책을 서비스에 명시해야 한다.

테스트 전략:

- DB에 저장된 값이 평문 substring을 포함하지 않는지 확인한다.
- service decrypt 권한 실패 시 평문이 반환되지 않는지 확인한다.
- token reveal API가 존재하지 않거나 항상 거부하는지 확인한다.
- `CREDENTIAL_ENCRYPTION_KEY` 변경/손실 시 복호화 실패가 `reset_required` 경로로 처리되는지 확인한다.
- Django admin/list/detail serializer가 encrypted field 원문 또는 평문을 표시하지 않는지 확인한다.

## 8. Fingerprint/Hash 설계 검토

필요한 fingerprint/hash:

- `client_id_fingerprint`: 사용자 credential 중복 등록 방지.
- `account_hash`: 대표 Toss 계좌 중복 연결 방지.
- `external_user_hash`: 외부 사용자 identity가 제공되는 경우 소유 관계 추적.
- `actor_ref_hash`, `target_user_ref_hash`: AuditLog export/display에서 사용자 식별자 원문 노출 최소화.

권장 방식:

- `CREDENTIAL_HASH_PEPPER` 기반 HMAC-SHA256을 사용한다.
- pepper는 DB에 저장하지 않는다.
- 입력은 normalize 후 hash한다. 예: trim, provider prefix 포함, account type/scope 포함 여부 결정.
- raw account number, account sequence, order id, token, header는 저장하지 않는다.

unique constraint 설계:

- active 또는 pending_verification credential에서 `client_id_fingerprint` 중복을 막는다.
- active account에서 `account_hash`가 다른 사용자와 충돌하면 등록을 막는다.
- revoked/disconnected row는 중복 정책에서 제외할지 별도 정책이 필요하다.

pepper rotation 리스크:

- HMAC은 복호화할 수 없으므로 pepper만 바꾸면 기존 fingerprint와 신규 fingerprint 비교가 깨진다.
- rotation 시에는 기존 encrypted credential을 controlled decrypt 후 새 pepper로 fingerprint를 재계산하거나, old/new pepper 병행 검증 기간이 필요하다.
- `hash_version` 또는 `pepper_version` 필드를 두는 것이 안전하다.

## 9. SQLCipher 후보 비교

| 후보 | 방식 | Django 5.x 호환성 | 개발환경 영향 | CI 영향 | 운영 PostgreSQL 관계 | 장점 | 단점 | theStock 적합도 |
|---|---|---|---|---|---|---|---|---|
| SQLCipher CLI/공식 library | SQLite DB 파일 자체 암호화 | Django backend 별도 필요 | OS package/key 설정 필요 | CI에 SQLCipher 설치 필요 | PostgreSQL에는 비적용 | DB 파일 유출 방어 | Django ORM 연결은 별도 과제 | 별도 phase 적합 |
| `pysqlcipher3` | Python DB-API SQLCipher binding | Django backend 연결 추가 필요 | `libsqlcipher` 선행 설치 필요 | 빌드/패키지 변동성 | PostgreSQL에는 비적용 | SQLCipher 기능 노출 | maintenance/빌드 리스크 | 검증 후보 |
| `sqlcipher3-binary` / `sqlcipher3-wheels` | bundled SQLCipher wheel | Django backend 연결 추가 필요 | 설치는 쉬울 수 있음 | 플랫폼 wheel 확인 필요 | PostgreSQL에는 비적용 | OS dependency 부담 완화 가능 | Django backend 안정성 별도 확인 | PoC 후보 |
| `django-sqlcipher` 계열 backend | Django DB backend wrapper | Django 5.x 검증 필요 | settings `ENGINE` 변경 필요 | test DB 영향 큼 | PostgreSQL에는 비적용 | Django ORM 통합 목적 | 오래된 backend가 많아 위험 | 낮음~PoC |
| OS/disk encryption | filesystem/block layer encryption | Django 무관 | 인프라 설정 | CI 영향 낮음 | PostgreSQL에도 인프라 계층 적용 가능 | 운영 단순성 | app-level column 보호는 못 함 | 보조 방어 |

후보별 상세 평가:

- SQLCipher 공식 library는 SQLite 파일 유출 방어에 가장 직접적이다. 다만 Django 5.2에서 표준 `django.db.backends.sqlite3`를 그대로 쓰는 현재 구조에 바로 붙지 않는다.
- `pysqlcipher3`는 SQLCipher Python interface지만 `libsqlcipher` 선행 설치가 필요하고 현재 프로젝트에는 설치되어 있지 않다.
- `sqlcipher3-binary` 또는 wheel 계열은 설치 편의성이 있을 수 있으나, Django backend로 안정적으로 연결하는 검증이 별도로 필요하다.
- `django-sqlcipher` 계열 backend는 settings 변경, test database, migration, deploy 영향이 커서 바로 적용하면 위험하다. Django 5.x 호환성 검증이 선행되어야 한다.
- PostgreSQL 운영 전환 시 SQLCipher는 적용 대상이 아니다. 이 경우 인프라/디스크/backup 암호화와 application-level encrypted field를 유지한다.

## 10. SQLCipher와 Credential Column Encryption 역할 분리

- SQLCipher는 SQLite DB 파일 전체를 보호하는 계층이다.
- application-level encryption은 credential column 자체를 ciphertext로 저장하는 계층이다.
- 둘은 대체 관계가 아니라 보완 관계다.
- SQLCipher만으로 “SQL query로 credential 평문이 안 보인다”는 요건을 만족하지 않는다.
- 애플리케이션이 DB를 열고 평문 column에 credential을 저장하면 SQLCipher DB에서도 SQL query 결과는 평문일 수 있다.
- 따라서 Toss credential은 SQLCipher 적용 여부와 관계없이 application-level encrypted field 또는 service-layer encryption으로 저장해야 한다.
- PostgreSQL 전환 시 SQLCipher는 제외되지만 field encryption은 계속 유지한다.

## 11. Secret/Key Management 초안

필수 key/env:

- `CREDENTIAL_ENCRYPTION_KEY`: credential encryption/decryption용. DB에 저장하지 않는다.
- `CREDENTIAL_HASH_PEPPER`: fingerprint/HMAC용. DB에 저장하지 않는다.
- `SQLCIPHER_DATABASE_KEY`: SQLite SQLCipher DB file encryption용. DB에 저장하지 않는다.
- `DJANGO_SECRET_KEY`: Django signing/security용. credential encryption key와 혼용하지 않는다.
- `DATABASE_URL` 또는 `POSTGRES_*`: 운영 PostgreSQL 설정용.
- 기존 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT_ID`: legacy/global credential로 staff-only transition 또는 운영 점검에만 제한하고 일반 사용자 기능에서는 사용하지 않는다.

.env 유지/제거 대상:

- `.env` 파일 자체는 삭제 대상이 아니다.
- `.env` 또는 Secret Manager에는 Django secret, DB 접속 설정, encryption key, hash pepper, SQLCipher key 같은 운영 secret을 둘 수 있다.
- 일반 사용자 기능용 전역 Toss credential은 제거 대상이다.

key rotation 초안:

- encryption key는 MultiFernet key list와 `key_version` 필드로 rotation을 검토한다.
- 새 key는 encrypt primary로 사용하고 old key는 decrypt fallback으로 유지한다.
- controlled rotation job으로 ciphertext를 새 key로 재암호화한 뒤 old key를 제거한다.
- hash pepper rotation은 기존 hash 재계산이 필요하므로 별도 계획이 필요하다.

손망실/복호화 실패:

- 운영자 복구를 제공하지 않는다.
- 해당 credential은 `reset_required`로 전환하고 encrypted 값은 삭제 또는 crypto-shredding한다.
- 사용자가 다시 등록하도록 안내한다.

## 12. 보안 리스크와 완화책

- admin 자동 복호화 노출 위험: model field 자동 복호화 패키지를 1차에서 피하고 service-layer decrypt만 허용한다.
- logs/traceback secret 유출 위험: raw Toss request/response, token, header, account, order id는 logging 금지한다.
- test fixture secret 유출 위험: 실제 credential fixture 금지, fake placeholder만 사용한다.
- DB dump/export 위험: ciphertext도 민감정보로 취급한다. export 권한, 보관 기간, 폐기 정책이 필요하다.
- key loss 위험: 복구 불가 정책을 명확히 하고 `reset_required` + 사용자 재등록 절차를 마련한다.
- key leak 위험: incident severity를 높게 보고, token revocation, credential reset, rotation을 수행한다.
- SQLCipher key와 credential encryption key 혼동 위험: 목적과 보관 위치를 문서/코드 이름으로 분리한다.
- 중복 등록 우회 위험: `client_id_fingerprint`, `account_hash`에 active/pending 중복 검사를 둔다.
- token reveal 위험: token decrypt service는 provider 호출용 내부 API만 제공하고 화면/API reveal 경로를 만들지 않는다.
- staff 내부자 리스크: staff도 secret/token reveal 불가, 민감 조회는 `IntegrationAuditLog`에 남긴다.

## 13. 권장 구현 방향

### 13.1 1차 권장안

- Encrypted credential 저장 방식: `cryptography.Fernet` 또는 `MultiFernet` 기반 service-layer encryption 직접 구현. 모델에는 ciphertext `TextField`만 저장한다.
- Fingerprint/hash 방식: `CREDENTIAL_HASH_PEPPER` 기반 HMAC-SHA256. `client_id_fingerprint`, `account_hash`, audit ref hash를 별도 저장한다.
- SQLCipher 처리: 1차 credential 모델 구현의 blocker로 두지 않는다. SQLite DB 파일 보호 hardening phase에서 별도 PoC로 검증한다.
- Toss 인증 모델 처리: 로컬 근거상 client credentials 흐름은 확인되지만 발급 단위는 공식 확인 전까지 확정하지 않는다. 일반 사용자 구현은 read-only와 reset 가능한 구조부터 시작한다.
- key/env 처리: `CREDENTIAL_ENCRYPTION_KEY`, `CREDENTIAL_HASH_PEPPER`, `SQLCIPHER_DATABASE_KEY`는 DB에 저장하지 않고 .env 또는 Secret Manager에서 관리한다. 기존 전역 `TOSS_INVEST_*`는 일반 사용자 기능에서 사용하지 않는다.

### 13.2 보류/후속 과제

- user-only encryption
- PIN/2FA 기반 재인증
- 다계좌 연결
- 전역 audit 앱
- Android API
- Ollama 예측
- SQLCipher 실제 적용
- key rotation 자동화
- credential reveal session timeout UX

## 14. 구현 전 Open Questions

- Toss증권 Open API client_id/client_secret 발급 단위 최종 확인 필요 여부: 필요.
- encrypted field 패키지 최종 선택: 1차는 직접 구현 권장이나 보안 리뷰 후 확정 필요.
- SQLCipher driver/backend 최종 선택: `pysqlcipher3`, `sqlcipher3-binary`, Django backend wrapper 각각 PoC 필요.
- `CREDENTIAL_ENCRYPTION_KEY` 포맷과 생성 방식: Fernet key list, base64, key id/version 정책 확정 필요.
- key rotation 방식: MultiFernet rotate job, migration-less rotation job, 실패 복구 정책 필요.
- `CREDENTIAL_HASH_PEPPER` rotation 시 기존 fingerprint 처리: decrypt 후 재hash 또는 old/new pepper 병행 정책 필요.
- `SQLCIPHER_DATABASE_KEY` backup/restore 정책: key 보관, 복구 테스트, 분실 시 폐기 정책 필요.
- prod PostgreSQL 전환 시 운영 정책: field encryption 유지, backup encryption, Secret Manager, key rotation 절차 필요.
- admin 마스킹 구현 방식: encrypted field raw/ciphertext/평문 모두 노출하지 않는 admin form/list 설계 필요.
- credential reveal session/timeout 방식: 비밀번호 재확인 후 reveal duration, audit event, 재확인 실패 lockout 정책 필요.

## 15. 다음 Codex 작업 제안

1. docs/54에 docs/55 조사 결론 반영
2. integrations 앱 skeleton 및 암호화 유틸 구현 설계
3. TossInvestCredential/IntegrationAuditLog 모델 구현
4. credential 등록/수정/삭제/reveal 화면 구현
5. Toss provider user-scoped resolver 리팩터링
6. SQLCipher 별도 적용 검증

## 16. 조사한 외부 자료

- `cryptography` Fernet/MultiFernet 공식 문서: https://cryptography.io/en/latest/fernet/
  확인 날짜: 2026-06-17. Fernet symmetric encryption, MultiFernet key rotation, `rotate()` 동작을 확인했다.
- SQLCipher 공식 사이트: https://www.zetetic.net/sqlcipher/
  확인 날짜: 2026-06-17. SQLite용 transparent full database encryption, Community/Commercial/Enterprise 구분, DB 파일 암호화 역할을 확인했다.
- SQLCipher GitHub: https://github.com/sqlcipher/sqlcipher
  확인 날짜: 2026-06-17. SQLCipher가 SQLite fork이며 AES 기반 DB file encryption과 key derivation/tamper 관련 기능을 제공한다는 설명을 확인했다.
- `pysqlcipher3` PyPI: https://pypi.org/project/pysqlcipher3/
  확인 날짜: 2026-06-17. Python DB-API interface, `libsqlcipher` 선행 설치 필요, 2023년 release 이력을 확인했다.
- `sqlcipher3-wheels` PyPI: https://pypi.org/project/sqlcipher3-wheels/
  확인 날짜: 2026-06-17. bundled/binary SQLCipher wheel 후보와 system SQLCipher build 방식을 확인했다.
- `django-fernet-encrypted-fields` PyPI/GitHub: https://pypi.org/project/django-fernet-encrypted-fields/
  확인 날짜: 2026-06-17. `EncryptedTextField`, `SALT_KEY` list rotation, `SECRET_KEY_FALLBACKS` 지원 설명을 확인했다.
- `django-fernet-fields` PyPI: https://pypi.org/project/django-fernet-fields/
  확인 날짜: 2026-06-17. 2019년 release, Fernet model field, SQLite/PostgreSQL/MySQL tested 설명을 확인했다.
- `django-encrypted-model-fields` PyPI: https://pypi.org/project/django-encrypted-model-fields/
  확인 날짜: 2026-06-17. cryptography 기반 Django field wrapper, release 2022년, Django classifier 범위를 확인했다.
- `django-cryptography` PyPI/문서: https://pypi.org/project/django-cryptography/
  확인 날짜: 2026-06-17. `encrypt()` wrapper 방식과 자동 양방향 복호화 성격을 확인했다.

## 17. 수행한 명령

- `pwd; git status --short; ls docs | sort | tail -40`
- `python --version`
- `python -c "import django; print(django.get_version())"`
- `python -c "import rest_framework; print(rest_framework.VERSION)"`
- `sed -n '1,240p' requirements.txt`
- `test -f docs/54_technical_architecture_and_toss_credential_design.md && echo "docs/54 exists" || echo "docs/54 missing"`
- `test -f docs/55_security_foundation_research_report.md && echo "docs/55 exists" || echo "docs/55 missing"`
- `rg -n "TOSS_INVEST_CLIENT_ID|TOSS_INVEST_CLIENT_SECRET|TOSS_INVEST_ACCOUNT_ID|CREDENTIAL_ENCRYPTION_KEY|CREDENTIAL_HASH_PEPPER|SQLCIPHER_DATABASE_KEY" . --glob '!**/.env' --glob '!**/__pycache__/**' --glob '!staticfiles/**' --glob '!media/**' --glob '!backups/**'`
- `sed -n '1,260p' stock_service/settings/base.py`
- `sed -n '1,260p' stock_service/settings/prod.py`
- `sed -n '1,260p' data_pipeline/providers/toss_auth.py`
- `sed -n '1,340p' data_pipeline/providers/toss_client.py`
- `sed -n '1,380p' data_pipeline/providers/toss_provider.py`
- `find docs/toss_OpenAPI_guide -maxdepth 2 -type f -print -exec sed -n '1,220p' {} \;`
- `python manage.py check`
- `python -c "import importlib.util; mods=['cryptography','encrypted_fields','fernet_fields','django_cryptography','encrypted_model_fields','pysqlcipher3','sqlcipher3']; [print(f'{m}:', 'installed' if importlib.util.find_spec(m) else 'not_installed') for m in mods]"`
- `rg -n "client_id|client_secret|TOSS_INVEST|X-Tossinvest|Authorization|token|account|grant_type|client_credentials" data_pipeline stock_service docs/toss_OpenAPI_guide deploy/production --glob '!**/.env' --glob '!**/__pycache__/**' | head -260`
- `sed -n '1,220p' docs/52_user_account_mapping_design.md`
- `sed -n '1,220p' docs/18_privacy_and_financial_data_policy.md`
- `sed -n '1,220p' docs/21_toss_openapi_security_checklist.md`
- `sed -n '1,220p' docs/10_toss_openapi_provider_design.md`
- 외부 자료 web search/open: PyPI, GitHub, SQLCipher 공식 문서, cryptography 공식 문서

## 18. 변경 파일

- 이번 단계에서 생성/변경한 파일: `docs/55_security_foundation_research_report.md`
- 다른 코드 파일, settings, migration, requirements, .env는 변경하지 않는다.
- 작업 시작 전부터 존재한 다른 docs 변경과 untracked `docs/54_technical_architecture_and_toss_credential_design.md`는 이번 단계의 변경이 아니며 되돌리지 않는다.
