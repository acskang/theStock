# Staff Order History API Smoke Report

## 1. 목적

Step W2A에서 구현한 staff-only Toss Order History API가 실제 네트워크 read-only 경로로 동작하는지 확인했다.

점검 범위는 `GET /api/operations/toss/order-history/` API이며, 내부적으로 Toss OpenAPI `GET /api/v1/orders`만 사용한다. 주문 생성, 정정, 취소 API는 호출하지 않는다.

## 2. 점검 대상

- API: `GET /api/operations/toss/order-history/`
- 권한: 인증 사용자 중 staff 사용자만 허용
- provider: `TossOpenApiProvider.get_order_history_candidates(...)`
- Toss endpoint: `GET /api/v1/orders`
- 조회 조건:
  - `status=CLOSED`, `symbol=035250`, `limit=5`
  - `status=OPEN`, `symbol=035250`
  - `status=CLOSED`, all-symbol, `limit=5`

## 3. settings 안전 상태

- `TOSS_ORDER_EXECUTION_ENABLED`: `False`
- `TOSS_INVEST_PROVIDER_ENABLED`: `True`
- 주문 실행 flag는 비활성 상태를 유지했다.

## 4. 권한 smoke

- anonymous 요청: `403`
- non-staff 요청: `403`, `staff_required`
- staff 요청: 실제 read-only API smoke 진행 가능

판정: PASS

## 5. CLOSED symbol API smoke

- endpoint: `/api/operations/toss/order-history/`
- query: `status=CLOSED`, `symbol=035250`, date range, `limit=5`
- status code: `200`
- `network_call`: `True`
- `dry_run`: `True`
- `status_filter`: `CLOSED`
- `symbol`: `035250`
- `order_count`: `4`
- `has_next`: `True`
- `next_cursor_present`: `True`
- orders length: `4`
- 주문 식별자는 masked field만 확인했다.
- `orderId`, `clientOrderId`, 계좌 식별자, token/header/raw response는 응답에 포함되지 않았다.

판정: PASS

## 6. OPEN symbol API smoke

- endpoint: `/api/operations/toss/order-history/`
- query: `status=OPEN`, `symbol=035250`
- status code: `200`
- `network_call`: `True`
- `dry_run`: `True`
- `status_filter`: `OPEN`
- `symbol`: `035250`
- `order_count`: `0`
- `has_next`: `False`
- `next_cursor_present`: `False`
- 민감정보와 raw response는 응답에 포함되지 않았다.

판정: PASS

## 7. CLOSED all-symbol limited API smoke

- endpoint: `/api/operations/toss/order-history/`
- query: `status=CLOSED`, date range, `limit=5`
- status code: `200`
- `network_call`: `True`
- `dry_run`: `True`
- `order_count`: `5`
- `has_next`: `True`
- `next_cursor_present`: `True`
- safe summary 기준으로 symbol, side, status, quantity, price, currency만 확인했다.
- 주문 식별자 원문, 계좌 식별자, token/header/raw response는 응답에 포함되지 않았다.

판정: PASS

## 8. validation smoke

- invalid status: `400`
- invalid symbol: `400`
- invalid limit: `400`
- validation error는 provider 호출 전 차단되는 safe error 형태로 반환되었다.
- 민감정보는 포함되지 않았다.

판정: PASS

## 9. DB count 변화

| Model | Before | After | 변화 |
|---|---:|---:|---:|
| Stock | 17 | 17 | 없음 |
| DailyPrice | 3 | 3 | 없음 |
| UserHolding | 1 | 1 | 없음 |
| DataProviderStatus | 0 | 0 | 없음 |
| DataIngestionLog | 91 | 91 | 없음 |

API 조회로 domain model 저장과 `DataIngestionLog` 생성은 발생하지 않았다.

## 10. DataIngestionLog 확인

- API 조회로 `DataIngestionLog` row는 생성되지 않았다.
- API 조회 metadata 저장도 발생하지 않았다.
- command 기반 ingestion log와 staff-only API 조회 경로는 분리되어 있다.

판정: PASS

## 11. mutation endpoint 미호출 확인

- 사용 endpoint: `GET /api/v1/orders`
- `POST /api/v1/orders`: 호출 없음
- modify endpoint: 호출 없음
- cancel endpoint: 호출 없음
- 주문 생성/정정/취소 API: 호출 없음
- `TOSS_ORDER_EXECUTION_ENABLED=False` 유지

mutation 위험 grep은 테스트의 부정 검증 문자열과 `canceled_at` normalized field 등 false positive만 확인되었다.

## 12. 민감정보 점검

응답과 출력에서 다음 항목은 확인되지 않았다.

- accountNo/accountSeq
- `X-Tossinvest-Account`
- Authorization header
- access token
- client secret
- orderId 원문
- clientOrderId
- raw response
- next cursor 원문

`next_cursor_present` 안전 필드 때문에 단순 substring 검사에서 `cursor` 문자열은 잡힐 수 있으나, exact forbidden key scan 결과 forbidden key count는 `0`이었다.

민감정보 패턴 grep 결과: 문제 없음

## 13. 최종 판정

PASS

이유:

- `python manage.py check` 통과
- `python manage.py test` 406개 통과
- anonymous/non-staff 접근 차단 확인
- staff API actual read-only 호출 성공
- Toss Order History는 `GET /api/v1/orders`만 사용
- 주문 mutation 호출 없음
- `orderId` 원문, `clientOrderId`, 계좌 식별자, token/header/raw response 미노출
- `nextCursor` 원문 미노출
- Stock/DailyPrice/UserHolding/DataProviderStatus 변화 없음
- `DataIngestionLog` 변화 없음

## 14. 다음 단계

- Step W2C: staff-only Order History 화면 구현
- Step W3: 매매 내역을 Portfolio/손익 분석에 연결할지 설계
- 주문 생성/정정/취소 API는 계속 비활성 유지
