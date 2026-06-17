# Order History to Portfolio P&L Connection Design

## 1. 목적

Toss Order History read-only 조회 결과를 Portfolio Summary, `UserHolding`, 손익 분석에 연결할지 판단하고, 연결한다면 필요한 보안 조건과 단계별 설계 범위를 정리한다.

이번 문서는 설계 문서다. 코드, template, API response, settings, DB schema, migration은 변경하지 않는다.

## 2. 현재 Order History 구현 상태

현재 구현된 Order History 경로:

- Provider: `TossOpenApiProvider.get_order_history_candidates(...)`
- Command: `python manage.py toss_order_history_dryrun`
- Staff-only API: `GET /api/operations/toss/order-history/`
- Staff-only 화면: `GET /operations/toss/order-history/`
- Toss endpoint: `GET /api/v1/orders`
- 지원 status: `OPEN`, `CLOSED`
- command 외 API/화면 조회는 `DataIngestionLog`를 생성하지 않음
- DB domain row 저장 없음
- 주문 생성, 정정, 취소 구현 없음
- `POST /api/v1/orders` 구현 없음
- modify/cancel endpoint 구현 없음
- `orderId`, `clientOrderId`, account/header/token/raw response 원문 미노출

현재 Portfolio 관련 경로:

- Portfolio Summary는 `UserHolding.average_price`, `UserHolding.quantity`, 최신 `DailyPrice.close_price` 기반으로 평가금액, 손익, 수익률을 계산한다.
- Additional Buy Simulation은 추가 예산과 최근 일봉 종가 또는 입력 가격으로 평균단가를 계산한다.
- 기존 `portfolio` 앱에는 CSV/`Transaction` 기반 실현손익 분석이 있으나 Toss Order History와 직접 연결되어 있지 않다.

## 3. 핵심 판단

Toss Order History를 Portfolio/손익 분석에 자동 연결하는 것은 아직 이르다.

이유:

- 현재 Toss credential은 앱 전역 `.env` credential이다.
- `request.user`와 Toss account의 소유 관계가 없다.
- Order History는 실제 매매 내역으로 보유잔고보다 민감도가 높다.
- `UserHolding`은 앱 user 소유 데이터지만 Order History는 아직 user-scoped 데이터가 아니다.
- 잘못 연결하면 다른 사용자에게 운영 계좌 거래 내역이 노출될 수 있다.
- 실현손익 계산은 매수, 매도, 부분체결, 취소, 수수료, 세금, 정산일 처리가 필요하다.
- 현재 Portfolio Summary는 DB-only `UserHolding` + `DailyPrice` 기반이라 안전하다.

권장 결론:

- 단기적으로는 staff-only read-only reconciliation report만 검토한다.
- 일반 사용자 Portfolio/손익 기능과 자동 연결은 user-account mapping 설계 전까지 보류한다.

## 4. 연결 후보 비교

### 후보 A: 연결하지 않고 staff-only 조회만 유지

설명:

- Order History는 command, staff-only API, staff-only 화면으로만 조회한다.
- Portfolio Summary와 연결하지 않는다.

장점:

- 가장 안전하다.
- 현재 검증 완료 상태를 유지한다.
- 개인정보와 거래내역 노출 위험이 낮다.

단점:

- 사용자는 매매 내역 기반 손익 분석을 바로 볼 수 없다.

### 후보 B: staff-only reconciliation report

설명:

- staff-only 화면/API에서 Order History와 `UserHolding`을 비교한다.
- 예: 최근 체결 평균가와 `UserHolding.average_price` 비교, 체결 수량 합계와 `UserHolding.quantity` 비교, symbol 기준 거래 요약.
- DB 저장 없음.
- 일반 사용자 노출 없음.

장점:

- 운영자가 데이터 정합성을 확인할 수 있다.
- DB 저장 없이 구현 가능하다.
- 민감 데이터 노출 범위가 staff로 제한된다.

단점:

- 실제 거래내역을 화면에 보여주므로 staff 권한 관리가 중요하다.
- 일반 사용자 기능은 아니다.
- 단순 비교 결과를 공식 손익이나 확정 평균단가로 오해할 수 있다.

### 후보 C: OrderHistory / TradeExecution 저장 모델 도입

설명:

- Toss Order History를 DB에 저장한다.
- `order_id_hash`, execution fields, symbol, side, quantity, price, commission/tax 등을 저장한다.
- user-account mapping이 필요하다.

장점:

- 실현손익, 세금, 수수료, 과거 분석이 가능하다.
- 반복 조회 없이 빠른 분석이 가능하다.

단점:

