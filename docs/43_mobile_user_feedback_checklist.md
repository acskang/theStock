# Mobile User Feedback Checklist

## 1. 목적

이 문서는 Portfolio Summary 화면의 모바일 사용자 피드백을 실제로 수집하기 위한 체크리스트와 기록 양식을 정의한다.

현재 모바일 개선은 table 구조를 유지하면서 가로 스크롤 wrapper, scroll hint, 숫자 컬럼 class, Simulation form/result 모바일 class를 추가한 최소 개선이다. 실제 모바일 사용자가 표를 읽고, 평균단가 계산 form을 열고, 계산 결과와 안전 문구를 이해하는지 확인하는 것이 목적이다.

이 문서는 기능 구현 문서가 아니다. 코드, template, JavaScript, CSS, API schema, DB schema는 변경하지 않는다.

## 2. 현재 모바일 개선 상태

현재 화면:

- route: `GET /portfolio/summary/`
- 인증: 로그인 필요
- 데이터: 저장된 `UserHolding`과 `DailyPrice` 기반
- 가격 label: `최근 일봉 종가`
- 가격 안내: `실시간 가격이 아닙니다`
- Simulation UI:
  - `평균단가 계산` 버튼
  - `additional_budget`
  - `buy_price`
  - `target_price`
  - `계산하기` 버튼
- 안전 문구:
  - 계산 전용
  - 주문을 실행하지 않습니다
  - 매수/매도 추천이 아닙니다
  - 수익을 보장하지 않습니다
  - 수수료와 세금은 포함하지 않습니다

Step Q4A 적용 항목:

- `portfolio-table-scroll` wrapper
- `portfolio-summary-table`
- `portfolio-scroll-hint`
- `표를 좌우로 스크롤할 수 있습니다.`
- `portfolio-number`
- `simulation-form-grid`
- `simulation-field`
- `simulation-result`
- CSS 위치: `portfolio/static/portfolio/css/styles.css`

Step Q4B smoke 결과:

- 화면 status_code: `200`
- 모바일 markup/CSS 확인
- DB count 변화 없음
- `DataIngestionLog` 변화 없음
- Toss API 호출 없음
- 주문 API 호출 없음
- 금지 CTA 없음
- 민감정보 없음
- `python manage.py test`: `393 tests passed`

## 3. 테스트 대상 환경

필수 확인 환경:

- iOS Safari
- Android Chrome
- Desktop Chrome narrow width
- Desktop Safari 또는 Firefox narrow width

사용자 유형:

- 실제 로그인 사용자
- 테스트 사용자

주의:

- 실제 계정 정보는 피드백 문서에 기록하지 않는다.
- 실제 사용자 식별값, username, email을 기록하지 않는다.
- 계좌번호, accountSeq, token, header, raw response를 기록하지 않는다.
- 화면 캡처를 받을 경우 민감정보가 포함되지 않았는지 먼저 확인한다.

권장 viewport 기준:

- 모바일 세로: 360px-430px 폭
- 모바일 가로: 640px-932px 폭
- desktop narrow: 375px, 390px, 430px, 768px 근처

## 4. 사용자 확인 시나리오

### 시나리오 1: 포트폴리오 요약 확인

1. 모바일 브라우저에서 로그인한다.
2. `/portfolio/summary/` 화면에 접근한다.
3. 보유종목이 표시되는지 확인한다.
4. `최근 일봉 종가`가 실시간 가격이 아니라 저장된 일봉 기준임을 이해하는지 확인한다.
5. 보유 수량, 평균단가, 평가금액, 손익률이 읽기 쉬운지 확인한다.
6. 안전 문구가 과하거나 부족하지 않은지 확인한다.

### 시나리오 2: 표 가로 스크롤 확인

1. 화면 폭을 좁힌다.
2. 보유종목 table이 잘리는지 확인한다.
3. `표를 좌우로 스크롤할 수 있습니다.` 문구를 확인한다.
4. table을 좌우로 스크롤한다.
5. 오른쪽의 `평균단가 계산` 버튼까지 자연스럽게 도달할 수 있는지 확인한다.
6. 스크롤 중 종목명, 숫자, 금액이 혼란스럽게 줄바꿈되지 않는지 확인한다.

