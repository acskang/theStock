# Order History Storage Model Necessity Review

## 1. 목적

이 문서는 Toss Order History 데이터를 DB에 저장할 필요가 있는지 검토하고, 저장한다면 어떤 전제 조건과 안전 설계가 필요한지 정리한다.

이번 단계는 설계 검토 문서 작성만 수행한다. Python 코드, Django model, migration, template, JavaScript, API response, settings, 운영 DB schema는 변경하지 않는다. 실제 Toss API 호출, order history command 실행, staff-only smoke, 저장 command, 주문 생성/정정/취소 API 구현 또는 호출도 수행하지 않는다.

## 2. 현재 구현 상태

현재 Order History 관련 구현은 read-only 조회 중심이다.

- Provider: `TossOpenApiProvider.get_order_history_candidates(...)`
- Command: `python manage.py toss_order_history_dryrun`
- Staff-only API: `GET /api/operations/toss/order-history/`
- Staff-only 화면: `GET /operations/toss/order-history/`
- Staff-only reconciliation API: `GET /api/operations/toss/order-history/reconciliation/`
- Staff-only reconciliation 화면: `GET /operations/toss/order-history/reconciliation/`
- Toss endpoint: `GET /api/v1/orders`
- 지원 status: `OPEN`, `CLOSED`
- 주문 생성/정정/취소 API 구현 없음
- `POST /api/v1/orders`, modify endpoint, cancel endpoint 호출 없음
- Order History / TradeExecution 저장 모델 없음
- user-account mapping 저장 모델 없음

현재 Order History normalized fields는 다음 범위로 제한된다.

- 주문 요약: `order_id_masked`, `symbol`, `side`, `order_type`, `time_in_force`, `status`, `price`, `quantity`, `order_amount`, `currency`, `ordered_at`, `canceled_at`
- 체결 요약: `filled_quantity`, `average_filled_price`, `filled_amount`, `commission`, `tax`, `filled_at`, `settlement_date`
- pagination 요약: `has_next`, `next_cursor_present`
- raw response, raw request/response header, account 식별자 원문, token, secret은 반환/표시/저장하지 않는다.

현재 reconciliation aggregate fields는 다음 범위다.

- `buy_order_count`
- `sell_order_count`
- `skipped_execution_count`
- `buy_filled_quantity_sum`
- `sell_filled_quantity_sum`
- `net_filled_quantity`
- `buy_filled_amount_sum`
- `sell_filled_amount_sum`
- `buy_commission_sum`
- `sell_commission_sum`
- `buy_tax_sum`
- `sell_tax_sum`
- `weighted_average_buy_price`

현재 `UserHolding`은 `user`, `stock`, `average_price`, `quantity`, `is_active`, `max_additional_budget`, `risk_level`, `memo` 중심의 현재 보유 모델이다. Portfolio Summary는 `UserHolding.average_price`, `UserHolding.quantity`, 최신 `DailyPrice.close_price`로 평가금액, 미실현 손익, 수익률을 계산한다.

현재 `DataIngestionLog` 정책은 command와 화면/API를 분리한다.

- `toss_order_history_dryrun` command는 safe summary row를 생성할 수 있다.
- Staff-only API/화면/reconciliation 조회는 `DataIngestionLog`를 생성하지 않는다.
- 조회성 운영자 접근 감사가 필요하면 `DataIngestionLog`보다 별도 `AuditLog`가 적합하다.

## 3. 핵심 질문과 최종 권고

핵심 질문:

```text
지금 Order History를 DB에 저장해야 하는가?
```

최종 권고:

```text
지금은 Order History 저장 모델을 만들지 않는다.
```

이유:

- 현재 구현은 read-only 조회와 staff-only reconciliation만으로 운영 참고 가치를 제공한다.
- 일반 사용자와 Toss account의 소유 관계를 증명하는 user-account mapping이 없다.
- Order History는 실제 거래정보라 `UserHolding`보다 민감도가 높다.
- 저장 시 order 식별자, account 식별자, 체결 금액, 수수료, 세금, 정산일 등 민감 거래정보 보관 리스크가 커진다.
- retention/delete policy, AuditLog, backup/restore, migration/rollback 설계가 아직 없다.
- 실현손익 계산에는 lot matching, 부분체결, 취소, 정정, 세금, 수수료, 정산일, 환율, corporate action 정책이 필요하다.
- 부정확한 실현손익을 확정값처럼 보여줄 위험이 있다.
- DB schema 변경과 migration rollback 부담을 지금 감수할 필요가 명확하지 않다.

