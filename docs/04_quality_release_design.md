
# 04_quality_release_design.md

# 물타기 타이밍 판단 시스템 4단계 설계서: Quality & Release

---

# 0. 문서 목적

이 문서는 시스템의 **품질 완성 + 배포 준비 단계**를 정의한다.

3단계까지:
- 기능은 완성됨 (API 동작)
- 로직은 존재함 (Scoring Engine)

4단계에서는 다음을 완성한다:

```text
1. 테스트 완전성 확보
2. 데이터 신뢰성 검증
3. 에러/엣지케이스 안정화
4. 성능 최적화
5. 로깅 및 모니터링
6. 운영 환경 배포 준비
7. 문서화
```

이 단계는 “기능 개발”이 아니라 **서비스 품질 완성 단계**다.

---

# 1. 목표 정의

## 1.1 최종 목표

```text
"사용자가 실제로 사용 가능한 안정적인 서비스 상태"
```

---

## 1.2 완료 기준

```text
1. 모든 핵심 로직 테스트 존재
2. API 실패 없이 동작
3. 데이터 부족 상황에서도 정상 응답
4. 성능 문제 없음 (N+1 제거)
5. 로그로 문제 추적 가능
6. 기본 배포 환경 실행 가능
7. README 및 사용 방법 문서 존재
```

---

# 2. 테스트 전략 (핵심)

## 2.1 테스트 계층

```text
1. Unit Test (지표/점수 함수)
2. Service Test (evaluate 엔진)
3. API Test (endpoint)
4. Integration Test (전체 흐름)
```

---

## 2.2 반드시 구현할 테스트

### 2.2.1 Indicator 테스트

```text
MA 계산 정확성
RSI 경계값 (0, 50, 100)
MACD 구조 반환
ATR 계산 정상
Bollinger Band 정상
```

---

### 2.2.2 Scoring 테스트

```text
추세 점수 정상
지지선 점수 정상
거래량 점수 정상
수급 점수 정상
시장 점수 정상
리스크 감점 정상
critical risk → D 등급
```

---

### 2.2.3 Evaluation 테스트

```text
정상 데이터 → 결과 생성
데이터 부족 → 정상 응답
critical risk → 즉시 종료
score_breakdown 포함
```

---

### 2.2.4 API 테스트

```text
POST evaluate → 200
GET decisions → 정상 리스트
권한 차단 확인
response schema 검증
```

---

## 2.3 테스트 실패 기준

다음은 반드시 실패로 처리:

```text
None 처리 누락
division by zero
빈 리스트 처리 실패
Decimal 오류
```

---

# 3. 데이터 품질 검증

## 3.1 데이터 검증 규칙

```text
가격 음수 금지
volume 음수 금지
날짜 중복 금지
```

---

## 3.2 계산 전 validation

```python
if not price_rows:
    raise ValueError("Price data required")
```

---

# 4. 에러 처리 전략

## 4.1 원칙

```text
예상 가능한 에러 → 정상 응답
예상 불가능 에러 → 로그 + 500
```

---

## 4.2 예시

| 상황 | 처리 |
|---|---|
| 가격 없음 | 정상 응답 |
| holding 없음 | 404 |
| DB 오류 | 500 |

---

# 5. 성능 최적화

## 5.1 필수

```text
select_related 적용
prefetch_related 적용
쿼리 수 최소화
```

---

## 5.2 금지

```text
루프 안에서 DB 조회
serializer 내부 DB 조회
```

---

# 6. 로깅 설계

## 6.1 필수 로그

```text
evaluate 실행
score 결과
critical risk 발생
에러 발생
```

---

## 6.2 로그 구조

```python
logger.info({
    "event": "evaluate",
    "user": user.id,
    "score": score,
    "grade": grade
})
```

---

# 7. 보안

## 7.1 필수

```text
user 기반 필터링
다른 user 데이터 접근 차단
```

---

## 7.2 금지

```text
id만으로 조회
```

---

# 8. 환경 설정

## 8.1 개발 환경

```text
SQLite
DEBUG=True
```

---

## 8.2 운영 환경

```text
PostgreSQL
DEBUG=False
SECRET_KEY 환경변수
```

---

# 9. 배포 준비

## 9.1 필수 작업

```text
.env 설정
requirements.txt 정리
DB migration
```

---

## 9.2 실행 명령

```bash
python manage.py migrate
python manage.py runserver
```

---

# 10. README 작성

## 10.1 포함 내용

```text
프로젝트 개요
설치 방법
API 사용법
테스트 실행 방법
```

---

# 11. 샘플 데이터

## 11.1 필요 데이터

```text
Stock
UserHolding
DailyPrice
InvestorFlow
MarketIndex
```

---

# 12. 최종 점검 체크리스트

```text
[ ] API 정상 동작
[ ] 테스트 통과
[ ] 권한 문제 없음
[ ] 로그 기록됨
[ ] 데이터 부족 처리됨
[ ] README 존재
```

---

# 13. 다음 단계 없음

이 단계가 완료되면 MVP 완성이다.

---

# 14. 핵심 요약

```text
4단계 = 품질 + 안정성 + 배포 준비
```

이 단계가 없으면 서비스는 “동작은 하지만 위험한 상태”다.
