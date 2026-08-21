#!/bin/zsh
# 2차 경합 러너. 시한 초과 워커를 실제로 종료한 뒤에만 다음 회차를 시작합니다.
#
# 1차 실행(2026-08-20)에서 시한 초과를 기록만 하고 프로세스를 죽이지 않아
# 잔류 워커가 다음 회차의 워크트리에 커밋했습니다. oc_nemo3ultra 결과가
# 그렇게 오염됐습니다. 종료 확인 전에는 워크트리를 재사용하지 않습니다.
set -u

REPO=${BENCH_REPO:-$(git rev-parse --show-toplevel)}
W=${BENCH_WORKSPACES:?BENCH_WORKSPACES 에 워크트리 상위 경로를 지정하십시오}
SP=${BENCH_OUT:?BENCH_OUT 에 결과 디렉터리를 지정하십시오}
KIMI=${KIMI_BIN:-kimi}
BASE=${BENCH_BASE_REF:-bench/free-worker-bakeoff-2}
CAPSULE="$REPO/benchmarks/free_workers/builder_02/capsule.yaml"
SCORER="$REPO/benchmarks/free_workers/builder_02/scoring_02.py"
CONC=${BENCH_CONCURRENCY:-3}
# 종료 확인에 허용하는 최대 대기 시간입니다. 넘기면 그 스택을 봉인합니다.
KILL_CONFIRM_SEC=${BENCH_KILL_CONFIRM_SEC:-60}

# 측정 대상 스택입니다. 일부만 다시 재려면 BENCH_STACKS 로 좁힙니다. 이때도
# 경합 조건을 바꾸지 않도록 원래와 같은 수의 스택을 동시에 돌려야 합니다.
STACKS=(${=BENCH_STACKS:-oc_nemo3ultra laguna_xs deepseek or_nemoultra mimo})
typeset -A MODEL
typeset -A POOL
MODEL[oc_nemo3ultra]="opencode/nemotron-3-ultra-free"
MODEL[laguna_xs]="or-free/laguna-xs"
MODEL[deepseek]="opencode/deepseek-v4-flash-free"
MODEL[or_nemoultra]="or-free/nemotron-ultra"
MODEL[mimo]="opencode/mimo-v2.5-free"
POOL[oc_nemo3ultra]="opencode-nemotron3-ultra"
POOL[laguna_xs]="or-free-laguna-xs"
POOL[deepseek]="opencode-deepseek"
POOL[or_nemoultra]="or-free-nemotron-ultra"
POOL[mimo]="opencode-mimo"

PROMPT='TASK: scripts/audit_model_inventory.py 에 --json 출력 옵션을 추가한다. 계약 정본은 이 워크트리의 benchmarks/free_workers/builder_02/capsule.yaml 이다. 그 파일을 먼저 읽고 required_change 와 acceptance 를 그대로 따르라. 다른 문서를 읽지 마라. 작업이 끝나면 uv run pytest tests/test_audit_model_inventory.py -q 로 검증하고 이 브랜치에 커밋하라. 커밋까지 마치면 종료하라.'

# ---------------------------------------------------------------------------
# Capsule 이 벤치마크 사전 등록값의 정본입니다. 러너에 값을 따로 두면 어긋납니다.
# ---------------------------------------------------------------------------
read_capsule_value() {
  uv run python - "$CAPSULE" "$1" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as fh:
    doc = yaml.safe_load(fh)
value = (doc.get("benchmark") or {}).get(sys.argv[2])
if value is None:
    sys.exit(1)
print(value)
PY
}

# ---------------------------------------------------------------------------
# preflight. 없는 것을 만들거나, 만들 수 없으면 시작하지 않고 종료합니다.
# ---------------------------------------------------------------------------
preflight() {
  local failed=0

  for bin in orca opencode uv git; do
    if ! command -v "$bin" >/dev/null 2>&1; then
      echo "[preflight 실패] $bin 를 찾을 수 없습니다"
      failed=1
    fi
  done
  if ! command -v "$KIMI" >/dev/null 2>&1; then
    echo "[preflight 실패] Kimi CLI ($KIMI) 를 찾을 수 없습니다. KIMI_BIN 을 확인하십시오"
    failed=1
  fi
  if [[ -z "${KIMI_CODE_HOME:-}" ]]; then
    echo "[preflight 실패] KIMI_CODE_HOME 이 비어 있습니다. 쓰기 권한 프로필 사본 경로가 필요합니다"
    failed=1
  elif [[ ! -d "$KIMI_CODE_HOME" ]]; then
    echo "[preflight 실패] KIMI_CODE_HOME 경로가 없습니다: $KIMI_CODE_HOME"
    failed=1
  fi

  if [[ ! -f "$CAPSULE" ]]; then
    echo "[preflight 실패] Capsule 이 없습니다: $CAPSULE"
    failed=1
  fi
  if [[ ! -f "$SCORER" ]]; then
    echo "[preflight 실패] 채점기가 없습니다: $SCORER"
    failed=1
  # 구문 검사만 하면 "채점기가 fail 과 pass 를 구별하는가" 를 확인하지 못합니다.
  # 채점기가 전원 만점을 주도록 망가져도 통과하므로 실제 self-test 를 돌립니다.
  # PYTHONPATH 가 없으면 후보 모듈의 `from scripts...` 가 깨져 채점 불가가 됩니다.
  elif ! PYTHONPATH="$REPO" uv run python "$SCORER" --self-test >/dev/null 2>&1; then
    echo "[preflight 실패] 채점기 self-test 실패: $SCORER"
    echo "           재현: PYTHONPATH=$REPO uv run python $SCORER --self-test"
    failed=1
  fi

  if ! git -C "$REPO" rev-parse --verify "$BASE" >/dev/null 2>&1; then
    echo "[preflight 실패] base ref 가 없습니다: $BASE"
    failed=1
  fi

  mkdir -p "$SP/logs" "$SP/artifacts" || failed=1

  local s wt
  for s in $STACKS; do
    wt="$W/b2-$s"
    if [[ ! -d "$wt/.git" && ! -f "$wt/.git" ]]; then
      echo "[preflight] 워크트리 생성: $wt"
      if ! git -C "$REPO" worktree add "$wt" -b "b2-$s" "$BASE" >/dev/null 2>&1; then
        echo "[preflight 실패] 워크트리를 만들 수 없습니다: $wt"
        failed=1
      fi
    fi
  done

  return $failed
}