따라서 현재 command, staff-only API, staff-only 화면, reconciliation 화면의 read-only 체계를 유지한다. 저장 모델은 user-account mapping, retention policy, order id hashing, AuditLog, migration/rollback 설계 후 별도 단계에서 다시 검토한다.

## 4. 선택지 비교

### 선택지 A: 저장하지 않음, read-only 조회 유지

설명:

- 현재처럼 command, staff-only API, staff-only 화면, reconciliation 화면으로 필요 시 조회한다.
- DB에는 Order History domain row를 저장하지 않는다.

장점:

- 가장 안전하다.
- 개인정보/거래정보 보관 리스크가 낮다.
- migration이 없다.
- raw response 저장 위험이 없다.
- 삭제/보관 기간 정책 부담이 낮다.
- 현재 W1-W3 smoke 결과와 구현 구조를 유지할 수 있다.

단점:

- 과거 분석을 매번 Toss API 조회에 의존한다.
- rate limit 또는 API 장애 영향을 받을 수 있다.
- 장기 분석, 기간별 리포트, 실현손익 자동화가 어렵다.

판단:

- 현 단계 권장안이다.

### 선택지 B: aggregate snapshot만 저장

설명:

- 원본 주문/체결 개별 row는 저장하지 않는다.
- symbol/date range 기준 aggregate summary만 저장한다.
- 후보 필드 예: `buy_filled_quantity_sum`, `sell_filled_quantity_sum`, `weighted_average_buy_price`, `commission_sum`, `tax_sum`, `generated_at`

장점:

- 개별 주문 저장보다 민감도가 낮다.
- 화면/리포트 속도를 개선할 수 있다.
- raw order id 저장 없이 요약 분석이 가능하다.

단점:

- 원천 주문 row가 없어 재계산과 감사가 제한된다.
- range, pagination, `has_next` 누락 시 잘못된 snapshot이 저장될 수 있다.
- 사용자별/계좌별 구분을 위해 여전히 user-account mapping 또는 `account_ref_hash`가 필요할 수 있다.
- 요약값만으로 세부 정합성 확인이 어렵다.

판단:

- 저장이 꼭 필요해졌을 때도 normalized 저장보다 먼저 검토할 수 있으나, 지금 도입하지 않는다.

### 선택지 C: normalized order/execution 저장

설명:

- 주문/체결 row를 normalized model로 저장한다.
- raw response는 저장하지 않는다.
- order 식별자는 hash/masked만 저장한다.
- client order 식별자는 저장하지 않거나 hash만 저장한다.

장점:

- 분석 가능성이 높다.
- 실현손익, 세금, 수수료, 정산일 분석 기반이 된다.
- 반복 API 호출 의존도를 줄일 수 있다.
- pagination과 backfill을 통제하면 장기 리포트가 가능하다.

단점:

- 민감 거래정보를 DB에 저장한다.
- migration이 필요하다.
- retention/delete/AuditLog가 필요하다.
- user-account mapping이 필수다.
- 중복 처리, unique constraint, hash collision, 부분 import rollback 설계가 복잡하다.
- 보안 사고 시 피해가 크다.

판단:

- user-account mapping, retention, hash, AuditLog, migration 설계 후 별도 단계에서만 검토한다.

### 선택지 D: raw response 저장

설명:

- Toss raw response 전체를 저장한다.

판단:

```text
금지한다.
```

이유:

- account/order/client 식별자와 원문 응답이 섞일 위험이 높다.
- 필요 이상의 민감정보를 저장하게 된다.
- redaction 실패 시 피해 범위가 크다.
- 개인정보/거래정보 보관 리스크가 매우 크다.
- debug 편의보다 보안/운영 리스크가 훨씬 크다.

결론:

- 현 단계에서는 선택지 A를 유지한다.
- 저장 필요성이 명확해져도 선택지 D는 계속 금지한다.

## 5. 저장 모델 후보

아래는 저장을 도입한다면 검토할 수 있는 개략 후보일 뿐이다. 이번 단계에서는 실제 `models.py`를 수정하지 않고 migration도 만들지 않는다.

