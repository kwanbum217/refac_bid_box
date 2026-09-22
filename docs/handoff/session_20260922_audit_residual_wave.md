# 세션 인수인계: 2026-09-22 외부 감사 잔여 처리, G1 기준선 복구, RTO 실측

> **작성일**: 2026-09-22
> **작성자**: Claude Opus 5 (Orca 코디네이터)
> **기준 커밋**: `main` `ee20058b`
> **Orca Run**: `run_c1b3bb4a8856` (Task 11건 전부 `completed`, 배달 큐 비움)
> **이어받은 문서**: [`session_20260921c_offload_followup_and_tooling.md`](session_20260921c_offload_followup_and_tooling.md)

---

## 1. 한 줄 요약

외부 감사 잔여 RAG-3, BE-1, INF-3 과 경고 예산 출처를 처리했고, 후속으로 테스트 임베딩 격리, 야간 대조 질의 최적화, G1 기준선 드리프트 게이트를 병합했습니다. INF-3 restore drill 이 **운영 DB 의 G1 스키마 서명 검증이 2026-09-14 부터 8일간 실패 중이던 사실**을 드러냈고, 기준선을 갱신하고 재발 방지 게이트를 넣었습니다. **D2 따라잡기 판정 측정은 쿨다운 키 때문에 다음 세션으로 넘깁니다.**

---

## 2. 이번 세션 병합 (first-parent)

| 병합 커밋 | 내용 | 검증 |
| --- | --- | --- |
| `5c64de8a` | W1 평가 UI 테스트의 클래스 스코프 fixture 3개를 `@classmethod` 로 바꿔 경고 출처 제거 | 코디네이터 직접, 전량 5,297 경고 0, CI 성공 |
| `d2961388` | B1 staging CORS: `*` 대체를 development 전용으로, staging 은 `CORS_ALLOWED_ORIGINS` 필수(fail-closed) | 리뷰 pass, Level 1 11/11, 전량 5,308, CI 성공 |
| `9e80c4ef` | R1 Meilisearch 공고·낙찰 건수와 DB 를 야간 스케줄에서 읽기 전용 대조 | 리뷰 pass, Level 1 11/11, 전량 5,311 |
| `88d2c5af` | source_commit 갱신 | 통합 main 전량 5,322 경고 0, CI 성공 |
| `a767d90f` | X1 테스트 전용 결정적 가짜 임베딩으로 chromadb ONNX MiniLM 다운로드 제거 | 리뷰 pass, Level 1 11/11, 전량 5,326, CI 성공 |
| `d1958dd7` | source_commit 갱신 | 규칙 21/21 |
| `44dd7546` | X2 대조 질의를 윈도 함수에서 파티션 GROUP BY 로 교체 | 리뷰 pass, Level 1 11/11, 전량 5,323, CI 성공 |
| `00222bd0` | G1 스키마 서명 기준선 갱신(테이블 2개 추가) | G1 6/6, 전량 5,327, CI 성공 |
| `8164fd5c` | INF-3 drill 보고서, RTO 단계표 실측, 복구 도구 실행 명령 정정 | 전량 5,327, CI 성공 |
| `ee20058b` | G2 G1 기준선 드리프트 정적 게이트 | 리뷰 pass, Level 1 11/11, 전량 5,336. CI 는 세션 종료 시점 확인 중 |

워커 모델: 빌더 Command Code `deepseek/deepseek-v4.1-flash`(effort high), 리뷰어 OpenCode `opencode/muse-spark-1.3-contributor-free`. 전부 `orca_taskctl.py dispatch --terminal` 터미널 부착 경로이며 **비감독 경로**입니다. W1, 기준선 갱신, INF-3 문서는 코디네이터가 직접 작성했습니다.

---

## 3. 주요 측정과 판정

| 항목 | 값 | 근거 |
| --- | --- | --- |
| X2 야간 공고 건수 질의 | 3회 중앙값 263.98초에서 7.08초 (코디네이터 재측정 7.77초) | 결과 4,879,588 동일, 파티션 키 NULL 행 0 |
| CI 경고 예산 잡 | 1건에서 **0건** (예산 5) | `8164fd5c` CI |
| restore drill (snapshot_20260921_061612) | 총 1,423.9초, G1 PASS | `data/backups/restore_drill_report_20260922.json` |
| 서비스 정상화 | 3회 21.7·15.1·15.1초, 중앙값 15.1초 | app·meilisearch `--force-recreate` 부터 `/accounts/login/` 200 까지 |
| RTO 합계(재색인 제외) | 약 1,439초 | `docs/ops/rpo_rto_policy.md` 3장 |

DB import 가 09-11 의 823.9초에서 1,391.6초로 1.7배가 된 원인은 **확정하지 못했습니다.** 행 수(약 0.2%)와 덤프 크기(약 1%)는 거의 같고, 그 사이 추가된 커버링 인덱스 2개(약 1.16GB)와 테이블 2개(약 268MB)만으로 설명된다는 근거는 없습니다.

---

## 4. G1 기준선 사고

