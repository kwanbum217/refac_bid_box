# 인수인계: 20260908 Wave AM/AN 세션 종료

> **작성일**: 2026-09-08
> **Run**: `run_a6eec92b5e01`
> **기준 커밋**: `7ce7c3b` -> (본 커밋)
> **미병합 브랜치**: 없음
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260907_wave_ak_session_close.md`](handoff_20260907_wave_ak_session_close.md)

---

## 0. 다음 세션 첫 작업 (최우선)

**대시보드 금액 집계의 전환 효과를 실측으로 확인하십시오.** 코드는 이미 바뀌었는데
그 효과가 한 번도 측정되지 않았습니다.

> **2026-09-08 갱신**: 1차 실측(`kwanbum217/dashboard-latency`)은 리뷰 fail 로 반려됐습니다.
> `GET /api/v1/bids/stats` 는 `get_dashboard_stats`(BidResult, Redis 캐시) 라
> `_announcement_amount_expr` 경로가 아닙니다. **측정 대상을 `get_compare_stats_data`
> 로 바로잡아 다시 하십시오.** 상세는 13.4 절.

| 항목 | 내용 |
| --- | --- |
| 무엇 | `agency_announce_top10` 을 포함한 대시보드 집계가 `base_amount` 컬럼 기반으로 전환됐으나(`30aba4e`), 그 경로의 API 레이턴시를 측정한 적이 없습니다 |
| 왜 최우선인가 | G3 는 상시 과제이고 "기능이 동작하는 것으로 완료가 아니며 실측으로 성능을 확인해야 완료" 입니다. 사용자 대면 경로에 미검증 성능 주장이 남아 있는 유일한 항목입니다 |
| 알려진 값 | API 웜 31.97초(전환 전). DB 레벨 실측은 JSON 파싱 58.8~68.3초 대 컬럼 2.22~2.38초로 **26~29배**, 산출값 완전 일치 |
| 기대 | 전환 후 API 웜이 6초 안팎으로 내려가야 합니다. 내려가지 않으면 병목이 집계가 아닌 다른 구간이라는 뜻이며 그 자체가 결론입니다 |
| 선행 조건 | 없음. 안전 판정은 이미 끝났습니다(아래) |
| 측정 대상 | `GET /api/v1/bids/dashboard` (`src/app/api/v1/bids.py:176` -> `get_dashboard_stats`). 구현은 `src/app/services/dashboard.py` 의 `_announcement_amount_expr` |
| 하네스 | `scripts/benchmark_latency.py` 계열을 씁니다. 새로 만들지 마십시오 |
| 공유 자원 | Docker 스택과 DB 를 점유합니다. Task 의 `shared_resources` 에 `docker` 를 `exclusive` 로 선언하십시오 |

**안전 판정은 이미 끝났습니다.** `base_amount` 컬럼과 JSON 파싱값의 불일치 343건은
2026-09-04 에 전수 조사돼 **집계 총액 차이 최대 107원**(총액 2,126조 대비 상대오차
5e-17)으로 확정됐고 "전환해도 안전하다" 로 판정났습니다
([`../analysis/base_amount_column_mismatch_343_20260904.md`](../analysis/base_amount_column_mismatch_343_20260904.md)).
**이 조사를 다시 하지 마십시오.**

**측정 시 주의**: 콜드 SQL 총량은 2026-09-01 결정대로 게이트가 아니라 관찰
지표입니다. 버퍼풀 상태에 지배되므로 웜 조건을 정본으로 삼고, 산출물 provenance 에
버퍼풀 페이지 수가 기록되는지 확인하십시오(Wave AL1 이 그 기록을 넣었습니다).

**착수 전 확인**: 이 세션은 Docker 를 기동하지 않았습니다. 스택을 올릴 때
`LATENCY_SEGMENT_LOGGING=true` 가 필요하면 `.env` 를 백업하고 바꾼 뒤 측정 후
완전 일치로 원복하십시오. 헬스 경로는 `/api/v1/health/ready` 입니다.

---

## 1. 한 줄 요약

**선행 인수인계 0장이 지정한 최우선 작업(테스트 부작용 제거)을 닫았고, 그 조사 중에
드러난 워커 런처 계열의 구조적 결함까지 8건을 병합했습니다.** 사용하시는 CLI 7종 중
6종이 이제 `dispatch --launcher` 정규 경로에 올라 있습니다.

---

## 2. 닫은 항목

| Wave | 내용 | 작업 커밋 | 병합 |
| --- | --- | --- | --- |
| AM1 | **런처 테스트의 실제 프로세스 부작용 제거** (사용자 지정 최우선) | `31d8435` | `131640a` |
| AM2 | 자동 승인 감시기 자기 종료 | `4a6823c`, `72c7203` | `7ca21b9` |
| AM3 | 워커 회수 서브커맨드와 감시기 동반 정리 | `c8e4698` | `6990554` |
| AM4 | 런처 preamble 인계 규약 공용화 | `cb3e009` | `7a3ac53` |
| AM5 | claude, opencode, grok 런처 신설 | `1d1774e` | `5af97f0` |
| AN1 | claude 런처 권한 인자를 acceptEdits 로 전환 | `60930ef` | `b997460` |
| AN2 | dispatch 런처 자동 선택과 fail-closed | `4540856`, `d6ed305` | `9819210` |
| AN3 | claude 권한 모드 허용값을 acceptEdits 로 제한 | `d72d9eb` | `45348fe` |
| AO1 | Task 분석 문서 자동 주입 제거와 신규 `docs/analysis/task_*.md` 차단 | `f7f747d` | `a32f364` |
| AO2 | `docs/` 동일 문서 9쌍 정리. 대응표 파일은 AO1 차단 규칙과 충돌해 제거 | `33b206a`, `1f8e9d4` | `8e722f5` |

빌더는 전부 Antigravity `gemini-3.8-flash-medium`, 리뷰어는 Qwen Code `qwen3.7-plus`
입니다. AM/AN 8건의 Level 1 게이트는 9종 전량 통과입니다. AO1 은 게이트 6(리베이스 후 보고 정합성), AO2 는 게이트 3(`validate_doc_links.py` 허용 목록)을 코디네이터 실측으로 갈음하고 병합했습니다.

---

## 3. 선행 최우선 항목이 실제로 무엇을 막았는지

선행 인수인계 8.6.2 가 지목한 결함입니다. `tests/test_orca_agy_launch.py` 가
`mod.main(...)` 을 8곳에서 부르면서 `os.execvpe` 만 monkeypatch 했고, 그 직전의
`common.schedule_permission_setup` 은 실제 `subprocess.Popen` 으로 분리 자식을
띄웠습니다. 그 자식의 인자는 `ORCA_TERMINAL_HANDLE` 이며 테스트는 코디네이터
터미널 안에서 돌므로 **코디네이터 핸들**이 들어갑니다.

**병합 직전에 그 위험을 실측으로 재현했습니다.** AM2 브랜치(안전망 이전 코드)에서
전량 테스트를 돌렸더니 `--setup-permissions` 프로세스 10개가 생겼고 전부 코디네이터
핸들을 들고 있었습니다. 정리한 뒤 병합된 `main` 에서 같은 프로브를 돌렸습니다.

```
ORCA_TERMINAL_HANDLE=term_PROBE_MAIN_VERIFY uv run pytest \
  tests/test_orca_agy_launch.py tests/test_orca_kimi_launch.py -q
