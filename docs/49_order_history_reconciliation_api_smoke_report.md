# Order History Reconciliation API Smoke Report

## 1. 목적

Step W3C에서 구현한 staff-only Order History Reconciliation API가 운영 설정에서 실제 Toss Order History read-only 조회를 통해 안전하게 동작하는지 확인한다.

## 2. 점검 대상

- Endpoint: `GET /api/operations/toss/order-history/reconciliation/`
- Query: `symbol=035250`, `from_date=2026-01-01`, `to_date=2026-06-17`, `limit=5`
- Provider path: Toss `GET /api/v1/orders`
- 비교 대상: 현재 `UserHolding` read-only 조회

## 3. settings 안전 상태

- `TOSS_ORDER_EXECUTION_ENABLED`: `False`
- `TOSS_INVEST_PROVIDER_ENABLED`: `True`
- 판정: PASS

## 4. 권한 smoke

- Anonymous: `403`
- Non-staff: `403`, `staff_required`
- Staff: actual reconciliation API 접근 가능
- 판정: PASS

## 5. actual reconciliation smoke

- status_code: `200`
- report_type: `order_history_reconciliation`
- read_only: `True`
- order_execution: `False`
- symbol: `035250`
- order_history:
  - order_count: `4`
  - has_next: `True`
  - next_cursor_present: `True`
  - used_cursor: `False`
- aggregates:
  - buy_order_count: `1`
  - sell_order_count: `0`
  - skipped_execution_count: `3`
  - buy_filled_quantity_sum: `1`
  - sell_filled_quantity_sum: `0`
  - net_filled_quantity: `1`
  - buy_filled_amount_sum: `15080.00`
  - sell_filled_amount_sum: `0.00`
  - weighted_average_buy_price: `15080.00`
- user_holding_comparison:
  - matching_user_holding_exists: `True`
  - matching_user_holding_count: `1`
  - user_holding_quantity: `2`
  - user_holding_average_price: `15116.50`
  - quantity_difference: `1`
  - average_price_difference: `36.50`
- warnings:
  - staff-only read-only report
  - not official realized P&L
  - no orders are placed
  - order IDs masked and raw responses excluded
  - fees/taxes summarized separately
  - skipped execution data warning
  - more pages exist warning
- forbidden exact key 노출: 없음
- 참고: 단순 substring 검사에서 `raw responses` 안전 문구와 `next_cursor_present` 허용 키 때문에 `raw`, `response`, `next_cursor`, `cursor`가 true로 잡혔으나 원문 raw response/cursor 값은 노출되지 않았다.
- 판정: PASS

## 6. validation smoke

- missing_symbol: `400`
- invalid_symbol: `400`
- invalid_limit: `400`
- unsupported_status: `400`
- unsupported_cursor: `400`
- unsupported_account: `400`
- unsupported_user_id: `400`
- provider 호출 전 차단: PASS
- 민감정보 포함: 없음

## 7. DB count 변화

- before Stock count: `17`
- after Stock count: `17`
- before DailyPrice count: `3`
- after DailyPrice count: `3`
- before UserHolding count: `1`
- after UserHolding count: `1`
- before DataProviderStatus count: `0`
- after DataProviderStatus count: `0`
- before DataIngestionLog count: `91`
- after DataIngestionLog count: `91`
- 판정: PASS

## 8. DataIngestionLog 확인

- API 조회로 DataIngestionLog 생성: 없음
- domain model 저장: 없음
- metadata 생성: 없음
- 판정: PASS

## 9. mutation endpoint 미호출 확인

- 사용 endpoint: Toss `GET /api/v1/orders`
- `POST /api/v1/orders`: 호출 없음
- modify/cancel endpoint: 호출 없음
- order execution flag 변경: 없음
- mutation 위험 grep: 기존 테스트 fixture 및 부정 검증 문자열 false positive만 확인
- 판정: PASS

## 10. 민감정보 점검

- orderId 원문: 없음
- clientOrderId: 없음
- accountNo/accountSeq: 없음
- X-Tossinvest-Account: 없음
- Authorization/access_token/client_secret: 없음
- nextCursor/cursor 원문: 없음
- raw response: 없음
- user_id/username/email: 없음
- 민감정보 grep: 출력 없음
- 판정: PASS

## 11. 최종 판정

PASS

이유:

- check/test 모두 통과했다.
- staff-only 권한 정책이 동작했다.
- actual reconciliation API가 200으로 aggregate summary와 UserHolding comparison을 반환했다.
- response는 read-only이며 주문 실행을 하지 않는다.
- DB count 및 DataIngestionLog count 변화가 없다.
- 민감정보와 order mutation 흔적이 없다.

## 12. 다음 단계

- Step W3E: staff-only reconciliation 화면 설계/구현
- Step W4: Order History 저장 모델 필요성 검토
- Step W5: user-account mapping 설계
- 주문 생성/정정/취소 API는 계속 비활성 유지
