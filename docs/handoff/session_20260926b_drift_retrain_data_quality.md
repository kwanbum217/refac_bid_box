# 세션 인수인계: 2026-09-26(후반) 드리프트 기준 분포, 재학습 OOM, 데이터 품질 웨이브

> **작성일**: 2026-09-26
> **작성자**: Claude Opus 5.5 (Orca 코디네이터)
> **기준 커밋**: `main` `f963440c` (이 문서 병합 전)
> **Orca Run**: `run_1bfc04b2de02` (Task 22건 completed, 워커 터미널 전부 회수)
> **이어받은 문서**: [`session_20260926_runbook_audit_and_state_meta.md`](session_20260926_runbook_audit_and_state_meta.md)

---

## 1. 한 줄 요약

드리프트 감시와 용역 재학습을 앞당겨 수동 실행하면서 결함 두 개가 드러났고 둘 다 고쳤습니다. 재학습이 드리프트 기준 분포를 전체 학습 프레임으로 덮어쓰던 결함(B1)과, worker 컨테이너 안 재학습의 OOM(M1, 최대 RSS 9.93GiB 에서 3.92GiB)입니다. 이어서 드리프트 오탐을 조사하다 데이터 품질 문제 두 가지를 찾았습니다. 대형 공고 낙찰결과가 조달청 API 쪽에서 미등록·지연되는 상류 공백(C1)과, 운영 DB 에 남은 시험 행 20건(G1)입니다. 시험 행은 백업 후 삭제하고 재집계했습니다.

---

## 2. 병합 결과

| 섹션 | 병합 | 내용 | 검증 |
| --- | --- | --- | --- |
| B1 `task_87719a54047f` 기준 분포 덮어쓰기 제거 | `bd3c3b85` | `src/ml/trainer.py` 학습 경로가 `ml_registry/{model}/baseline/` 을 교체하던 호출 제거. 버전 디렉터리 baseline 은 유지 | 빌더 cmd GLM-5.3 Flash, 리뷰 pass, strict, 전량 5,431. 이후 실제 재학습에서 registry baseline 불변 확인 |
| B2 기준 분포 재생성 | (운영 조작) | 용역·공사 기준 분포를 `--start-at 2026-05-26` 으로 재생성 | 용역 22,305 건, 공사 33,627 건. 이후 G1 정리로 용역은 `b_20260926b_servc_post_regime` 22,295 건 |
| R0 개발 재학습 일시 중지 | `c4d5047e` | worker 안 재학습이 두 번 OOMKilled(최대 12.26GiB 이상)라 `ML_WEEKLY_RETRAIN_ENABLED=false` | M1 뒤 되돌림 |
| M1 `task_8401ae1a8696` 재학습 메모리 축소 | `dde5215c` | 특징 구축·범주 수집 50,000 행 청크, 후보·폴드·보정 모델 즉시 반납 | 호스트 최대 RSS 9.93GiB 에서 3.92GiB(-60.5%). 변경 전후 metadata 136개 값 동일(코디네이터 직접 대조, 리뷰어 전수 대조). 리뷰 pass, 전량 5,438 |
| 컨테이너 재검증 | (운영 조작) | worker 안 `run_retrain_pipeline_task(Servc)` | 17분, 최대 5.10GiB, OOM 없음. `v_20260926_085519_461` REJECT_CHALLENGER(서빙 불변), `retrain_logs` id 16 |
| R0 되돌림 | `67b9a1fe` | 개발 재학습 재개 | worker 안 `ML_WEEKLY_RETRAIN_ENABLED=true` 확인 |
| source_commit 갱신 | `ecf855d8` | 아래 4장 CI 실패 수정 | CI 전 잡 성공 |
| D1 `task_349b225ba017` PSI 민감도 분석 | `c4a982f1` | `docs/analysis/drift_psi_sensitivity_20260926.md` | 리뷰 pass. 단 `is_over_notice_amt` 급증 서술은 F1 이 정정(아래) |
| F1 `task_f36447fcf6fc` 드리프트 데이터 확인 | `6f8d71a1` | `docs/analysis/drift_data_check_20260926.md`. 레짐 플래그 혼입 6.92%는 기준 분포 컷(개찰일)과 특징 기준일(공고일) 불일치. `is_over_notice_amt` 는 급증이 아니라 급감이며 D1 은 2빈 PSI 역산에서 틀린 해를 골랐다 | 리뷰 pass. 작성자 note 746자 초과를 코디네이터가 600자로 축약(원본 `worker_done.orig.json`) |
| G1 `task_685f8ba3bb57` 시험 행 출처 | `16b2aaa6` | `docs/analysis/dbg_rows_origin_20260926.md`. 2026-09-19 하니스 작업이 운영 스키마에 `DBG-*` 20건(bid_results 10, bid_announcements 10) 삽입 | 리뷰 pass(삭제 조건 SELECT 재실행 20건 일치). 작성자가 보고 JSON 을 별칭 Capsule 경로에 써서 코디네이터가 정식 경로로 복사 |
| G1 정리 | `10e12484` | 백업 후 삭제, 집계 3곳 재집계, 용역 기준 분포 재생성. 조율 스킬 2.5 절에 운영 스키마 시험 행 금지 추가, D1 보고서에 정정 주석 | 백업 `data/backups/dbg_rows_20260926.sql`, `dbg_aggregates_before_20260926.sql`(gitignore). 트랜잭션 rowcount 10·10 확인 뒤 커밋. CI 성공 |
| C1 `task_1a76e281f829` 수집 공백 원인 | `f963440c` | `docs/analysis/result_collection_gap_20260926.md`. 수집기 결함이 아니라 조달청 낙찰정보 API 에 대형 공고 개찰결과가 미등록·지연. `inqryDiv=1` 은 등록일 기준 | 리뷰 pass(미등록 표본 3건 API 재조회로 부재 확인) |

