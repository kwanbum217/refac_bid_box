# 핸드오프 인수인계 — 정량평가 구간 공식 기준·지방계약 미상 조사 세션

> **작성일**: 2026-10-03
> **작성**: Claude 코디네이터 (run_b1f0cf9f171a)
> **기준 커밋**: `d731fc4c` (main, origin 동기화. 이 문서는 그 다음 병합으로 들어감)
> **직전 인수인계**: [handoff_20261003_regime_and_score_params_session_close.md](handoff_20261003_regime_and_score_params_session_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

Docker 와 worker 는 **올라가 있는 상태로 둡니다**(2026-09-26 사용자 결정, worker 상시 가동). 컴퓨터를 껐다 켰다면 다음으로 다시 올립니다.

```bash
open -a Docker
docker compose up -d
docker compose ps
```

main CI 결과를 먼저 확인하십시오. 이 세션 마지막 병합들의 CI 판정은 아래 6절에 적었습니다.

```bash
gh run list --branch main --limit 3
```

---

## 1. 이번 세션에서 main 에 병합된 것

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| `f051eec4` | 정량평가 기초금액 대체 영향 분석 문서 | 리뷰 pass(수치 전량 재현), strict, 전량 시험 |
| `2db39b21` | 지방계약 판별 미상 범주 조사 문서(코드 변경 없음) | 리뷰 pass, strict, 전량 시험 |
| `66e30dfa` | `braces` 상류 미수정 취약점 npm 예외 등록(만료 2026-12-31) | 로컬 공급망 세 층(pip-audit, npm audit 루트·frontend, Trivy) 통과, strict, 전량 시험 |
| `cb0c20e7` | 정량평가 배점표 구간을 공식 기준(추정가격)으로 선택, 기초금액 대체 제거 | 리뷰 pass, strict, 전량 시험 |
| `d731fc4c` | 구간 미정 API 차단 시험 1건(리뷰어 비차단 의견 반영, 코디네이터 직접) | 기초금액 대체 반례 주입 시 실패 확인, strict, 전량 시험 6,023 passed |

워커 구성: 빌더 codex `gpt-6-luna`(effort high/medium), 리뷰어 opencode `muse-spark-1.3-contributor-free`. 빌더 3대, 리뷰어 3대, 코디네이터 직접 3건(01:30 수집 확인, braces 예외, API 시험).

---

## 2. 운영 DB 와 환경 변경

없습니다. 운영 DB 쓰기와 스키마 변경이 없었고 `.env` 도 바꾸지 않았습니다. Docker 는 compose 전체를 기동했습니다.

---

## 3. 확정된 사실 (재조사 불필요)

### 3.1 01:30 수요기관 증분 수집

- 2026-10-03 01:30 KST 에 처음 실행됐고 정상이었다(`mode: incremental`, 2026-10-01~10-03 구간). `g2b_demand_institutions` 가 102,244 에서 102,245 행이 되고 `fetched_at` 이 그 시각으로 갱신됐다. 직전 인수인계 0절의 미확인 항목은 닫혔다.

### 3.2 정량평가 구간 판정 금액(공식 원문)

- 국가법령정보센터에서 직접 확인했다. 현행판은 **조달청 일반용역 적격심사 세부기준 제2026-390호(2026-07-27 시행, admRulSeq=2100000283412)** 이다. 연혁은 제2026-260호, 제2026-15호, 제2025-257호, 제2023-53호 순이다.
- 별표 1·2·3·6 의 배점한도 열 머리는 모두 "추정가격 5억원 이상 / 추정가격 5억원 미만" 이고, 입찰가격 예외 행은 "추정가격 고시금액 이상 / 미만" 이다. 제2조 제12호가 추정가격을 국가계약법 시행령 제7조로 산정한 가격으로 정의한다.
- 기초금액은 별표 2 주석에서 예정가격(복수예가) 산정용으로만 정의된다. 기초금액으로 구간을 정하는 규정은 없다.
- 추정가격이 없던 23행은 원천 `presmptPrce` 가 전부 0 이고 `base_amount` 는 배정예산 `asignBdgtAmt` 와 같으며 6,820원·25,000원·4,000억원 같은 비정상 값이 섞여 있다. 복구 불가.
- 구현: 정량평가 구간은 낙찰방법명 5억 표기 > 추정가격 > 미정(차단) 순으로 고른다. 방법명 판독은 `src/app/services/evaluation_rules.py` 의 `method_name_500m_side` 한 함수를 B 선택과 공유한다.

### 3.3 지방계약 미상 29.8%

- 미상 111,559건(29.84%)의 상위 범주는 기타기관(분류 없음), 4년제 대학, 기타공공기관·정부출연기관, 지자체 출자출연기관이다.
- 지자체 출자출연기관도 지방출자출연법 제2조의 적용 제외(지방공기업·지정 공공기관, 지분 50% 미만 출자기관)를 소관구분 값으로 가를 수 없어 None 을 유지했다. 분류값만으로는 근거 있는 새 규칙이 없다. 상세는 `docs/analysis/demand_institution_regime_unknown_20261003.md`.

### 3.4 braces 취약점

- GHSA-vfj7-8cjw-p6xm(스택 소진 서비스 거부)은 `braces` 3.0.3 이하 전 버전이 대상이고 수정 버전이 없다. 루트 devDependency `tailwindcss` 3.4.16 의 CSS 빌드에서만 고정 경로 패턴으로 쓰이고 런타임 이미지에는 없다. npm 이 제시하는 해소책은 `tailwindcss` 4 메이저 이전뿐이다.

---

## 4. 남은 일과 제안

| 우선 | 항목 | 비고 |
| --- | --- | --- |
| 1 | 추정가격 직접 입력 필드 | 구간 미정 공고에서 사용자가 추정가격을 넣는 기능. 요청·응답 스키마 변경이라 사용자 결정 필요 |
| 2 | `tailwindcss` 4 이전 | braces 예외 만료 2026-12-31 전에 완료. 브라우저 지원 범위(4 는 Safari 16.4+, Chrome 111+) 결정 뒤 이전, 주요 화면 시각 회귀 확인 |
| 3 | 지방계약 미상 축소 | 기관별 설립 근거·지분 정보 수집이 선행돼야 함 |
| 4 | 2027년 고시금액 | 2026-12 기획재정부 고시 후 `src/ml/notice_amount.py` 갱신 |
| 5 | Windows 실기 검증 | 장비 부재로 보류 |

codex 월간 한도가 이 세션 끝에 13% 남았습니다. 빌더 배정 시 고려하십시오.

---

## 5. 이번 세션 조율 함정

- 리뷰어 런처 터미널은 `orca terminal create --command 'uv run python scripts/orca_opencode_launch.py --model <모델> --role reviewer'` 로 만들어야 한다. 빈 셸 터미널에 `dispatch --launcher` 를 주면 "preamble 대기 표지를 확인하지 못했습니다" 로 종료 코드 2 가 난다.
- `release-worker` 가 성공을 반환해도 codex 빌더 터미널이 남는 경우가 있다. `orca_settled_session_audit.py` 가 다음 Dispatch 를 막으므로 `worker_done` 수신을 확인한 뒤 `orca terminal close --terminal <handle>` 로 닫는다.
- 상시 감시기가 codex 화면의 preamble 문구("reportPath 누락")를 "실패 정체" 로 오탐했다. 터미널 끝을 직접 읽어 판단한다.
- `taskctl create` 는 Intent 의 `--task-id` 별칭 디렉터리와 실제 Task ID 디렉터리에 Capsule 을 둘 다 만든다. 손으로 쓴 Capsule 은 두 곳 모두에 복사해야 워커가 어느 경로를 읽어도 같다(읽기 범위 초과 1건은 이 별칭 경로라 무해).
- 로컬 `validate_agent_rules.py` 가 통과해도 CI 의 "CURRENT_STATE 필수 필드" 가 `source_commit` 뒤처짐으로 실패할 수 있다. 병합이 여러 번인 세션은 마지막 병합 커밋 안에서 `source_commit` 을 갱신한다.
- 자동 생성 리뷰 Capsule 은 읽기 범위가 문서 하나뿐이고 쓰기 범위가 비어 있었다. 매번 코드·실행기 읽기 범위, report_path 쓰기 범위, DB 조회 형태, 커밋 금지를 보완했다.

---

## 6. 종료 시점 상태

- main 은 이 문서 병합 커밋이며 origin 과 동기화, 작업 브랜치 0, 워크트리는 주 저장소 하나.
- `d731fc4c` 병합 전 전량 시험 6,023 passed / 31 skipped / 3 deselected, 실패 0. 규칙 검증 21/21.
- main CI: `66e30dfa` 전 job 성공(공급망 job 복구). `cb0c20e7` 은 lint-and-validate 의 "CURRENT_STATE 필수 필드" 하나로 실패했다. 현황판 `source_commit` 이 `071e2d89` 로 뒤처진 탓이며 로컬 규칙 검증은 통과해 병합 전에 잡히지 않았다. 이 문서 병합이 `source_commit` 을 `d731fc4c` 로 갱신해 해소한다. 다음 세션은 이 문서 병합 커밋의 CI 를 먼저 확인하십시오.
- Orca 완료 세션 잔류 0, Run `run_b1f0cf9f171a` 의 Task 6건(빌더 3, 리뷰 3) 전부 completed. 상시 감시기와 배경 대기 작업은 모두 회수했다.
- Docker compose 전체 기동 상태(worker 포함) 유지.

---

## 7. 추가 작업 (13:30 이후, 인수인계 병합 뒤)

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| `7369839f` | tailwindcss 4 이전 영향 조사 `docs/analysis/tailwind4_migration_impact_20261003.md` | 리뷰 pass(수치 재현), strict, 전량 시험 |
| 이 절을 담은 병합 | 지방계약 미상 축소 단서 조사 `docs/analysis/demand_institution_unknown_signals_20261003.md` | 리뷰 pass(수치 재현), strict, 전량 시험 |

- tailwind 4 이전: 이름 변경 유틸리티는 `shadow-sm` 45, `rounded` 38, `outline-none` 26, `flex-shrink-*` 5, `backdrop-blur-sm` 4곳이라 기계 치환 가능하다. 시각 확인이 필요한 쪽은 색 미지정 `border` 144곳, `space-x/y` 103곳, `hover:` 111곳이다. 4절 2번 착수 시 이 문서부터 읽는다.
- 지방계약 미상: 미상 111,559건 중 상위기관이 LOCAL 인 공고 26,038건, NATIONAL 13,728건이다. 상위기관 판정 승계는 법적 근거가 없어(국립대학의 상위기관이 교육부 등) 지금 안전하게 줄일 수 있는 건수는 0건이다. 다음 단계는 외부 공시 대조와 개별 법률 적용 범위 확인이다.
- codex 월간 한도가 이 시점 **6%** 다. 2026-10-03 사용자 지시: codex 빌더가 소진되면 같은 워크트리 산출물을 보존한 채 cmd `deepseek/deepseek-v4.1-flash`(`scripts/orca_cmd_launch.py --auto --role builder`)로 교체해 같은 Task 를 이어서 진행하고, 리뷰 Intent 의 `builder_provider` 는 `cmd` 로 적는다.
- 조율 함정 추가: Capsule 을 `yaml.safe_dump` 기본 형식(목록 들여쓰기 없음)으로 쓰면 `summarize_worker_done.py` 가 허용 목록을 못 읽어 정상 산출물을 범위 위반으로 판정한다. Intent 키에 따옴표를 붙이면 `taskctl create` 가 역할을 못 읽어 리뷰 Capsule 이 빌더 기본값(`worker_done.json`, `ORCA_WORKER_DONE_V2`)으로 생성된다. Intent 는 키 무따옴표·값 따옴표로 손으로 쓰고, 생성 직후 `role`·`report_path`·`return_contract` 를 확인한다.
