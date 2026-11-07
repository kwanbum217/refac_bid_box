# 핸드오프 인수인계 - 2026-11-07 세션

> **작성일**: 2026-11-07
> **작성**: 코디네이터(Claude Opus 5.5). Orca Run `run_d3fa8d51ba74`
> **기준 커밋**: 작성 시점 `main` 과 `origin/main` 은 `a419fb24` 입니다. 이 문서는 브랜치 `kwanbum217/handoff-20261107` 에서 병합합니다.
> **상태 문서**: `docs/context/CURRENT_STATE.md` 의 `source_commit` 은 이 문서 병합에서 `a419fb24` 로 갱신했습니다.
> **워커 풀**: 빌더 cmd `deepseek/deepseek-v4.1-flash`, 리뷰어 cmd `z-ai/glm-5.3-flash`(사용자 지정). 워커 0대, 남은 워크트리는 이 문서 브랜치뿐입니다.
> **Docker**: app·db·redis·meilisearch·worker 기동 중.

---

## 0. 다음 세션이 바로 할 일

| 우선 | 과업 | 방법 |
| --- | --- | --- |
| 1 | 이 문서 병합 커밋의 main CI 확인 | `gh run list --branch main --limit 3`. 직전 `5253afb9` 는 전 job 통과 |
| 2 | Windows 팀원 데이터 묶음 전달 | 아래 4절. 전달 경로는 사용자 결정 |
| 3 | Windows 실기 첫 실행 확인 | `windows-onboarding` 스킬. winget ID `Python.Python.3.13`, `GnuWin32.Make` 실재 확인 |
| 4 | Codex 전역 hook 정리(사용자 직접) | 아래 5절 |

---

## 1. 이 세션에서 main 에 넣은 것

| 병합 | 내용 |
| --- | --- |
| `8e612506` | 결정 3-A 공기업 조달청 전환(판정 변화 26건), 공고 상세 분석 모델 카드 축소 |
| `ccb4cc22` | 공고 상세 추천 공고·과거 사례 재선정(분야 일치, 공고명 유사도, 마감 전 KST), 조사 문서 8건, 결정 백로그 42항목 통합 문서 |
| `4d36ad79` | 결정 백로그 권장안 구현(기관 판본·정량표, 건설폐기물 고시 경로, 낙찰방법명 교차 확인, 원장 취소공고 제외, 시·도 별표, 불일치 지표), KST 시각 기준 수정 20곳, 조사 문서 6건 |
| `5253afb9` | 비예가 문구 정정·공개값 표시, PQ 후속 가격입찰 공고 연결, 점검표·Windows 실행 스킬과 인덱스 |
| `a419fb24` | Windows 실행 스킬 백업 복원 호출을 `uv run python` 으로 정정 |

통합 전수 판정 변경 1,128건은 개별 브랜치 변경의 합집합과 같았습니다(대상 밖 0, 건설폐기물 고시 이탈 0).

---

## 2. 운영 수치

| 항목 | 이전 | 현재 |
| --- | ---: | ---: |
| 원장 집계 공고 | 31,325 | 27,723 (취소공고 3,602 제외) |
| 차단 | 9,728 | 8,688 |
| 사용자 입력으로 계산 가능 | 9,508 | 8,513 |
| 규칙 ID | 217종 | 234종(기관 97종) |

원장 정의가 바뀌어 산림청(`1400000`)이 최소 건수 아래로 빠졌고, `tests/test_rule_coverage_ledger.py` 에 예외로 두었습니다.

---

## 3. 결정과 판단 기록

