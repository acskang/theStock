# User-Account Mapping Design

## 1. 목적

이 문서는 향후 Toss holdings, Order History, portfolio, 손익 분석을 일반 사용자 기능으로 확장하기 전에 필요한 user-account mapping 설계를 정리한다.

이번 단계는 설계 문서 작성만 수행한다. Python 코드, Django model, migration, template, JavaScript, API response, settings, 운영 DB schema는 변경하지 않는다. 실제 Toss API 호출, command 실행, staff-only smoke, 저장 command, 주문 생성/정정/취소 API 구현 또는 호출도 수행하지 않는다.

## 2. 현재 상태와 문제 정의

핵심 문제:

```text
현재 Toss credential은 앱 전역 .env credential이다.
현재 request.user와 Toss account의 소유 관계가 없다.
따라서 일반 사용자에게 Toss holdings/order history/reconciliation을 노출하면 안 된다.
```

세부 문제:

- 하나의 Toss account가 어떤 Django user의 것인지 알 수 없다.
- 여러 사용자가 있을 때 같은 Toss 계좌 데이터가 잘못 노출될 위험이 있다.
- accountNo/accountSeq 원문은 저장하거나 출력하면 안 된다.
- 거래 내역은 보유 잔고보다 민감도가 높다.
- user-account mapping 없이 Portfolio/손익 분석에 Toss holdings 또는 Order History를 자동 연결하면 위험하다.
- staff-only 운영 조회는 가능하지만 일반 사용자 기능과 분리해야 한다.

현재 안전 기준:

- Order History API/화면/reconciliation은 staff-only다.
- Order History 조회는 `GET /api/v1/orders` read-only만 사용한다.
- 주문 생성/정정/취소 API는 구현되어 있지 않고 계속 비활성이다.
- raw response, account 원문, token, header, order id 원문은 노출하지 않는다.

## 3. 설계 목표와 비목표

목표:

- Django User와 Toss account reference의 안전한 연결
- accountNo/accountSeq 원문 저장 금지
- 사용자별 holdings/order history 조회 범위 제한
- 일반 사용자 Portfolio 기능의 owner scope 강화
- 다중 계좌 처리 가능성 확보
- 계좌 연결/해제 정책 수립
- credential rotation/revocation 정책 수립
- 삭제/retention 정책 수립
- staff 접근 audit 가능성 확보
- 주문 API와 완전 분리

비목표:

- 이번 단계에서 모델 생성 안 함
- 이번 단계에서 migration 생성 안 함
- 이번 단계에서 OAuth 또는 계좌 연결 구현 안 함
- 이번 단계에서 Toss API 호출 안 함
- 이번 단계에서 사용자별 credential 저장 구현 안 함
- 이번 단계에서 Order History 저장 안 함
- 이번 단계에서 주문 API 구현 안 함
- 이번 단계에서 자동매매 또는 매수/매도 추천 설계 안 함

## 4. 현재 구조와 한계

현재 가능:

- staff-only Toss Order History read-only 조회
- staff-only Toss Order History reconciliation 조회
- Toss accounts/holdings 관련 command 기반 read-only 또는 guarded 저장 흐름
- `UserHolding`은 Django `user` FK를 가지고 있음
- Holdings API는 `request.user` 기준 owner scope를 적용함
- Portfolio Summary는 `request.user` 기반 `UserHolding`만 조회함
- Additional Buy Simulation은 `request.user` owner scope 기반으로 특정 holding만 계산함
- Order History는 staff-only read-only로만 제공됨

현재 Toss account handling:

- provider는 앱 전역 settings의 `TOSS_INVEST_ACCOUNT_ID`를 우선 사용한다.
- 설정된 account id가 usable하지 않으면 accounts API fallback으로 단일 계좌일 때만 account sequence를 선택할 수 있다.
- account 값은 `mask_account_id(...)`로 masking된 safe value만 출력하도록 설계되어 있다.
- `get_accounts()`는 account count, account type, masked account summary만 반환한다.

