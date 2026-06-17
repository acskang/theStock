# Toss Order History Screen and API Design

## 1. 목적

Toss Order History read-only 조회 결과를 화면/API로 제공할 때 필요한 권한, 노출 범위, 응답 schema, 저장 정책, 안전 문구를 설계한다.

이번 문서는 구현 계획 문서다. 코드, template, API response, DB schema는 변경하지 않는다.

## 2. 현재 구현 및 smoke 상태

현재 구현:

- Provider method: `TossOpenApiProvider.get_order_history_candidates(...)`
- Command: `python manage.py toss_order_history_dryrun`
- Toss endpoint: `GET /api/v1/orders`
- `account_required=True`
- Supported status: `OPEN`, `CLOSED`
- DB domain row 저장 없음
- 주문 생성/정정/취소 구현 없음
- `POST /api/v1/orders` 구현 없음
- modify/cancel endpoint 구현 없음
- `orderId` 원문 미출력/미저장
- `clientOrderId` 미출력/미저장
- account/header/token/raw response 미출력/미저장

Step W1-Smoke 결과:

- 실제 `GET /api/v1/orders` read-only 조회 성공
- `CLOSED` + symbol `035250` 조회 성공: `order_count=4`, `has_next=true`, `next_cursor_present=true`
- `OPEN` + symbol `035250` 조회 성공: `order_count=0`
- `CLOSED` all-symbol limited 조회 성공: `order_count=5`
- `DataIngestionLog` safe row 생성
- Stock/DailyPrice/UserHolding/DataProviderStatus count 변화 없음
- 주문 mutation 호출 없음
- 민감정보 원문 노출 없음
- 최종 판정 PASS

## 3. 핵심 보안 판단

현재 Toss credential은 `.env` 기반 운영 credential이다. 따라서 Order History는 특정 Toss 계좌의 실제 매매 내역이다.

일반 authenticated user에게 바로 노출하면 안 된다.

권장 정책:

- 1차 MVP는 staff/operator-only read-only 화면/API로 설계한다.
- 일반 사용자용 확장은 사용자별 Toss credential 또는 account mapping 설계가 먼저 필요하다.

이유:

- 현재 Toss account credential은 앱 전역 설정이다.
- `request.user`와 Toss account의 1:1 소유 관계가 DB에 없다.
- `UserHolding`은 `request.user` owner scope가 있지만 Toss order history는 아직 user별 credential scope가 없다.
- 거래 내역은 보유잔고보다 민감한 데이터다.
- `orderId`, `clientOrderId`, account identifier는 민감한 식별자로 취급해야 한다.

## 4. 제공 범위 후보

### 후보 A: management command only 유지

설명:

- `toss_order_history_dryrun` command만 운영자가 사용한다.
- 화면/API는 만들지 않는다.

장점:

- 가장 안전하다.
- 접근 권한 노출 위험이 낮다.
- 이미 no-network와 실제 read-only smoke가 검증되었다.

단점:

- 사용자가 직접 확인하기 어렵다.
- 운영자 terminal workflow에 의존한다.

### 후보 B: staff-only API

후보 endpoint:

```text
GET /api/operations/toss/order-history/
```

권한:

- `IsAuthenticated`
- `user.is_staff=True` 또는 별도 운영자 permission

장점:

- 운영자용 확인이 편하다.
- 화면 구현 전에 API 단위로 권한과 masking을 검증할 수 있다.

단점:

- API 노출면이 증가한다.
- permission 실수 시 거래 내역 노출 위험이 있다.

### 후보 C: staff-only HTML 화면

후보 route:

```text
GET /operations/toss/order-history/
```

권한:

- `login_required`
- staff/operator-only

장점:

- 운영자가 normalized summary를 보기 쉽다.
- raw response 없이 안전한 표로 제한할 수 있다.

단점:

- 화면 권한 관리가 필요하다.
- pagination/filter UI가 추가된다.

