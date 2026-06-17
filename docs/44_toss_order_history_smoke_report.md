# Toss Order History Smoke Report

## 1. 목적

Step W1에서 구현한 Toss Order History read-only dry-run command가 실제 네트워크에서 `GET /api/v1/orders`만 사용해 주문 이력을 안전하게 조회하는지 확인한다.

이번 smoke는 주문 생성, 정정, 취소를 검증하지 않는다. 주문 mutation endpoint는 호출하지 않는다.

## 2. 점검 대상

- Command: `python manage.py toss_order_history_dryrun`
- Provider method: `TossOpenApiProvider.get_order_history_candidates(...)`
- Endpoint: `GET /api/v1/orders`
- Status filters: `CLOSED`, `OPEN`
- Safe output:
  - `orderId`는 masked value만 표시
  - `clientOrderId` 원문 미표시
  - 계좌 원문 미표시
  - token/header/secret 미표시
  - raw response 전체 미표시

## 3. settings 안전 상태

- `python manage.py check`: OK
- `TOSS_ORDER_EXECUTION_ENABLED`: `False`
- `TOSS_INVEST_PROVIDER_ENABLED`: `True`

주문 실행 flag는 비활성 상태였다.

## 4. DB count 변화

| 항목 | before | after | 변화 |
|---|---:|---:|---:|
| Stock | 17 | 17 | 없음 |
| DailyPrice | 3 | 3 | 없음 |
| UserHolding | 1 | 1 | 없음 |
| DataProviderStatus | 0 | 0 | 없음 |
| DataIngestionLog | 87 | 91 | +4 |

`DataIngestionLog` 증가는 no-network preflight 1회와 실제 read-only 조회 3회의 safe summary 기록이다. Domain row 저장은 없었다.

## 5. no-network preflight

Command:

```bash
python manage.py toss_order_history_dryrun --status=CLOSED --symbol=035250 --from-date=2026-01-01 --to-date=2026-06-17 --limit=5 --no-network
```

결과:

- Status: `SKIPPED`
- Safe reason: `no_network`
- Endpoint: `/api/v1/orders`
- Status filter: `CLOSED`
- Symbol: `035250`
- Limit: `5`
- `network_call`: `false`
- `dry_run`: `true`
- `order_execution_enabled`: `false`
- 민감정보 노출: 없음

## 6. CLOSED symbol order history smoke

Command:

```bash
python manage.py toss_order_history_dryrun --status=CLOSED --symbol=035250 --from-date=2026-01-01 --to-date=2026-06-17 --limit=5
```

결과:

- Status: OK
- Endpoint: `/api/v1/orders`
- HTTP method: `GET`
- Status filter: `CLOSED`
- Symbol: `035250`
- `network_call`: `true`
- `dry_run`: `true`
- `order_execution_enabled`: `false`
- `order_count`: `4`
- `has_next`: `true`
- `next_cursor_present`: `true`
- Order id: masked value만 출력
- `clientOrderId` 원문 노출: 없음
- 계좌/token/header 노출: 없음
- raw response 전체 노출: 없음

주문 목록은 민감정보 보호를 위해 상세 원문을 문서화하지 않는다. 출력은 normalized safe fields와 masked order id만 사용했다.

## 7. OPEN symbol order history smoke

Command:

```bash
python manage.py toss_order_history_dryrun --status=OPEN --symbol=035250
```

결과:

- Status: OK
- Endpoint: `/api/v1/orders`
- HTTP method: `GET`
- Status filter: `OPEN`
- Symbol: `035250`
- `network_call`: `true`
- `dry_run`: `true`
- `order_execution_enabled`: `false`
- `order_count`: `0`
- `has_next`: `false`
- `next_cursor_present`: `false`
- 민감정보 노출: 없음

진행 중 주문이 없는 상태로 확인되었다.

## 8. CLOSED all-symbol limited order history smoke

Command:

```bash
python manage.py toss_order_history_dryrun --status=CLOSED --from-date=2026-01-01 --to-date=2026-06-17 --limit=5
```

결과:

- Status: OK
- Endpoint: `/api/v1/orders`
- HTTP method: `GET`
- Status filter: `CLOSED`
- Symbol filter: 없음
- `network_call`: `true`
- `dry_run`: `true`
- `order_execution_enabled`: `false`
- `order_count`: `5`
- `has_next`: `true`
- `next_cursor_present`: `true`
- Safe summary:
  - normalized symbol/side/status/quantity/price 계열 필드만 출력
  - status 예: `CANCELED`, `REJECTED`
  - side 예: `BUY`, `SELL`
- Order id: masked value만 출력
- `clientOrderId` 원문 노출: 없음
- 계좌/token/header 노출: 없음
- raw response 전체 노출: 없음

개인 매매 데이터의 과도한 상세 문서화를 피하기 위해 전체 주문 목록은 기록하지 않는다.

## 9. DataIngestionLog 확인

최근 `toss_order_history_dryrun` 관련 row:

- no-network row 존재
  - `status`: `skipped`
  - `safe_reason`: `no_network`
  - `network_call`: `False`
  - `dry_run`: `True`
  - `candidate_count`: `0`
- actual network row 존재
  - `status`: `success`
  - `safe_reason`: `order_history_received`
  - `network_call`: `True`
  - `dry_run`: `True`
  - `candidate_count`: `4`, `0`, `5`
  - `saved_count`: `0`
  - `updated_count`: `0`
  - `failed_count`: `0`

Metadata 확인:

- command, data_type, endpoint, status_filter, symbol, network_call, dry_run, limit, order_count 계열 safe summary만 포함
- order id 원문 없음
- `clientOrderId` 없음
- accountNo/accountSeq 없음
- `X-Tossinvest-Account` 없음
- Authorization/access token 없음
- raw response 없음

## 10. mutation endpoint 미호출 확인

- 사용 endpoint: `GET /api/v1/orders`
- `POST /api/v1/orders`: 호출 없음
- order modify endpoint: 호출 없음
- order cancel endpoint: 호출 없음
- order detail endpoint: 호출 없음
- 주문 생성/정정/취소 API: 호출 없음
- `TOSS_ORDER_EXECUTION_ENABLED`: 변경 없음, `False`

Mutation 위험 grep 결과는 실제 구현이 아닌 false positive만 확인되었다.

- `canceled_at` normalized field
- 테스트의 금지 옵션 검증용 `cancel_order`, `modify_order`
- pycache binary match

## 11. 민감정보 점검

민감정보 패턴 grep 결과:

- 실제 secret/token/account/order id 원문 패턴: 없음
- `accountNo/accountSeq` 출력/저장: 없음
- `X-Tossinvest-Account` 출력/저장: 없음
- access token 출력/저장: 없음
- Authorization header 출력/저장: 없음
- `orderId` 원문 출력/저장: 없음
- `clientOrderId` 출력/저장: 없음
- raw response 출력/저장: 없음

## 12. 최종 판정

PASS.

판정 이유:

- `python manage.py check` OK
- `python manage.py test` OK, 401 tests passed
- 실제 `GET /api/v1/orders` read-only 조회 성공
- `network_call=true` actual smoke 확인
- order id는 masked value만 출력
- 민감정보 및 raw response 원문 노출 없음
- Stock/DailyPrice/UserHolding/DataProviderStatus count 변화 없음
- DataIngestionLog에는 safe summary만 생성
- 주문 생성/정정/취소 mutation endpoint 호출 없음

## 13. 다음 단계

- Step W2: Order History 화면/API 설계
- Step W3: 매매 내역을 Portfolio/손익 분석에 연결할지 설계
- 주문 생성/정정/취소 API는 계속 비활성 유지
