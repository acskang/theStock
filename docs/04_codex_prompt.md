
# 04_codex_prompt.md

# Codex 실행 프롬프트: 4단계 Quality & Release

## 사용 방법

이 파일을 Codex에 그대로 전달한다.

반드시 아래 문서를 함께 제공한다.

```text
docs/00_overview_and_data.md
docs/01_foundation_design.md
docs/02_scoring_engine_design.md
docs/03_api_workflow_design.md
docs/04_quality_release_design.md
```

---

# 실행 프롬프트 본문

너는 Django REST Framework 기반 서비스를 **운영 가능한 수준으로 완성하는 엔지니어**다.

이번 작업은 물타기 타이밍 판단 시스템의 **4단계 Quality & Release 작업**이다.

이 단계는 기능 개발이 아니라 **품질, 안정성, 테스트, 배포 준비**를 완성하는 단계다.

---

# 1. 목표

```text
1. 테스트 완전성 확보
2. 모든 API 안정성 확보
3. 데이터 부족/엣지케이스 처리 완성
4. 성능 최적화 (N+1 제거)
5. 로깅 시스템 추가
6. 환경 설정 분리
7. README 작성
8. 샘플 데이터 구성
```

---

# 2. 절대 하지 말 것

```text
1. 새로운 비즈니스 로직 추가
2. Scoring Engine 변경
3. API 구조 변경
```

---

# 3. 테스트 구현

다음 테스트를 반드시 구현하라:

## 3.1 Unit Test

```text
MA / RSI / MACD / ATR 정상 동작
데이터 부족 시 None 처리
```

## 3.2 Service Test

```text
evaluate_averaging_timing 정상 동작
critical risk 즉시 종료
```

## 3.3 API Test

```text
POST evaluate → 200
GET decisions → 정상
권한 차단
```

---

# 4. 성능 개선

반드시 적용:

```python
select_related("stock")
select_related("holding__stock")
```

---

# 5. 로깅 추가

```python
import logging
logger = logging.getLogger(__name__)

logger.info({
    "event": "evaluate",
    "user": request.user.id,
    "score": result.score,
    "grade": result.grade
})
```

---

# 6. 에러 처리

```text
holding 없음 → 404
데이터 부족 → 정상 응답
예상치 못한 오류 → 500 + 로그
```

---

# 7. 환경 설정

## settings.py 분리

```text
settings/base.py
settings/dev.py
settings/prod.py
```

---

# 8. README 작성

다음 포함:

```text
설치 방법
API 설명
테스트 실행 방법
```

---

# 9. 샘플 데이터

```text
Stock 생성
UserHolding 생성
가격 데이터 삽입
```

---

# 10. 실행 확인

```bash
python manage.py migrate
python manage.py test
python manage.py runserver
```

---

# 11. 완료 기준

```text
모든 테스트 통과
API 정상 응답
로그 기록됨
```

---

# 12. 완료 보고

```text
4단계 완료

테스트: OK
API: OK
배포 준비: OK
```

---

# 13. 지금 수행

```text
1. 테스트 작성
2. 성능 개선
3. 로깅 추가
4. README 작성
5. 실행 검증
```
