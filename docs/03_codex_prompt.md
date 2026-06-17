# 03_codex_prompt.md

# Codex 실행 프롬프트: 3단계 API Workflow 구현

## 사용 방법

이 파일은 Codex에 그대로 전달하기 위한 3단계 실행 프롬프트다.

Codex에게 이 파일과 함께 다음 문서를 반드시 참조하게 한다.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
docs/03_api_workflow_design.md
```

특히 `03_api_workflow_design.md`는 이번 단계의 직접 기준 문서다.

---

# 실행 프롬프트 본문

너는 Django REST Framework 기반 백엔드 서비스를 구현하는 개발 에이전트다.

이번 작업은 `물타기 타이밍 판단 시스템`의 **3단계 API Workflow 구현**이다.

1단계에서는 Django foundation이 구현되었다.  
2단계에서는 Scoring Engine이 구현되었다.  
이번 3단계에서는 2단계의 계산 엔진을 실제 API 요청 흐름에 연결한다.

이 시스템은 주식 매수 추천 서비스가 아니다.  
사용자의 보유 종목에 대해 물타기, 즉 추가 매수 가능성을 검토할 수 있는 위험 구간인지 판단하기 위한 **투자 참고용 데이터 분석 시스템**이다.

---

# 1. 반드시 참조할 문서

아래 문서를 기준으로 구현하라.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
docs/03_api_workflow_design.md
```

우선순위는 다음과 같다.

```text
1. 00_overview_and_data.md: 시스템 철학과 투자 참고용 원칙
2. 03_api_workflow_design.md: 이번 단계의 직접 구현 기준
3. 02_scoring_engine_design.md: 호출해야 할 계산 엔진 기준
4. 01_foundation_design.md: 모델과 앱 구조 기준
```

---

# 2. 이번 작업의 목표

이번 단계의 목표는 다음과 같다.

```text
1. POST /api/holdings/{id}/evaluate/ API 완성
2. evaluate_averaging_timing(holding) 호출
3. EvaluationResult를 AveragingDecision으로 저장
4. 저장된 AveragingDecision을 serializer로 변환
5. 판단 결과 JSON 응답 반환
6. GET /api/holdings/{id}/decisions/ API 완성
7. 자기 holding과 decision만 접근 가능하도록 권한 강화
8. API 테스트 작성
9. 에러 처리 명확화
10. N+1 쿼리 방지를 위한 select_related 적용
```

---

# 3. 이번 단계에서 절대 하지 말 것

이번 단계에서는 다음을 하지 마라.

```text
1. Scoring Engine 내부 로직을 views.py에 다시 구현하지 말 것
2. Serializer에서 점수 계산하지 말 것
3. View에서 임시 점수나 임시 등급을 만들지 말 것
4. 외부 주식 API 연동하지 말 것
5. 뉴스/공시 크롤러 만들지 말 것
6. 프론트엔드 화면 만들지 말 것
7. 자동 매매 기능 만들지 말 것
8. 매수/매도 추천 문구를 쓰지 말 것
```

이번 단계의 역할은 다음 하나다.

```text
Scoring Engine → API → DB 저장 → JSON 응답
```

---

# 4. 구현 대상 API

## 4.1 평가 실행 API

다음 endpoint를 완성하라.

```http
POST /api/holdings/{id}/evaluate/
```

### 요청

```text
Body 없음
Query parameter 없음
인증 필요
```

### 처리 흐름

```text
1. request.user 인증 확인
2. UserHolding을 id와 request.user 기준으로 조회
3. 조회 실패 시 404 반환
4. evaluate_averaging_timing(holding) 호출
5. EvaluationResult 반환값 수신
6. create_decision_from_result(holding, result) 호출
7. AveragingDecision 저장
8. AveragingDecisionSerializer로 직렬화
9. 200 OK로 응답
```

---

## 4.2 판단 이력 조회 API

다음 endpoint를 완성하라.

```http
GET /api/holdings/{id}/decisions/
```

### 처리 흐름

```text
1. request.user 인증 확인
2. UserHolding을 id와 request.user 기준으로 조회
3. 조회 실패 시 404 반환
4. 해당 holding의 AveragingDecision 목록 조회
5. 최신순 정렬
6. AveragingDecisionSerializer 또는 list serializer로 응답
```