---

## 3. 드러난 사실과 판단

| 사실 | 판단·조치 |
| --- | --- |
| 드리프트는 기준 분포를 바로잡은 뒤에도 세 분류 모두 DRIFT_DETECTED(용역 31/70, 공사 15/68, 물품 22/68) | D1: 용역은 7일 표본 332건이라 고카디널리티 범주형 노이즈만으로 판정이 참이 된다. 월·요일 달력 특징과 레짐 플래그 혼입은 구조적 오탐. 개선안 A(윈도우 28일), D(달력 특징 제외), N1(기준 분포 구간을 공고일로)은 수집 정상화 뒤로 미뤘다 |
| 대형 공고(2.3억 이상) 결과 매칭률이 8월 26.6%에서 9/21 주 3.9%(2025 같은 시기 44~50%) | C1: 상류 API 공백. 8/17~8/31 주 용역 확정 결손 약 164건, 9/7~9/21 주 결손 상한 약 1,350건(자연 지연 포함). 모델 평가, 재학습, 드리프트 모두에 편향 요인 |
| 수집 스케줄 실행 공백: 8/15~9/5(약 22일), 9/11~9/13, 9/21, 9/23~9/25 | 8/27 비스케줄 적재로 대부분 회수됨. 공백이 7일을 넘으면 창이 클램프되어 그 이전 등록분은 영영 조회되지 않으며 경고 로그만 남는다(`collector_service.py:174-188`) |
| C1 R5: 2026-09-26 W1(Frgcpt 체크포인트 제외)로 실행 공백 시 자동 회수 폭이 줄었다 | 구조적 결함은 아니나 감시(R4)로 보완 필요 |
| M1 병합부터 CI lint-and-validate 실패 | 이 세션 병합 동안 `source_commit` 을 갱신하지 않아 main 이 14커밋 앞섰다. 작업 브랜치에서는 경고로 강등되어 병합 전 검증에서 드러나지 않았다. `ecf855d8` 로 해소 |
| 조사 워커의 DB 질의가 30~80초씩 걸렸다 | `bid_announcements` 637만 행에 `openg_dt` 인덱스가 없고 조인 키에 함수를 씌웠다. 이후 Capsule 에 "공고일 인덱스로 먼저 좁히기, `MAX_EXECUTION_TIME(60000)`" 을 명시했다 |
| 워커 두 명이 보고 JSON 을 별칭 Capsule 경로(`task_<slug>/`)에 썼다 | Intent 에 `report_path` 가 없으면 preamble 이 별칭 경로를 안내한다. 코디네이터가 정식 경로로 복사했다 |

---

## 4. 다음 세션

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | 이 문서 병합의 CI 확인 | |
| 2 | Docker 재기동 뒤 드리프트 판정 기록 확인(컴퓨터가 꺼져 있던 동안의 04:00 실행은 건너뛰어짐) | `retrain_logs` 에 `drift_monitor` 3행. 결과는 여전히 DRIFT_DETECTED 일 것이며 원인은 D1·F1 |
| 3 | 용역 주간 재학습 결과 확인 | 월요일 03:00 에 worker 가 떠 있어야 실행된다. 컨테이너 재검증 통과. 승격은 수동 |
| 4 | C1 복구 후보 결정 | R2(나라장터 화면과 표본 대조, 필요 시 조달청 문의), R3(분류×금액대 결과 매칭률 주간 지표), R4(클램프·실행 공백 3일 이상 알림). R1(등록일 창 백필)은 API 에 없는 결과를 회수하지 못해 실효가 제한적 |
| 5 | 드리프트 판정 개선 | 수집 정상화 판단 뒤 A, D, N1 설계. C 는 보정 상수 근거가 필요 |
| 6 | (선택) Docker VM fsync, G1 20.8초 재발, G2 Windows 실기 | 변동 없음 |

---

## 5. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | `main` 은 이 문서 병합 후 clean, 원격 반영. 워커 워크트리 0건, 작업 브랜치 0건 |
| Orca | Run `run_1bfc04b2de02` Task 22건 completed. 워커 터미널 전부 닫음, 배달 큐 비움, 잔류 세션 감사 통과, 상시 감시기 종료 |
| Docker | 세션 종료 때 사용자가 컴퓨터를 끄려고 요청해 Redis 는 `SHUTDOWN NOSAVE`, 나머지는 `docker compose stop` 으로 전부 내렸고 Docker Desktop 도 종료했다(볼륨 보존). VM 메모리 설정은 18GB(보고 17.5GiB)로 유지된다. **다음 세션은 Docker Desktop 기동 후 `docker compose up -d` 로 worker 까지 전부 올린다.** worker 는 `ML_WEEKLY_RETRAIN_ENABLED=true`, `ANONYMIZED_TELEMETRY=False` 이며 2026-09-26 결정대로 평소에는 내리지 않는다. 꺼져 있는 동안 수집·04:00 드리프트·월요일 재학습이 돌지 않으며, 재기동하면 따라잡기 수집이 1회 돈다 |
| ml_registry | 기준 분포: 용역 `b_20260926b_servc_post_regime`, 공사 `b_20260926_cnstwk_post_regime`, 물품 `b_20260915_thng_post_regime`. 도전 모델 `v_20260926_085519_461`(기각) 추가 |
| 백업 | `data/backups/dbg_rows_20260926.sql`, `data/backups/dbg_aggregates_before_20260926.sql`(gitignore, 복원용 INSERT) |