| 항목 | 결정 |
| --- | --- |
| 결정 백로그 42항목 | 사용자 권장안 일괄 승인. 구현 항목과 현행 유지 항목은 `docs/analysis/decision_backlog_20261107.md` 와 각 구현 회귀 문서 |
| MOIS_OTHER 일반용역 | 순천 2행은 2026-07-16 시행 지침을 소급하지 않음(시행일 불일치 원칙), 원주 1행 갈래 미확정 유지, 기술용역 전용 유지 |
| 비예가 211건 | 차단 유지, 문구 '예정가격(기초금액) 미공개', 하한율·추정가격 공개값만 표시, 참고 계산 미제공, 후속 공고는 `bfSpecRgstNo` 정확 일치로 목록 연결(금액 미노출) |
| 스킬 | `platform-health-checklist`, `windows-onboarding` 정본·미러·인덱스 등록. Claude, Grok 4.7, OpenCode 2.2.6(DeepSeek V4.1 Flash Free), Codex 0.167.0 이 모두 `AGENTS.md` 인덱스로 찾는 것을 실측 |

---

## 4. Windows 팀원 데이터 묶음

| 파일 | 크기 |
| --- | ---: |
| `db_dump.sql.gz` | 2.4GB |
| `chroma_db.tar.gz` | 3.0GB |
| `models.tar.gz` | 144MB |
| `qualification_sources.tar.gz` | 75MB |

- 위치: 이 맥의 `data/backups/snapshots/snapshot_20261107_123933` (gitignore 대상, 총 5.3GB). `backup_recovery.py verify` 통과.
- 같은 디렉터리의 `SHA256SUMS.txt` 로 받은 쪽이 무결성을 확인합니다.
- 운영 데이터이므로 공개 저장소·공개 링크에 올리지 않습니다. 전달 경로는 사용자가 정합니다.

---

## 5. 운영 메모

| 항목 | 내용 |
| --- | --- |
| Codex hook 오류 | 전역 `~/.codex/hooks.json` 이 없는 `~/.cmux/hooks/*.sh` 를 불러 `Hook failed 127` 이 뜹니다. 에이전트 설정 변경은 권한 정책상 코디네이터가 하지 못해 사용자가 정리합니다 |
| OpenCode 2.2.6 | TUI 는 `--model` 을 받지 않습니다. `OPENCODE_CONFIG_CONTENT='{"model":"..."}' opencode --standalone` |
| 게이트 3 | 검증 명령에 `python3 scripts/...` 를 넣으면 허용 목록 밖으로 거부됩니다. 미러 일치는 규칙 검증이 이미 검사합니다 |
| 원문 자료 회수 | gitignore 원문은 워크트리 제거 전에 회수합니다(이번 세션 14개 유실 후 재수집) |

---

## 6. 세션 종료 (2026-11-07 22:50)

> 사용자 지시로 컴퓨터 종료를 위해 마감합니다.

| 항목 | 상태 |
| --- | --- |
| main | `72c35985` 까지 6회 병합, 모두 CI 12개 job 통과(windows-latest py3.11 포함). 이 절의 병합 커밋 CI 는 다음 세션에서 확인 |
| 워커·워크트리 | 워커 0대, 남은 워크트리 없음, 상시 감시기(`orca_worker_watch.py`) 종료 |
| Docker | app·db·redis·meilisearch·worker 정지, Docker Desktop 종료. 다음 세션은 `make up` 후 worker 의 크론 등록 확인 |
| 데이터 묶음 | `data/backups/snapshots/snapshot_20261107_123933/` 에 `db_dump.sql.gz`, `chroma_db.tar.gz`, `models.tar.gz`, `qualification_sources.tar.gz`, `backup_manifest.json`, `SHA256SUMS.txt`. 전달은 사용자 |

### 6.1 다음 세션이 바로 할 일

| 우선 | 과업 |
| --- | --- |
| 1 | 이 문서 병합 커밋의 main CI 확인 |
| 2 | Docker 기동(`make up`) 후 app 응답과 worker 크론 등록 확인 |
| 3 | Windows 팀원 첫 실행 결과 반영(`windows-onboarding` 스킬의 winget ID 2개 실측) |
| 4 | 사용자 정리 대기: Codex 전역 hook 의 cmux 항목 |