### 후보 1: TossOrderHistorySnapshot

목적:

- 주문 단위 normalized snapshot 저장

필드 후보:

- `id`
- `provider`
- `account_ref_hash`
- `symbol`
- `market`
- `side`
- `order_status`
- `order_type`
- `time_in_force`
- `order_id_hash`
- `order_id_masked`
- `client_order_id_hash`
- `price`
- `quantity`
- `order_amount`
- `currency`
- `ordered_at`
- `canceled_at`
- `source`
- `fetched_at`
- `created_at`

금지 필드:

- order 식별자 원문
- client order 식별자 원문
- account number 원문
- account sequence 원문
- `raw_response`
- `Authorization`
- `access_token`
- request/response header

주의:

- dedupe를 위해 `provider`, `account_ref_hash`, `order_id_hash` 조합을 검토할 수 있다.
- `order_id_hash`는 secret salt/pepper 없이 만들면 dictionary attack 또는 cross-system correlation 위험이 있다.
- `order_id_masked`는 화면 표시용이며 유일성 보장 목적으로 쓰면 안 된다.

### 후보 2: TossTradeExecution

목적:

- 체결 단위 normalized execution 저장

필드 후보:

- `id`
- `order_snapshot` FK
- `symbol`
- `side`
- `filled_quantity`
- `average_filled_price`
- `filled_amount`
- `commission`
- `tax`
- `currency`
- `filled_at`
- `settlement_date`
- `created_at`

주의:

- API에서 체결 고유 id가 없거나 불명확하면 uniqueness 설계가 어렵다.
- `order_id_hash`, `filled_at`, `symbol`, `filled_quantity`, `filled_amount` 조합을 검토할 수 있으나 부분체결/정정/재조회에서 안정적인지 별도 검증이 필요하다.
- execution row 저장은 실현손익 분석에 유용하지만 거래정보 민감도를 높인다.

### 후보 3: OrderHistoryAggregateSnapshot

목적:

- 개별 주문 저장 없이 aggregate summary 저장

필드 후보:

- `id`
- `provider`
- `account_ref_hash`
- `symbol`
- `from_date`
- `to_date`
- `order_count`
- `buy_order_count`
- `sell_order_count`
- `buy_filled_quantity_sum`
- `sell_filled_quantity_sum`
- `net_filled_quantity`
- `buy_filled_amount_sum`
- `sell_filled_amount_sum`
- `commission_sum`
- `tax_sum`
- `weighted_average_buy_price`
- `has_next`
- `incomplete`
- `generated_at`
- `created_at`

주의:

- `has_next=True`이면 `incomplete=True`로 저장해야 한다.
- aggregate만으로 정확한 재계산과 감사가 불가능하다.
- date range, pagination, filter 조건을 snapshot key에 포함해야 한다.
- snapshot을 공식 손익으로 표시하면 안 된다.

## 6. user-account mapping 전제 조건

저장 모델을 만들기 전 다음 설계가 필요하다.

- User와 Toss account의 소유 관계 모델
- account number/account sequence 원문 저장 금지
- `account_ref_hash` 설계
- account display mask 설계
- credential/account rotation 정책
- 계좌 연결/해제 정책
- 사용자 동의/고지
- 탈퇴 시 삭제 정책
- 다중 계좌 처리
- staff 접근 정책
- AuditLog
- retention policy
- backup/restore policy
- 데이터 암호화 또는 field-level protection 검토

결론:

```text
user-account mapping 없이 일반 사용자용 Order History 저장/조회/손익 분석은 금지한다.
```

현재 Toss credential은 앱 전역 설정 기반이다. 이 상태에서 일반 사용자 기능으로 Order History를 저장하거나 노출하면 운영 계좌 거래 내역이 잘못된 사용자에게 연결될 수 있다.

## 7. order id / client order id 정책

식별자 정책:

- order 식별자 원문 저장 금지
- order 식별자는 hash 또는 masked only
- hash에는 secret salt/pepper가 필요하다.
- hash 설계 시 같은 주문 dedupe 가능성을 고려해야 한다.
- client order 식별자는 사용자 정의 문자열일 수 있으므로 원문 저장 금지
- client order 식별자가 꼭 필요하면 hash only
- 화면/API에는 masked order id만 표시
- 로그와 `DataIngestionLog`에는 order 식별자 원문 금지

