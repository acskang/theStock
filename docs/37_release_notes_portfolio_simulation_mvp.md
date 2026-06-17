# Release Notes: Portfolio Summary and Simulation MVP

## 1. 릴리즈 목적

이번 MVP는 Toss OpenAPI 연동으로 수집한 데이터를 theStock 사용자 가치 기능으로 연결하는 첫 운영 가능한 범위를 정리한다.

핵심 목적:

- Toss OpenAPI로 실제 데이터를 가져올 수 있는 인증, quote, candle, holdings 경로를 검증했다.
- `DailyPrice`와 `UserHolding`의 최소 저장, skip, update 경로를 검증했다.
- 저장된 `UserHolding`과 최신 `DailyPrice`를 사용해 Portfolio Summary 화면/API를 제공한다.
- 사용자는 보유 종목 기준 평균단가, 최신가, 평가금액, 손익, 손익률을 확인할 수 있다.
- 사용자는 추가 예산 기준 평균단가 변화를 계산할 수 있다.
- 기능 범위는 계산, 요약, 시뮬레이션이다.
- 주문 실행은 포함하지 않는다.
- 자동매매는 포함하지 않는다.

## 2. 릴리즈 범위 요약

포함:

- Toss OpenAPI read-only smoke 및 ingestion command 기반 검증.
- `DailyPrice` 단일 저장 경로.
- `DailyPrice` batch dry-run.
- Toss holdings 기반 `UserHolding` mapping/save/skip/update 경로.
- `DataIngestionLog` 기록 경로.
- Portfolio Summary service/API/화면.
- Additional Buy Simulation service/API.
- Portfolio Summary 화면의 inline simulation UI.
- 투자 조언 오해 방지 문구.

미포함:

- 주문 API.
- 자동매매.
- scheduler/cron/systemd 실제 등록.
- DailyPrice batch commit.
- UserHolding 대량 commit.
- optional live quote UI.
- 계좌/토큰/헤더/raw response 노출.

## 3. 사용자에게 제공되는 기능

### Portfolio Summary 화면

Route:

```text
GET /portfolio/summary/
```

사용자 기능:

- 로그인 사용자의 보유 현황 요약을 보여준다.
- 저장된 `UserHolding`과 latest `DailyPrice`를 사용한다.
- 평가금액, 평가손익, 평가손익률을 표시한다.
- read-only 화면이다.
- 주문 버튼을 제공하지 않는다.
- 자동매매 UI를 제공하지 않는다.

### Portfolio Summary API

Endpoint:

```text
GET /api/portfolio/summary/
```

사용자 기능:

- JSON portfolio summary를 제공한다.
- `IsAuthenticated`가 필요하다.
- `request.user` 기준 owner scope를 적용한다.
- active `UserHolding`만 기본 포함한다.
- `include_inactive=true`로 inactive holding 포함 조회가 가능하다.
- DB-only이다.
- `DataIngestionLog`를 생성하지 않는다.

### Additional Buy Simulation API

Endpoint:

```text
POST /api/holdings/{id}/additional-buy-simulation/
```

사용자 기능:

- 특정 보유종목 기준 추가 예산 시뮬레이션을 계산한다.
- `simulation_only=true`를 반환한다.
- `order_execution=false`를 반환한다.
- 추가 후 평균단가, 손익분기점, latest price 기준 손익률을 계산한다.
- `target_price`가 있으면 목표가 기준 계산을 함께 제공한다.
- DB write를 하지 않는다.
- 주문 실행을 하지 않는다.

### Portfolio Summary 화면 inline simulation UI

사용자 기능:

- 각 holding row에서 `평균단가 계산` 버튼을 제공한다.
- `additional_budget`, `buy_price`, `target_price`를 입력할 수 있다.
- `POST /api/holdings/{id}/additional-buy-simulation/`로 계산 결과를 가져온다.
- 화면 결과에 계산 전용, 주문 미실행, 투자 권유 아님, 수익 보장 아님, 수수료/세금 제외 문구를 표시한다.

