# 핸드오프 인수인계 — 추정가격 입력·tailwind 4 이전·날짜 시험 세션

> **작성일**: 2026-10-04
> **작성**: Claude 코디네이터 (run_03599ec1fd4a)
> **기준 커밋**: `e9363e2e` (main, origin 동기화. 이 문서는 그 다음 병합으로 들어감)
> **직전 인수인계**: [handoff_20261003_quant_band_official_session_close.md](handoff_20261003_quant_band_official_session_close.md)

---

## 0. 다음 세션이 가장 먼저 할 일

Docker 와 worker 는 올라가 있는 상태로 둡니다(2026-09-26 사용자 결정). 이번 세션 시작 때 Docker 데몬이 꺼져 있었고, `refac_bid_box-db-1` 컨테이너가 비정상 종료(137) 뒤 쓰기 계층 메타데이터를 잃어 `RWLayer ... is unexpectedly nil` 로 기동되지 않았습니다. 데이터 볼륨 `refac_bid_box_mysql_data`(41.6GB)는 온전했고 `docker compose up -d --force-recreate --no-deps db` 로 컨테이너만 다시 만들어 복구했습니다(`bid_announcements` 5,529,157행 확인). 같은 증상이 나오면 볼륨을 먼저 확인한 뒤 같은 명령을 씁니다.

```bash
open -a Docker
docker compose up -d
docker compose ps
gh run list --branch main --limit 3
```

**로그인이 필요한 화면을 눈으로 확인하십시오.** tailwind 4 이전의 시각 대조는 공개 화면(로그인·회원가입)만 했습니다. 대시보드, 공고 목록·상세, 낙찰 결과, 비교, 챗봇 화면은 운영 DB 에 시험 계정을 만들지 않으려고 대조하지 않았습니다.

---

## 1. 이번 세션에서 main 에 병합된 것

| 병합 | 내용 | 검증 |
| --- | --- | --- |
| `d96f71df` | 매칭률 감시 태스크 시험 기준일 고정(오늘 날짜로 터진 시한폭탄) | strict, 전량 시험(코디네이터 직접) |
| `f2072619` | 지방계약 미상 외부 공시 대조 조사 문서 | 리뷰 pass(수치 재현), strict, 전량 시험 게이트 1회 우회(사용자 승인) 후 main 전량 재검증 |
| `f925d3cb` | 정량평가 선택 입력 추정가격(공고에 없을 때만 사용) | 재작업(main 병합 재검증)·재리뷰 pass, strict, 전량 시험 |
| `ed8f4b4d` | 외부 대조 문서에 리뷰 관찰 2건 반영(코디네이터 직접) | strict, 전량 시험 |
| `eafe68bd` | Capsule 평문 목록 값의 끝 따옴표 보존(`scripts/orca_contract.py`) | 리뷰 pass, strict, 전량 시험 |
| `de160f95` | tailwindcss 4.3.3 이전, `@tailwindcss/postcss`+`postcss-cli` 경로, 레이어 해제, braces 예외 제거 | 재작업 3회, 최종 리뷰 pass, 코디네이터 계산 스타일 대조, strict, 전량 시험, main 에서 CSS 재현성·루트 npm audit 확인 |
| `e9363e2e` | 날짜 의존 시험 전수 조사와 기준일 고정(시험 4파일, 조사 문서) | 리뷰 pass(+365일 재현), strict, 전량 시험, 병합 후 main 전량 6,033 passed |

워커 구성: 빌더는 codex `gpt-6-luna` 로 시작했으나 세 대 모두 월간 한도 소진(재개 2026-10-31)으로 중단되어 cmd `deepseek/deepseek-v4.1-flash` 로 교체해 같은 워크트리 산출물을 이어받았습니다. 리뷰어는 opencode `muse-spark-1.3-contributor-free`.

---

## 2. 운영 DB 와 환경 변경

운영 DB 쓰기와 스키마 변경은 없습니다. DB 컨테이너만 재생성했습니다(0절). `.env` 변경 없음. 루트 `package.json`·`package-lock.json` 이 tailwind 4 경로로 바뀌었으므로 로컬에서 `npm ci` 를 한 번 다시 해야 `npm run build:css` 가 동작합니다.

---

## 3. 확정된 사실 (재조사 불필요)

### 3.1 추정가격 선택 입력