-> 51 passed in 4.03s
pgrep -fl "setup-permissions term_PROBE_MAIN_VERIFY"
-> 없음
```

안전망은 `tests/conftest.py` 의 autouse 픽스처와 런처 테스트 파일별 픽스처 이중
구조이며, `subprocess.Popen` 미호출을 단언하는 회귀 테스트가 세 파일에 있습니다.

---

## 4. 감시기 자기 종료 실패의 원인을 확정했습니다

선행 인수인계 8.6.1 은 `orca_auto_approve.py` 17개가 살아남은 사실만 기록하고
원인은 조사하지 않았습니다. **코디네이터가 실측으로 확정했습니다.**

| 조건 | `orca terminal read` 결과 |
| --- | --- |
| 존재하지 않는 핸들 | 종료 코드 1, stderr `terminal_handle_stale` |
| **닫힌 터미널** | **종료 코드 0, 본문에 `status: exited`** |

`read()` 는 종료 코드로만 실패를 판정하므로 닫힌 터미널은 실패로 세지지 않고,
`MAX_CONSECUTIVE_READ_FAILURES` 상한에 영원히 도달하지 못합니다.

AM2 가 `is_terminal_exited` 를 추가해 **read 앞머리 메타데이터 영역만** 검사하고,
연속 관측 상한 `MAX_CONSECUTIVE_EXIT_OBSERVATIONS=3` 을 두어 조기 종료를 막았습니다.
화면 본문 전체를 검색하면 워커가 그 문자열을 출력하는 것만으로 감시가 끊깁니다.

AM3 는 `orca_taskctl.py release-worker` 를 추가해 회수와 감시기 중지를 한 호출로
묶었습니다. **이번 세션에서 워커 14대를 전부 이 명령으로 회수했고 감시기 잔류가
한 건도 없었습니다.**

---

## 5. 런처 결함은 qwen 하나가 아니었습니다

리뷰어를 `qwen3.7-plus` 로 바꾸면서 처음 드러났습니다. `taskctl dispatch --launcher`
는 시도 단위 격리를 위해 preamble 을 `preamble_{task_id}_{dispatch_id}_{nonce}.txt`
로 쓰는데, agy 만 그것을 glob 으로 집어갔습니다.

| 런처 | 수정 전 | 수정 후 |
| --- | --- | --- |
| agy | glob·소비·삭제 (정본) | 공용 함수 참조 |
| qwen | 고정 경로만 대기 (**고장**) | 공용 함수 참조 |
| kimi | 고정 경로만 대기 (**고장**) | 공용 함수 참조 |
| claude, opencode, grok | **런처 없음** | 신설, 공용 함수 참조 |
| codex | preamble 경로 없음 (다른 구조) | 대상 아님 |

**원인은 같은 로직이 런처마다 복제된 것**이며 그래서 agy 만 고쳐졌습니다. AM4 가
`orca_worker_launch_common.py` 로 단일화했고, 세 런처에서 `glob`·`unlink`·
`def wait_for_preamble` 이 0건인 것을 확인했습니다.

**수정 효과를 병합 전에 운영에서 확인했습니다.** AM4 리뷰어를 정규 경로로 투입했을
때 `verified_launcher_pickup` 이 나왔습니다. 그 직전까지 세 번은 코디네이터가 손으로
`.orca/preamble.txt` 에 복사해야 했고, 그 우회는 격리 규약을 깨는 방식이라 유지할 수
없었습니다.

AM5 가 세 런처를 신설할 때 조사 보고서
`.orca/reports/am5_launcher_gap_survey.md` 를 먼저 만들어 근거로 삼았습니다
(`.orca/` 는 gitignore 대상이라 마크다운 링크로 걸지 않고 인라인 코드로 참조합니다). 미확인 0건이며 코디네이터가 근거 표본 4건을
직접 대조했습니다. 단발 모드를 `os.execvpe` 로 띄우면 창이 즉시 닫혀 출력을 잃는다는
지적이 그 보고서에서 나왔고, 세 런처 모두 `subprocess.run` 후 셸로 이어받습니다.

AN2 는 `dispatch` 가 모델에서 런처와 `cli_type` 을 함께 판정하게 했습니다. 종전에는
무엇을 띄우든 `scripts/orca_agy_launch.py` 로 고정이었습니다. 판정 불가 시 조용히
기본값으로 떨어지지 않고 종료 코드 2 로 거부합니다.

---

## 6. 권한 인자를 두 단계로 좁혔습니다

AM5 워커가 claude 런처의 권한 완화 수단으로 `--dangerously-skip-permissions` 를
채택했으나, 조사 보고서는 `--permission-mode acceptEdits` 를 권고했습니다. 둘은
위험도가 다릅니다.

| 인자 | 효과 |
| --- | --- |
| `--permission-mode acceptEdits` | 파일 편집만 자동 승인, 셸 명령은 확인 유지 |
| `--dangerously-skip-permissions` | **모든 권한 검사 우회** |

이 저장소는 명령 승인을 `orca_auto_approve.py` 의 `classify_command` 화이트리스트로
판정하므로, 명령 확인이 남아 있어야 그 감시기가 의미를 갖습니다. AN1 이 인자를
교체했고, **AN3 가 `choices=["acceptEdits"]` 로 값까지 제한했습니다.**

AN1 만으로는 부족했습니다. 인자 이름을 바꿔도 `--permission-mode bypassPermissions`
로 같은 결과에 도달할 수 있었고, 코디네이터와 리뷰어가 독립적으로 같은 지적을 했습니다.
**인자를 지운 것과 같은 결과에 도달하는 경로를 막은 것은 다릅니다.**

`opencode --auto` 와 `grok --always-approve` 는 기본값 꺼짐으로 노출만 되어 있습니다.
두 CLI 에 `acceptEdits` 에 해당하는 중간 단계가 확인되지 않아 범위에서 뺐습니다.
필요해지면 조사부터 하십시오.

---

## 7. 게이트가 사람이 놓친 것을 세 번 잡았습니다

이번 세션의 가장 중요한 기록입니다.

| 게이트 | 잡은 것 |
| --- | --- |
| 6 (worker_done 진실성) | AM4 워커가 전량 테스트를 4,006건인데 1,793건으로 보고 |
| 6 | **코디네이터가 리뷰 끝난 브랜치에 커밋을 올려** 보고와 실제가 어긋남 |
| 5 (리뷰 보고) | 리뷰어의 `answer` 극성 오류. 근거는 맞는데 라벨이 뒤집힘 |

### 7.1 코디네이터가 검증 대상 브랜치에 커밋하지 마십시오

AN1 에서 리뷰가 끝난 뒤 코디네이터가 `choices` 제한 커밋을 그 브랜치에 올렸습니다.
테스트가 1건 늘어 게이트 6이 건수 불일치로 실패했습니다. **더 중요한 것은 그 커밋을
아무도 리뷰하지 않았다는 사실**이며, 게이트가 없었으면 미검증 코드가 워커의 증언
아래 병합될 뻔했습니다.

AM2 에서도 같은 짓을 했는데 그때는 테스트 수가 안 바뀌어 드러나지 않았습니다.

해소는 `git reset --hard` 로 리뷰된 상태로 되돌리고 그 변경을 AN3 로 분리해 정상
절차(워커 + 리뷰어 + 게이트)를 거치는 방식으로 했습니다. **다음 코디네이터도 같은
유혹을 받을 것입니다. 작아 보여도 별도 Task 로 내십시오.**

### 7.2 리뷰어가 두 번 연속 형식에서 실패했습니다

| 시도 | 실패 |
| --- | --- |
| 1차 | `answer` 를 결함 유무 판정으로 적음. `defect_when: no` 항목에 근거는 "덮어쓴다"고 쓰고 `answer` 는 `no` |
| 2차 | `checklist_results` 대신 `findings` 형식, `verdict` 를 계약에 없는 `conditional_pass`, 지정 경로가 아닌 `.orca/review_done.json` 에 저장 |

2차는 형식이 틀렸으나 **내용은 옳았습니다.** 코디네이터가 Level 3 에서 지적했던
명시 런처 경로의 fail-closed 누락을 결함으로 확정했고, 그 지적대로 AN2 재작업에서
닫았습니다. 재현으로 확인했습니다.

```
resolve_launcher_and_cli(model='unknown-model-xyz',
                         explicit_launcher='scripts/custom_launcher.py')