현재 한계:

- Toss account와 Django user 연결 모델이 없다.
- global env credential 하나만 사용한다.
- 일반 사용자별 Toss credential/account가 없다.
- account ownership proof가 없다.
- 다중 계좌 mapping이 없다.
- `account_ref_hash`가 없다.
- 계좌 연결/해제/삭제 정책이 없다.
- 계좌 접근 감사용 AuditLog 모델이 없다.
- Order History 저장 모델이 없다.
- user credential 모델 또는 외부 credential reference 모델이 없다.

## 5. 선택지 비교

### 선택지 A: 앱 전역 credential 유지 + staff-only만 허용

설명:

- 현재 구조를 유지한다.
- Toss data는 운영자만 read-only로 조회한다.
- 일반 사용자에게 Toss account, holdings, order history를 직접 노출하지 않는다.

장점:

- 가장 안전하다.
- 이미 구현된 기능과 일치한다.
- credential 관리가 단순하다.
- 노출 범위가 staff-only로 제한된다.
- user-account mapping 부재로 인한 오노출 위험을 피할 수 있다.

단점:

- 일반 사용자가 본인 계좌를 연동할 수 없다.
- 개인화된 Order History 또는 holdings 자동 반영이 불가능하다.
- 손익 분석 자동화는 제한된다.

판단:

- 단기 권장안이다.

### 선택지 B: 앱 전역 credential + 수동 user-account mapping

설명:

- 같은 Toss credential으로 조회한 계좌를 특정 Django user에 수동 연결한다.
- 원문 계좌 식별자 대신 `account_ref_hash`로 매핑한다.

장점:

- 구현은 비교적 단순하다.
- 내부/1인 운영 환경에서는 제한적으로 가능할 수 있다.
- 기존 staff-only read-only 체계에서 확장하기 쉽다.

단점:

- 다중 사용자 환경에서는 위험하다.
- 수동 매핑 오류 위험이 있다.
- 계좌 소유권 증명이 부족하다.
- 운영자 실수로 다른 사용자에게 계좌 데이터가 노출될 수 있다.
- 일반 서비스 구조에는 부적합하다.

판단:

- 내부 운영 보조 또는 단일 계좌 상황에서도 매우 제한적으로만 검토한다.
- 일반 사용자 서비스 확장의 기본안으로 쓰지 않는다.

### 선택지 C: 사용자별 Toss credential / delegated connection

설명:

- 각 user가 본인 Toss credential 또는 위임 연결을 통해 계좌를 연결한다.
- user별 account scope를 명확히 한다.

장점:

- 일반 사용자 기능으로 확장 가능하다.
- owner scope가 명확하다.
- 다중 사용자 구조에 적합하다.
- holdings/order history/portfolio/pnl 기능을 user-scoped로 설계할 수 있다.

단점:

- credential 저장, 암호화, rotation, revocation 설계가 필요하다.
- UX, 보안, 법적 검토가 필요하다.
- secret manager 또는 encrypted storage가 필요하다.
- 구현 복잡도가 높다.

판단:

- 일반 사용자 확장 전 필요한 목표 구조다.
- 구현 전 threat model, retention, AuditLog, secret management 설계가 먼저 필요하다.

### 선택지 D: Toss account raw id를 user profile에 직접 저장

설명:

- accountNo/accountSeq 원문을 user profile 또는 별도 model에 직접 저장한다.

판단:

```text
금지한다.
```

이유:

- 민감 식별자 원문 저장이다.
- 로그, 백업, 관리자 화면, dump에서 노출될 수 있다.
- 최소 저장 원칙을 위반한다.
- 계좌 연결 해제와 탈퇴 시 삭제 범위가 불명확해진다.

권장 결론:

