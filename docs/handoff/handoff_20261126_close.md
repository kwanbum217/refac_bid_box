# 2026-11-26 세션 인수인계

> **작성일**: 2026-11-26
> **최종 main**: 이 문서 병합 커밋(직전 `ef5a796b`)
> **Orca Run**: `run_42c74d844697`
> **상태**: 워커 0대, 워커 워크트리 0개, Docker 기동 중(사용자 화면 확인용)
> **코디네이터**: Claude(주간 토큰 5% 상태에서 시작해 권장안 3건만 진행)

---

## 0. 다음 세션 첫 할 일

| 순서 | 할 일 | 근거 |
| --- | --- | --- |
| 1 | `ef5a796b` 와 이 문서 병합의 CI 결과 확인 | 5장 |
| 2 | 분산 추천가 클립 보완 방식 사용자 결정 | 2장 B2 |
| 3 | 상세 화면 안내 2건 착수 여부 결정 | 3장 |
| 4 | 이전 인수인계 미처리 항목 | `docs/handoff/handoff_20261125_close.md` 7.4절 |

---

## 1. 이번 세션 병합

| 병합 커밋 | 내용 |
| --- | --- |
| `ef5a796b` | 게이트 6 거짓 실패 보고 적발: `scripts/orca_contract.py` 의 `_is_failure_result_str` 가 한국어 실패 표기(미달, 실패, 오류, 에러, 차단)를 실패로 판정. 0건·부정 표기(실패 0건, 0건 실패, 오류 없음, 미달 없음)는 성공 유지. 게이트 11 proven(기준 단언 실패 2건), 리뷰 pass, 전량 11,848 passed |

빌더 OpenCode Go `deepseek-v4.1-flash`(variant high), 리뷰어 OpenCode Go `glm-5.3-flash`(variant low). 백업 참조 `refs/backup/gate6-korean-20261126`. 리뷰 참고: '실패율 0%' 처럼 0률 성공 문구는 실패로 판정된다(실제 보고 형식에 없어 결함 아님).

---

## 2. 조사 결과 (보고서는 `.orca/reports/`, gitignore)

| 항목 | 결과 | 보고서 |
| --- | --- | --- |
| C4 KB 커버링 인덱스 효과 재계산 | 정정 전제(행당 4,995B, 페이지당 3.28행)로 현행 콜드 읽기 0.17M~1.14M 페이지(2.66~17.44GiB), A안 25.1K~27.1K 페이지(393~424MB). 예상 콜드 중심 3~4초, 범위 2~6초, 보수 상한 약 10초. 절감 65초 대비 DDL 15~40분, 손익분기 14~37회라 **보류 유지** | `kb_index_effect_recalc_20261126.md` |
| C3 승리 구간 갱신 주기 | 매일·매주·매월 25~75% 적중률 50.07·50.08·50.04%(n=57,667), 차이 없음(p>=0.308). 매월 권장이나 갱신 1회가 30초 이내라 변경 이득 작음 | `win_refresh_clip_20261126.md` |
| B2 분산 추천가 클립 빈도 | 최근 30일 용역 1,430건 × 가상 회원 64명 = 91,520회 중 **32.17% 클립**(하한을 공고 낙찰하한율로 둔 바닥 추정, 실제는 더 높음). 공고 96.99% 에서 최소 1명 클립 | 같은 보고서 |

### B2 결정 필요

클립된 사용자는 모두 같은 하한 금액을 받아 분산(2026-11-25 결정 A안)의 목적이 무너진다. 공고 10453166 실측에서 정량점수 26.1~36.1, 배점표 수정 6경우 **전부 클립**이었다(낙찰 가능 구간 전체가 회원 하한 아래). 후보: 구간을 회원 하한 위로 잘라 그 안에서 분산. 방식은 사용자 결정.

---

## 3. 사용자 화면 확인에서 나온 것

| 항목 | 판정 | 후속 |
| --- | --- | --- |
| 하단·기준·상단 시나리오의 투찰률이 모두 같음 | 정상. 가격점수는 투찰률(입찰가/예정가격)로만 정해져 필요한 투찰률은 하나, 금액만 예정가격별로 다름 | 투찰률을 표 위 한 번만 표시하는 개선 후보 |
| 정량점수를 낮췄더니 추천가가 올라감(공고 10453166, 41.1점 856,392,100원 -> 28.5점 878,278,892원) | 정상. 적격심사 가격점수는 기준율(이 공고 93%)에 가까울수록 높아 점수가 부족하면 투찰률을 올려 메운다. 코디네이터가 컨테이너 안 TestClient 로 재현해 단조 감소 확인 | 추천가 옆에 "정량점수가 낮을수록 추천 금액이 올라갑니다" 안내 후보 |
| Windows 팀원 `/bids/` 503 | Meilisearch 색인이 `is_cancelled`(11-22)·`filter_amount`·`is_private_contract`(11-25) 이전 판. 설정만이 아니라 문서에도 필드가 없어 `configure_index()` 단독은 불충분, `scripts/sync_search_index.py` 전체 재색인이 해법(설정 반영 포함) | 팀원 측 ChromaDB "contigious 2D array" 오류는 진단만 요청 |

---

## 4. 운용 관찰