수정 전 -> ('scripts/custom_launcher.py', 'antigravity')
수정 후 -> ValueError: cli_type을 자동 판정할 수 없습니다. --agent 로 명시하십시오
```

3차 리뷰 Capsule 에 두 실패를 예시로 넣어 방지 조항을 못박았고 통과했습니다.

---

## 8. 워커 경향 세 가지와 Capsule 방지 조항

같은 모델(`gemini-3.8-flash-medium`) 워커에게서 반복 관측했습니다.

| 경향 | 사례 |
| --- | --- |
| 요구하지 않은 API 표면 추가 | AM2 의 죽은 별칭과 `**kwargs` 우회, AM3 의 서브커맨드 별칭 2개와 위치 인자 |
| 테스트 건수 오보 | AM4 가 4,006건을 1,793건으로 |
| `worker_done` 중복 전송 | AM4 가 두 번 보내 코디네이터의 게이트 실행이 무효화 |

AM4 이후 Capsule `ground_truth` 에 세 조항을 표준으로 넣었고 **그 뒤로는 재발하지
않았습니다.** 다음 Capsule 에도 그대로 쓰십시오. 문구는
`.orca/intents/run_a6eec92b5e01/an3_permission_mode_choices.yaml` 에 있습니다.

---

## 9. rework 함정을 미리 제거하십시오

`orca_taskctl.py rework` 는 `.orca/capsules/<원래 task_id>_rework/capsule.yaml`
이라는 유사 이름 Capsule 을 만들고 그것을 `allowed_read_files` **첫 줄**에 넣습니다.
이 저장소에는 워커가 그 경로로 이탈해 옛 `task_id` 까지 베낀 전례가 있습니다.

이번에는 rework 세 건 모두 투입 전에 주 저장소와 워크트리 양쪽에서 그 디렉터리를
삭제하고 목록에서도 뺐습니다. **이탈이 한 건도 없었습니다.**

---

## 10. 자동 승인 화이트리스트 밖 명령의 실제 비용

조사 워커 하나에 사람 개입이 세 번 필요했습니다. 막힌 형태는 다음과 같습니다.

| 명령 | 판정 |
| --- | --- |
| `pgrep -fl '...'` | `hold` (안전목록 밖) |
| `ORCA_TERMINAL_HANDLE=... uv run pytest ...` | `hold` (환경변수 접두) |
| `grok --help`, `grok models` | `hold` |
| `git add`, `git commit` | `hold` |
| `orca orchestration send --type worker_done` | `hold` |

읽기 전용인 `pgrep` 은 대화 한정 허용, 좁게 지정된 `pkill -f 'setup-permissions
term_PROBE_AM1'` 은 1회만 승인했습니다. **Capsule 에 명령 형태를 못박을 때는 그것이
자동 승인 대상인지 먼저 확인하십시오.** AM1 이 `pgrep` 앞에서 멈춘 것은 코디네이터가
그 확인 없이 형태를 지정했기 때문입니다.