- `QualificationInput.estimated_price`(선택, 원). 공고 `presmpt_prce > 0` 이면 무시하고 응답에 알리며, 없을 때만 배점표 구간과 B·k 판정에 씁니다. 낙찰방법명 5억 표기가 여전히 최우선입니다. `src/app/api/v1/evaluations.py` 의 `_effective_estimated_price` 한 함수가 두 경로에 공급합니다.
- React(`frontend/src/App.tsx`)는 정량평가 경로를 쓰지 않아 범위에서 뺐습니다. 입력란은 Jinja `detail.html` 에만 있습니다.

### 3.2 tailwind 4 이전에서 드러난 것

- 직전 인수인계의 "braces 해소책은 tailwindcss 4 이전뿐" 은 틀렸습니다. 공식 CLI `@tailwindcss/cli` 는 `@parcel/watcher -> micromatch -> braces 3.0.3` 을 끌어옵니다. `@tailwindcss/postcss`+`postcss-cli` 경로는 braces·micromatch 가 0개이고 npm audit 0건입니다.
- v4 산출물은 전부 `@layer` 안에 있고, 같은 화면이 레이어 밖의 bootstrap 5.3.3·daisyui 4.12.23 을 함께 불러 vendor 규칙이 항상 이깁니다. 기본 테두리색·본문 글자색·여백이 v3 와 달라졌습니다. `postcss.config.mjs` 의 자체 플러그인(새 패키지 없음)으로 레이어를 풀어 해결했습니다.
- v4 `space-*` 는 선택자·속성이 v3 와 달라 배치가 밀립니다. v3 형태로 되돌렸습니다.
- v4 `text-*` 줄높이는 비율값이라 `harness.css` 가 글자 크기를 덮어쓴 요소에서 커집니다. `@theme` 에 v3 rem 값을 고정했습니다.
- daisyui 4 는 v3 변형 변수(`--tw-rotate`, `--tw-skew-x` 등)에 기대므로 v4 에서 `transform` 식이 무효가 됩니다(모달·드롭다운 애니메이션). v3 기본값을 복원했습니다.
- 빌더·리뷰어 체크리스트("선택자가 생성됐는가")는 위 회귀를 하나도 잡지 못했습니다. CSS 변경의 수용 기준은 **계산 스타일 대조**여야 합니다. 방법: 앱이 렌더링한 HTML 을 받아 tailwind.css 링크만 v3·v4 파일로 바꿔 끼우고, 모든 요소의 계산 스타일(테두리, 여백, 글꼴, 색, 그림자, transform, 위치·크기)을 브라우저에서 대조합니다. 색은 canvas 로 정규화하고 채널 차이 6 이하는 v4 팔레트 차이로 허용했습니다. 최종 결과 로그인 100요소·회원가입 184요소 모두 위치·크기 차이 0, 페이지 높이 동일.

### 3.3 날짜 시한폭탄

- `src/` 13개 모듈이 `date.today()`/`datetime.now()` 를 기준일로 씁니다. 고정 날짜 데이터로 이 함수들을 시험하면 시간이 지나 깨집니다. 2026-10-04 에 `test_task_notifies_only_when_alert` 가 코드 변경 없이 깨져 모든 병합을 막았습니다.
- 임시 pytest 플러그인으로 운영 모듈 13개의 시계를 +30/+90/+365일로 옮겨 전량 시험을 돌렸습니다(`docs/analysis/date_dependent_tests_audit_20261004.md`). 기준일을 고정한 시험은 5건(4파일)입니다.
- 독립 리뷰 판정: **진짜 시한폭탄은 `tests/test_kb_builder.py::test_memory_bound_announcements_query_streaming` 1건**입니다(시드 2026-06-01, `utcnow()` 기준 최근 1년 창이라 2027-06-01 부터 실제로 실패). 나머지 4건(`test_monitor_catchup`, `test_query_planning` 3건 중 스냅샷·분기, `test_rag_multi_institution`)은 시험 기대값도 실행 시계를 써서 실제로는 함께 움직이므로 깨지지 않는 플러그인 부작용이며, 고정은 시험을 결정적으로 만들 뿐 해가 없습니다. 문서가 5건을 모두 시한폭탄으로 묶어 적은 것은 과장입니다(비차단, 정정 미반영).
- 플러그인은 운영 모듈 시계만 옮기므로 "시험 쪽 시계를 쓰는 기대값" 을 시한폭탄으로 오인합니다. 다음에 같은 조사를 하면 기대값이 고정 날짜인지 실행 시계인지부터 가릅니다.

### 3.4 지방계약 미상 외부 대조

