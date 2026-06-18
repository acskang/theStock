# Toss Credential Issuance Model Research Report

조사일: 2026-06-17

## 1. 목적

이 문서는 Toss증권 Open API의 `client_id` / `client_secret` 발급 단위와 인증 모델을 공식 근거 기준으로 확인하고, theStock의 사용자별 Toss credential 1:1 구조에 미치는 영향을 정리한다.

이번 단계는 구현 전 조사/문서화 단계다. Python/Django 소스코드, settings, models, views, serializers, urls, templates, static asset, migration, requirements, `.env`, DB schema는 변경하지 않는다. 실제 Toss API 호출, token 발급, credential/account/order 값 출력도 수행하지 않는다.

## 2. 결론 요약

- 판정: `MODEL_A_PERSONAL_CREDENTIAL`
- 판정 신뢰도: medium
- 공식 근거:
  - Toss증권 공식 Open API 개요 문서는 사용자가 토스증권 WTS에 로그인한 뒤 설정의 Open API 메뉴에서 `client_id`와 `client_secret`을 발급받는 흐름을 설명한다.
  - Toss증권 공식 개발자 자료는 모든 API가 OAuth2 client credentials 방식으로 발급받은 `access_token`을 사용한다고 설명한다.
  - 공식 OpenAPI spec은 `oauth2ClientCredentials` security scheme, `/oauth2/token`의 client credentials flow, `Authorization: Bearer` 사용, 계좌/자산/주문 API의 `X-Tossinvest-Account` header 사용을 정의한다.
  - 공식 spec은 `refresh_token`을 제공하지 않고 만료 시 같은 token endpoint로 재발급한다고 설명한다.
- 구현 영향:
  - 현재 `integrations.TossInvestCredential`의 사용자별 `client_id_ciphertext` / `client_secret_ciphertext` 저장 방향은 공식 인증 흐름과 대체로 맞다.
  - `access_token_ciphertext`는 필요하지만 `refresh_token_ciphertext`는 공식 spec 기준 1차 구현에서 사용하지 않을 가능성이 높다.
  - `account_hash` / `account_masked`는 `X-Tossinvest-Account`에 필요한 account sequence를 원문 저장하지 않기 위한 필수 구조로 유지한다.
  - 단, 외부 서비스인 theStock이 사용자의 Toss client secret을 수집/저장해도 되는지는 공식 약관/승인 확인이 필요하다. 이 항목은 public production rollout 전 blocker다.
- 다음 단계 권고:
  - Option 1. 사용자 credential 입력 UI 진행 가능.
  - 단, 실제 Toss provider user-scoped resolver와 public 운영 배포 전에는 Toss증권 공식 약관/신청 정책에서 외부 서비스의 사용자 credential 보관 허용 여부를 확인해야 한다.

## 3. 현재 로컬 구현 조사 결과

### 현재 `toss_auth.py` 인증 흐름

- `data_pipeline/providers/toss_auth.py`는 token endpoint 기본 경로를 `/oauth2/token`으로 둔다.
- token 요청은 OAuth2 client credentials 흐름이다.
- 요청 form에는 `grant_type=client_credentials`, settings 기반 `client_id`, `client_secret`이 사용된다.
- 응답에서 `access_token`, `token_type`, `expires_in`을 읽는다.
- 로컬 코드에는 `authorization code` flow나 `refresh_token` 저장/갱신 흐름이 없다.

### 현재 `toss_client.py` header/token 사용 방식

- `TossOpenApiClient`는 요청마다 `Authorization: Bearer <token>` header를 구성한다.
- account-required 요청에서는 명시 account 인자 또는 settings의 `TOSS_INVEST_ACCOUNT_ID`를 사용해 `X-Tossinvest-Account` header를 추가한다.
- header repr/masking 경로는 Authorization과 account header 원문 노출을 피하는 방향이다.

### 현재 settings `TOSS_INVEST_*` 사용 방식