---

## 11. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **최우선** | 금액 집계 전환 효과 실측 (0장) | 없음. Docker 점유 |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 원격 워커 경로가 열려 있다 |
| **R-10 2단계** | Prometheus 추가 | 메트릭 계측 선행 |
| 자동 승인 화이트리스트 | 9장의 다섯 형태를 열지 여부 판단 | 사용자 결정 |
| `opencode`/`grok` 권한 중간 단계 | `acceptEdits` 상당 옵션 존재 여부 조사 | 조사 선행 |
| 비런처 경로 `detected_cli` | `orca_taskctl.py` 5229행 부근이 gemini/grok 만 검사 | 하위 판정이 fail-closed 라 안전 문제 아님 |
| 선행 AK 8.6.3 | `schedule_permission_setup` 이 코디네이터 핸들을 거부하게 만들기 | 워커도 자기 핸들을 상속받으므로 구분 방법 선행 |
| **문서 역사층 분리** | `task_*.md` 269개와 handoff 96개를 annotated tag + SHA256 manifest 로 퇴역시켜 674 -> 250 이하 | Wave AO1(생성 차단) 병합 후. 경로 문자열 참조가 `docs/` 밖 71개 파일에 있어 일괄 갱신 필요 |

**컷오버를 막는 것은 여전히 R-12 하나입니다.** 다만 R-12 는 장비 부재로 착수할 수 없으므로 다음 세션의 첫 작업은 0장입니다.

