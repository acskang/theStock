# Codex Prompt: theStock Toss OpenAPI First Provider Policy

## 작업 요약

`theStock` 운영 데이터 공급 정책을 Toss OpenAPI first provider 정책으로 정리한다.

운영 서비스 URL:

- https://stock.thesysm.com/

공식 문서:

- https://developers.tossinvest.com/docs
- https://developers.tossinvest.com/llms.txt
- https://openapi.tossinvest.com/openapi-docs/overview.md
- https://openapi.tossinvest.com/openapi-docs/latest/api-reference/README.md
- https://openapi.tossinvest.com/openapi-docs/latest/openapi.json

## 핵심 지시

1. Toss OpenAPI에서 제공하는 데이터는 `TossOpenApiProvider`를 1순위 provider로 사용한다.
2. Toss OpenAPI에서 제공하지 않거나 제공 범위가 부족한 데이터만 fallback provider를 사용한다.
3. MockDataProvider, pykrx, OPENDART, 수동 입력 provider는 제거하지 않는다.
4. provider 우선순위는 설정값으로 제어한다.
5. Toss API 장애, rate limit, 인증 실패가 서비스 전체 장애로 번지지 않게 한다.
6. 실패는 `DataIngestionLog` 또는 운영 로그에 남긴다.
7. 컨설팅 엔진은 provider가 무엇인지 몰라도 되도록 기존 도메인 모델과 service interface를 유지한다.
8. 주문 생성/정정/취소는 별도 승인 전까지 비활성화한다.
9. 실제 API Key, Secret Key, Access Token, 계좌번호는 문서나 Git에 저장하지 않는다.

## 산출물

다음 문서를 수정 또는 생성한다.

- `docs/00_current_state_entrypoint.md`
- `docs/08_data_pipeline_design.md`
- `docs/10_toss_openapi_provider_design.md`
- `docs/15_operations_runbook.md`
- `docs/16_observability_and_alerting_design.md`
- `docs/18_privacy_and_financial_data_policy.md`
- `docs/19_toss_openapi_first_provider_policy.md`
- `docs/20_toss_openapi_mapping_table.md`
- `docs/21_toss_openapi_security_checklist.md`
