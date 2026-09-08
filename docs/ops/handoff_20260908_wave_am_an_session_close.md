# 인수인계: 20260908 Wave AM/AN 세션 종료

> **작성일**: 2026-09-08
> **Run**: `run_a6eec92b5e01`
> **기준 커밋**: `7ce7c3b` -> (본 커밋)
> **미병합 브랜치**: 없음
> **인수 대상**: 다음 코디네이터
> **선행 문서**: [`handoff_20260907_wave_ak_session_close.md`](handoff_20260907_wave_ak_session_close.md)

---

## 0. 한 줄 요약

**선행 인수인계 0장이 지정한 최우선 작업(테스트 부작용 제거)을 닫았고, 그 조사 중에
드러난 워커 런처 계열의 구조적 결함까지 8건을 병합했습니다.** 사용하시는 CLI 7종 중
6종이 이제 `dispatch --launcher` 정규 경로에 올라 있습니다.

---

## 1. 닫은 항목

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

빌더는 전부 Antigravity `gemini-3.8-flash-medium`, 리뷰어는 Qwen Code `qwen3.7-plus`
입니다. Level 1 게이트는 8건 모두 9종 전량 통과, 리뷰 판정은 전부 `pass` 입니다.

---

## 2. 최우선 항목이 실제로 무엇을 막았는지

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

## 3. 감시기 자기 종료 실패의 원인을 확정했습니다

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

## 4. 런처 결함은 qwen 하나가 아니었습니다

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
[`../../.orca/reports/am5_launcher_gap_survey.md`](../../.orca/reports/am5_launcher_gap_survey.md)
를 먼저 만들어 근거로 삼았습니다. 미확인 0건이며 코디네이터가 근거 표본 4건을
직접 대조했습니다. 단발 모드를 `os.execvpe` 로 띄우면 창이 즉시 닫혀 출력을 잃는다는
지적이 그 보고서에서 나왔고, 세 런처 모두 `subprocess.run` 후 셸로 이어받습니다.

AN2 는 `dispatch` 가 모델에서 런처와 `cli_type` 을 함께 판정하게 했습니다. 종전에는
무엇을 띄우든 `scripts/orca_agy_launch.py` 로 고정이었습니다. 판정 불가 시 조용히
기본값으로 떨어지지 않고 종료 코드 2 로 거부합니다.

---

## 5. 권한 인자를 두 단계로 좁혔습니다

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

## 6. 게이트가 사람이 놓친 것을 세 번 잡았습니다

이번 세션의 가장 중요한 기록입니다.

| 게이트 | 잡은 것 |
| --- | --- |
| 6 (worker_done 진실성) | AM4 워커가 전량 테스트를 4,006건인데 1,793건으로 보고 |
| 6 | **코디네이터가 리뷰 끝난 브랜치에 커밋을 올려** 보고와 실제가 어긋남 |
| 5 (리뷰 보고) | 리뷰어의 `answer` 극성 오류. 근거는 맞는데 라벨이 뒤집힘 |

### 6.1 코디네이터가 검증 대상 브랜치에 커밋하지 마십시오

AN1 에서 리뷰가 끝난 뒤 코디네이터가 `choices` 제한 커밋을 그 브랜치에 올렸습니다.
테스트가 1건 늘어 게이트 6이 건수 불일치로 실패했습니다. **더 중요한 것은 그 커밋을
아무도 리뷰하지 않았다는 사실**이며, 게이트가 없었으면 미검증 코드가 워커의 증언
아래 병합될 뻔했습니다.

AM2 에서도 같은 짓을 했는데 그때는 테스트 수가 안 바뀌어 드러나지 않았습니다.

해소는 `git reset --hard` 로 리뷰된 상태로 되돌리고 그 변경을 AN3 로 분리해 정상
절차(워커 + 리뷰어 + 게이트)를 거치는 방식으로 했습니다. **다음 코디네이터도 같은
유혹을 받을 것입니다. 작아 보여도 별도 Task 로 내십시오.**

### 6.2 리뷰어가 두 번 연속 형식에서 실패했습니다

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

## 7. 워커 경향 세 가지와 Capsule 방지 조항

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

## 8. rework 함정을 미리 제거하십시오

`orca_taskctl.py rework` 는 `.orca/capsules/<원래 task_id>_rework/capsule.yaml`
이라는 유사 이름 Capsule 을 만들고 그것을 `allowed_read_files` **첫 줄**에 넣습니다.
이 저장소에는 워커가 그 경로로 이탈해 옛 `task_id` 까지 베낀 전례가 있습니다.

이번에는 rework 세 건 모두 투입 전에 주 저장소와 워크트리 양쪽에서 그 디렉터리를
삭제하고 목록에서도 뺐습니다. **이탈이 한 건도 없었습니다.**

---

## 9. 자동 승인 화이트리스트 밖 명령의 실제 비용

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

## 10. 남은 항목

| ID | 내용 | 선행 조건 |
| --- | --- | --- |
| **R-12** | G2 Windows Docker Desktop 실기 | Windows 장비. `worker-start --on <saved-environment>` 원격 워커 경로가 열려 있다 |
| **R-10 2단계** | Prometheus 추가 | 메트릭 계측 선행 |
| 자동 승인 화이트리스트 | 9장의 다섯 형태를 열지 여부 판단 | 사용자 결정 |
| `opencode`/`grok` 권한 중간 단계 | `acceptEdits` 상당 옵션 존재 여부 조사 | 조사 선행 |
| 비런처 경로 `detected_cli` | `orca_taskctl.py` 5229행 부근이 gemini/grok 만 검사 | 하위 판정이 fail-closed 라 안전 문제 아님 |
| 선행 AK 8.6.3 | `schedule_permission_setup` 이 코디네이터 핸들을 거부하게 만들기 | 워커도 자기 핸들을 상속받으므로 구분 방법 선행 |

**컷오버를 막는 것은 여전히 R-12 하나입니다.**

---

## 11. 정리 상태

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