---

## 12. 문서 증가 문제와 채택한 대응

2026-09-04 GPT 제안서(`refac_bid_box_문서_축소_및_에이전트_검색_방안`)를 검토하고
수치를 재실측했습니다. **진단은 정확하며 문제는 그 사이 더 나빠졌습니다.**

| 지표 | 제안서(09-04) | 재실측(09-08) |
| --- | ---: | ---: |
| 전체 Markdown | 536 | **674** (+26%) |
| `docs/analysis/task_*.md` | 200 | **269** |
| handoff 포함 | 84 | **97** |

**이번 세션 하나가 `task_*.md` 8개를 새로 만들었습니다.** 근원은
`scripts/orca_taskctl.py:1096` 과 `:1169` 로, Capsule 확장기가 Task 마다
`docs/analysis/<task_id>.md` 를 쓰기 범위와 artifact_paths 에 **기계적으로
강제**합니다. 같은 사실이 Capsule, `worker_done.json`, 그 문서, handoff, commit
다섯 곳에 중복됩니다.

**제안서에서 채택하지 않은 것 세 가지입니다.**

| 제안 | 판정 |
| --- | --- |
| 최종 목표 40개 | **기각.** 부트스트랩은 `AGENTS.md` 8,930자 + `CURRENT_STATE.md` 6,676자로 이미 작고 워커는 `allowed_read_files` 만 읽습니다. `validate_doc_links.py` 도 672개를 0.26초에 처리합니다. 674->40 은 실제 병목이 아닌 지표를 최적화하며, 그러려면 제안서 스스로 경계한 "한 문서 한 주제" 를 깨야 합니다. **250 이하는 근거가 있고 40 은 없습니다** |
| live handoff 최종 0개 | **기각.** 이 세션은 전적으로 이전 handoff 0장으로 구동됐습니다. 진단·재현 명령·조사한 것과 안 한 것의 구분은 fact 한 줄로 압축되지 않습니다. **1건 유지가 최종 목표입니다** |
| 완전 동일 7쌍 정리 | **부분 채택.** 저장소 전체로는 21쌍이지만 그중 12쌍은 `.agents`/`.claude`/`.opencode` 의 **의도된 SKILL.md 미러**이며 `validate_agent_rules.py:443` 의 `check_skills_mirror` 가 동일성을 통과 조건으로 검사합니다. 지우면 규칙 검증이 깨집니다. `docs/` 내부 실제 중복 **9쌍**만 대상입니다 |