```text
단기: 선택지 A 유지
내부 운영/단일 계좌 상황에서도 선택지 B는 매우 제한적으로만 검토
일반 사용자 확장 전에는 선택지 C 수준의 user-scoped credential/account mapping 설계 필요
선택지 D는 금지
```

## 6. 권장 domain model 후보

이번 단계에서는 실제 모델을 만들지 않는다. 아래는 향후 별도 단계에서 검토할 후보 설계다.

### 후보 모델: UserTossAccountLink

목적:

- Django User와 Toss account reference의 안전한 연결

필드 후보:

- `id`
- `user` FK
- `provider`
- `account_ref_hash`
- `account_masked`
- `account_type`
- `market_scope`
- `is_active`
- `linked_at`
- `revoked_at`
- `last_verified_at`
- `source`
  - `manual_staff_link`
  - `user_connected`
  - `imported`
- `metadata`
  - safe JSON only
- `created_at`
- `updated_at`

금지 필드:

- accountNo 원문
- accountSeq 원문
- X-Tossinvest-Account 원문
- access token 원문
- refresh token 원문
- client secret 원문
- Authorization header 원문
- raw accounts response
- raw holdings response
- raw order history response

제약 후보:

- active link 기준으로 `user`, `provider`, `account_ref_hash` unique 검토
- 다중 계좌를 허용하되 동일 user에 같은 account hash 중복 연결은 금지
- revoked link는 history 보관 여부를 retention policy와 함께 결정

### 후보 모델: UserTossCredentialReference

목적:

- 사용자별 credential이 필요할 경우 DB에는 외부 secret store reference만 저장

필드 후보:

- `id`
- `user` FK
- `provider`
- `credential_ref`
- `credential_status`
- `scopes`
- `linked_at`
- `revoked_at`
- `last_rotated_at`
- `last_verified_at`

주의:

- credential 원문 DB 저장 금지
- 실제 secret은 DB 밖 secret manager 또는 암호화 저장소 필요
- read-only scope를 우선한다.
- 주문 scope는 별도 승인 전까지 금지한다.
- 이번 MVP에서는 구현하지 않는다.

### 후보 모델: AccountAccessAuditLog

목적:

- staff 또는 user가 계좌 관련 민감 조회를 수행한 감사 기록

필드 후보:

- `actor_user_hash` 또는 `actor_ref`
- `action`
- `provider`
- `account_ref_hash`
- `target_user_hash`
- `endpoint_name`
- `success`
- `safe_reason`
- `created_at`

주의:

- username/email/user id 원문 저장 여부는 별도 검토한다.
- raw response 저장 금지
- order id 원문 저장 금지
- account 원문 저장 금지
- AuditLog 자체의 retention policy가 필요하다.

## 7. account_ref_hash 설계

입력 후보:

- `provider`
- account sequence 또는 account number 원문 값
- optional account type
- secret pepper

출력:

- `account_ref_hash`

정책:

- accountNo/accountSeq 원문은 DB에 저장하지 않는다.
- hash 계산 후 원문은 폐기한다.
- hash에는 secret pepper를 사용한다.
- pepper는 원문 출력하지 않는다.
- pepper는 코드 저장소에 넣지 않는다.
- pepper rotation 정책이 필요하다.
- hash collision 가능성을 검토한다.
- hash는 화면에 표시하지 않는다.
- 화면에는 `account_masked`만 표시한다.
- `account_masked`도 원문 복원이 어려운 형태로 제한한다.
- `account_ref_hash`는 URL query 또는 client-visible identifier로 직접 노출하지 않는 것이 바람직하다.

설정 후보:

- `TOSS_ACCOUNT_HASH_PEPPER`

주의:

- 이번 단계에서는 실제 hash 구현을 하지 않는다.
- settings를 수정하지 않는다.
- 실제 pepper 값을 문서화하지 않는다.
- hash 설계는 secret rotation, backup, restore, dedupe 정책과 함께 확정해야 한다.

## 8. 계좌 연결 workflow