### 후보 D: 일반 사용자용 order history 화면

후보 route:

```text
GET /portfolio/order-history/
```

필수 조건:

- 사용자별 Toss account mapping
- 계좌 소유권 검증
- 다중 사용자 credential 설계
- 민감정보 redaction과 감사 정책

판단:

- 현재 단계에서는 보류한다.

권장안:

- 단기: 후보 A를 유지하면서 staff-only API/화면 설계만 진행한다.
- 구현 우선순위: staff-only API가 staff-only 화면보다 먼저다.
- 일반 사용자용 화면/API는 사용자별 계좌 매핑 설계 전까지 보류한다.

## 5. 권장 API 설계

권장 endpoint:

```text
GET /api/operations/toss/order-history/
```

이유:

- 운영자 전용 성격이 route에서 명확하다.
- 일반 `portfolio` API와 분리된다.
- Toss 계좌 거래 내역을 일반 사용자 API처럼 보이지 않게 한다.

권한:

- `IsAuthenticated`
- `user.is_staff=True`
- 또는 custom permission: `CanViewTossOrderHistory`

Query parameters:

| Parameter | Required | Policy |
|---|---:|---|
| `status` | No | `OPEN` 또는 `CLOSED`, 기본 `CLOSED` |
| `symbol` | No | 단일 symbol만 허용 |
| `from_date` | No | `YYYY-MM-DD` |
| `to_date` | No | `YYYY-MM-DD` |
| `cursor` | No | staff-only에서도 원문 노출 최소화 필요 |
| `limit` | No | 기본 20, 최대 100 |

Response 후보:

```json
{
  "provider": "toss",
  "endpoint": "/api/v1/orders",
  "status_filter": "CLOSED",
  "symbol": "035250",
  "from_date": "2026-01-01",
  "to_date": "2026-06-17",
  "network_call": true,
  "dry_run": true,
  "order_count": 1,
  "has_next": true,
  "next_cursor_present": true,
  "orders": []
}
```

Cursor 정책:

- `nextCursor` 원문은 API response에 그대로 반환하지 않는 것을 권장한다.
- pagination을 제공해야 하면 다음 대안을 먼저 설계한다.
  - 서버 session에 cursor 저장
  - cursor를 짧은 cache key로 매핑
  - 단기 MVP에서는 cursor pagination UI 보류
- `next_cursor_present=true/false`만 우선 노출한다.

민감정보 제외:

- `orderId` 원문 제외
- `clientOrderId` 제외
- accountNo/accountSeq 제외
- `X-Tossinvest-Account` 제외
- Authorization/access token 제외
- raw response 제외
- request/response header 제외

Mutation 분리:

- API는 `GET /api/v1/orders`만 호출한다.
- `POST /api/v1/orders`와 modify/cancel endpoint는 route, serializer, service, button 어디에도 추가하지 않는다.
- `TOSS_ORDER_EXECUTION_ENABLED=False` 정책을 유지한다.

## 6. 권장 화면 설계

권장 route:

```text
GET /operations/toss/order-history/
```

권한:

- `login_required`
- `user.is_staff=True`
- 또는 custom permission: `CanViewTossOrderHistory`

화면 표시 항목:

- status filter
- symbol filter
- date range
- limit
- order_count
- has_next
- next_cursor_present
- orders table:
  - masked order id
  - symbol
  - side
  - order_type
  - status
  - quantity
  - price
  - currency
  - ordered_at
  - filled_quantity
  - average_filled_price
  - filled_amount
  - settlement_date

금지 표시:

- `orderId` 원문
- `clientOrderId`
- accountNo/accountSeq
- `X-Tossinvest-Account`
- Authorization/access token
- raw response
- 주문하기 버튼
- 취소하기 버튼
- 정정하기 버튼
- 자동매매 버튼

안전 문구:

```text
이 화면은 주문/체결 내역을 읽기 전용으로 조회합니다.
주문 생성, 정정, 취소 기능을 제공하지 않습니다.
주문 식별자는 마스킹되어 표시됩니다.
계좌 식별자는 표시하지 않습니다.
```

