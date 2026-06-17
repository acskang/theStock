# Order History Reconciliation Screen Smoke Report

## 1. 목적

Step W3E에서 구현한 staff-only Order History Reconciliation HTML 화면이 실제 read-only 조회 경로에서 안전하게 동작하는지 확인한다.

## 2. 점검 대상

- 화면 route: `GET /operations/toss/order-history/reconciliation/`
- view: `toss_order_history_reconciliation_page`
- template: `data_pipeline/toss_order_history_reconciliation.html`
- 실제 read-only 조회: `run=1`, `symbol=035250`, `from_date=2026-01-01`, `to_date=2026-06-17`, `limit=5`
- provider 경로: Toss Order History `GET /api/v1/orders`

## 3. settings 안전 상태

- `python manage.py check`: OK
- `TOSS_ORDER_EXECUTION_ENABLED`: `False`
- `TOSS_INVEST_PROVIDER_ENABLED`: `True`
- 주문 생성/정정/취소 기능은 활성화하지 않았다.

## 4. 권한 smoke

- active staff user count: 1
- active non-staff user count: 1
- selected staff user exists: `True`
- selected non-staff user exists: `True`
- anonymous 접근: 302 login redirect
- non-staff 접근: 403
- non-staff 화면에 reconciliation result 없음
- non-staff 화면에 `weighted_average_buy_price` 없음

## 5. default GET smoke

- staff default GET status_code: 200
- `run=1` 없는 기본 진입에서는 provider/service/network 호출 없음
- form 표시 확인
- 안전 문구 확인:
  - `staff-only read-only report`
  - `공식 실현손익 계산이 아닙니다`
  - `주문을 실행하지 않습니다`
  - `주문 생성, 변경, 취소 기능을 제공하지 않습니다`
- `비교 조회` 버튼 표시
- reconciliation result는 표시되지 않음
- mutation 버튼 없음
- 민감정보 forbidden key 없음

## 6. actual reconciliation 화면 smoke

- staff `run=1` actual screen status_code: 200
- symbol: `035250`
- report summary 표시 확인:
  - `order_history_reconciliation`
  - `read_only`
  - `order_execution`
- `order_execution` 값은 HTML에서 lowercase `false`로 표시된다.
- order_history summary 표시 확인:
  - `order_count`
  - `has_next`
  - `next_cursor_present`
- aggregates 표시 확인:
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
- `user_holding_comparison` 표시 확인:
  - `matching_user_holding_exists`
  - `matching_user_holding_count`
  - `user_holding_quantity`
  - `user_holding_average_price`
  - `quantity_difference`
  - `average_price_difference`
- warnings 영역 표시 확인
- 공식 실현손익 아님 문구 표시
- 주문 미실행 문구 표시
- 화면 content 전체 또는 raw response는 출력하지 않았다.

## 7. validation 화면 smoke

- invalid symbol validation status_code: 200
- safe validation error 표시 확인:
  - `invalid` 포함
- provider/service 호출 전 validation에서 차단되는 경로다.
- raw exception 노출 없음
- 민감정보 forbidden key 없음

## 8. DB count 변화

### Before

- Stock count: 17
- DailyPrice count: 3
- UserHolding count: 1
- DataProviderStatus count: 0
- DataIngestionLog count: 91

### After

- Stock count: 17
- DailyPrice count: 3
- UserHolding count: 1
- DataProviderStatus count: 0
- DataIngestionLog count: 91

### 변화 여부

- Stock 증가 없음
- DailyPrice 증가 없음
- UserHolding 증가 없음
- DataProviderStatus 증가 없음
- DataIngestionLog 증가 없음

## 9. DataIngestionLog 확인

- 화면 조회로 DataIngestionLog 생성 없음
- API/화면 조회성 기능은 ingestion log를 생성하지 않는 정책 유지
- metadata 생성 없음

## 10. mutation endpoint 미호출 확인

- 실제 조회 경로는 `GET /api/v1/orders` read-only provider 경로만 사용
- `POST /api/v1/orders` 호출 없음
- modify/cancel 호출 없음
- Order Info detail endpoint 호출 없음
- 주문 생성/정정/취소 API 호출 없음
- order execution flag 변경 없음
- mutation 버튼 없음
- mutation 위험 grep 결과:
  - 테스트의 부정 검증 문자열
  - fake/test 데이터의 `CANCELED`
  - 기존 unsupported option 테스트용 `cancel_order`, `modify_order`
  - 실제 mutation 구현/호출 흔적은 없음

## 11. 민감정보 점검

- 화면에 `orderId` 원문 없음
- 화면에 `clientOrderId` 없음
- 화면에 `accountNo/accountSeq` 없음
- 화면에 `X-Tossinvest-Account` 없음
- 화면에 `Authorization` 없음
- 화면에 `access_token/client_secret` 없음
- 화면에 `nextCursor/cursor` 원문 없음
- 화면에 raw response 없음
- 화면에 `user_id/username/email` 없음
- 민감정보 grep 결과: 출력 없음

## 12. 최종 판정

PASS

이유:

- `python manage.py check` OK
- `python manage.py test` OK, 427 tests passed
- `TOSS_ORDER_EXECUTION_ENABLED=False`
- anonymous 차단
- non-staff 차단
- staff default GET 200
- default GET에서 provider/service/network 미호출
- staff `run=1` actual screen 200
- read-only report, order_history summary, aggregates, user_holding_comparison, warnings 표시
- 공식 실현손익 아님 및 주문 미실행 문구 표시
- orderId/clientOrderId/account/token/header/cursor/raw/user 식별자 미노출
- domain DB count 변화 없음
- DataIngestionLog 변화 없음
- mutation endpoint 호출/구현/버튼 없음

## 13. 다음 단계

- Step W4: Order History 저장 모델 필요성 검토
- Step W5: user-account mapping 설계
- Step W6: staff-only reconciliation release note 업데이트
- 주문 생성/정정/취소 API는 계속 비활성 유지