### Workflow A: staff manual link

용도:

- 내부 운영 또는 단일 계좌 환경

흐름:

1. staff가 Toss accounts read-only 조회
2. account summary 확인
3. staff가 특정 Django user와 연결 후보 검토
4. `account_ref_hash` 생성
5. `account_masked` 저장
6. user에게 노출하기 전 검증
7. 감사 로그 기록

위험:

- 수동 매핑 오류
- 계좌 소유권 증명 부족
- 운영자 실수
- 다중 사용자 서비스에 부적합

권장:

- 내부/운영 보조용으로만 제한한다.
- 일반 사용자 서비스 확장의 기본 workflow로 사용하지 않는다.

### Workflow B: user self-connect

용도:

- 일반 사용자 서비스 확장

흐름:

1. 사용자가 계좌 연결 시작
2. 사용자 동의
3. 사용자별 credential 또는 delegated connection 생성
4. accounts read-only 조회
5. 사용자가 연결할 계좌 선택
6. `account_ref_hash` 저장
7. `account_masked` 표시
8. 연결 완료
9. 사용자가 연결 해제 가능

필수:

- 동의/고지
- credential 보호
- 연결 해제
- 삭제 정책
- audit
- 다중 계좌 처리
- permission regression test
- raw response 미저장 검증

## 9. 다중 계좌 정책

정책:

- user는 여러 Toss account를 연결할 수 있다.
- `account_ref_hash`는 user+provider 범위에서 unique가 필요하다.
- 기본 계좌 설정 가능성을 검토한다.
- holdings/order history 조회 시 account 선택이 필요하다.
- account 선택 UI는 masked label만 사용한다.
- accountNo/accountSeq 원문 UI 표시 금지
- inactive/revoked account link 처리가 필요하다.
- staff-only global account와 user-linked account를 혼동하면 안 된다.

조회 정책:

- account 선택이 없고 active account가 하나면 default로 사용할 수 있다.
- active account가 여러 개면 명시 선택을 요구한다.
- revoked account는 조회, sync, portfolio 연결 대상에서 제외한다.
- staff-only 운영 조회와 user-scoped 조회 endpoint를 분리한다.

## 10. permission / owner scope 정책

일반 사용자:

- 본인의 active `UserTossAccountLink`만 조회 가능
- 다른 user의 account reference 접근 불가
- `account_ref_hash`를 직접 query로 노출하지 않는 것이 바람직
- 계좌 선택은 opaque link id 또는 server-side selection key를 사용
- response에는 account 원문, credential 원문, raw response를 포함하지 않음

staff:

- 운영 목적 조회 가능
- 조회 감사 필요
- account 원문 식별자 표시 금지
- 일반 사용자 계좌 연결/해제 수행 시 AuditLog 필요
- staff-only global credential 조회와 user-scoped 조회를 UI/API에서 명확히 분리

system command:

- 앱 전역 credential 사용 가능
- user-scoped sync와 분리 필요
- user-scoped sync가 생기면 explicit account link와 explicit user scope가 필요
- command metadata에 username/email/account 원문 저장 금지

금지:

- `user_id` query로 다른 사용자 계좌 조회
- username/email query로 계좌 조회
- accountNo/accountSeq query 허용
- raw account identifier URL query 사용
- 일반 사용자에게 staff-only order history/reconciliation route 제공

## 11. holdings / order history / portfolio 연결 정책

user-account mapping 이후에만 가능한 것:

- user-scoped holdings sync
- user-scoped order history 조회
- user-scoped order history 저장
- Portfolio Summary에 broker-backed holdings 반영
- `UserHolding`과 Toss holdings reconciliation
- `UserHolding`과 Order History reconciliation
- 손익 분석
- 다중 계좌별 holdings/order history 분리 조회

그 전까지 가능한 것:

- staff-only read-only Order History 조회
- staff-only read-only reconciliation
- DB-only Portfolio Summary
- DB-only Additional Buy Simulation
- guarded command 기반 `UserHolding` 단일 symbol 저장/갱신

그 전까지 금지:

- 일반 사용자 화면에서 Toss Order History 노출
- 일반 사용자 Portfolio에 앱 전역 Toss account 데이터 자동 연결
- 일반 사용자에게 staff-only order history 화면/API 제공
- 일반 사용자에게 staff-only reconciliation 화면/API 제공
- user-account mapping 없이 손익 분석에 Order History 자동 반영

## 12. credential 정책

현재:

- 앱 전역 `.env` credential
- 운영/staff read-only 조회에만 사용
- 일반 사용자 credential scope가 아님
- request.user와 Toss account 소유 관계를 증명하지 않음

향후 사용자별 credential이 필요할 경우:

- DB에 token 원문 저장 금지
- DB에 client secret 원문 저장 금지
- DB에 Authorization header 저장 금지
- secret manager 또는 encrypted storage 필요
- token rotation 정책 필요
- revocation 정책 필요
- access scope 최소화
- read-only scope 우선
- 주문 scope는 별도 금지/보류
- credential leak 대응 절차 필요
- credential 상태값은 safe enum으로만 저장

권장:

- 사용자별 credential 원문은 DB에 직접 저장하지 않는다.
- DB에는 `credential_ref` 같은 외부 secret reference만 저장하는 방향을 우선 검토한다.
- credential 관리 설계 전에는 일반 사용자 계좌 연결을 구현하지 않는다.

## 13. retention / deletion 정책

user-account mapping이 생기면 필요한 정책:

- 계좌 연결 해제 시 mapping 비활성화
- 사용자 탈퇴 시 mapping 삭제 또는 비식별화
- `account_ref_hash` 보관 여부 결정
- AuditLog retention
- backup에 남은 데이터 처리
- 거래 내역 저장 시 별도 retention
- 사용자 요청 삭제 절차
- 법적/운영 요구 검토
- 삭제 후 복구 또는 재연결 시 dedupe 정책

기본 권장:

- link 해제 즉시 active 조회 대상에서 제외한다.
- user 탈퇴 시 account link와 credential reference를 삭제 또는 비식별화한다.
- AuditLog는 보안 감사 목적의 최소 필드만 보관한다.
- backup 잔존 데이터 처리와 deletion replay 절차를 별도 문서화한다.

## 14. AuditLog 정책

감사 대상:

- staff가 계좌 연결/해제 수행
- staff가 Order History 조회
- staff가 reconciliation 조회
- user가 account link 생성/해제
- user가 holdings/order history 조회
- failed permission access
- credential revocation 또는 rotation 이벤트

AuditLog에 넣을 수 있는 safe fields:

- `actor_ref_hash`
- `target_user_ref_hash`
- `provider`
- `action`
- `account_ref_hash`
- `success`
- `safe_reason`
- `created_at`

금지:

- username/email 원문
- accountNo/accountSeq 원문
- token/header
- raw response
- order id 원문
- client order id 원문
- credential 원문

주의:

- AuditLog 자체도 민감한 운영 데이터다.
- 조회 가능 staff 범위, 보관 기간, 삭제 예외, backup 정책을 별도 설계해야 한다.

## 15. 마이그레이션 전제 조건

실제 구현 전 필요한 문서/설계:

- threat model
- retention policy
- AuditLog design
- `account_ref_hash` implementation design
- secret management design
- migration plan
- rollback plan
- admin UI policy
- API permission tests
- privacy review
- data deletion workflow
- backup/restore policy
- safe logging policy

구현 전 검증 기준:

- account 원문 미저장 regression test
- raw response 미저장 regression test
- 일반 사용자 cross-user access 차단 test
- staff access audit test
- revoked account 조회 차단 test
- 다중 계좌 명시 선택 test
- 주문 API mutation 미호출 test

