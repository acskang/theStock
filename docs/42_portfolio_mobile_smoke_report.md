# Portfolio Mobile Smoke Report

## 1. 목적

Step Q4A에서 적용한 Portfolio Summary 최소 모바일 가독성 개선이 운영 DB 기준 read-only 화면 렌더링에서 정상적으로 반영되는지 확인한다.

이번 smoke는 Django RequestFactory 렌더링, CSS 파일 내용 확인, DB count 전후 비교, grep, 전체 테스트를 기준으로 한다. 실제 모바일 브라우저 viewport 픽셀 렌더링은 별도 사용자/브라우저 확인 대상으로 남긴다.

## 2. 점검 대상

- 화면: `GET /portfolio/summary/`
- template: `portfolio/templates/portfolio/summary.html`
- CSS: `portfolio/static/portfolio/css/styles.css`
- 주요 markup:
  - `portfolio-table-scroll`
  - `portfolio-summary-table`
  - `portfolio-scroll-hint`
  - `portfolio-number`
  - `simulation-form-grid`
  - `simulation-field`
  - `simulation-result`
- 점검 대상 holding:
  - holding id: `1`
  - stock code: `035250`
  - stock name: `강원랜드`
  - quantity: `2`
  - average_price: `15116.50`
  - latest close price: `16340.00`

## 3. DB count 변화

Smoke 전:

- Stock count: `17`
- DailyPrice count: `3`
- UserHolding count: `1`
- DataProviderStatus count: `0`
- DataIngestionLog count: `85`

Smoke 후:

- Stock count: `17`
- DailyPrice count: `3`
- UserHolding count: `1`
- DataProviderStatus count: `0`
- DataIngestionLog count: `85`

판정:

- DB count 변화 없음
- DataIngestionLog 생성 없음

## 4. 화면 렌더링 결과

RequestFactory로 인증 사용자 요청을 구성해 `portfolio_summary_page`를 직접 렌더링했다.

- selected user exists: `True`
- page status_code: `200`

화면 표시 확인:

- `포트폴리오`: 표시됨
- `035250`: 표시됨
- `강원랜드`: 표시됨
- `최근 일봉 종가`: 표시됨
- `일봉 기준일`: 표시됨
- `실시간 가격이 아닙니다`: 표시됨

## 5. 모바일 markup 확인

다음 모바일 개선 markup이 HTML에 포함됨을 확인했다.

- `portfolio-table-scroll`: 있음
- `portfolio-summary-table`: 있음
- `portfolio-scroll-hint`: 있음
- `portfolio-number`: 있음
- `표를 좌우로 스크롤할 수 있습니다`: 있음

Simulation UI hook 유지:

- `simulation-form-grid`: 있음
- `simulation-field`: 있음
- `simulation-result`: 있음
- `simulation-toggle`: 있음
- `simulation-submit`: 있음
- `data-simulation-endpoint`: 있음
- `additional_budget`: 있음
- `buy_price`: 있음
- `target_price`: 있음

## 6. CSS 확인

확인된 CSS 파일:

- `portfolio/static/portfolio/css/styles.css`

CSS 내용 확인:

- `portfolio-table-scroll`: 있음
- `overflow-x`: 있음
- `-webkit-overflow-scrolling`: 있음
- `portfolio-summary-table`: 있음
- `min-width`: 있음
- `portfolio-number`: 있음
- `white-space`: 있음
- `simulation-form-grid`: 있음
- `simulation-result`: 있음
- `@media`: 있음
- `max-width`: 있음

## 7. 안전 문구 확인

다음 안전 문구가 화면에 유지됨을 확인했다.

- `계산 전용`: 있음
- `주문을 실행하지 않습니다`: 있음
- `매수/매도 추천이 아닙니다`: 있음
- `수익을 보장하지 않습니다`: 있음
- `수수료와 세금은 포함하지 않습니다`: 있음
- `가격은 저장된 DailyPrice의 최근 일봉 종가 기준입니다`: 있음
- `실시간 가격이 아닙니다`: 있음

## 8. 금지 표현 / 민감정보 확인

화면 렌더링 결과에서 다음 항목은 포함되지 않았다.

- `username`: 없음
- `email`: 없음
- `user_id`: 없음
- `accountNo`: 없음
- `accountSeq`: 없음
- `X-Tossinvest-Account`: 없음
- `access_token`: 없음
- `Authorization`: 없음
- `raw_response`: 없음
- `order_id`: 없음
- `orderNo`: 없음
- `매수하기`: 없음
- `매도하기`: 없음
- `주문하기`: 없음
- `자동매매`: 없음
- `추천대로 매수`: 없음

grep 결과:

- 금지 표현 grep은 `portfolio/tests.py`의 부정 검증 토큰만 탐지했다.
- 실제 UI template/static CSS에는 금지 CTA가 없다.
- 민감정보 패턴 grep 결과는 없었다.

## 9. read-only 보장

- 화면 렌더링은 RequestFactory 기반 read-only 확인으로 수행했다.
- Django Client login/force_login은 사용하지 않았다.
- 운영 DB write 없음
- DataIngestionLog 생성 없음
- Toss API 직접 호출 없음
- 주문 API 호출 없음
- no-network command 직접 실행 없음
- scheduler 실행 없음

전체 테스트 실행 중 출력된 management command 로그는 테스트 DB에서 수행되는 기존 테스트 로그이며, 이번 smoke에서 운영 command를 별도로 실행한 것이 아니다.

## 10. 테스트 결과

- `python manage.py check`: OK
- `python manage.py test`: OK, `393 tests passed`

## 11. 최종 판정

PASS

이유:

- check/test 통과
- Portfolio Summary 화면 200 렌더링
- 모바일 wrapper/class/hint 렌더링 확인
- CSS class와 media query 확인
- Simulation UI hook 유지
- 안전 문구 유지
- 금지 CTA 없음
- 민감정보 없음
- DB count 변화 없음
- DataIngestionLog count 변화 없음
- Toss API 호출 없음
- 주문 API 호출 없음

## 12. 남은 주의사항

- Django RequestFactory smoke는 실제 모바일 viewport 픽셀 렌더링을 완전히 검증하지 못한다.
- 실제 iOS/Android/desktop narrow width 브라우저에서 가로 스크롤, 터치 영역, form/result 가독성을 추가 확인해야 한다.
- 사용자 피드백에서 table scrolling이 여전히 불편하면 mobile card layout 설계를 별도 Step으로 진행한다.
- 주문 API와 자동매매는 계속 비활성 유지한다.