## 4. 운영자에게 제공되는 기능

운영 command 상세 allow/deny 정책은 `docs/27_operational_command_policy.md`를 따른다.

운영자가 사용할 수 있는 주요 기능:

- Toss provider 설정 상태 확인.
- Toss token/quote/candle/holdings read-only smoke.
- DailyPrice 단일 symbol dry-run/save/skip/update.
- DailyPrice batch dry-run.
- Toss holdings mapping dry-run.
- UserHolding 단일 symbol save/skip/update.
- scheduler wrapper profile 확인 및 no-network preflight.
- `DataIngestionLog` 기반 command 실행 결과 확인.

주의:

- no-network command도 `DataIngestionLog` row를 생성할 수 있다.
- DB write command는 `--commit --confirm-save`가 필요하다.
- `UserHolding` write command는 `--user-id` 또는 `--username`으로 owner를 명시해야 한다.
- 운영 DB domain write는 별도 승인과 전후 count 확인이 필요하다.

## 5. 구현된 API

| API | Method | Auth | DB write | Toss API | DataIngestionLog | 설명 |
|---|---|---|---:|---:|---:|---|
| `/api/portfolio/summary/` | GET | 필요 | 없음 | 없음 | 없음 | 포트폴리오 요약 |
| `/api/holdings/{id}/additional-buy-simulation/` | POST | 필요 | 없음 | 없음 | 없음 | 추가매수 계산 시뮬레이션 |

기존 holdings API와 evaluate/probability/consult API도 존재하지만, 이번 릴리즈의 핵심 사용자 노출 범위는 Portfolio Summary와 Additional Buy Simulation이다.

## 6. 구현된 화면

| 화면 | Route | Auth | DB write | Toss API | 설명 |
|---|---|---|---:|---:|---|
| Portfolio Summary | `/portfolio/summary/` | 필요 | 없음 | 없음 | 보유 현황 및 계산 UI |

화면 정책:

- 로그인 필요.
- `request.user`의 holding만 표시.
- username, email, user id, account, token, header, raw response를 표시하지 않음.
- 주문 버튼 없음.
- 자동매매 UI 없음.

## 7. 구현된 command

| command | 용도 | 실제 API 호출 | DB 저장 | 운영 정책 |
|---|---|---:|---:|---|
| `check_toss_provider` | Toss provider 설정 확인 | 없음 | 로그 가능 | order execution flag 확인 |
| `toss_token_smoke` | token endpoint smoke | 가능 | 로그 가능 | raw token 출력 금지 |
| `toss_quote_smoke` | quote endpoint smoke | 가능 | 로그 가능 | DB domain save 없음 |
| `toss_daily_price_ingest_dryrun` | 단일 symbol 일봉 조회/저장 | 가능 | 조건부 | `--commit --confirm-save` |
| `toss_daily_price_batch_dryrun` | 여러 symbol 일봉 후보 조회 | 가능 | 없음 | dry-run 전용 |
| `toss_holdings_sync_dryrun` | 보유주식 조회/저장 | 가능 | 조건부 | `--map-user-holdings` + user + confirm |
| `run_scheduled_ingestion` | scheduler wrapper | profile별 상이 | 현재 profile은 로그 중심 | systemd 미등록 |

## 8. 실제 검증 완료 항목