- migration이 필요하다.
- 개인정보와 거래정보 보관 정책이 필요하다.
- `orderId`, `clientOrderId` 처리 정책이 필요하다.
- retention policy, backup/rollback, audit가 필요하다.
- 잘못 저장하면 보안 리스크가 크다.

### 후보 D: 일반 사용자 Portfolio 손익 분석에 자동 연결

설명:

- 사용자 화면에서 매매 내역 기반 평균단가, 실현손익, 미실현손익을 제공한다.

장점:

- 사용자 가치가 높다.

단점:

- 현재 구조에서는 위험하다.
- user-account mapping과 credential/user ownership 검증이 필요하다.
- 권한 테스트와 민감정보 redaction 테스트가 필요하다.
- 지금은 보류해야 한다.

## 5. 권장 방향

권장안:

- 단기: 후보 A를 유지하고, 후보 B를 별도 staff-only reconciliation dry-run으로 설계한다.
- 중기: 후보 C 저장 모델은 보류하고 별도 보안/DB 설계 후 검토한다.
- 장기: 후보 D는 user-account mapping 이후 검토한다.

현재 Portfolio Summary와 Additional Buy Simulation은 계속 DB-only/read-only 경로로 유지한다. Order History는 주문 실행, 자동매매, 매수/매도 추천과 분리한다.

## 6. staff-only reconciliation report 설계

후보 이름:

```text
Toss Order History Reconciliation Report
```

목표:

- DB 저장 없이 Order History 조회 결과와 현재 `UserHolding`을 비교한다.
- staff-only로 제한한다.
- read-only로 동작한다.
- `DataIngestionLog`를 생성하지 않는다.
- 주문 mutation을 호출하지 않는다.

입력:

- `symbol`
- `from_date`
- `to_date`
- `status=CLOSED`
- `limit`
- optional user / holding selection은 MVP에서 보류
- MVP는 symbol 기준 비교만 허용

데이터:

- Toss Order History normalized orders
- `UserHolding.objects.filter(stock__code=symbol, is_active=True)`
- latest `DailyPrice` optional

출력 후보:

- `symbol`
- `order_count`
- `closed_buy_count`
- `closed_sell_count`
- `filled_quantity_buy_sum`
- `filled_quantity_sell_sum`
- `net_filled_quantity`
- `weighted_average_buy_price`
- `total_buy_amount`
- `total_sell_amount`
- `total_commission`
- `total_tax`
- `current_user_holding_count`
- `matching_user_holding_exists`
- `user_holding_quantity`
- `user_holding_average_price`
- `quantity_difference`
- `average_price_difference`
- `warnings`

노출 제한:

- 실제 username/email/user id 출력 금지
- 일반 사용자에게 노출 금지
- `orderId` 원문 출력 금지
- raw response 출력 금지
- 매수 추천/주문 실행과 무관

## 7. 평균단가 비교 설계

Order History 기반 참고 평균 매수가:

```text
weighted_average_buy_price =
    sum(filled_quantity * average_filled_price) / sum(filled_quantity)
```

또는:

```text
total_buy_amount / filled_quantity_buy_sum
```

주의:

- 수수료/세금 포함 여부 정책이 필요하다.
- 매도 체결을 고려하면 현재 보유 평균단가와 단순 비교가 틀릴 수 있다.
- 부분 매도 후 평균단가는 broker accounting 방식에 따라 달라질 수 있다.
- 취소, 부분체결, 정정 주문은 status와 execution을 기준으로 필터링해야 한다.
- `UserHolding.average_price`와 단순 차이를 보여주더라도 공식 평균단가로 사용하면 안 된다.

권장:

- Step W3에서는 “검증용 참고 비교”로만 설계한다.
- Portfolio Summary의 공식 `average_price` 값을 Order History로 자동 보정하지 않는다.

## 8. 실현손익 / 미실현손익 검토

실현손익 계산에 필요한 것:

- 매수 lot
- 매도 lot matching 방식
  - FIFO
  - average cost
  - broker-provided realized P/L if available
- 수수료
- 세금
- 정산일
- 통화
- corporate action
- 분할/병합
- 배당/배당세
- 환율

현재 단계 결론:

- Toss Order History 기반 실현손익 계산은 아직 구현하지 않는다.
- 단순 order history 요약과 `UserHolding` 비교까지만 검토한다.
- 기존 CSV/`Transaction` 기반 실현손익 분석과 Toss Order History는 별도 입력 소스이므로 자동 병합하지 않는다.

미실현손익:

- 현재 Portfolio Summary가 `UserHolding.average_price` + `DailyPrice.close_price`로 계산 중이다.
- Order History 없이도 현재 미실현손익 계산은 가능하다.
- Order History는 `average_price` 검증/보정 후보일 뿐, 현재 단계에서는 자동 반영하지 않는다.

