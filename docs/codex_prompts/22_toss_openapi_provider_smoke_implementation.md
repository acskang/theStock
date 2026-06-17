# Codex Prompt: TossOpenApiProvider 1차 Smoke 구현

## 0. 작업 배경

나는 theStock 서비스를 운영하고 있다.

운영 서비스 URL:

- https://stock.thesysm.com/

theStock는 주식 물타기/추가매수 판단을 돕는 데이터 기반 컨설팅 서비스이다.

최근 문서에 다음 정책을 반영했다.

- 토스증권 OpenAPI에서 제공하는 데이터는 TossOpenApiProvider를 1순위 provider로 사용한다.
- 토스증권 OpenAPI에서 제공하지 않거나, 장애/rate limit/인증 실패가 발생하면 fallback provider를 사용한다.
- 주문 생성/정정/취소는 기본 비활성화한다.
- 실제 API Key, Secret, Access Token, 계좌 식별자는 문서/Git/log에 저장하지 않는다.

토스증권 OpenAPI 공식 문서:

- https://developers.tossinvest.com/docs
- https://developers.tossinvest.com/llms.txt
- https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md
- https://openapi.tossinvest.com/openapi-docs/latest/openapi.json

이번 작업은 전체 연동이 아니라 **TossOpenApiProvider 1차 smoke 구현**이다.

절대 무리하게 전체 기능을 구현하지 말고, 안전한 최소 단위만 구현한다.

---

## 1. 이번 작업 목표

이번 작업의 목표는 다음이다.

1. Toss OpenAPI 인증 token 발급 smoke command 구현
2. TossOpenApiProvider health check 구현
3. 단일 종목 시세 조회 dry-run command 구현
4. Toss API 호출 결과 또는 실패를 DataIngestionLog 또는 기존 로그 모델에 기록
5. 실제 주문 생성/정정/취소 API는 구현하지 않거나, 구현하더라도 강제로 차단
6. 실제 DB 저장은 기본적으로 하지 않고, `--commit` 옵션이 있을 때만 저장 가능하게 설계
7. 기존 서비스 기능, 화면, API에 영향이 없게 구현

---

## 2. 가장 중요한 안전 원칙

반드시 지켜라.

### 2.1 Secret 보호

- API Key, Secret, Access Token, 계좌 식별자 실제값을 코드, 문서, 테스트 fixture, 로그에 남기지 말 것.
- `.env.example`에는 변수명만 추가할 것.
- 로그 출력 시 secret/token/account는 반드시 마스킹할 것.
- 예외 메시지에도 token/client_secret/account id가 섞이지 않게 할 것.

### 2.2 주문 실행 금지

다음 API 또는 기능은 이번 작업에서 절대 실제 실행하지 않는다.

- 주문 생성
- 주문 정정
- 주문 취소
- 자동 매매
- 조건 충족 시 자동 주문

환경변수 기본값은 반드시 다음 상태여야 한다.

```env
TOSS_ORDER_EXECUTION_ENABLED=false
```