# ---------------------------------------------------------------------------
# 워커 기동. 터미널 핸들을 반드시 보관합니다. 핸들이 없으면 죽일 수 없습니다.
# ---------------------------------------------------------------------------
typeset -A HANDLE
typeset -A START
typeset -A SEALED

launch() {
  local s=$1 rep=$2
  local wt="$W/b2-$s" model="${MODEL[$s]}" tag="${s}_r${rep}"

  git -C "$wt" reset --hard "$BASE" --quiet
  git -C "$wt" clean -fd --quiet -e .env

  local cmd
  if [[ "$model" == or-free/* ]]; then
    cmd="cd '$wt' && KIMI_CODE_HOME=$KIMI_CODE_HOME '$KIMI' -m '$model' -p '$PROMPT'"
  else
    cmd="cd '$wt' && opencode run -m '$model' '$PROMPT'"
  fi
  local full="s=\$SECONDS; { $cmd } 2>&1 | tee '$SP/logs/$tag.log'; echo \"\${pipestatus[1]} \$((SECONDS-s))\" > '$SP/$tag.exit'; echo '[$tag 종료]'"

  local handle
  handle=$(orca terminal create --worktree "path:$wt" --title "b2 $s r$rep" --command "$full" --json 2>/dev/null \
    | uv run python -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    sys.exit(0)
t=(d.get('result') or {}).get('terminal') or {}
print(t.get('handle') or '')")

  if [[ -z "$handle" ]]; then
    # 기동 실패도 하나의 회차입니다. 결과에 남기지 않으면 분모가 줄어 성공률이
    # 실제보다 좋아집니다. 3회 중 1회가 여기서 사라지면 2/2 로 읽힙니다.
    echo "[기동 실패] $tag  터미널 핸들을 받지 못했습니다. 실패 회차로 기록합니다"
    echo "125 0" > "$SP/$tag.exit"
    return 1
  fi
  HANDLE[$tag]=$handle
  echo "[투입] $tag  $model  handle=$handle"
  return 0
}

# ---------------------------------------------------------------------------
# 시한 초과 워커 종료. 이 함수가 0 을 돌려주기 전에는 워크트리를 재사용하지
# 않습니다. pkill 은 쓰지 않습니다. 다른 스택까지 죽습니다.
# ---------------------------------------------------------------------------
terminate_worker() {
  local tag=$1
  local handle=${HANDLE[$tag]:-}
  if [[ -z "$handle" ]]; then
    echo "[종료불가] $tag  보관된 핸들이 없습니다"
    return 1
  fi

  orca terminal close --terminal "$handle" --json >/dev/null 2>&1

  local waited=0 alive
  while (( waited < KILL_CONFIRM_SEC )); do
    alive=$(orca terminal show --terminal "$handle" --json 2>/dev/null \
      | uv run python -c "
import json,sys
try:
    d=json.load(sys.stdin)
except Exception:
    print('unknown'); raise SystemExit
t=(d.get('result') or {}).get('terminal') or {}
print('yes' if t.get('connected') else 'no')")
    if [[ "$alive" == "no" ]]; then
      echo "[종료확인] $tag  handle=$handle"
      unset "HANDLE[$tag]"
      return 0
    fi
    sleep 3
    waited=$((waited + 3))
  done

  echo "[종료실패] $tag  ${KILL_CONFIRM_SEC}초 안에 종료를 확인하지 못했습니다"
  return 1
}

collect() {
  local s=$1 rep=$2 tag="${s}_r${rep}" wt="$W/b2-$s"
  cp "$wt/scripts/audit_model_inventory.py" "$SP/artifacts/$tag.py" 2>/dev/null
  local commits=$(git -C "$wt" log --oneline "$BASE"..HEAD 2>/dev/null | wc -l | tr -d ' ')
  local exit_line=$(cat "$SP/$tag.exit" 2>/dev/null || echo "124 $TIMEOUT")
  local code=${exit_line%% *} elapsed=${exit_line##* }
  local status="failed" failure="exit_$code"
  if [[ "$code" == "0" && "$commits" -gt 0 ]]; then
    status="succeeded"
    failure=""
  elif [[ "$code" == "124" ]]; then
    failure="timeout"
  elif [[ "$code" == "125" ]]; then
    failure="launch_failed"
  elif [[ "$code" == "0" ]]; then
    failure="no_commit"
  fi

  echo "$tag\t$exit_line\t$commits" >> "$SP/results.tsv"
  local observation_id="$(basename "$SP"):$tag"
  local record_args=(--pool "${POOL[$s]}" --role builder --status "$status" --elapsed-sec "$elapsed" --observation-id "$observation_id")
  [[ -n "$failure" ]] && record_args+=(--failure "$failure")
  uv run python "$REPO/scripts/orca_model_router.py" reliability-record $record_args >/dev/null
  echo "[수집] $tag  커밋=$commits  $exit_line"
}

# ---------------------------------------------------------------------------
if ! preflight; then
  echo "[중단] preflight 실패. 벤치마크를 시작하지 않습니다"
  exit 2
fi

TIMEOUT=$(read_capsule_value timeout_sec) || {
  echo "[중단] Capsule 에서 benchmark.timeout_sec 을 읽지 못했습니다"; exit 2; }
REPS=$(read_capsule_value repetitions_per_stack) || {
  echo "[중단] Capsule 에서 benchmark.repetitions_per_stack 을 읽지 못했습니다"; exit 2; }
echo "[사전등록] timeout=${TIMEOUT}s  repetitions=${REPS}  concurrency=${CONC}"

QUEUE=()
for rep in {1..$REPS}; do for s in $STACKS; do QUEUE+=("$s:$rep"); done; done

RUNNING=()
: > "$SP/results.tsv"

while (( ${#QUEUE} > 0 || ${#RUNNING} > 0 )); do
  for item in $RUNNING; do
    s=${item%%:*}; rep=${item##*:}; tag="${s}_r${rep}"
    if [[ -f "$SP/$tag.exit" ]]; then
      # 정상 종료. 프로세스가 스스로 끝났으므로 핸들만 정리합니다.
      [[ -n "${HANDLE[$tag]:-}" ]] && unset "HANDLE[$tag]"
      collect "$s" "$rep"
      RUNNING=("${(@)RUNNING:#$item}")
    elif (( $(date +%s) - START[$tag] > TIMEOUT )); then
      echo "[시한초과] $tag  종료를 시도합니다"
      if terminate_worker "$tag"; then
        echo "124 $TIMEOUT" > "$SP/$tag.exit"
        collect "$s" "$rep"
        RUNNING=("${(@)RUNNING:#$item}")
      else
        # 종료를 확인하지 못했습니다. 잔류 프로세스가 워크트리에 쓸 수 있으므로
        # 이 스택의 남은 회차를 전부 버립니다. 오염된 값을 만드는 것보다 낫습니다.
        echo "[봉인] $s  종료 미확인이라 이 스택의 남은 회차를 실행하지 않습니다"
        SEALED[$s]=1
        echo "124 $TIMEOUT" > "$SP/$tag.exit"
        collect "$s" "$rep"
        RUNNING=("${(@)RUNNING:#$item}")
        QUEUE=("${(@)QUEUE:#${s}:*}")
      fi
    fi
  done

  while (( ${#RUNNING} < CONC && ${#QUEUE} > 0 )); do
    picked=""
    for i in {1..${#QUEUE}}; do
      cand=${QUEUE[$i]}; cs=${cand%%:*}
      [[ -n "${SEALED[$cs]:-}" ]] && continue
      busy=0
      for r in $RUNNING; do [[ "${r%%:*}" == "$cs" ]] && busy=1; done
      (( busy )) || { picked=$cand; QUEUE=("${(@)QUEUE[1,i-1]}" "${(@)QUEUE[i+1,-1]}"); break; }
    done
    [[ -z "$picked" ]] && break
    ps=${picked%%:*}; pr=${picked##*:}
    if launch "$ps" "$pr"; then
      START[${ps}_r${pr}]=$(date +%s)
      RUNNING+=("$picked")
    else
      # QUEUE 에서 이미 뺐으므로 여기서 수집하지 않으면 회차가 조용히 사라집니다.
      collect "$ps" "$pr"
    fi
  done
  sleep 20
done

echo "[전원 완료] $(wc -l < "$SP/results.tsv") 회"
if (( ${#SEALED} > 0 )); then
  echo "[경고] 봉인된 스택: ${(k)SEALED}. 이 스택의 결과는 회차 수가 부족합니다"
fi