- [x] Toss token smoke
- [x] Toss quote smoke
- [x] Toss provider quote smoke
- [x] Toss registry quote smoke
- [x] DailyPrice dry-run
- [x] DailyPrice 신규 저장
- [x] DailyPrice existing row skip
- [x] DailyPrice `--update-existing`
- [x] DailyPrice batch dry-run `--symbols`
- [x] DailyPrice batch dry-run `--from-stock-db`
- [x] Toss accounts diagnostic
- [x] Toss holdings dry-run
- [x] UserHolding mapping dry-run
- [x] UserHolding 신규 저장
- [x] UserHolding existing row skip
- [x] UserHolding `--update-existing`
- [x] scheduler wrapper command 구현
- [x] no-network scheduler profile 검증
- [x] Portfolio Summary service
- [x] Portfolio Summary API smoke
- [x] Portfolio Summary 화면 smoke
- [x] Additional Buy Simulation service
- [x] Additional Buy Simulation API smoke
- [x] Simulation UI 화면/API 통합 smoke
- [x] 표현 안전 문구 반영
- [x] 주문 API 미호출 확인
- [x] 민감정보 미노출 확인

## 9. 운영 DB 마지막 검증 상태

마지막 수동 검증 기준:

| Model | Count |
|---|---:|
| `Stock` | 17 |
| `DailyPrice` | 3 |
| `UserHolding` | 1 |
| `DataProviderStatus` | 0 |
| `DataIngestionLog` | 85 |

주의:

- 실제 운영 DB count는 이후 command 실행에 따라 달라질 수 있다.
- `DataIngestionLog`는 command 실행으로 계속 증가할 수 있다.
- Portfolio Summary 화면/API 조회는 `DataIngestionLog`를 생성하지 않는다.
- Additional Buy Simulation API 호출은 `DataIngestionLog`를 생성하지 않는다.

## 10. 안전 정책

화면/API:

- Portfolio Summary는 DB-only이다.
- Additional Buy Simulation API는 DB-only이다.
- 화면/API는 Toss API를 호출하지 않는다.
- 화면/API는 DB write를 하지 않는다.
- 화면/API는 `DataIngestionLog`를 생성하지 않는다.
- 화면/API는 주문 API를 호출하지 않는다.

command:

- Toss API는 ingestion/smoke command에서만 사용한다.
- command DB write는 `--commit --confirm-save`가 필요하다.
- `UserHolding` write는 user selector가 필요하다.
- `Stock` 자동 생성은 금지한다.
- inactive `UserHolding` 자동 재활성화는 금지한다.
- US/fractional holdings 저장은 보류한다.

## 11. 민감정보 보호 정책

금지:

- `.env` 원문 출력.
- client id/client secret 원문 출력.
- access token 원문 출력.
- Authorization header 출력.
- accountNo/accountSeq 원문 출력.
- `X-Tossinvest-Account` 원문 출력.
- request headers/body 출력.
- raw API response 전체 출력/저장.
- username/email 화면/API response 노출.
- user id 화면/API response 노출.

허용:

- configured/missing boolean.
- masked summary.
- endpoint name.
- safe status/reason.
- candidate/saved/skipped/failed count.

## 12. 주문 API / 자동매매 정책

현재 정책:

- 주문 API는 미구현이다.
- 주문 생성/정정/취소 API를 호출하지 않는다.
- Order API / Order History / Order Info는 호출하지 않는다.
- 매수 가능 금액 API와 매도 가능 수량 API는 현재 workflow에 포함하지 않는다.
- 자동매매 기능은 없다.
- 조건 충족 시 자동 주문 기능은 없다.
- 화면에는 주문 버튼이 없다.
- Additional Buy Simulation API response에는 `order_execution=false`만 포함된다.
- 주문 ID, 주문번호, 주문 상태는 response에 없다.
- `TOSS_ORDER_EXECUTION_ENABLED=false` 기본 정책을 유지한다.

## 13. 보류된 항목

- scheduler/cron/systemd 실제 등록.
- actual network scheduler profile 운영 실행.
- DailyPrice batch commit.
- UserHolding 대량 commit.
- fallback provider 자동 전환.
- `DataProviderStatus` 자동 갱신.
- alerting 연동.
- optional live quote UI.
- US/fractional holdings 저장.
- currency field 확장.
- 다중 계좌 account hash 설계.
- 주문 API.
- 자동매매.