**문서 과다의 실제 피해는 문맥 비용이 아니라 최신성 drift 입니다.** 이 세션에서
실증됐습니다. `CURRENT_STATE.md` 6.1 이 "금액 집계: 불일치 343건의 정체 확인이
남았습니다" 로 나흘째 멈춰 있었는데, 그 조사는 2026-09-04 에 끝났고 코드도 이미
전환(`30aba4e`)된 상태였습니다. 0장의 최우선 작업이 여기서 나왔습니다.

**채택한 실행안은 3단계 중 A 즉시 + B 백로그입니다.**

| 단계 | 내용 | 판정 |
| --- | --- | --- |
| A | Task 문서 자동 생성 중단 + 신규 생성 차단 게이트 + `docs/` 중복 9쌍 정리 | **완료** (`a32f364`, `8e722f5`) |
| B | tag + manifest 역사층 분리, 674 -> 250 이하 | 백로그 (11장) |
| C | `architecture`/`runbooks`/`domains` 재편, 40개 목표 | **기각** |

**A 를 먼저 하지 않으면 B 를 해도 4일이면 되돌아옵니다.**

---

## 13. 코디네이터 교대와 catchup 병합 (2026-09-08 오후)

Claude 5시간 한도로 Grok 4.6 에 인계했다가 다시 인수했습니다. 그 사이 Grok 이
Wave AO 를 닫고 대시보드 실측과 catchup 을 진행했습니다.

### 13.1 인계 절차에서 배운 것

| 항목 | 내용 |
| --- | --- |
| Run 바인딩 | `orca orchestration run-use --id <run>` 로 `coordinator_handle` 을 넘긴다. 넘기지 않으면 배달이 새 코디네이터에게 오지 않는다 |
| 배달 fencing | 구 코디네이터 세대의 `deliveryId` 는 `fenced consumer generation` 으로 거부된다. 다시 `check` 하면 새 세대 ID 로 재발급되며 내용은 같다 |
| 스킬 영수증 | `taskctl create` 가 구 코디네이터 영수증을 핸들 불일치로 거부한다. `scripts/orca_skill_receipt.py issue` 로 재발급한다 |
| 캐시 접두부 | Run ID 를 `.grok/rules` 에 고정하지 말 것. 교대할 때마다 뒤처진다 |