### 시나리오 3: 평균단가 계산 form 확인

1. `평균단가 계산` 버튼을 누른다.
2. inline form이 열리는지 확인한다.
3. `추가 예산`, `계산 기준 가격`, `목표가 기준 계산` label이 이해되는지 확인한다.
4. 입력 필드가 모바일에서 충분히 크게 보이는지 확인한다.
5. `계산 기준 가격`을 비우면 저장된 최근 일봉 종가를 사용한다는 안내가 이해되는지 확인한다.
6. `계산하기` 버튼이 주문 버튼처럼 보이지 않는지 확인한다.

### 시나리오 4: 계산 결과 확인

1. 추가 예산을 입력한다.
2. 필요하면 계산 기준 가격과 목표가 기준 계산 값을 입력한다.
3. `계산하기` 버튼을 누른다.
4. 계산 중 상태가 보이는지 확인한다.
5. 추가 가능 수량, 남은 예산, 추가 후 평균단가, 손익분기점이 이해되는지 확인한다.
6. 목표가 기준 결과가 있다면 의미를 이해하는지 확인한다.
7. `주문을 실행하지 않습니다` 문구가 명확한지 확인한다.
8. 결과가 매수 추천이나 수익 보장처럼 느껴지는 표현이 있는지 확인한다.

## 5. 화면 가독성 체크리스트

- [ ] 보유종목명이 한눈에 보인다.
- [ ] 종목 코드와 종목명이 구분된다.
- [ ] 시장 정보가 과도하게 방해되지 않는다.
- [ ] 수량, 평균단가, 최근 일봉 종가가 읽기 쉽다.
- [ ] 일봉 기준일이 가격 기준일로 이해된다.
- [ ] 평가금액과 손익률이 읽기 쉽다.
- [ ] table이 잘릴 때 가로 스크롤 가능함을 알 수 있다.
- [ ] `표를 좌우로 스크롤할 수 있습니다.` 문구가 잘 보인다.
- [ ] 모바일에서 글자가 너무 작지 않다.
- [ ] 금액 숫자가 줄바꿈되어 혼란스럽지 않다.
- [ ] 손익 정보가 색상만으로 구분되지 않는다.
- [ ] 안전 문구가 너무 길어서 핵심 정보를 방해하지 않는다.
- [ ] 페이지를 처음 본 사용자가 어디서 계산을 시작하는지 알 수 있다.

## 6. Simulation 입력 UX 체크리스트

- [ ] `평균단가 계산` 버튼이 주문 버튼처럼 보이지 않는다.
- [ ] `평균단가 계산` 버튼을 찾기 쉽다.
- [ ] `평균단가 계산` 버튼 터치 영역이 충분하다.
- [ ] form이 열린 상태와 닫힌 상태가 구분된다.
- [ ] 추가 예산 입력 의미가 명확하다.
- [ ] 계산 기준 가격을 비우면 최근 일봉 종가를 사용한다는 점이 이해된다.
- [ ] 목표가 기준 계산 입력이 이해된다.
- [ ] input label과 input이 시각적으로 연결되어 보인다.
- [ ] 모바일 키보드 입력이 불편하지 않다.
- [ ] `계산하기` 버튼이 충분히 누르기 쉽다.
- [ ] `계산하기` 버튼이 주문 버튼처럼 보이지 않는다.
- [ ] 잘못된 입력에 대한 오류 메시지가 이해된다.
- [ ] 계산 중 상태가 충분히 보인다.

## 7. 결과 표시 체크리스트

- [ ] 계산 결과가 form 바로 아래에 표시된다.
- [ ] 추가 가능 수량이 이해된다.
- [ ] 사용 예산과 남은 예산이 이해된다.
- [ ] 추가 후 총 수량이 이해된다.
- [ ] 추가 후 평균단가가 이해된다.
- [ ] 손익분기점이 이해된다.
- [ ] 최근 일봉 종가 기준 예상 손익률이 이해된다.
- [ ] 목표가 기준 계산 결과가 이해된다.
- [ ] 수수료와 세금 미포함 안내가 보인다.
- [ ] 결과가 매수 추천처럼 보이지 않는다.
- [ ] 주문이 실행되지 않는다는 점이 명확하다.
- [ ] 오류 결과가 raw response처럼 보이지 않는다.

