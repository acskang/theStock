# Staff Order History Screen Smoke Report

## 1. 목적

Step W2C에서 구현한 staff-only Toss Order History HTML 화면이 실제 read-only 조회 경로에서 안전하게 동작하는지 확인한다.

## 2. 점검 대상

- 화면 route: `GET /operations/toss/order-history/`
- view: `toss_order_history_page`
- template: `data_pipeline/toss_order_history.html`
- 실제 read-only provider 경로: Toss `GET /api/v1/orders`
- 금지 범위: 주문 생성, 정정, 취소, raw response 표시, 계좌/token/header/order id 원문 표시

## 3. settings 안전 상태

- `TOSS_ORDER_EXECUTION_ENABLED`: `False`
- `TOSS_INVEST_PROVIDER_ENABLED`: `True`
- 판정: PASS

## 4. 권한 smoke

- anonymous 접근: `302` login redirect
- non-staff 접근: `403`
- staff 접근: 허용
- non-staff 화면에 order table 미표시
- 판정: PASS

## 5. default GET smoke

- staff default GET status: `200`
- `run=1` 없이 접근 시 provider/network 호출 없음
- filter form 표시 확인
- 읽기 전용, 주문 미실행, 주문 생성/정정/취소 미제공 문구 표시 확인
- mutation 버튼 없음
- 민감정보 표시 없음
- 판정: PASS

## 6. CLOSED symbol 화면 smoke

- 조건: `run=1`, `status=CLOSED`, `symbol=035250`, `limit=5`
- status: `200`
- 실제 read-only 결과 영역 표시 확인
- `CLOSED`, `035250`, `network_call`, `dry_run`, `order_count`, `has_next`, `next_cursor_present`, `order_id_masked` 표시 확인
- forbidden key 및 mutation 버튼 미표시
- 판정: PASS

## 7. OPEN symbol 화면 smoke

- 조건: `run=1`, `status=OPEN`, `symbol=035250`
- status: `200`
- 조회 결과 요약 또는 empty state가 안전하게 표시됨
- `OPEN`, `035250`, 읽기 전용 문구 표시 확인
- forbidden key 및 mutation 버튼 미표시
- 판정: PASS

## 8. CLOSED all-symbol limited 화면 smoke

- 조건: `run=1`, `status=CLOSED`, `limit=5`
- status: `200`
- 조회 결과 요약 표시 확인
- safe normalized fields 중심 표시 확인
- forbidden key 및 mutation 버튼 미표시
- 개인 매매 상세 목록은 문서화하지 않음
- 판정: PASS

## 9. validation 화면 smoke

- 조건: `run=1`, `status=BAD`
- status: `200`
- safe validation error 표시 확인
- provider 호출 전 validation 차단 경로 확인
- raw exception 및 민감정보 미표시
- 판정: PASS

## 10. DB count 변화

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

## 11. DataIngestionLog 확인

- 화면 조회로 DataIngestionLog 생성 없음
- 화면 조회 metadata 생성 없음
- command ingestion log와 화면 조회 audit는 분리 유지
- 판정: PASS

## 12. mutation endpoint 미호출 확인

- 사용 경로: Toss `GET /api/v1/orders`
- `POST /api/v1/orders` 호출 없음
- modify/cancel endpoint 호출 없음
- 주문 생성/정정/취소 API 호출 없음
- mutation 버튼 없음
- mutation 위험 grep 결과는 테스트의 부정 검증 문자열 및 fake option 검증만 확인됨
- 판정: PASS

## 13. 민감정보 점검

- accountNo/accountSeq 화면 표시 없음
- `X-Tossinvest-Account` 화면 표시 없음
- access_token 화면 표시 없음
- Authorization header 화면 표시 없음
- orderId 원문 화면 표시 없음
- clientOrderId 화면 표시 없음
- cursor 원문 화면 표시 없음
- raw response 화면 표시 없음
- 민감정보 패턴 grep 결과 없음
- 판정: PASS

## 14. 최종 판정

PASS

이유:

- `python manage.py check` 통과
- `python manage.py test` 411개 통과
- staff-only 권한 정책 정상
- default GET은 provider/network 미호출
- `run=1` 실제 화면 조회는 read-only로 성공
- DB domain row 및 DataIngestionLog 변화 없음
- 민감정보, raw response, cursor 원문, mutation 버튼 노출 없음
- 주문 생성/정정/취소 mutation 호출 흔적 없음

## 15. 다음 단계

- Step W3: 매매 내역을 Portfolio/손익 분석에 연결할지 설계
- Step W4: Order History 저장 모델 필요성 검토
- 주문 생성/정정/취소 API는 계속 비활성 유지