---

# 5. 권한 처리 요구사항

## 5.1 절대 원칙

```text
사용자는 자기 UserHolding만 조회, 평가, 이력 조회할 수 있다.
사용자는 다른 사용자의 AveragingDecision을 조회할 수 없다.
```

---

## 5.2 금지 구현

다음 구현은 금지한다.

```python
UserHolding.objects.get(id=pk)
```

이 구현은 다른 사용자의 holding에 접근할 수 있는 보안 문제를 만든다.

---

## 5.3 필수 구현

다음처럼 반드시 request.user를 조건에 포함하라.

```python
holding = get_object_or_404(
    UserHolding.objects.select_related("stock"),
    id=pk,
    user=request.user,
)
```

---

## 5.4 AveragingDecision queryset

다음처럼 반드시 holding__user 조건을 포함하라.

```python
AveragingDecision.objects.select_related(
    "holding",
    "holding__stock",
).filter(
    holding__user=request.user,
)
```

특정 holding의 이력 조회는 다음 조건을 사용한다.

```python
AveragingDecision.objects.select_related(
    "holding",
    "holding__stock",
).filter(
    holding=holding,
).order_by("-created_at")
```

---

# 6. View 구현 요구사항

## 6.1 구현 위치

프로젝트 구조에 따라 다음 중 하나에 구현하라.

권장 위치:

```text
holdings/views.py
```

또는 기존 구조가 decisions 중심이면:

```text
decisions/views.py
```

단, URL은 반드시 다음 endpoint가 동작해야 한다.

```text
POST /api/holdings/{id}/evaluate/
GET /api/holdings/{id}/decisions/
```

---

## 6.2 APIView 구현 예시

다음 구조를 기준으로 구현하라.

```python
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from holdings.models import UserHolding
from decisions.serializers import AveragingDecisionSerializer
from decisions.services.averaging_decision_service import (
    create_decision_from_result,
    evaluate_averaging_timing,
)


class HoldingEvaluateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        holding = get_object_or_404(
            UserHolding.objects.select_related("stock"),
            id=pk,
            user=request.user,
        )

        result = evaluate_averaging_timing(holding)
        decision = create_decision_from_result(holding, result)

        serializer = AveragingDecisionSerializer(decision)
        return Response(serializer.data, status=200)
```

판단 이력 API 예시:

```python
class HoldingDecisionHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        holding = get_object_or_404(
            UserHolding.objects.select_related("stock"),
            id=pk,
            user=request.user,
        )

        decisions = (
            holding.decisions.select_related("holding", "holding__stock")
            .all()
            .order_by("-created_at")
        )

        serializer = AveragingDecisionSerializer(decisions, many=True)
        return Response(serializer.data, status=200)
```

---

# 7. create_decision_from_result 구현 요구사항

## 7.1 구현 위치

```text
decisions/services/averaging_decision_service.py
```

---

## 7.2 함수가 이미 있으면 완성하라

1단계 또는 2단계에서 skeleton만 있던 다음 함수를 완성하라.

```python
def create_decision_from_result(holding, result):
    ...
```

---

## 7.3 정확한 저장 매핑

`EvaluationResult`의 값을 `AveragingDecision`에 다음처럼 매핑한다.

```python
def create_decision_from_result(holding, result):
    return AveragingDecision.objects.create(
        holding=holding,
        score=result.score,
        grade=result.grade,
        decision=result.decision,
        reason_summary=result.reason_summary,
        reasons=result.reasons,
        score_breakdown=result.score_breakdown,
        suggested_budget=result.suggested_budget,
        stop_loss_price=result.stop_loss_price,
        disclaimer=result.disclaimer,
    )
```

만약 기존 `AveragingDecision.disclaimer` 모델 필드에 default가 있고 result에 disclaimer가 없다면 default를 사용해도 된다.  
하지만 `EvaluationResult`에 disclaimer가 있다면 그 값을 저장하라.

---

# 8. Serializer 요구사항

## 8.1 AveragingDecisionSerializer 필수 필드

`decisions/serializers.py`의 `AveragingDecisionSerializer`가 아래 필드를 반환하도록 보장하라.

```text
id
holding_id
stock_code
stock_name
score
grade
decision
reason_summary
reasons
score_breakdown
suggested_budget
stop_loss_price
disclaimer
created_at
```