- 미상 7,425개 기관(111,565건)을 클린아이·알리오 목록과 이름 대조: LOCAL 후보 512개 기관 12,958건, NATIONAL 후보 2개 기관 143건, 알리오 기타공공기관 245개 기관 23,765건 판단 불가. 이름 대조만으로 규칙을 만들면 동명 기관 오인 위험이 있어(반례 6건) 근거 있는 상한은 13,101건(11.7%)이고 실제 적용 가능 값은 기관별 확인 뒤에 정해집니다. 상세 `docs/analysis/demand_institution_external_match_20261004.md`.

---

## 4. 남은 일과 제안

| 우선 | 항목 | 비고 |
| --- | --- | --- |
| 1 | 로그인 화면 시각 확인 | tailwind 4 이전 후 대시보드·공고 상세 등. 이상 시 3.2 의 대조 방법으로 재현 |
| 2 | 지방계약 미상 축소 결정 | 지방 출자출연기관을 앱의 LOCAL(±3%)로 볼지 사용자 결정, 기관별 사업자번호·설립 지자체 검증 |
| 3 | 2027년 고시금액 | 2026-12 고시 후 `src/ml/notice_amount.py` 갱신 |
| 4 | Windows 실기 검증 | 장비 부재로 보류 |

codex 월간 한도는 소진되었고 2026-10-31 에 재개됩니다. 그 전까지 빌더는 cmd `deepseek-v4.1-flash` 입니다.

---

## 5. 이번 세션 조율 함정

- **Orca 앱 자동 업데이트**(1.4.219 -> 1.4.220)로 런타임이 잠깐 끊기고, 이후 `orca_taskctl dispatch` 가 정본 스킬 영수증 버전 불일치로 거부했습니다. `orca skills get orchestration` 재독 후 `python3 scripts/orca_skill_receipt.py issue`.
- **codex 한도 소진 교체 절차**: 터미널에 "usage limit" 이 보이고 마지막 턴에 `worker_done` 이 없으면 `worker-stop --dispatch` (워크트리 보존) -> `task-update --id <task> --status ready` -> cmd 런처 터미널 생성 -> `taskctl dispatch --terminal --launcher scripts/orca_cmd_launch.py`. Capsule 에 "앞선 미커밋 변경을 읽고 이어서, 버리지 말라" 를 추가합니다. cmd 는 첫 기동 때 "Build Your Coding Taste" 대화창을 띄우므로 `n` 으로 닫습니다.
- **시한폭탄과 병합 증거**: 이미 끝난 빌더 커밋은 main 의 수정이 없어 전량 시험 증거가 반드시 실패합니다. 빌더 브랜치에 코디네이터가 main 을 병합하면 게이트 6 이 깨지므로, 빌더 재작업(main 병합 후 재보고)이 정상 경로입니다.
- **재작업 Capsule 쓰기 범위**: `main...HEAD` 에 원래 구현 파일이 잡히므로 쓰기 범위에 원 Task 파일을 넣어야 다이제스트가 범위 초과로 판정하지 않습니다. `required_write_files` 의 옛 보고서 경로도 새 경로로 바꿔야 dispatch 가 거부하지 않습니다. 재작업 Task 는 원 Task 의존으로 `pending` 이라 `task-update --status ready` 가 필요합니다.
- **실패 worker_done 과 에스컬레이션이 함께 오는 경우**: 워커가 escalation 뒤 `outcome failed` worker_done 까지 보내면 Dispatch 는 종결됩니다. 그 터미널에 후속 지시를 넣지 말고 재작업 Task 를 발급합니다.
- **리뷰 체크리스트 id**: 리뷰 Intent 를 손으로 쓰면 빌더 Capsule 의 id 를 빠뜨리기 쉽습니다. 빌더 Capsule 의 `review_checklist` 를 그대로 복사해 Intent 를 생성했습니다.
- **Capsule 을 yaml.dump 로 쓸 때** 목록 들여쓰기를 문자열 치환으로 넣으면 중첩 객체가 깨집니다. `SafeDumper` 의 `increase_indent(flow, False)` 를 재정의한 덤퍼를 씁니다.
- **셸 `&` 로 띄운 게이트**는 추적되지 않아 결과 없이 매달렸습니다. 게이트·전량 시험은 항상 추적되는 배경 작업으로 띄웁니다.
- **증거 파일은 주 저장소 공통**(`.cache/level1_strict_evidence.json`, `.cache/premerge_full_suite_evidence.json`)이라 다른 브랜치 기록이 덮습니다. 병합 직전에 그 브랜치로 다시 기록합니다.
- **`orca worktree rm`** 직후 `git worktree list` 에 잠시 남아 보입니다. 디렉터리 부재를 확인하고 `git worktree prune`.

