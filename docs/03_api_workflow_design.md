
# 03_api_workflow_design.md (Detailed Version)

# 물타기 타이밍 판단 시스템 3단계 설계서: API Workflow (상세 설계)

---

# 0. 문서 목적

이 문서는 2단계에서 구현된 Scoring Engine을 실제 서비스 API로 연결하는 **정확하고 완전한 실행 설계서**다.

이 문서는 다음을 목표로 한다:

- “어떻게 API가 동작해야 하는지”를 코드 수준까지 명확히 정의
- Codex가 **추측 없이 그대로 구현 가능한 수준**으로 상세화
- 모호함 제거
- 모든 edge case 명시

---

# 1. 전체 시스템 흐름 (정확 정의)

## 1.1 단일 요청 흐름

```text
[Client]
   ↓
POST /api/holdings/{id}/evaluate/
   ↓
[Authentication Check]
   ↓
[UserHolding 조회 (user 필터 포함)]
   ↓
[Scoring Engine 실행]
   ↓
[EvaluationResult 생성]
   ↓
[AveragingDecision DB 저장]
   ↓
[Serializer 변환]
   ↓
[JSON Response 반환]
```

---

# 2. 핵심 API: evaluate

## 2.1 Endpoint

```http
POST /api/holdings/{id}/evaluate/
```

---

## 2.2 Request

```text
Body 없음
Query 없음
Header: Authorization 필요
```

---

## 2.3 Response (정확 구조)

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
  "disclaimer": "본 결과는 투자 참고용 데이터 분석이며...",
  "created_at": "2026-04-28T12:00:00Z"
}
```

---

# 3. View 구현 (정확 코드 수준)

## 3.1 위치

```text
holdings/views.py
또는
decisions/views.py
```

---

## 3.2 View 코드 구조 (정확)

```python
class HoldingEvaluateAPIView(APIView):

    def post(self, request, pk):
        # 1. holding 조회 (권한 포함)
        holding = get_object_or_404(
            UserHolding,
            id=pk,
            user=request.user
        )

        # 2. 평가 실행
        result = evaluate_averaging_timing(holding)

        # 3. DB 저장
        decision = create_decision_from_result(holding, result)

        # 4. serializer 변환
        serializer = AveragingDecisionSerializer(decision)

        return Response(serializer.data, status=200)
```

---

# 4. AveragingDecision 저장 로직

## 4.1 위치

```text
decisions/services/averaging_decision_service.py
```

---

## 4.2 정확 구현

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
    )
```

---

# 5. 이력 조회 API

## 5.1 Endpoint

```http
GET /api/holdings/{id}/decisions/
```

---

## 5.2 Queryset (정확)

```python
AveragingDecision.objects.filter(
    holding__id=pk,
    holding__user=request.user
).order_by("-created_at")
```

---

## 5.3 Response 구조

```json
[
  {
    "id": 10,
    "score": 55,
    "grade": "B",
    "created_at": "..."
  },
  {
    "id": 9,
    "score": 40,
    "grade": "C",
    "created_at": "..."
  }
]
```

---

# 6. 권한 처리 (매우 중요)

## 6.1 절대 규칙

```text
UserHolding → 반드시 owner만 접근
AveragingDecision → 반드시 owner 기준 조회
```

---

## 6.2 잘못된 구현 (금지)

```python
UserHolding.objects.get(id=pk)
```

---

## 6.3 올바른 구현

```python
UserHolding.objects.get(id=pk, user=request.user)
```

---

# 7. Serializer 설계 (명확화)

## 7.1 AveragingDecisionSerializer

반드시 포함:

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

## 7.2 stock 정보 제공 방법

```python
stock_code = serializers.CharField(source="holding.stock.code", read_only=True)
stock_name = serializers.CharField(source="holding.stock.name", read_only=True)
```

---

# 8. 에러 처리 (정확 정의)

## 8.1 holding 없음

```http
404 Not Found
```

---

## 8.2 권한 없음

```http
404 또는 403
```

권장:

```text
404 (정보 노출 방지)
```

---

## 8.3 데이터 부족

```text
에러 아님
정상 응답 + reasons에 포함
```

---

# 9. 성능 최적화

## 9.1 필수 적용

```python
UserHolding.objects.select_related("stock")
AveragingDecision.objects.select_related("holding__stock")
```

---

## 9.2 금지

```text
반복 쿼리 발생 (N+1)
```

---

# 10. 테스트 (상세)

## 10.1 evaluate API

```text
정상 요청 → 200
결과 저장됨
response 구조 검증
```

## 10.2 권한 테스트

```text
다른 user → 접근 불가
```

## 10.3 데이터 부족

```text
가격 없음 → 정상 응답 + reason 포함
```

---

# 11. 로깅 (권장)

```python
logger.info({
    "user": request.user.id,
    "holding": holding.id,
    "score": result.score,
    "grade": result.grade
})
```

---

# 12. 절대 금지

```text
View에 계산 로직 작성
Serializer에서 계산 수행
evaluate에서 임시 점수 생성
```

---

# 13. 다음 단계

```text
04_quality_release_design.md
```

---

# 14. 핵심 요약

3단계는 “엔진 → 서비스 연결”이다.

```text
Scoring Engine → API → DB → Response
```

이 흐름이 깨지면 전체 시스템이 무너진다.