추가 고려:

- hash pepper는 코드 저장소가 아니라 secret 관리 경로에서 관리해야 한다.
- salt/pepper rotation 시 기존 hash와 dedupe가 깨질 수 있으므로 rotation 정책이 필요하다.
- masked value는 사람이 식별하기 위한 참고값일 뿐 보안 식별자 또는 unique key로 쓰면 안 된다.

## 8. raw response 정책

raw response 저장 금지.

구체 정책:

- raw response 저장 금지
- raw request/response header 저장 금지
- Authorization 저장 금지
- X-Tossinvest-Account 저장 금지
- raw body 저장 금지
- 필요한 필드만 normalized mapping
- unknown field는 버린다.
- debug용 raw dump 금지
- fixture/test/doc에도 raw API response 예시는 남기지 않는다.

허용되는 것은 safe summary뿐이다.

- endpoint name
- status filter
- symbol
- order count
- `has_next`
- `next_cursor_present`
- normalized numeric summary
- masked order id

## 9. retention / deletion 정책

저장 모델을 도입한다면 retention/delete policy가 먼저 필요하다.

검토 항목:

- 거래 내역 보관 기간
- 사용자 요청 삭제
- 계좌 연결 해제 시 삭제
- 탈퇴 시 삭제
- backup에 남은 데이터 처리
- AuditLog retention
- 법적/운영상 보관 필요성
- 최소 저장 원칙
- 민감정보 노출 사고 시 대응
- 운영자 접근 기록 보관 기간
- 삭제 요청 후 비동기 삭제 완료 확인 방식

권장:

```text
저장 모델 설계 전 retention policy 문서가 먼저 필요하다.
```

정책이 없으면 데이터가 얼마나 오래 남는지, 어떤 이벤트에서 삭제되는지, backup과 audit에는 무엇이 남는지 설명할 수 없다. 거래정보는 사용자 신뢰와 법적 리스크가 모두 크므로 저장 모델보다 보관/삭제 정책이 먼저다.

## 10. 실현손익 계산 필요성

Order History 저장이 필요할 수 있는 경우:

- 실현손익 계산
- 세금/수수료 반영
- 과거 매매 리포트
- 포트폴리오 성과 분석
- 거래 습관 분석
- API 재조회 없이 기간별 리포트 제공

하지만 지금 보류해야 하는 이유:

- lot matching 정책이 필요하다.
- FIFO, 평균법, 브로커 제공 방식 중 어떤 기준을 쓸지 정해야 한다.
- 부분체결, 취소, 정정 처리가 필요하다.
- 수수료, 세금, 정산일 처리가 필요하다.
- 미국주식, 환율, 소수점 수량 문제가 있다.
- corporate action 처리가 필요하다.
- broker와 앱 계산 결과가 다를 수 있다.
- 부정확한 실현손익을 확정값처럼 표시할 위험이 있다.
- 현재 `UserHolding`은 KR/KRW integer quantity 중심이라 확장 전제도 제한적이다.

결론:

```text
지금은 실현손익 저장/계산 모델을 만들지 않는다.
staff-only reconciliation은 “참고 비교”로만 유지한다.
```

reconciliation의 `weighted_average_buy_price`는 공식 평균단가 또는 공식 실현손익이 아니다. 수수료와 세금은 별도 요약이며, pagination 누락이나 skipped execution이 있으면 결과가 불완전할 수 있다.

## 11. DataIngestionLog / AuditLog 정책

현재:

- command 실행은 `DataIngestionLog` safe row를 생성할 수 있다.
- staff-only API/화면/reconciliation은 `DataIngestionLog`를 생성하지 않는다.
- `DataIngestionLog` metadata에는 safe summary만 허용한다.

저장 모델 도입 시:

- ingestion run 자체는 `DataIngestionLog` 또는 별도 ingestion log에 기록할 수 있다.
- 운영자 조회는 `DataIngestionLog`가 아니라 `AuditLog`가 더 적합하다.
- 거래 내역 조회는 민감하므로 audit 필요성이 높다.
- 그러나 `AuditLog` 자체도 민감정보 최소화가 필요하다.
- AuditLog에는 order/account 식별자 원문, raw response, token/header를 저장하지 않는다.