---

## 8.2 stock_code, stock_name 구현

다음 방식을 사용하라.

```python
stock_code = serializers.CharField(source="holding.stock.code", read_only=True)
stock_name = serializers.CharField(source="holding.stock.name", read_only=True)
holding_id = serializers.IntegerField(source="holding.id", read_only=True)
```

---

## 8.3 응답 예시

평가 API 응답은 다음 구조를 만족해야 한다.

```json
{
  "id": 12,
  "holding_id": 3,
  "stock_code": "005930",
  "stock_name": "삼성전자",
  "score": 68,
  "grade": "B",
  "decision": "관찰 구간",
  "reason_summary": "일부 반등 신호 존재",
  "reasons": [
    "현재가가 MA5 위에 있습니다.",
    "외국인 순매수가 3일 이상입니다."
  ],
  "score_breakdown": {
    "trend": 15,
    "support": 10,
    "volume": 5,
    "flow": 10,
    "market": 5,
    "risk": -5,
    "raw_total": 40,
    "final_total": 40
  },
  "suggested_budget": "300000.00",
  "stop_loss_price": "65000.00",
  "disclaimer": "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다.",
  "created_at": "2026-04-28T12:00:00Z"
}
```

---

# 9. URL 라우팅 요구사항

## 9.1 holdings/urls.py

다음 URL이 동작해야 한다.

```python
from django.urls import path

from .views import HoldingDecisionHistoryAPIView, HoldingEvaluateAPIView

urlpatterns = [
    path("<int:pk>/evaluate/", HoldingEvaluateAPIView.as_view(), name="holding-evaluate"),
    path("<int:pk>/decisions/", HoldingDecisionHistoryAPIView.as_view(), name="holding-decisions"),
]
```

기존에 router를 사용하고 있다면 router URL과 충돌하지 않게 구성하라.

예:

```python
urlpatterns = [
    path("", include(router.urls)),
    path("<int:pk>/evaluate/", HoldingEvaluateAPIView.as_view(), name="holding-evaluate"),
    path("<int:pk>/decisions/", HoldingDecisionHistoryAPIView.as_view(), name="holding-decisions"),
]
```

---

# 10. 에러 처리 요구사항

## 10.1 holding이 없거나 다른 사용자의 holding인 경우

권장 응답:

```http
404 Not Found
```

이유:

```text
다른 사용자의 holding 존재 여부를 노출하지 않기 위해 404를 사용한다.
```

---

## 10.2 최신 가격 데이터가 없는 경우

이 경우는 API 에러가 아니다.

Scoring Engine이 다음과 같은 EvaluationResult를 반환해야 한다.

```text
score = 0
grade = D 또는 평가 불가 상태
decision = 데이터 부족으로 평가 불가
reasons에 최신 가격 데이터 부족 포함
suggested_budget = 0
```

API는 이 결과를 저장하고 200 OK로 반환한다.

---

## 10.3 Scoring Engine 내부 예외

예상 가능한 데이터 부족은 Scoring Engine에서 정상 결과로 처리해야 한다.

예상하지 못한 예외가 발생하면 다음 중 하나로 처리한다.

개발 단계:

```text
예외를 그대로 발생시켜 테스트에서 발견
```

운영 단계 확장:

```text
logger.exception 기록
500 응답
```

3단계에서는 억지로 예외를 숨기지 마라.

---

# 11. 로깅 요구사항

가능하면 평가 실행 시 로그를 남겨라.

```python
logger.info(
    "Averaging decision evaluated",
    extra={
        "user_id": request.user.id,
        "holding_id": holding.id,
        "stock_code": holding.stock.code,
        "score": result.score,
        "grade": result.grade,
    },
)
```

프로젝트 로깅 설정이 없다면 최소한 logger를 선언하고 향후 확장 가능하게 둔다.

```python
import logging

logger = logging.getLogger(__name__)
```

---

# 12. 테스트 요구사항

## 12.1 평가 API 정상 케이스

테스트 내용:

```text
1. 사용자 생성
2. 종목 생성
3. UserHolding 생성
4. 필요한 가격 데이터 생성
5. API 로그인
6. POST /api/holdings/{id}/evaluate/ 호출
7. 200 응답 확인
8. AveragingDecision이 1개 생성되었는지 확인
9. 응답에 score, grade, decision, disclaimer 포함 확인
```

