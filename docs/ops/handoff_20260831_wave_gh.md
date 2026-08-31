# 인수인계: Wave G·H 조율 평면 정합성 작업 (2026-08-31)

> **작성일**: 2026-08-31
> **Run**: `run_cd97f1f89fb6`
> **기준 커밋**: 본 문서 병합 시점 `main`
> **작성 사유**: 마감(18:20) 내 Wave H 병합이 끝나지 않을 경우를 대비한 인수인계

---

## 1. 배경

외부 감사 보고서 두 건(GPT·Grok)을 받아 현재 코드와 교차 검증한 뒤, 실제 잔여만
Task 로 만들어 처리했습니다.

**Grok 보고서는 `4aa444f`(2026-08-18) 기준으로 838 커밋 뒤처져 10건 중 8건이 이미
수정 완료였습니다.** 감사 보고서를 받으면 기준 커밋부터 확인하십시오. 상세는
[`orca_do_not_repeat.md`](orca_do_not_repeat.md) 참조 대상입니다.

GPT 보고서는 당시 HEAD 기준이라 7건이 전부 유효했으나, q21 항목의 인용 수치가
틀렸습니다. `CURRENT_STATE` 의 개선 델타 비교표(`144/144`, `recall 1.0`)를 품질
정본으로 오독했고 실제 정본은 `138/144`, `0.958` 입니다.

---

## 2. 완료 (병합됨)

| Wave | 내용 | 병합 |
| --- | --- | :---: |
| G1 | 모델 정책 3중 분기 수렴, q21 모순 제거, 2.4 절 warm 한정, EXPLAIN 추정치 표기 | 완료 |
| G2 | 리뷰어 provider 독립성 fail-closed, `commit_count` 타입 검증 | 완료 |
| G3 | ngram 회귀 하네스, 경계값 14 클래스 픽스처 | 완료 |
| G4 | 리뷰어 실행기 CLI 라우팅 (provider 별 agy/qwen 분기) | 완료 |
| - | agy 런처 승인 자동화 (2회 수정) | 완료 |
| - | `structured_data.py` EXPLAIN 추정치 주석 | 완료 |
| H1 | `TIER_POLICY` 문서 drift 검사, AGENTS.md 배정표 재삽입 검사, CURRENT_STATE 모순 검사 | 완료 |

**q21 판정 근거**: 날짜가 아니라 코드로 판정했습니다. `src/rag/vector_store.py:217`
이 이미 `title_key in query_key` 포함 매칭이므로 "수정 미적용" 서술이 낡은
것이었습니다. 날짜만 보면 그쪽이 더 최신이라 반대로 지울 뻔했습니다.

**H1 실증 검증 결과**: 원본 통과, primary 조작 실패, 표 삭제·파싱 실패 시 실패,
문서에만 있는 조합 실패, 코드에만 있는 조합 실패, AGENTS.md 표 재삽입 실패.

---

## 3. 미완료 (다음 세션에서 이어받을 것)

### 3.1 H2 ngram feature flag — 검증 완료, 병합 대기

- 브랜치: `kwanbum217/orca-h2-ngram` (커밋 2건, 최신 `dbd1fb2f`)
- 워크트리: `/Users/kwanbum/orca/workspaces/refac_bid_box/orca-h2-ngram`
- `worker_done`: `.orca/capsules/task_6d21228d563c_rework/worker_done.json` (위반 0)
- **Level 1 게이트 통과**
- **Level 2 리뷰어 미완**: `claude-sonnet-4-6` 과 `qwen3.7-plus` 모두 JSON 파싱
  실패로 종료 코드 2. 결함 지적이 아니라 모델 출력 형식 문제입니다.
- Level 3(코디네이터 검토) 완료. 이 검토에서 실제 결함 1건을 찾아 재작업으로
  닫았습니다(3.4 절).

**다음 명령**:

```bash
python3 scripts/orca_run_reviewer.py \
  --capsule <워크트리>/.orca/capsules/task_6d21228d563c/capsule.yaml \
  --repo <워크트리> --diff-base main --diff-branch kwanbum217/orca-h2-ngram \
  --model claude-sonnet-4-6 --max-diff-chars 80000 --out /tmp/h2_review.json --json
```

### 3.2 H3 런처 승인 공통화 — 게이트 대기

- 브랜치: `kwanbum217/orca-h3-launcher` (커밋 1건 `bde4908`)
- 워크트리: `/Users/kwanbum/orca/workspaces/refac_bid_box/orca-h3-launcher`
- `worker_done`: `.orca/capsules/task_b39d478921fd_rework/worker_done.json` (위반 0)
- Level 1 게이트 재실행 중이었습니다. Level 2·3 미실시.
- 산출물: `scripts/orca_worker_launch_common.py` 신설, 세 런처 공통화.

### 3.3 Wave I (미착수) — 운영 FULLTEXT 인덱스

**사용자 승인 없이 시작하지 마십시오.** 수 GB 테이블의 최초 FULLTEXT 생성은
테이블 재구축과 쓰기 차단을 유발할 수 있습니다.

순서를 지키십시오.