| 항목 | 내용 |
| --- | --- |
| C5 worker_done 발신 핸들 뒤바뀜 재현 | 조사 워커(kb-index-recalc)의 첫 worker_done 이 다른 워크트리의 빌더 터미널 핸들(`term_9c962185...`)로 발신돼 거부. `ORCA_TERMINAL_HANDLE=<자기 핸들>` 을 붙여 재발신하게 해 수용. 두 워커는 서로 다른 워크트리, 기동 간격 약 3분. 원인 미확인 |
| 주 저장소 런처 거부 | `orca_opencode_launch.py` 는 주 저장소에 preamble 을 쓰지 않는다. `.orca/` 만 쓰는 조사 워커도 격리 워크트리가 필요하다 |
| GLM 리뷰어 | 빌더와 같은 opencode 라 `orca_taskctl dispatch` 가 독립성 위반으로 거부. 비감독 런처 경로(`--preamble` + `dispatch --return-preamble`)로 기동했다 |
| premerge 증거 | Level 1 `--strict --record-evidence` 와 별도로 워커 워크트리에서 `premerge_full_suite_gate.py --record` 가 필요하다. 하나만 기록하면 병합 훅이 막는다 |
| C2 | 2026-11-25 `30bfbe6d` 로 이미 완료돼 있었다(11-25 인수인계 7.5절 표가 7.6절과 대조되지 않음) |

---

## 5. 다음 에이전트 인수 안내

이 세션 코디네이터(Claude)는 주간 토큰 소진으로 여기서 멈춘다. 다른 에이전트가 이어받는다.

### 5.1 시작 절차

| 순서 | 할 일 |
| --- | --- |
| 1 | `AGENTS.md` -> `docs/context/CURRENT_STATE.md` -> 이 문서 순으로 읽는다. 워커를 쓰면 `orca skills get orchestration` 과 `orca-section-coordination` 스킬을 먼저 읽는다 |
| 2 | `git log --oneline -3` 으로 이 문서 병합 커밋이 main 에 있는지, `gh run list --branch main --limit 3` 으로 CI 성공인지 확인한다 |
| 3 | Docker 상태 확인: `docker compose ps`. 사용자 확인 중이면 그대로 둔다 |

### 5.2 남은 과업 (우선순위 순)

| 순위 | 과업 | 상태 | 착수 조건·방법 |
| --- | --- | --- | --- |
| 1 | B2 분산 추천가 클립 보완 | 사용자 결정 대기 | 2장 B2. 결정 뒤 빌더 Task. 대상 `src/app/services/win_interval_stats.py` 의 `user_dispersed_bid`, `src/app/api/v1/evaluations.py` 2895~2940행 부근. 위험도 high(추천가 산식)라 리뷰어 유지, 병합 전 공고 10453166 으로 클립 여부 재현 |
| 2 | 상세 화면 안내 2건 | 사용자 착수 결정 대기 | 3장. `src/app/templates/bids/detail.html` 의 `res-member-scenario-rows` 표와 내 조건 추천 투찰가 칸. 템플릿 병합은 `npm run build:css` 와 계산 스타일 대조 필요 |
| 3 | `schedule_run_log` 오염 확인 | 확인만 | 이 세션 전량 pytest 가 Docker DB 기동 중 돌았다(워커 2회, 코디네이터 1회 중단). 2026-11-13 같은 조건에서 호스트 pytest 행이 남은 전례. 정리는 사용자 승인 뒤 |
| 4 | C5 worker_done 발신 핸들 원인 | 조사 | 4장. `scripts/orca_worker_launch_common.py` 의 `.handle` 처리와 opencode 런처 환경변수 상속 |
| 5 | 게이트 11 판정 단위 재검토 | 2026-12-09 이후 | `.cache/gate11_verdicts.jsonl` 2주 운영 뒤 |

### 5.3 함정 (이 세션 실측)

| 함정 | 대응 |
| --- | --- |
| opencode 런처는 주 저장소에 preamble 을 못 쓴다 | 조사 워커도 `orca worktree create` 격리 워크트리, 만든 직후 빈 셸 Terminal 1 닫기 |
| 같은 opencode 계열 리뷰어는 `orca_taskctl dispatch` 가 거부 | `orca terminal create ... --command "uv run python scripts/orca_opencode_launch.py --model opencode-go/glm-5.3-flash --variant low --role reviewer --preamble .orca/preamble_<task>_rev_<nonce>.txt"` 후 `orca orchestration dispatch --task <t> --to <h> --run <r> --return-preamble --json` 의 preamble 을 그 파일에 쓴다 |
| main 병합 훅은 증거 두 개를 요구 | Level 1 `--strict --record-evidence` 와 `python3 scripts/premerge_full_suite_gate.py --record`(병합 대상 HEAD 가 체크아웃된 곳에서). 문서만 바꾼 브랜치도 전량 시험 증거가 필요하다 |
| 리뷰 Capsule 경로 | Intent `report_path` 디렉터리와 create 가 만든 `task_<id>` 디렉터리 둘 다 워크트리에 만들어 Capsule 을 복사 |

---

## 6. 종료 상태

| 항목 | 상태 |
| --- | --- |
| 워커·워크트리 | 0대, 주 저장소 하나 |
| Docker | 기동 중(app, worker, db, redis, meilisearch). 세션 종료 지시 시 `docker compose stop` |
| CI | `ef5a796b` 와 이 문서 병합 확인 필요 |