---

## 6. 종료 시점 상태

- main 은 이 문서 병합 커밋이며 origin 과 동기화. 작업 브랜치 0, 워크트리는 주 저장소 하나.
- 마지막 병합 `e9363e2e` 뒤 main 전량 시험 6,033 passed / 31 skipped / 3 deselected, 실패 0. 규칙 검증 21/21.
- main CI: `d96f71df`, `f2072619`, `f925d3cb`, `ed8f4b4d`, `eafe68bd`, `de160f95` 전부 성공(`de160f95` 의 공급망 job 포함). `e9363e2e` 와 이 문서 병합의 CI 는 다음 세션이 먼저 확인합니다.
- Orca Run `run_03599ec1fd4a` 의 빌더·재작업·리뷰 Task 전부 settled, 완료 세션 잔류 0. codex 로 띄운 첫 Dispatch 3건은 한도 소진으로 `worker-stop` 했습니다. 배경 감시·대기 작업은 모두 회수했습니다.
- 워커 산출물(보고서, 외부 대조 원본 파일, 날짜 시험 플러그인)은 주 저장소 `.orca/capsules/` 에 보존했습니다(gitignore 대상).
- Docker compose 전체 기동 상태(worker 포함) 유지.

---

## 7. 추가 작업: 미수집 기관·지역 용역 산식 수집 (인수인계 병합 뒤)

### 7.1 배경과 병합

정량평가 레지스트리(`src/app/services/evaluation_rules.py`)의 규칙 45개는 전부 조달청 일반용역 적격심사 세부기준 계열이고, 기관·지역 규칙은 0개입니다. 2026-09-30 수집 세션(`docs/handoff/session_20260930_servc_formula_collection.md`)이 "이미 코드에 있다" 며 빼 둔 12곳은 실제로 이 저장소와 원본 bid_box 어디에도 산식이 없었고, 그 세션의 원문 추출물(`/tmp/qual-formulas/`)도 재부팅으로 사라졌습니다. 그래서 미확보·부분·출처 없음 29곳을 워커 3대(cmd `deepseek-v4.1-flash`, 리뷰어 opencode muse-spark)로 다시 수집했습니다.

| 병합 | 문서 | 검증 |
| --- | --- | --- |
| `8619efac` | [servc_formula_collection_energy_20261004.md](../analysis/servc_formula_collection_energy_20261004.md) 에너지·공항 공기업 8곳 | 리뷰 pass(수치 원문 대조), strict, 전량 시험 |
| `f6af0f2f` | [servc_formula_collection_local_20261004.md](../analysis/servc_formula_collection_local_20261004.md) 지자체 12곳 | 리뷰 pass, strict, 전량 시험 |
| `8204127c` | [servc_formula_collection_central_20261004.md](../analysis/servc_formula_collection_central_20261004.md) 중앙부처·공단 9곳 | 첫 리뷰 fail(방위사업청 통과점수 2칸 오기) -> 재작업 -> 재리뷰 pass, strict, 전량 시험 |
| `8ce1032f` | [servc_formula_kogas_qualification_20261004.md](../analysis/servc_formula_kogas_qualification_20261004.md) 한국가스공사 적격심사 현행판 | 리뷰 pass, strict, 전량 시험 |
| `095df81a` | 중앙부처 문서의 한국가스공사 판정 정정(코디네이터 직접) | strict, 전량 시험 |

코드(`evaluation_rules.py`)는 바꾸지 않았습니다. 확인된 산식을 레지스트리에 넣을지는 사용자 결정 사항입니다.

### 7.2 결과

| 등급 | 대상 |
| --- | --- |
| 확인 17 | 행정안전부 예규 제373호, 인천(예규 제488호), 제주(예규 제82호), 강원, 세종(예규 제32호), 경북, 울산(공고 제2022-1100호), 충북(공고 제2023-1428호), 전남광주(예규 제3호), 경남(공고 제2023-23호), 국토교통부(훈령 제965호 일반용역), 방위사업청(예규 제1082호, 10억 이상 k 미확정), 국가유산청(고시 제2024-6호, 평탄 점수 미인쇄), 한국가스공사, 한국전력기술, 한국수자원공사 |
| 부분 5 | 대구(단순노무 외 일반용역 별표 2022-09-30 삭제), 경기(예규 제748호, 별표 1-1 예외 상수 0.25 불일치. 최신 제751호는 별표 동일), 환경부(별표가 이미지), 한국도로공사(2022-10-01 판 원문 재확보 실패), 한국수력원자력 |
| 미확인 8 | LH·한국철도공사·한국지역난방공사(로그인·보안모듈), 한국농어촌공사·한국석유공사·한전 전력연구원(DNS 실패·시간 초과, 부재의 증거 아님), 한전KPS·인천국제공항공사(09-30 에는 받았으나 이번에 재확보 실패) |