## 14. 배포 전 checklist

- [ ] `python manage.py check` 통과.
- [ ] `python manage.py test` 통과.
- [ ] 민감정보 grep 결과 확인.
- [ ] `.env` 원문을 출력하지 않았음.
- [ ] `TOSS_ORDER_EXECUTION_ENABLED=false` 확인.
- [ ] `/portfolio/summary/` 인증 필요 확인.
- [ ] `/api/portfolio/summary/` 인증 필요 확인.
- [ ] `/api/holdings/{id}/additional-buy-simulation/` 인증 필요 확인.
- [ ] 주문 버튼/자동매매 UI 없음 확인.
- [ ] 운영 command allow/deny policy 확인.
- [ ] DB backup 필요 여부 확인.

## 15. 배포 후 smoke checklist

화면/API smoke:

- [ ] `/portfolio/summary/` 로그인 사용자 200.
- [ ] `/api/portfolio/summary/` 로그인 사용자 200.
- [ ] `POST /api/holdings/{id}/additional-buy-simulation/` 200.
- [ ] invalid budget 400.
- [ ] DB count 변화 없음.
- [ ] `DataIngestionLog` 변화 없음.
- [ ] 금지 표현 없음.
- [ ] 민감정보 없음.

운영 command smoke는 별도 승인 후 진행한다:

- [ ] `run_scheduled_ingestion --profile=toss_no_network_preflight`
- [ ] 필요 시 `toss_daily_price_batch_dryrun --symbols=...` actual dry-run

주의:

- no-network command도 `DataIngestionLog`를 생성할 수 있다.
- 이 릴리즈 노트 작성 단계에서는 위 smoke command를 실행하지 않는다.

## 16. 모니터링 항목

- Portfolio Summary 500 error.
- Additional Buy Simulation API 400/500 error 비율.
- response에 forbidden key가 포함되는지 여부.
- `DataIngestionLog` command failure.
- Toss auth/rate limit failure.
- 민감정보 grep 이상.
- `order_execution=true`가 response에 나타나는지 여부.
- 주문 관련 endpoint 호출 흔적.
- 화면에 주문 버튼이나 자동매매 UI가 노출되는지 여부.

## 17. rollback / 중단 기준

즉시 중단 기준:

- access token 원문 노출.
- accountNo/accountSeq 원문 노출.
- Authorization header 노출.
- 주문 API 호출 흔적.
- 화면에 주문 버튼 노출.
- `UserHolding`/`DailyPrice` 예상 외 증가.
- Simulation API가 DB write 발생.
- `order_execution=true` 응답.

조치:

- 배포 중단.
- 노출 로그 접근 제한.
- token/secret 재발급 검토.
- 마지막 배포/커밋 확인.
- DB backup 복원 필요 여부 판단.
- 추가 command 실행 중지.

## 18. 알려진 제한사항

- Portfolio Summary는 latest `DailyPrice` 기준이며 실시간 가격이 아니다.
- DailyPrice 데이터가 부족하면 평가금액과 손익 계산이 제한된다.
- `UserHolding` 데이터가 적으면 화면 가치가 제한적이다.
- Additional Buy Simulation은 수수료, 세금, 슬리피지를 포함하지 않는다.
- Additional Buy Simulation은 투자 권유가 아니다.
- live quote는 아직 UI에 연결하지 않았다.
- batch commit은 아직 보류이다.
- scheduler 자동화는 아직 운영 등록하지 않았다.
- US/fractional holdings는 현재 저장 대상이 아니다.

## 19. 다음 단계 후보

- Step Q: 사용자 피드백 반영.
- Step S: 운영 배포 전 최종 점검.
- Step T: 배포 후 smoke.
- Step U: optional live quote 설계.
- Step V: DailyPrice batch commit 설계.
- 주문 API는 계속 비활성 유지.