## 7. 일반 사용자용 확장 조건

일반 사용자에게 Order History를 제공하려면 다음 설계가 먼저 필요하다.

- 사용자별 Toss credential 또는 account mapping 모델
- 사용자가 본인 계좌를 연결했다는 증명
- accountNo/accountSeq 원문 저장 금지 설계
- account hash 또는 opaque account reference 설계
- 연결 동의 및 연결 해제 정책
- 다중 계좌 처리
- credential rotation / revocation
- 개인정보 처리 정책
- 거래 내역 보관 기간 정책
- audit log 정책
- 화면/API permission 테스트
- 민감정보 redaction 테스트

그 전까지 일반 사용자용 Order History 화면/API는 보류한다.

## 8. DataIngestionLog 정책

현재 command:

- `toss_order_history_dryrun`은 `DataIngestionLog` safe summary row를 생성한다.
- `target_type`은 `smoke`를 사용한다.
- metadata에는 command, data_type, endpoint, status filter, network_call, dry_run, count 계열 safe summary만 기록한다.
- `orderId` 원문 없음
- `clientOrderId` 없음
- account/header/token 없음
- raw response 없음

향후 staff-only API/화면 선택지:

### 선택 A: DataIngestionLog 기록 안 함

장점:

- 화면 조회마다 ingestion log가 증가하지 않는다.
- 사용자/운영자 조회 event와 ingestion log를 분리할 수 있다.

단점:

- 운영자 조회 감사가 약하다.

### 선택 B: 별도 AuditLog 설계

장점:

- 운영자 조회 이력 감사가 가능하다.
- 조회 목적, user, time, filter shape를 분리해서 기록할 수 있다.

단점:

- 모델/migration이 필요하다.

권장:

- 화면/API 조회는 `DataIngestionLog`에 기록하지 않는다.
- 운영자 조회 감사가 필요하면 별도 `AuditLog`를 설계한다.
- command 실행만 `DataIngestionLog`에 기록한다.

## 9. DB 저장 정책

이번 Order History 화면/API는 DB 저장하지 않는다.

향후 저장하려면 별도 설계가 필요하다.

- `OrderHistory` model
- `TradeExecution` model
- user/account mapping
- order id hash
- `clientOrderId` redaction
- retention policy
- unique constraint
- migration
- backfill
- backup/rollback
- privacy/security review

권장:

- W2 이후에도 즉시 DB 저장은 하지 않는다.
- staff-only read-only API/화면을 먼저 검토한다.

## 10. Portfolio/손익 분석 연결 가능성

가능한 활용:

- 실제 매수/매도 체결 기반 평균단가 검증
- `UserHolding.average_price`와 실제 체결 내역 비교
- 실현손익/미실현손익 분리
- 수수료/세금 기반 손익 보정
- 매매 이력 기반 리포트

보류 이유:

- 거래 내역은 민감도가 높다.
- 저장 모델과 user/account mapping이 필요하다.
- 세금, 수수료, 정산일, 통화 처리가 필요하다.
- 매수/매도/취소/부분체결 상태 처리가 필요하다.
- 잘못 연결하면 투자 성과 계산 오류가 발생할 수 있다.

권장:

- W3에서 별도 설계한다.
- W2에서는 화면/API read-only 제공 범위만 설계한다.

## 11. permission / auth 정책

staff-only API/화면 권장 permission:

- `IsAuthenticated`
- `user.is_staff=True`
- 또는 custom permission: `CanViewTossOrderHistory`

일반 authenticated user는 접근 불가다.

접근 실패 정책:

- API: 403
- HTML 화면: anonymous는 login redirect, authenticated non-staff는 403

테스트 전략:

- anonymous 접근 차단
- non-staff 접근 차단
- staff 접근 허용
- response에 민감정보 없음
- order mutation 없음
- DB write 없음