## 9. DB 저장 모델 필요성

저장 모델 후보:

### TossOrderHistorySnapshot

- `provider`
- `account_ref_hash`
- `symbol`
- `status`
- `order_id_hash`
- `order_id_masked`
- `side`
- `order_type`
- `time_in_force`
- `order_status`
- `price`
- `quantity`
- `order_amount`
- `currency`
- `ordered_at`
- `canceled_at`
- `raw_summary`
- `created_at`

### TossTradeExecution

- order snapshot FK
- `symbol`
- `filled_quantity`
- `average_filled_price`
- `filled_amount`
- `commission`
- `tax`
- `filled_at`
- `settlement_date`
- `currency`

이번 결론:

- 저장 모델은 지금 만들지 않는다.
- 먼저 user-account mapping, retention, privacy, migration, backup/rollback 설계가 필요하다.
- `orderId`는 원문 저장 금지, hash 또는 opaque reference만 검토한다.
- `clientOrderId`는 사용자 정의 문자열일 수 있으므로 저장하지 않는 것을 기본값으로 둔다.
- raw response 저장은 금지한다.

## 10. user-account mapping 필요성

일반 사용자 기능으로 확장하려면 다음이 필요하다.

- user별 Toss credential 또는 delegated account reference
- account ownership proof
- accountSeq/accountNo 원문 저장 금지
- `account_ref_hash` 설계
- account masking
- credential rotation
- 연결 해제
- 동의/고지
- 거래 내역 보관 기간
- 접근 권한 테스트
- 탈퇴/삭제 정책
- audit log

결론:

- user-account mapping 전에는 일반 사용자용 order history/손익 분석 연결을 금지한다.
- 앱 전역 Toss credential 기반 거래 내역을 일반 사용자 Portfolio에 자동 연결하지 않는다.

## 11. permission / exposure 정책

단기 staff-only report 권한:

- `IsAuthenticated`
- `is_staff=True`
- 또는 `CanViewTossOrderHistoryReconciliation`

노출 금지:

- `orderId` 원문
- `clientOrderId`
- accountNo/accountSeq
- token/header
- raw response
- username/email
- user id
- 주문 버튼
- 자동매매 버튼

노출 허용:

- symbol
- side
- order status
- quantity
- price
- filled_quantity
- average_filled_price
- commission/tax 요약
- masked order id
- aggregate summary

## 12. DataIngestionLog / AuditLog 정책

현재:

- command는 `DataIngestionLog` safe row를 생성한다.
- staff-only API/화면은 `DataIngestionLog`를 생성하지 않는다.

향후 reconciliation report:

- 일반 화면 조회성 기능이므로 `DataIngestionLog`는 생성하지 않는 것을 권장한다.
- 운영자 조회 감사가 필요하면 별도 `AuditLog`를 설계한다.
- 거래 내역 조회는 민감하므로 audit 필요성은 높다.
- 그러나 `AuditLog`는 모델, migration, retention 정책이 필요하므로 별도 Step으로 보류한다.

권장:

- W3A 구현 시에는 `DataIngestionLog`를 생성하지 않는다.
- `AuditLog`는 별도 설계로 보류한다.

## 13. 단계별 구현 계획

### Step W3A: staff-only reconciliation report 설계 상세화

- DB 저장 없음
- symbol 기준
- fake provider 기반 테스트
- order history + `UserHolding` 비교
- actual smoke는 별도

### Step W3B: reconciliation service 구현

- read-only service
- provider result + `UserHolding` queryset 비교
- no DB write
- 공식 손익 확정값이 아니라 참고용 reconciliation 결과로 표시

### Step W3C: staff-only reconciliation API 또는 화면 구현

- 후보 route: `/operations/toss/order-history/reconciliation/`
- staff-only
- `run=1` 명시 조회
- no mutation

### Step W3D: actual reconciliation smoke

- 실제 order history read-only
- DB write 없음
- 민감정보 없음

### Step W4: Order History 저장 모델 필요성 검토

- 저장/분석이 정말 필요한지 판단
- user-account mapping 포함

### Step W5: user-account mapping 설계

- 일반 사용자 제공 전 필수

## 14. 금지 항목

- 일반 사용자에게 앱 전역 Toss credential 기반 order history 노출
- `request.user`와 account 매핑 없이 Portfolio 손익에 자동 연결
- `orderId` 원문 저장
- `clientOrderId` 원문 저장
- accountNo/accountSeq 원문 저장
- raw response 저장
- 주문 생성/정정/취소 API 구현
- 자동매매
- 매수/매도 추천
- 수익 보장
- 실현손익을 부정확하게 확정값처럼 표시