## 16. 최종 권고

최종 권고:

```text
지금은 user-account mapping 모델을 만들지 않는다.
```

대신:

1. 현재 staff-only read-only 체계를 유지한다.
2. 일반 사용자용 Toss order history/holdings 연결은 보류한다.
3. 다음 구현이 필요하다면 먼저 threat model, retention policy, AuditLog 설계를 진행한다.
4. 그 후 `UserTossAccountLink` 모델을 별도 단계에서 설계/구현한다.
5. 사용자별 credential이 필요하면 secret management design을 먼저 완료한다.
6. 주문 생성/정정/취소 API는 계속 비활성 유지한다.

판단 이유:

- 현재 앱 전역 credential은 일반 사용자 소유권을 증명하지 못한다.
- user-account mapping 없이 Order History 또는 holdings를 일반 사용자에게 노출하면 오노출 위험이 크다.
- accountNo/accountSeq 원문을 저장하지 않는 hash/mask 설계가 선행되어야 한다.
- credential, retention, AuditLog, rollback 정책이 아직 없다.
- 현재 staff-only read-only 도구로 운영 참고 목적은 충족된다.

## 17. 후속 단계 후보

- Step W6: staff-only order history/reconciliation release note 업데이트
- Step W7: Order History storage threat model
- Step W8: retention/delete policy 설계
- Step W9: AuditLog 설계
- Step W10: UserTossAccountLink 모델 상세 설계
- Step W11: user-scoped holdings sync 설계
- 주문 생성/정정/취소 API는 계속 비활성 유지

## 18. 2026-06 Architecture Update: 사용자별 Toss Credential 1:1 구조

이 문서의 기존 권고인 "지금은 user-account mapping 모델을 만들지 않는다"는 즉시 구현을 보류하기 위한 안전 기준으로 계속 유효하다. 다만 후속 목표 구조는 다음 기준으로 보강한다.

```text
theStock user : Toss증권 security/API user credential = 1:1
```

새 아키텍처 방향:

- 일반 사용자용 Toss 연동은 사용자별 credential 1:1 구조를 목표로 한다.
- 기존 후보 `UserTossCredentialReference`는 외부 secret manager reference 중심이었으나, 현재 요구사항은 사용자가 직접 `client_id`와 `client_secret`을 입력하고 DB에는 application-level encryption으로 저장하는 구조다.
- SQLCipher는 SQLite DB 파일 유출 방어용이다.
- Toss credential column 보안의 핵심은 SQLCipher가 아니라 application-level encrypted field다.
- SQL query로 조회해도 `client_id`, `client_secret`, access token, refresh token 평문이 보이면 안 된다.
- 모델 후보는 `UserTossAccountLink` 단독이 아니라 `TossInvestCredential` 중심으로 확장한다.
- `UserProfile`에는 Toss credential/account mapping을 넣지 않고 `integrations` 앱으로 분리한다.
- 일반 사용자 기능에서 전역 `TOSS_INVEST_CLIENT_ID`, `TOSS_INVEST_CLIENT_SECRET`, `TOSS_INVEST_ACCOUNT_ID` 사용을 금지한다.
- read-only scope를 우선한다.
- 주문 생성/정정/취소 API와 자동매매는 계속 금지한다.

후속 구현 전제:

- 상세 기준 문서는 `docs/54_technical_architecture_and_toss_credential_design.md`다.
- threat model, retention policy, AuditLog 설계가 선행되어야 한다.
- application-level encrypted field 패키지 선정과 key management 검증이 필요하다.
- `CREDENTIAL_ENCRYPTION_KEY`, `CREDENTIAL_HASH_PEPPER`, `SQLCIPHER_DATABASE_KEY`는 DB에 저장하지 않는다.
- Toss증권 Open API의 `client_id`/`client_secret`이 사용자 개인별 credential인지 서비스 앱 단위 credential인지 최종 확인해야 한다.