### 13.2 catchup 병합 (`80d7cb0`)

놓친 02:00 크론 슬롯 판정입니다. 종전에는 경과 24시간 임계치만 봐서 19시간 경과
시점에 `threshold_not_exceeded` 로 거부했습니다.

| 검증 | 결과 |
| --- | --- |
| Level 1 게이트 | 8종 pass, 실패 0. 게이트 3만 `backend_mypy` 미검증으로 skip |
| skip 보완 | 코디네이터가 `uv run mypy src` 직접 실행, 93파일 무결함 |
| Level 2 리뷰 (`qwen3.7-plus`) | verdict pass, blocking 0, 8항목 전부 결함 없음 |
| Level 3 diff | 슬롯 기준 판정, 삭제 줄 0건(쿨다운 보존), 크론·타임존 불변, 수집 미호출 확인 |
| 전량 테스트 | 4,078건 통과 (워커 주장과 일치, 게이트 6 통과) |

**운영에서 발화와 수집을 확인했습니다.** 스택 재기동 시 `reason=missed_schedule`,
`last_cron_slot=2026-09-08T02:00:00`, `elapsed_hours=20.1` 로 따라잡기가 시작됐고
347초 뒤 종료했습니다. 단위 테스트만 있던 상태에서 실경로 증거를 확보했습니다.

| 지표 | 수집 전 | 수집 후 |
| --- | ---: | ---: |
| `bid_announcements` | 5,498,959 | **5,500,771** (+1,812) |
| 최신 `collected_at` | 2026-09-07 12:58:50 | **2026-09-08 09:05:59** |

**다만 파이프라인 전체는 `failed` 로 끝났습니다.** 수집 단계는 커밋됐으나 이어지는
ChromaDB 색인에서 `sqlite3.OperationalError: disk I/O error` 가 났습니다.
스택은 `kb_builder._flush` -> `collection.upsert` ->
chromadb `embeddings_queue.submit_embeddings` -> SQLite commit 입니다.

**원인은 미규명입니다.** 코디네이터가 처음에 디스크 공간 부족으로 진단했으나
**그 진단은 틀렸고 실증으로 반증됐습니다.** 사용자가 "30G 정도 남았는데 공간
부족이 이해가 안 간다" 고 지적했고, 컨테이너 안에서 확인한 결과는 다음과 같습니다.

| 시험 | 결과 |
| --- | --- |
| `/app/chroma_db` 에 신규 SQLite 생성 + 5,000행 커밋 | 성공 (1,089,536바이트) |
| 기존 `chroma.sqlite3` 에 `BEGIN IMMEDIATE` + DDL 커밋 | 성공 |

공간 부족이면 이 둘도 실패했어야 합니다. 또한 SQLite 는 공간 부족일 때
`SQLITE_FULL`(`database or disk is full`)을 내며 이번 것은 `SQLITE_IOERR` 로
**오류 코드가 다릅니다.** `df` 94% 라는 상관을 인과로 단정한 오진이었습니다.

**남은 후보 두 가지이며 어느 쪽인지 단정하지 않습니다.**

1. 동시 접근 충돌. 스택 재기동으로 `chroma_db` 마운트 원본이 `dashboard-latency`
   워크트리에서 주 저장소로 바뀌었고, app 과 worker 두 컨테이너가 같은 SQLite
   파일을 물고 있습니다. macOS virtiofs bind mount 에서 SQLite 잠금이 깨지는 것은
   알려진 유형입니다.
2. 대량 배치 upsert 특유의 실패. 위 시험은 소규모이므로 `_flush` 의 실제 배치
   크기에서만 재현될 수 있습니다.

**코드 결함이 아닙니다.** 따라잡기 판정과 수집은 정상 동작했고 실패는 그 아래
색인 계층입니다. 쿨다운 TTL 약 6시간이 걸려 자동 재시도는 없습니다.

