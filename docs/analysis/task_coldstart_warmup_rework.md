# 과업 재작업 보고서: 예측 API 콜드스타트 지연 후보 분석 및 미입증 단정 제거

> **작성일**: 2026-08-22
> **Task ID**: `task_coldstart_warmup_rework`
> **역할**: Investigator
> **상태**: 완료 (Succeeded)
> **대상 커밋**: `1308223`
> **산출물**: `docs/analysis/predict_coldstart_analysis.md`

---

## 1. 재작업 배경 및 목적

1차 조사 산출물(`predict_coldstart_analysis.md`)은 워밍업 위치와 위험 요소를 유효하게 짚었으나, 단계별 계측이 부재한 상태에서 DB 풀·AnyIO 스레드·ML C-Extension 초기화를 383.1ms의 '확인된 원인'으로 단정하고 MySQL TLS나 OS 스레드 10개 생성 등 미확인 세부 사항을 사실처럼 기술한 결함이 있었습니다.

본 재작업은 다음 목적을 달성하기 위해 수행되었습니다.
1. **원인과 후보의 엄격한 분리**: 실측은 종단 간(End-to-End) 회차별 P50/P95/P99뿐이며 구간별 계측이 없음을 명시하고, 코드상 식별된 초기화 지점을 '코드상 비용 후보'로 표현하며 383.1ms 기여도를 '미확정'으로 낮춤.
2. **미입증 단정 제거**: MySQL TLS 사용, OS 스레드 10개 생성, OpenMP 초기화 등 설정 및 계측으로 확인되지 않은 세부 단정을 제거하고 추정으로 명시.
3. **가설 검증 절차 선행**: 섣부른 워밍업 코드 적용에 앞서 구간별 소요 시간 정밀 계측 우선순위를 먼저 제시.
4. **워밍업 위험 및 결정 유보 유지**: 기동 시간 증가, 헬스체크 타임아웃(CrashLoopBackOff), 자원 스파이크 위험을 명시하고 채택 결정을 운영 정책으로 유보.
5. **메타데이터 정정 및 산출물 정리**: 대상 커밋을 `1308223`으로 바로잡고, 1차 요약 파일(`docs/analysis/task_coldstart_warmup_investigation.md`)을 제거하고 본 재작업 요약(`docs/analysis/task_coldstart_warmup_rework.md`)으로 일원화.

---

## 2. 주요 수정 및 정정 내역

### 2.1 383.1ms 원인 단정 완화 및 기여도 미확정 표기
- DB 커넥션 풀 지연 생성, AnyIO 스레드 풀 지연 기동, ML C-Extension 첫 추론 진입, FastAPI Lifespan 백그라운드 태스크 미대기를 모두 '코드상 후보'로 분류.
- 종합 분류 표의 판정을 '확인됨/매우 높음'에서 `코드상 확인 사실`, `런타임 동작 (추정)`, `383ms 실측 기여도: 미확정 (구간 계측 없음)`으로 객관화.

### 2.2 미확인 런타임 세부 단정 제거
- DB 핸드셰이크 설명에서 'TCP+TLS+인증 10건 동시 병목' 단정 대신 'TCP 핸드셰이크 및 인증 동시 발생 가능성'으로 조정.
- AnyIO 스레드 설명에서 'OS 스레드 10개 지연 생성 및 컨텍스트 스위칭' 단정 대신 '요청 시점에 워커 스레드 지연 기동 가능성'으로 기술.
- ML 라이브러리 설명에서 'OpenMP 스레드 상태 구조체 초기화' 등의 단정을 배제하고 C 라이브러리 내부 메모리/버퍼 첫 진입 오버헤드 가능성으로 정정.

### 2.3 가설 검증 우선순위 선행 제시
- 4.1절에 4단계 세부 계측 우선순위 명시:
  1. Lifespan 기동 타이밍 계측 (모델 로드 완료 시점 vs Uvicorn 트래픽 수신 시작 시점)
  2. DB 커넥션 풀 연결 시간 계측 (첫 요청 세션 획득 및 첫 쿼리 소요 시간)
  3. AnyIO 스레드 풀 기동 및 디스패치 지연 계측
  4. ML 모델 첫 추론 전후 소요 시간 계측 (전처리 vs 순수 추론 연산)

### 2.4 대상 커밋 및 문서 메타데이터 정정
- 대상 커밋을 기준 `main`인 `1308223`으로 수정.
- 과업명을 `task_coldstart_warmup_rework`로 반영.

---

## 3. 검증 결과

1. **규칙 검증 통과**:
   - `python3 scripts/validate_agent_rules.py --quiet` 전량 통과 (12/12 건 PASS).
2. **코드 무변경 준수**:
   - 소스 코드(`src/`) 수정 0건 (재측정 배제, Docker 미기동, 순수 문서 정비).
3. **최종 변경 파일**:
   - `docs/analysis/predict_coldstart_analysis.md` (상세 분석 보고서 정정)
   - `docs/analysis/task_coldstart_warmup_rework.md` (재작업 요약 보고서)
   - 1차 요약(`docs/analysis/task_coldstart_warmup_investigation.md`) 삭제 완료.