| 사실 | 내용 |
| --- | --- |
| 원인 | 2026-09-14 `6c9bf5fa` 가 마이그레이션 `9d4e2b7a1c63` 으로 테이블 2개를 추가했으나 기준선은 09-13 `32c5ff34` 그대로였다 |
| 영향 | 운영 DB 의 `verify_migration.py` 스키마 서명 항목이 8일간 FAIL. CI 는 실제 DB 로 이 검사를 돌리지 않아 드러나지 않았다 |
| 발견 | 첫 drill 이 `g1_db_verification` FAIL(총 1,616.6초). 실패 보고서는 커밋하지 않았다 |
| 조치 | 기준선 재생성(35개에서 37개, 기존 정의 변경 0건) 후 drill 재실행 PASS |
| 재발 방지 | `tests/test_g1_baseline_drift_gate.py` 가 DB 없이 ORM 테이블·컬럼과 마이그레이션 upgrade() 의 테이블·인덱스(원문 SQL 포함)가 기준선에 있는지 검사. 옛 기준선을 넣으면 8건으로 실패함을 코디네이터가 재현했다 |

---

## 5. 다음 세션 할 일

| 순서 | 할 일 | 근거와 주의 |
| --- | --- | --- |
| 1 | `ee20058b` CI 확인 | 세션 종료 시점에 실행 중이었다 |
| 2 | **D2 따라잡기 판정 측정** | 이전 인수인계 6장 1번 절차 그대로. 쿨다운 키 `bidbox:schedule:catchup_cooldown` 은 2026-09-22 03:58Z 기록, TTL 6시간이라 이미 만료됐다. Docker 는 `db`·`redis` 만, 정규화 부하 30% 이하 |
| 3 | **경고 예산 상한 결정** | 로컬·CI 모두 실측 0건. 상한 5 를 낮출지 사용자 결정 |
| 4 | Meilisearch 전체 재색인 시간 실측 | 스냅샷에 Meili 데이터가 없어 실제 복구에 필요하나 미측정. RTO 단계 예산 배분은 이것을 잰 뒤 |
| 5 | DB import 1.7배 원인 | 다음 drill 에서 import 내부(테이블별·인덱스 빌드) 시간을 나눠 잰다 |
| 6 | X2 리뷰 권장 | NULL 키 행을 넣은 동치 테스트 추가. 운영 NULL 0 이라 비차단 |
| 7 | OP-3 주간 재학습 | worker 는 A안대로 정지 상태. 이번 세션 초반 실수로 기동했다가 정지했다(수집 1회 실행, 쿨다운 기록) |

사용자 결정 대기: `data/promotion_audit.log` 정리(이번 세션도 보류로 결정), D8 잔여 약 1ms.

---

## 6. 이번 세션에서 드러난 사실

| 사실 | 조치 |
| --- | --- |
| `taskctl dispatch --launcher` 의 `--repo` 는 주 저장소다. 워크트리를 주면 preamble 거부로 exit 2 | `--repo <주 저장소> --worktree path:<워크트리>` |
| `orca_prepare_worktree.py --capsule` 은 Capsule 을 복사하지 않는다 | `.orca/capsules/` 를 직접 복사 |
| 런처로 띄운 cmd 터미널에는 재작업을 inject 할 수 없다("no recognized agent") | 창을 닫고 새 런처 터미널로 |
| Intent 에 note 상한을 1,000·1,500자로 잘못 적어 X1 보고서가 게이트 6 위반 | 상한은 600자. X1 은 보고서만 재작업 |
| worker_done payload 의 filesModified 는 일부만 적힐 수 있다 | 판정은 diff 와 summarize_worker_done 으로 |
| 무거운 DB 질의와 동시에 돈 전량 테스트는 MySQL 테스트가 skip 되어 70 skipped 로 보였다 | 단독 재실행에서 40 skipped |
| **`orca worktree create` 의 빈 셸을 두 번 남겨 사용자가 지적했다** | 만든 직후 닫는다. 코디네이터 직접 워크트리는 회수 감사 도구가 못 잡는다 |
| 복구 도구 문서의 `python3` 명령은 macOS 기본 3.9 에서 import 실패 | 문서 10곳을 `uv run python` 으로 정정 |
| 첫 drill 의 import 시간 증가를 "데이터 증가" 로 확인 없이 설명했다 | 행 수 대조로 틀렸음을 확인하고 "원인 미확정" 으로 기록 |
| 세션 초반 `docker compose up` 으로 A안에서 정지하기로 한 worker 까지 기동했다 | 발견 즉시 정지 |

---

## 7. 자원 상태

| 대상 | 상태 |
| --- | --- |
| Git | `main` 은 이 문서 병합 후 clean, 원격 반영. 작업 브랜치·워크트리 0건 |
| Orca | Run `run_c1b3bb4a8856` Task 11건 `completed`, 워커 터미널 전부 회수 |
| Docker | 컴퓨터 종료를 위해 전 서비스 `docker compose stop`(볼륨 보존) |
| 배경 프로세스 | 상시 워커 감시기와 자동 승인 감시기 종료 |