**재현 시도 결과 (2026-09-08)**: worker 컨테이너에서 별도 probe 컬렉션에
100건씩 10회 upsert(총 1,000건)를 돌렸으나 **재현되지 않았습니다.** 단일 writer
소규모 경로는 정상입니다. `INDEX_BATCH_SIZE` 는 100 이라 대량 배치 가설도 약합니다.

관측된 사실 하나가 남습니다. **app 컨테이너가 `chroma.sqlite3` 를 fd 7개로 열고
있고 worker 는 1개입니다.** 두 컨테이너가 같은 SQLite 파일을 bind mount 로 공유하며
macOS virtiofs 에서 SQLite 잠금이 깨지는 것은 알려진 유형입니다. 다만 probe 가
그 조건에서도 성공했으므로 이것만으로 단정할 수 없습니다.

**원인은 여전히 미규명입니다.** 재현하려면 실제 임베딩(bge-m3, 1024차원)과 실제
문서량으로 `kb_builder` 경로를 돌려야 합니다. probe 는 Chroma 기본 MiniLM 을 썼고
데이터량도 실제와 다릅니다.

**금지**: 디스크 정리 같은 조치를 하지 마십시오. 근거 없는 조치이며 원인이 아닙니다.

**G1 확인**: 조사 중 `bidding_kb` 536,002건 무결, probe 컬렉션 잔존 0건입니다.

### 13.3 코디네이터 실수 하나

**워크트리를 제거하기 전에 Docker 마운트 원본인지 확인하지 않았습니다.**
`dashboard-latency` 워크트리를 `git worktree list` 와 `orca worktree list` 만 보고
"터미널 0개, 미병합 브랜치뿐" 으로 판단해 제거했는데, 실행 중인 Compose 스택이 그
경로를 `/app/src` 등 4곳의 bind mount 원본으로 물고 있었습니다. 제거 순간 컨테이너
소스가 사라져 스택이 깨졌습니다.

**데이터 피해는 없었습니다.** DB 5,498,959행 정상, 데이터 볼륨 3종 보존, 브랜치
커밋 2건은 제거 전 `git push` 로 원격 백업해 두었고 Orca 도 `preservedBranch` 로
로컬에 남겼습니다.

복구는 스택을 주 저장소 기준으로 재기동해 마쳤고, 그 과정이 곧 catchup 의 운영
검증이 됐습니다. 재발 방지 항목을 `docs/ops/coordinator_operational_memory.md` 4장에
넣었습니다.

### 13.4 남은 것

- 대시보드 실측 브랜치 `kwanbum217/dashboard-latency` @ `2f43b3c` 는 리뷰 fail 로 **미병합**입니다. 원격에 백업돼 있고 워크트리 카드는 회수했습니다. 보고서 4.2절의 compare-stats 수치가 산출물 JSON 에 없다는 것이 반려 사유입니다
- 대시보드 실측은 `get_dashboard_stats`(BidResult, Redis 캐시) 를 잰 것이라 `_announcement_amount_expr` 경로가 아닙니다. 전환 전 31.97초와 같은 경로로 비교한 결론은 기각됐습니다. **금액 집계 실측은 `get_compare_stats_data` 로 다시 해야 합니다**

---

## 14. 정리 상태

**모든 자원을 회수했습니다.** 빌더 8대와 리뷰어 6대 전부 `worker_done` ack 직후
`orca_taskctl.py release-worker` 로 회수했고, 그 명령이 `worker-release` 와
감시기 중지를 함께 수행했습니다. 창은 `orca terminal close --terminal` 로 닫았습니다
(`--tab` 미사용).

워크트리 8개(`wave-am1`~`wave-am5`, `wave-am5-survey`, `wave-an1`~`wave-an3`)를
`main` 병합 확인 후 제거했고 브랜치도 `git branch -d` 로 삭제했습니다(`-D` 미사용).
`orca_settled_session_audit.py` 잔류 없음, `pgrep -f orca_auto_approve` 0건,
`pgrep -f setup-permissions` 0건입니다.

남은 터미널은 코디네이터와 사용자의 grok 창 둘뿐입니다. **Docker 는 이 세션에서
기동하지 않았습니다.**