---

## 12.2 다른 사용자 접근 차단

테스트 내용:

```text
1. user_a의 holding 생성
2. user_b로 로그인
3. user_a의 holding evaluate 호출
4. 404 또는 403 확인
5. AveragingDecision이 생성되지 않았는지 확인
```

권장 상태 코드는 404다.

---

## 12.3 판단 이력 조회 테스트

테스트 내용:

```text
1. holding에 decision 여러 개 생성
2. GET /api/holdings/{id}/decisions/ 호출
3. 최신순 정렬 확인
4. 응답 리스트 길이 확인
5. stock_code, stock_name 포함 확인
```

---

## 12.4 데이터 부족 케이스

테스트 내용:

```text
1. holding은 있으나 DailyPrice가 없음
2. POST /api/holdings/{id}/evaluate/ 호출
3. 200 응답
4. decision이 저장됨
5. reason에 데이터 부족 관련 메시지 포함
6. suggested_budget이 0인지 확인
```

---

## 12.5 Serializer 응답 구조 테스트

필수 필드 확인:

```text
id
holding_id
stock_code
stock_name
score
grade
decision
reason_summary
reasons
score_breakdown
suggested_budget
stop_loss_price
disclaimer
created_at
```

---

# 13. 성능 요구사항

## 13.1 select_related 적용

holding 조회:

```python
UserHolding.objects.select_related("stock")
```

decision 조회:

```python
AveragingDecision.objects.select_related("holding", "holding__stock")
```

---

## 13.2 N+1 방지

다음 상황을 피하라.

```text
decision 목록 직렬화 시 각 decision마다 holding과 stock을 다시 조회하는 문제
```

따라서 decision history 조회는 반드시 `select_related("holding", "holding__stock")`를 사용한다.

---

# 14. 기존 코드와 충돌 시 처리

이미 유사한 ViewSet, serializer, url이 있다면 다음 원칙을 따른다.

```text
1. 기존 기능을 삭제하지 말고 확장한다.
2. endpoint 경로는 설계서 기준을 우선한다.
3. 중복 serializer가 있으면 AveragingDecisionSerializer에 필요한 필드를 보강한다.
4. create_decision_from_result가 skeleton이면 완성한다.
5. evaluate_averaging_timing이 이미 구현되어 있으면 재구현하지 말고 호출한다.
```

---

# 15. 완료 후 실행해야 할 명령

모델 변경이 없다면 migration은 필요 없을 수 있다.  
하지만 serializer나 service 변경과 관계없이 테스트는 반드시 실행 가능해야 한다.

```bash
python manage.py test
```

프로젝트가 pytest를 사용한다면:

```bash
pytest
```

---

# 16. 완료 보고 형식

작업 완료 후 다음 형식으로 보고하라.

```text
3단계 API Workflow 구현 완료

구현/수정한 파일:
- ...

구현한 API:
- POST /api/holdings/{id}/evaluate/
- GET /api/holdings/{id}/decisions/

핵심 구현:
- evaluate_averaging_timing 호출
- create_decision_from_result 저장
- AveragingDecisionSerializer 응답
- holding owner 권한 제한
- decision history 최신순 조회

테스트:
- ...

아직 구현하지 않은 것:
- 프론트엔드 UI
- 외부 데이터 연동
- 배포 설정

다음 단계:
04_quality_release_design.md 기준으로 테스트, 문서화, 샘플 데이터, 품질 보강을 진행한다.
```

---

# 17. 지금 바로 수행할 작업

지금 바로 다음 순서로 구현하라.

```text
1. 현재 holdings/views.py, decisions/views.py, urls.py 구조 확인
2. AveragingDecisionSerializer 필드 확인 및 보강
3. create_decision_from_result 구현 또는 보강
4. HoldingEvaluateAPIView 구현
5. HoldingDecisionHistoryAPIView 구현
6. holdings/urls.py 라우팅 추가
7. 권한과 queryset 제한 확인
8. select_related 적용
9. 테스트 작성
10. 테스트 실행
11. 완료 보고 작성
```

반드시 `docs/03_api_workflow_design.md`의 상세 설계를 따른다.