권장:

```text
Order History 저장 도입 전 AuditLog 설계를 별도 Step으로 분리한다.
```

## 12. migration / rollback 고려사항

저장 모델을 만들 경우 필요한 준비:

- migration plan
- SQLite/Postgres 차이 확인
- schema 변경 전 backup
- rollback plan
- backfill 중단 기준
- duplicate handling
- unique constraint
- hash collision 정책
- partial import rollback
- dry-run first
- commit guard
- confirm-save guard
- batch size limit
- raw response 미저장 검증
- 민감정보 grep 절차
- pagination incomplete 처리
- `has_next=True` 저장 정책
- migration 후 기존 read-only 경로 회귀 테스트

추가 원칙:

- 저장 command는 기본 dry-run이어야 한다.
- 저장은 명시적 commit guard 없이는 불가능해야 한다.
- backfill은 단일 symbol/date range/batch size로 제한해 시작해야 한다.
- 실패 시 domain row와 ingestion log의 일관성을 확인해야 한다.

## 13. 보안 checklist

저장 모델 도입 전 checklist:

- [ ] user-account mapping 설계 완료
- [ ] account 원문 저장하지 않음
- [ ] order 식별자 원문 저장하지 않음
- [ ] client order 식별자 원문 저장하지 않음
- [ ] raw response 저장하지 않음
- [ ] raw request/response header 저장하지 않음
- [ ] Authorization/token/secret 저장하지 않음
- [ ] `account_ref_hash` salt/pepper 정책 정의
- [ ] `order_id_hash` salt/pepper 정책 정의
- [ ] `client_order_id_hash` 필요성 검토 완료
- [ ] retention/delete policy 작성
- [ ] 탈퇴/계좌 연결 해제 시 삭제 정책 작성
- [ ] backup/restore 잔존 데이터 정책 작성
- [ ] AuditLog 설계
- [ ] migration rollback 계획
- [ ] staff-only 접근 정책
- [ ] 일반 사용자 노출 범위 정의
- [ ] 실현손익 표현 안전 문구 정의
- [ ] 주문 API mutation과 분리 검증
- [ ] 테스트/grep 절차 정의
- [ ] raw response 미저장 regression test 정의
- [ ] DataIngestionLog safe metadata 검증
- [ ] 저장 command dry-run/commit guard 설계
- [ ] 주문 생성/정정/취소 API 비활성 유지 검증

## 14. 최종 권고

최종 권고:

```text
지금은 Order History 저장 모델을 만들지 않는다.
```

대신 다음을 유지한다.

1. 현재 command/staff-only API/staff-only 화면/reconciliation 화면 read-only 체계를 유지한다.
2. staff-only reconciliation을 실제 운영 참고 도구로 사용한다.
3. 저장이 필요하다는 사용자/운영 요구가 명확해지면 user-account mapping 설계부터 진행한다.
4. 이후 retention/AuditLog/hash/migration 설계를 완료한 뒤 normalized storage를 검토한다.
5. raw response 저장은 계속 금지한다.
6. 주문 생성/정정/취소 API는 계속 비활성 유지한다.

판단 기준별 결론:

- 사용자 가치: 장기적으로는 있으나 현재 user-account mapping 부재로 일반 사용자 제공 불가
- 운영 가치: staff-only reconciliation으로 단기 운영 참고 가능
- 보안 리스크: 저장 시 크게 증가
- 개인정보/거래정보 보관 리스크: retention/delete 정책 전에는 수용하기 어려움
- 실현손익 필요성: 장기 후보이나 현재 계산 정책 미정
- 구현 복잡도: schema, dedupe, hash, migration, audit 모두 필요
- migration/rollback 부담: 현재 단계에서는 불필요
- 데이터 정합성: pagination, partial execution, duplicate 처리 설계 전에는 위험

## 15. 후속 단계 후보

- Step W5: user-account mapping 설계
- Step W6: staff-only order history/reconciliation release note 업데이트
- Step W7: Order History storage threat model
- Step W8: retention/delete policy 설계
- Step W9: AuditLog 설계
- Step W10: normalized storage 모델 상세 설계
- 주문 생성/정정/취소 API는 계속 비활성 유지