## 12. response / 화면 schema

Normalized order item schema 예시:

```json
{
  "order_id_masked": "abcd****wxyz",
  "symbol": "035250",
  "side": "BUY",
  "order_type": "LIMIT",
  "time_in_force": "DAY",
  "status": "FILLED",
  "price": "16000",
  "quantity": "2",
  "order_amount": null,
  "currency": "KRW",
  "ordered_at": "2026-06-16T09:00:00+09:00",
  "canceled_at": null,
  "execution": {
    "filled_quantity": "2",
    "average_filled_price": "16000",
    "filled_amount": "32000",
    "commission": "...",
    "tax": "...",
    "filled_at": "...",
    "settlement_date": "..."
  }
}
```

예시는 fake/placeholder만 사용한다. 실제 order id, actual account, raw response, `clientOrderId`는 문서화하지 않는다.

## 13. UI/문구 안전 정책

권장 문구:

- 주문/체결 내역 조회
- 읽기 전용
- 주문을 실행하지 않습니다
- 주문 생성, 정정, 취소 기능은 제공하지 않습니다
- 주문 식별자는 마스킹되어 표시됩니다

금지 버튼:

- 주문하기
- 취소하기
- 정정하기
- 다시 매수
- 자동매매
- 추천대로 매수

금지 설명:

- 이 주문을 다시 실행
- 이 가격에 매수
- 수익 보장
- 자동 주문

## 14. 테스트 전략

API tests:

1. anonymous 401/403
2. non-staff 403
3. staff 200
4. status validation
5. symbol validation
6. date validation
7. limit validation
8. provider fake success
9. provider fake failure
10. order id masked only
11. `clientOrderId` excluded
12. account/token/header excluded
13. raw response excluded
14. DB write 없음
15. API/화면 기준 `DataIngestionLog` 생성 없음
16. mutation endpoint not called
17. `POST /api/v1/orders` not present
18. modify/cancel not present

HTML tests:

1. staff 화면 접근 가능
2. non-staff 접근 차단
3. table에 safe normalized fields 표시
4. masked id만 표시
5. mutation button 없음
6. raw response 없음
7. 금지 CTA 없음
8. read-only warning 있음

## 15. 단계별 구현 계획

### Step W2A: staff-only API 구현

- `GET /api/operations/toss/order-history/`
- `IsAuthenticated` + staff-only permission
- fake provider tests
- Codex 검증 중 no-network/fake only

### Step W2B: staff-only API smoke

- 실제 `GET /api/v1/orders` read-only 호출
- DB write 없음
- order id masked
- mutation 없음

### Step W2C: staff-only HTML 화면 설계/구현

- `GET /operations/toss/order-history/`
- table view
- filters
- no mutation buttons

### Step W2D: Order History 저장 여부 재검토

- 저장 모델이 필요한지 판단
- 필요하면 별도 migration 설계

### Step W3: Portfolio/손익 분석 연결 설계

- 체결 내역 기반 평균단가/수수료/세금 보정
- 실현/미실현 손익 분리

## 16. 보류/금지 항목

보류:

- 일반 사용자용 Order History 화면/API
- cursor 원문을 직접 노출하는 pagination
- Order History DB 저장
- Portfolio/손익 분석 자동 연결
- 별도 AuditLog model

금지:

- `POST /api/v1/orders` 구현/호출
- 주문 생성 API 구현/호출
- 주문 정정 API 구현/호출
- 주문 취소 API 구현/호출
- modify/cancel endpoint 구현/호출
- Order Info detail endpoint 호출
- 매수 가능 금액 API 호출
- 매도 가능 수량 API 호출
- 자동매매 설계
- 조건 충족 시 자동 주문 로직 설계
- `orderId` 원문 노출
- `clientOrderId` 원문 노출
- accountNo/accountSeq 원문 노출
- `X-Tossinvest-Account` 노출
- Authorization/access token 노출
- raw response 노출