## 8. 안전 문구 이해도 체크리스트

- [ ] `계산 전용`이라는 점이 명확하다.
- [ ] `주문을 실행하지 않습니다` 문구가 명확하다.
- [ ] `매수/매도 추천이 아닙니다` 문구가 명확하다.
- [ ] `수익을 보장하지 않습니다` 문구가 명확하다.
- [ ] `수수료와 세금은 포함하지 않습니다` 문구가 명확하다.
- [ ] `실시간 가격이 아닙니다` 문구가 명확하다.
- [ ] 사용자가 이 기능을 자동매매로 오해하지 않는다.
- [ ] 사용자가 이 기능을 매수/매도 판단 대신 자동 추천으로 오해하지 않는다.
- [ ] 안전 문구가 충분하지만 화면 사용을 과도하게 방해하지 않는다.

## 9. 금지 CTA / 주문 오해 체크리스트

다음 항목은 화면에 없어야 한다.

- [ ] `매수하기` 버튼 없음
- [ ] `매도하기` 버튼 없음
- [ ] `주문하기` 버튼 없음
- [ ] `자동매매 시작` 버튼 없음
- [ ] `추천대로 매수` 문구 없음
- [ ] `수익 보장` 문구 없음
- [ ] `확정 수익` 문구 없음
- [ ] 주문번호 표시 없음
- [ ] 주문상태 표시 없음
- [ ] 계좌번호 표시 없음
- [ ] accountSeq 표시 없음
- [ ] token/header/raw response 표시 없음

점검 원칙:

- `주문을 실행하지 않습니다` 같은 부정 문맥의 주문 단어는 허용한다.
- 버튼이나 CTA가 주문 실행처럼 보이면 D 분류로 보류한다.

## 10. 접근성 체크리스트

- [ ] 버튼 터치 영역이 충분하다.
- [ ] input label이 명확하다.
- [ ] result 영역이 form 바로 아래에 표시된다.
- [ ] result 영역에 `aria-live`가 있어 계산 결과 변화가 전달될 수 있다.
- [ ] 오류 메시지가 입력 위치와 연결되어 이해된다.
- [ ] 색상만으로 손익을 구분하지 않는다.
- [ ] 키보드 사용 시 table scroll 영역에 접근 가능하다.
- [ ] 키보드 사용 시 form 접근이 가능하다.
- [ ] screen reader 사용자를 위한 label과 상태가 유지된다.
- [ ] 가로 스크롤 영역이 사용자가 인지할 수 있는 방식으로 안내된다.

## 11. 피드백 분류 기준

### A. 즉시 반영

조건:

- label 변경
- 문구 변경
- spacing/padding 조정
- table scroll 안내 문구 개선
- 버튼 문구 개선
- 작은 CSS/template class 조정
- 테스트 보강
- DB schema 변경 없음
- Toss API 호출 없음
- 주문 API 무관

예:

- `표를 좌우로 스크롤할 수 있습니다` 위치 개선
- `평균단가 계산` 버튼 크기 조정
- form 도움말 문구를 더 짧게 변경
- 모바일 spacing 조정

### B. 설계 후 반영

조건:

- template 구조 변경이 큼
- JavaScript interaction 변경 필요
- API/service 계산 변경 가능성 있음
- 추가 테스트 필요
- 투자 조언 오해 가능성 검토 필요

예:

- mobile card layout 전환
- detail disclosure 추가
- 수수료/세금 계산 옵션
- `additional_quantity` 직접 입력 지원
- target projection 표시 방식 개선

### C. 별도 프로젝트

조건:

- DB schema 변경 필요
- batch commit 필요
- scheduler 필요
- Toss live quote 필요
- 운영 리스크 있음
- rollback/monitoring 계획 필요