```
플래그 OFF 로 코드 배포 (H2 병합)
  -> 운영 FULLTEXT 인덱스 생성 (별도 runbook, Alembic 자동 마이그레이션 금지)
  -> 인덱스 존재 확인 + canary 질의
  -> 경계값 7 클래스 실측 (3.4 절)
  -> 플래그 ON
  -> cold canonical 재측정 (32문항 x 3회 규약)
```

### 3.4 경계값 7 클래스 실측 (Wave I 선행 조건)

`tests/fixtures/ngram_edge_keywords.json` 의 다음 7건이 `is_safe_for_ngram: true`
인데 **실측된 값이 아닙니다.** MySQL 통합 테스트는 실 DB 없이 skip 되므로 아무도
검증한 적이 없습니다.

`edge_04`(괄호), `edge_05`(하이픈), `edge_07`(영문숫자), `edge_09`(`%`),
`edge_10`(`_`), `edge_11`(따옴표), `edge_12`(boolean 연산자)

현재 H2 코드는 이들을 **보수적으로 제외**해 LIKE 단독으로 보냅니다. 안전하지만
기관명에 괄호가 흔하므로 최적화 적용 범위가 좁아집니다.

**의심 근거**: `100%` 의 경우 `LIKE '%100%%'` 는 "100" + 임의 문자열을 매칭하지만
구문 검색 `+"100%"` 는 리터럴을 요구하므로 MATCH 가 진부분집합이 되어 **조용한
누락**이 납니다. 픽스처 값이 틀렸을 가능성이 높습니다.

실 MySQL + FULLTEXT 인덱스에서 G3 하네스로 확인한 뒤 픽스처를 정정하십시오.

### 3.5 그 밖의 잔여

- 분석 문서 수치 자동 생성 (원시 JSON -> 요약 생성기). GPT 보고서 7 장.
- `orca_run_reviewer.py` 의 `--max-diff-chars` 기본값 20,000 이 실제 Task diff
  규모(41,000자대)의 절반입니다. 기본값 상향 검토.
- `qwen3.7-plus` 리뷰어 신뢰도: 2026-08-31 에 JSON 이 아닌 응답을 반환해 실패.
  `TIER_POLICY` 의 리뷰어 주 모델이므로 재현되면 배정 재검토가 필요합니다.

---

## 4. 워커 승인 중단 — 오늘 드러난 네 층

같은 증상("워커가 승인에서 멈춤")의 원인이 네 가지로 달랐습니다. 다시 만나면
어느 층인지부터 가르십시오.

| 층 | 원인 | 조치 |
| --- | --- | --- |
| 1 | `taskctl dispatch` 를 우회해 준비 4단계 누락 | 런처 경로에서 `prepare-worker` 호출 |
| 2 | 헬퍼를 직접 불러 CLI 메타데이터 미기록 -> 판정 fail-closed | `prepare_worker_terminal` 을 통째로 호출 |
| 3 | 부분 실패인데 최상위 `ok=true` 라 재시도 조기 종료 | `file_edit_auto_approve.ok` 로만 판정 |
| 4 | 셸 명령 승인은 `accept-edits` 로 덮이지 않음 | 워커에게 파일 편집 도구를 쓰게 지시 |

1·2 는 병합 완료, 3 은 H3 산출물에 포함, 4 는 지시로 우회합니다.

`shift+tab`(`\x1b[Z`) 순환은 `normal -> accept-edits -> plan -> normal` 입니다.
**연속 전송하면 `plan` 으로 밀려 워커가 파일을 못 고칩니다.** 한 번 보낼 때마다
`detect_antigravity_mode` 로 확인하고, 화면이 스피너라 `unknown` 이면 키를 더
보내지 말고 기다리십시오. 실측에서 한 워커는 12회차(약 2분) 만에 확보됐습니다.

---

## 5. 워커 계약 위반 재발 유형

Wave G·H 에서 워커 5대 중 4대가 `worker_done` 계약을 어겼습니다. Capsule 의
acceptance 에 다음을 명시하십시오.

| 유형 | 사례 | 예방 문구 |
| --- | --- | --- |
| 필드명 임의 변경 | `verification_results`, `commit_hash`, `outcome` | 정본 템플릿을 작성 **전에** 읽으라고 명시 |
| 검증 시점 오류 | 문서를 나중에 추가하고 이전 테스트 결과를 보고 | 모든 파일을 쓴 **뒤** 마지막에 테스트를 돌리라고 명시 |
| 문서 링크 | `docs/analysis/` 에서 루트 기준 경로 사용 | `../../` 접두가 필요하다고 명시 |
| 교차 참조 오인용 | 코드 주석이 픽스처 값을 반대로 인용 | 인용한 값을 실제로 읽어 대조하라고 명시 |

---

## 6. 정리 상태

- Wave G 워크트리·브랜치: **반납 완료**
- Wave H 워크트리 3개: **유지 중** (`orca-h1-drift`, `orca-h2-ngram`, `orca-h3-launcher`)
  - `orca-h1-drift` 는 병합 완료이므로 정리 가능
  - 나머지 둘은 미병합이므로 **삭제하지 마십시오**
- Docker 컨테이너: 사용자가 웹 확인 중이라 **가동 유지**