- `stock_service/settings/base.py`는 env에서 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT_ID`를 읽는다.
- 현재 구현은 사용자별 DB credential이 아니라 앱 전역 settings credential 구조다.
- `deploy/production/thestock.env.example`에는 해당 key 이름이 비어 있는 예시로 존재한다.

### 현재 `data_pipeline` provider 구조

- `data_pipeline/providers/toss_provider.py`는 accounts, holdings, orders read-only 조회를 제공한다.
- accounts API는 token만 사용한다.
- holdings/order history 계열은 account header가 필요하다.
- provider capability는 주문 생성/정정/취소를 지원하지 않는 read-only 성격이다.

### 현재 `integrations` 모델/service 구조

- Phase 3~5 기준으로 `integrations`에는 service-layer encryption, HMAC-SHA256 fingerprint/hash, masking utility, `TossInvestCredential`, `IntegrationAuditLog`, credential lifecycle service가 존재한다.
- `TossInvestCredential`은 `client_id_ciphertext`, `client_secret_ciphertext`, `access_token_ciphertext`, `refresh_token_ciphertext`, `client_id_fingerprint`, `account_hash`, `account_masked`, status lifecycle을 가진다.
- `register_or_replace_pending_credential`은 사용자 입력 credential을 encrypted 저장하고 `pending_verification` 상태로 둔다.
- `mark_credential_verification_success`는 미래의 read-only 검증 결과를 받아 `account_hash` / `account_masked` 저장 후 active 전환하는 구조다.

### 현재 로컬 docs 기준 판정 가능 여부

- 로컬 `docs/toss_OpenAPI_guide/`와 코드만으로도 OAuth2 client credentials 방식, `access_token`, `X-Tossinvest-Account` 사용은 확인된다.
- 하지만 로컬 자료만으로는 `client_id` / `client_secret`의 발급 단위가 개인 투자자별인지, 서비스 앱 단위인지 완전히 확정하기 어렵다.
- 외부 공식 문서 조사 결과를 합치면 개인 WTS 로그인 후 발급받는 credential 모델로 보는 것이 가장 타당하다.

## 4. 공식 문서 조사 결과

| 출처명 | URL | 확인일 | 접근 가능 여부 | 확인한 내용 | 발급 단위 관련 근거 | 인증 방식 관련 근거 | 계좌 header/account 식별 관련 근거 |
|---|---|---:|---|---|---|---|---|
| Toss증권 Open API 공식 페이지 | https://corp.tossinvest.com/ko/open-api | 2026-06-17 | 가능 | Toss증권 Open API 서비스 소개. 검색 결과와 페이지 메타 정보에서 토스증권 계좌 보유 투자자 대상 사전 신청 흐름 확인 | 개인 투자자/고객 대상 신청 흐름을 시사 | 상세 token flow는 별도 개발자 문서가 근거 | 상세 account header는 별도 개발자 문서가 근거 |
| Toss증권 Open API 이용 약관 | https://home.tossinvest.com/ko/terms/v2?id=752 | 2026-06-17 | 일부 가능 | 공식 약관 페이지. 검색 결과 snippet에서 고객이 Open API 서비스를 신청하면 보안코드가 발급된다는 설명 확인 | 고객 신청 후 보안코드 발급을 시사. 본문 동적 페이지라 로컬 추출은 제한됨 | 상세 token flow는 별도 개발자 문서가 근거 | 상세 account header는 별도 개발자 문서가 근거 |
| Toss증권 개발자센터 | https://developers.tossinvest.com/docs | 2026-06-17 | 가능 | 공식 개발자센터 진입점. Open API 가이드와 연동 문서 제공 | 발급 상세는 overview 문서가 근거 | 개발자 문서 세트가 공식 근거 | 개발자 문서 세트가 공식 근거 |
| Toss증권 개발자센터 llms.txt | https://developers.tossinvest.com/llms.txt | 2026-06-17 | 가능 | 공식 문서 색인. REST API, account/holdings/orders, OAuth2 client credentials, header 개요 확인 | 직접 발급 단위 설명은 제한적 | 모든 API가 OAuth2 client credentials grant로 발급받은 access token을 사용한다고 설명 | account/asset/order API는 `Authorization`과 `X-Tossinvest-Account` header가 필요하다고 설명 |
| Open API overview | https://openapi.tossinvest.com/openapi-docs/overview.md | 2026-06-17 | 가능 | 공식 개요. 본인 계좌의 보유 주식/주문 관리, 시작하기, token 발급, API 호출 설명 | WTS 로그인 후 설정 > Open API 메뉴에서 `client_id` / `client_secret` 발급 | `POST /oauth2/token`과 Client Credentials Grant 사용 | 계좌/자산/주문 API 호출 시 `X-Tossinvest-Account`에 account sequence 사용 |
| Open API reference README | https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md | 2026-06-17 | 가능 | 공식 API reference index | 발급 단위 직접 설명은 overview가 근거 | endpoint 목록과 인증 문서 연결 | account/order 계열 endpoint 확인 |
| OpenAPI JSON spec | https://openapi.tossinvest.com/openapi-docs/latest/openapi.json | 2026-06-17 | 가능 | OpenAPI 3.1.0 spec. security scheme, token endpoint, account/order header 정의 | 직접 발급 단위보다는 client credentials flow와 client 기준 token 정책 확인 | `oauth2ClientCredentials`, `clientCredentials`, tokenUrl `/oauth2/token`, `access_token` 사용. `refresh_token`은 제공하지 않음 | 계좌 목록은 사용자 본인 계좌 목록이고, account sequence를 `X-Tossinvest-Account`에 사용 |

비공식 블로그, GitHub, 커뮤니티 글은 결론의 주 근거로 사용하지 않았다.

## 5. 인증 모델 판정

### 5.1 MODEL_A_PERSONAL_CREDENTIAL

- 가능성: 높음
- 근거:
  - 공식 overview는 WTS 로그인 후 Open API 메뉴에서 `client_id` / `client_secret`을 발급받는 절차를 설명한다.
  - 공식 문서의 account API 설명은 사용자 본인의 계좌 목록을 반환하고, 계좌/자산/주문 API에는 account sequence 기반 `X-Tossinvest-Account`가 필요하다고 설명한다.
  - 공식 OpenAPI spec은 서비스 앱 OAuth redirect가 아니라 client credentials grant를 정의한다.
  - `refresh_token` 없이 client credentials로 `access_token`을 재발급하는 구조는 사용자가 발급받은 API key pair를 서버/CLI가 보유하고 호출하는 모델과 잘 맞는다.
- 반박 근거:
  - 공식 문서에서 “외부 서비스가 다수 사용자의 client_secret을 저장해도 된다”는 권한/약관 문구는 이번 조사에서 직접 확인하지 못했다.
  - 사전 신청, 계좌 인증, 약관 동의 범위에 따라 외부 서비스 내 credential 보관이 제한될 수 있다.
- theStock 영향:
  - `TossInvestCredential`의 `client_id_ciphertext` / `client_secret_ciphertext` 구조는 유지 가능하다.
  - 사용자 credential 입력 UI는 설계상 진행 가능하지만, public production 전에 공식 약관/허용 범위 확인이 필요하다.
  - provider user-scoped resolver는 user credential을 복호화해 read-only token 발급 후 account header를 사용하는 구조로 설계할 수 있다.

### 5.2 MODEL_B_SERVICE_APP_OAUTH

- 가능성: 낮음
- 근거:
  - 공식 spec에서 authorization code flow, redirect/callback, 사용자 동의 screen flow는 확인되지 않았다.
  - `oauth2ClientCredentials`만 security scheme으로 확인된다.
- 반박 근거:
  - 공식 문서가 로그인/신청자별 상세 정책을 별도 화면에서 제공할 수 있어, 서비스 앱/제휴사 모델이 완전히 없다고 단정하지는 않는다.
- theStock 영향:
  - 이 모델이 확인되면 사용자 `client_id` / `client_secret` 입력 UI는 중단해야 한다.
  - `TossInvestCredential`은 app credential이 아니라 사용자 token/account identity 저장 구조로 조정해야 한다.

### 5.3 MODEL_C_SERVICE_APP_WITH_ACCOUNT_HEADER

- 가능성: 중간 이하
- 근거:
  - 현재 로컬 구현은 전역 `TOSS_INVEST_CLIENT_ID` / `TOSS_INVEST_CLIENT_SECRET`으로 token을 받고, `TOSS_INVEST_ACCOUNT_ID` 또는 account API fallback으로 account header를 사용하는 형태다.
  - 공식 문서도 account/order 계열 API에 `X-Tossinvest-Account` header를 요구한다.
- 반박 근거:
  - 공식 overview는 WTS 로그인 사용자의 Open API 메뉴에서 credential을 발급받는 절차를 설명하므로, 단순 서비스 앱 credential + 사용자 account header 모델로만 보기는 어렵다.
  - account sequence는 token 소유자 본인 계좌 범위 안에서 사용되는 값으로 해석하는 것이 자연스럽다.
- theStock 영향:
  - 이 모델이 확인되면 account ownership verification이 가장 큰 blocker다.
  - account header를 사용자에게 직접 입력시키는 구조는 위험하며, 공식 계좌 조회 flow로 대표 계좌를 선택하게 해야 한다.

### 5.4 MODEL_D_PARTNER_OR_INSTITUTIONAL_ONLY

- 가능성: 낮음~중간
- 근거:
  - 공식 페이지와 약관에는 신청/사전신청 흐름이 존재한다.
  - 공식 문서 접근은 공개적으로 가능하다.
- 반박 근거:
  - 공식 페이지는 토스증권 계좌가 있는 투자자 대상 신청 흐름을 시사한다.
  - WTS 로그인 후 client 발급 절차가 문서화되어 있다.
- theStock 영향:
  - 만약 제휴/기관 전용 조건이 확인되면 일반 사용자 self-service credential 등록 UI는 보류해야 한다.

### 5.5 MODEL_E_INCONCLUSIVE

- 불확실한 항목:
  - 외부 서비스가 사용자별 `client_secret`을 저장하는 것이 약관상 허용되는지.
  - 개인 사용자 self-service 발급이 모든 사용자에게 일반 제공되는지, 사전 신청/순차 개방/계좌 인증 조건이 있는지.
  - read-only scope와 주문 scope가 발급/약관/콘솔에서 분리되는지.
- 추가 확인 방법:
  - Toss증권 Open API 신청 화면 또는 WTS 설정 > Open API 메뉴에서 발급 단위와 약관을 직접 확인한다.
  - Toss증권 공식 고객/제휴 문의로 외부 서비스의 사용자 credential 보관 가능 여부를 확인한다.
  - 공식 OpenAPI 변경 이력에서 refresh token 또는 authorization code flow 추가 여부를 재확인한다.
- 구현 보류 범위:
  - public production rollout.
  - 실제 provider user-scoped resolver의 Toss API 호출 활성화.
  - 일반 사용자에게 Toss credential 입력을 요구하는 정식 운영 화면 공개.

## 6. theStock 현재 구현과의 적합성 분석

| 항목 | 판정 | 이유 |
|---|---|---|
| `integrations.TossInvestCredential.user` OneToOne | 그대로 유지 | 1차 대표 credential 1개 모델과 공식 client credentials 흐름이 맞는다. |
| `client_id_ciphertext` | 그대로 유지 | 사용자가 발급받은 `client_id`를 평문 저장하지 않는 구조가 필요하다. |
| `client_secret_ciphertext` | 그대로 유지 | `client_secret`은 secret이므로 service-layer encryption 저장이 필요하다. |
| `access_token_ciphertext` | 그대로 유지 | 발급된 `access_token`을 저장/캐시할 경우 ciphertext 저장이 필요하다. |
| `refresh_token_ciphertext` | 수정 필요 가능 | 공식 spec은 `refresh_token` 미제공으로 확인된다. 필드는 미래 호환성으로 남길 수 있으나 1차 구현에서는 사용하지 않을 가능성이 높다. |
| `client_id_fingerprint` | 그대로 유지 | 중복 등록 방지에 필요하다. |
| `account_hash` | 그대로 유지 | `X-Tossinvest-Account` 원문 저장 금지와 중복 계좌 연결 방지에 필요하다. |
| `account_masked` | 그대로 유지 | 사용자 화면 표시용 safe account label이 필요하다. |
| `status=pending_verification/active/reset_required` | 그대로 유지 | 입력 후 read-only 검증 전/후 상태 전환에 적합하다. |
| `register_or_replace_pending_credential` | 그대로 유지 | 공식 모델이 개인 credential 발급이면 현재 lifecycle 구조가 적합하다. |
| `reveal_client_credentials` | 그대로 유지 | `client_id` / `client_secret` 본인 재인증 reveal은 내부 정책상 허용하되 짧은 시간만 가능해야 한다. |
| `mark_credential_verification_success` | 그대로 유지 | account sequence를 원문 저장하지 않고 `account_hash` / `account_masked`만 남기는 구조가 필요하다. |
| `mark_credential_verification_failure` | 그대로 유지 | 인증 실패 시 `reset_required`, transient 실패 시 pending 유지 정책이 적합하다. |
| 전역 `TOSS_INVEST_CLIENT_ID/SECRET` 제거 정책 | 그대로 유지 | 일반 사용자 기능에서는 전역 credential 공유 금지. staff-only/transition 용도로만 제한한다. |
| 사용자 credential 입력 화면 | 공식 확인 전 보류 일부 | MODEL_A medium 판정이므로 구현은 가능하지만, public 운영 전 약관/저장 허용 확인이 필요하다. |
| provider user-scoped resolver | 공식 확인 전 보류 일부 | 설계/구현은 가능하나 실제 Toss 호출 활성화 전 약관/신청 상태 확인 필요. |
| read-only holdings/order history sync | 공식 확인 전 보류 일부 | read-only부터 진행하는 방향은 맞지만 실제 sync 활성화는 credential 발급/허용 범위 확인 후 진행한다. |

## 7. 다음 구현 단계 결정

### Option 1. 사용자 credential 입력 UI 진행 가능

조건:

- `MODEL_A_PERSONAL_CREDENTIAL`이 medium 신뢰도로 확인됨.
- 공식 overview와 OpenAPI spec이 개인 WTS 발급, OAuth2 client credentials, `X-Tossinvest-Account` 구조를 뒷받침함.

다음 작업:

- credential 등록/수정/삭제/reveal Django Template 화면 구현.
- 화면은 read-only 검증 대기 상태까지만 연결하고, 실제 Toss API 호출은 명시적인 verification 단계로 분리한다.
- 사용자에게 `client_id` / `client_secret` 저장 방식, 암호화, reveal 제한, reset_required 정책, 주문 API/자동매매 금지를 명확히 고지한다.
- provider 검증은 공식 API sandbox/test 환경 또는 실제 사용자 동의/약관 확인 후 진행한다.

주의:

- 외부 서비스가 사용자 `client_secret`을 저장하는 것이 허용되는지 확인하기 전까지 public production rollout은 blocker로 둔다.

### Option 2. OAuth/connect flow 재설계 필요

조건:

- 향후 공식 확인에서 `MODEL_B_SERVICE_APP_OAUTH`가 확인되는 경우.

다음 작업:

- 사용자 `client_id` / `client_secret` 입력 UI 중단.
- OAuth redirect/callback/token storage 설계.
- `TossInvestCredential` 모델을 service app credential + 사용자 token/account identity 중심으로 조정.
- 전역 app credential은 `.env` 또는 Secret Manager에 유지.

### Option 3. account ownership 검증 설계 필요

조건:

- 향후 공식 확인에서 `MODEL_C_SERVICE_APP_WITH_ACCOUNT_HEADER`가 확인되는 경우.

다음 작업:

- 사용자별 account ownership verification 설계.
- account header를 사용자가 직접 입력하게 할지 금지하고, 공식 계좌 조회 flow로 선택하게 할지 확인.
- 전역 credential과 사용자 계좌 매핑 보안을 재설계.

### Option 4. 공식 확인 전 provider/UI 보류

조건:

- 향후 공식 확인에서 `MODEL_D_PARTNER_OR_INSTITUTIONAL_ONLY` 또는 `MODEL_E_INCONCLUSIVE`가 확인되는 경우.

다음 작업:

- 사용자 credential 입력 UI 보류.
- 공식 Toss증권 Open API 신청/문서 접근 확보.
- docs/54/55에 blocker 유지.
- 이미 구현된 integrations 보안 기반은 유지하되 provider/UI는 미진행.

## 8. 보안/컴플라이언스 리스크

- 공식 발급 단위 오해로 인한 잘못된 credential 수집 위험.
- 사용자가 입력하면 안 되는 service app secret을 수집할 위험.
- OAuth consent가 필요한데 `client_secret` 입력 UI를 만들 위험.
- account ownership 검증 없이 계좌 header를 저장할 위험.
- 전역 credential로 일반 사용자 데이터를 조회할 위험.
- 공식 약관/개방 범위 미확인 상태에서 서비스화할 위험.
- `client_id` / `client_secret`이 개인별 credential이어도 외부 서비스 보관 허용 여부는 별도 확인이 필요하다.
- DB에는 ciphertext만 저장해야 하며 SQL query로 평문 credential이 보여서는 안 된다.
- `access_token` / `refresh_token`은 사용자 본인에게도 화면 reveal 금지다.
- staff/admin/superuser도 secret/token 평문 reveal 금지다.
- 주문 API/자동매매 금지 정책을 계속 유지해야 한다.

## 9. Open Questions

- Toss증권 Open API `client_id` / `client_secret` 발급 단위 최종 확인.
- 개인 사용자 self-service 발급 가능 여부와 사전 신청/순차 개방 조건.
- 서비스 앱/제휴사 앱 등록 방식이 별도로 존재하는지 여부.
- 사용자 동의/authorization code flow 존재 여부. 현재 공식 spec에서는 확인되지 않음.
- `refresh_token` 발급 여부. 현재 공식 spec 기준 미제공으로 확인됨.
- 계좌 목록 조회/대표 계좌 선택 flow의 운영 UI 기준.
- `X-Tossinvest-Account` 또는 계좌 header 발급/확인 방식.
- sandbox/test API 존재 여부.
- API scope 단위와 read-only scope 존재 여부.
- 주문 scope와 read-only scope 분리 여부.
- 약관상 외부 서비스가 사용자 credential을 저장해도 되는지 여부.
- theStock이 사용자 credential을 저장하는 경우 필요한 동의/고지/삭제/감사 정책.

## 10. 수행한 명령

실제로 실행한 명령:

- `git status --short`
- `sed -n '1,260p' data_pipeline/providers/toss_auth.py`
- `sed -n '1,340p' data_pipeline/providers/toss_client.py`
- `sed -n '1,360p' data_pipeline/providers/toss_provider.py`
- `sed -n '1,220p' stock_service/settings/base.py`
- `sed -n '1,220p' deploy/production/thestock.env.example`
- `find docs/toss_OpenAPI_guide -maxdepth 2 -type f -print`
- `rg -n "client_id|client_secret|TOSS_INVEST|X-Tossinvest|Authorization|token|account|OAuth|scope|refresh" docs/toss_OpenAPI_guide data_pipeline stock_service deploy/production integrations --glob '!**/.env'`
- 공식 문서 검색:
  - `토스증권 Open API client_id client_secret 발급 공식`
  - `Toss Securities Open API client_id client_secret official`
  - `site:tossinvest.com Open API client_secret 토스증권`
  - `site:corp.tossinvest.com Open API client_id`
  - `site:developers.tossinvest.com docs 토스증권 Open API 인증`
- 공식 문서 URL 확인:
  - `https://corp.tossinvest.com/ko/open-api`
  - `https://home.tossinvest.com/ko/terms/v2?id=752`
  - `https://developers.tossinvest.com/docs`
  - `https://developers.tossinvest.com/llms.txt`
  - `https://openapi.tossinvest.com/openapi-docs/overview.md`
  - `https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md`
  - `https://openapi.tossinvest.com/openapi-docs/latest/openapi.json`
- `python - <<'PY' ... urllib.request ... PY`

secret 값이 출력될 수 있는 `.env` 파일은 열람하지 않았다. 로컬 command 출력의 공식 예시값 또는 placeholder는 문서에 원문으로 옮기지 않았다.

## 11. 변경 파일

- 이번 단계에서 변경된 파일은 `docs/56_toss_credential_issuance_model_research_report.md` 하나여야 한다.
- Python/Django 코드, settings, requirements, migration, template, static, `.env`는 변경하지 않는다.