예:

- optional live quote
- DailyPrice batch commit
- UserHolding 대량 sync
- `DataProviderStatus` 자동 갱신
- alerting
- scheduler 운영 등록
- US/fractional holdings 저장

### D. 금지/보류

조건:

- 주문 API 관련 요청
- 자동매매 요청
- 매수/매도 추천 요청
- 수익 보장 요청
- 계좌 원문 표시 요청
- token/header/raw response 표시 요청

예:

- 주문 API
- 자동 주문
- 매수/매도 추천
- 수익 보장
- 계좌 원문 표시
- token/header 표시
- raw Toss response 표시

처리:

- 구현하지 않는다.
- 계산용 시뮬레이션과 저장된 데이터 기반 요약이라는 대체 방향을 안내한다.
- 주문 API는 계속 비활성 유지한다.

## 12. 피드백 기록 양식

## 모바일 피드백 기록

- 날짜:
- 테스트 환경:
- 화면 폭 / 기기:
- 사용자 유형:
- 확인 시나리오:
- 피드백 내용:
- 문제 위치:
- 심각도: 낮음 / 중간 / 높음
- 분류: A / B / C / D
- 주문 API 관련 여부:
- 민감정보 관련 여부:
- 투자 조언 오해 가능성:
- 제안 처리:
- 담당자:
- 후속 Step:

기록 원칙:

- 실제 username, email, user id를 적지 않는다.
- 실제 계좌번호, accountSeq, token, header 값을 적지 않는다.
- 스크린샷에 민감정보가 들어 있으면 공유하지 않는다.
- 주문 실행 또는 자동매매 요청은 D로 분류한다.

## 13. 즉시 반영 후보

사용자 피드백 후 즉시 반영할 수 있는 후보:

- scroll hint 위치 조정
- scroll hint 문구 간결화
- `평균단가 계산` 버튼 여백 조정
- `계산하기` 버튼 터치 영역 조정
- form field spacing 조정
- result 영역 padding 조정
- 안전 문구 위치 조정
- table 숫자 정렬 또는 nowrap 범위 조정
- 관련 template/CSS 테스트 보강

즉시 반영 조건:

- API schema 변경 없음
- service 계산 로직 변경 없음
- DB write 없음
- Toss API 호출 없음
- 주문 API 무관
- 금지 CTA 추가 없음

## 14. 설계 후 반영 후보

설계 문서를 먼저 작성해야 하는 후보:

- mobile card layout
- 핵심 정보/상세 정보 분리
- detail disclosure
- Simulation result를 별도 panel로 분리
- 수수료/세금 입력 또는 계산 옵션
- `additional_quantity` 직접 입력
- target projection UI 재구성
- 모바일 전용 접근성 개선

설계 시 반드시 확인할 항목:

- owner scope 유지
- 민감정보 미노출
- `simulation_only=true`
- `order_execution=false`
- 주문 API 미호출
- DB write 없음
- Toss API 호출 여부 명확화

## 15. 보류/금지 후보

다음 요청은 보류 또는 금지한다.

- 주문 API
- 자동매매
- 조건 충족 시 자동 주문
- 매수/매도 추천
- 수익 보장
- 확정 수익 표현
- 주문번호/주문상태 표시
- 계좌번호 원문 표시
- accountSeq 표시
- access token 표시
- Authorization header 표시
- raw Toss response 표시
- live quote를 실시간 주문 UI처럼 보이게 연결하는 작업

대체 안내:

- 저장된 데이터 기반 포트폴리오 요약
- 계산용 평균단가 시뮬레이션
- 사용자가 직접 판단
- 주문은 서비스 밖에서 직접 실행

## 16. 다음 단계

- Step Q4C-Actual: 실제 모바일 사용자 피드백 수집
- Step Q4D: 피드백 기반 작은 문구/spacing 개선
- Step Q4E: card layout 설계 여부 결정
- Step U: optional live quote 설계
- Step V: DailyPrice batch commit 설계
- 주문 API는 계속 비활성 유지