- **한국가스공사 정정**: 처음에는 「용역계약 종합심사낙찰제 심사세부기준」만 보고 "적격 B-k 아님" 으로 판정했으나, 사용자가 준 단서로 「공사·용역 적격심사 세부기준」(2026-07-09 시행, 전자조달 규정실 LCD0000017)을 확보했습니다. 종심제는 제3조 3유형(기본계획·기본설계 30억 이상, 실시설계 40억 이상, 건설사업관리 50억 이상)에만 적용되고, 그 밖의 용역은 제17조 적격 B-k(기준비율 90, k 1.5/2/3/5, B 30/50/70, 시설분야 기준 92)를 씁니다.
- **원문 보관**: 내려받은 원본과 추출 텍스트(약 485개)는 주 저장소 `.orca/capsules/` 의 각 Task 폴더 `external/` 에 있습니다(지자체 `task_58ea8ddab6fb`, 중앙부처 `task_889fe5b87a19`, 공기업 `task_cfe0a9372ae4`, 가스공사 `task_a61c0e310be3`). gitignore 대상이라 다른 머신으로는 따라가지 않습니다.
- **사용자 제공 링크 검토**(2026-10-04): 19개 중 새 단서는 한국가스공사 1건이었습니다. 울산·인천·세종·경남·경기는 이미 같은 판을 확보했고, 충북(2020)·한국전력기술(2014)·전남광주(행정예고 제정안)는 확보본보다 오래됐습니다. 인천공항 링크는 자회사 인천공항시설관리, 제주 링크는 제주특별자치도개발공사, 국토교통부 링크는 건설엔지니어링 전용 기준이라 대상이 다릅니다. 강원·대구·경북·한국수력원자력·한전KPS 는 "첨부파일" 로만 적혀 있어 파일을 받지 못했습니다.

### 7.3 남은 일

| 우선 | 항목 | 비고 |
| --- | --- | --- |
| 1 | 첨부파일 3건 판정 | 대구(부분), 한국수력원자력(부분), 한전KPS(미확인). 사용자가 가진 파일을 받으면 판정 갱신 |
| 2 | 미확인 8곳 재확보 방법 결정 | 로그인 필요 3곳은 기관 계정, DNS 실패 3곳은 재시도 또는 정보공개 청구 |
| 3 | 레지스트리 반영 여부 결정 | 확인 17곳 중 어디까지 `evaluation_rules.py` 에 기관·지역 규칙으로 넣을지. 반영 시 공고의 공고기관·수요기관으로 규칙을 고르는 판정이 함께 필요 |

### 7.4 이 작업의 조율 함정

- 문서 추출 도구가 없어 사용자 승인으로 `uvx --from pdfminer.six pdf2txt.py`, `uvx --from pyhwp --with six hwp5txt` 를 일회성으로 썼습니다(프로젝트 의존성 변경 없음). HWPX 는 표준 zipfile 로 읽습니다. HWP 수식(HancomEQN)은 hwp5txt 가 계수를 빠뜨리므로 HWPX `Contents/section0.xml` 재추출이 필요했습니다(방위사업청).
- cmd 워커가 원본을 워크트리 밖 `$COMMANDCODE_SCRATCHPAD` 에 내려받다가 정정 지시로 `.orca/capsules/<task>/external/` 로 옮겼습니다. Capsule 에 저장 위치를 적어도 한 번은 확인해야 합니다.
- 리뷰가 같은 절 안의 인용 줄과 표 칸 사이 불일치(인용은 맞고 표만 틀림)를 잡았습니다. 원문 수치 대조 체크리스트가 효과가 있었습니다.
- 감시 스크립트가 하트비트마다 끝나 왕복이 늘었습니다. 하트비트만 든 배치는 스크립트가 ack 하고 계속 기다리게 고쳤습니다.
- 종료 시점: 작업 브랜치 0, 워크트리는 주 저장소 하나, 완료 세션 잔류 0. `8ce1032f`·`095df81a` 와 이 절 병합의 CI 는 다음 세션이 먼저 확인합니다.
