#!/bin/zsh
REPO=${BENCH_REPO:-$(git rev-parse --show-toplevel)}
W=${BENCH_WORKSPACES:?BENCH_WORKSPACES 에 워크트리 상위 경로를 지정하십시오}
SP=${BENCH_OUT:?BENCH_OUT 에 결과 디렉터리를 지정하십시오}
KIMI=${KIMI_BIN:-kimi}
BASE=bench/free-worker-bakeoff-2
TIMEOUT=720          # capsule.yaml 에 사전 등록한 값
CONC=3
cd "$REPO"

# 스택 정의: 이름 / 모델 / 하네스
STACKS=(oc_nemo3ultra laguna_xs deepseek or_nemoultra mimo)
typeset -A MODEL
MODEL[oc_nemo3ultra]="opencode/nemotron-3-ultra-free"
MODEL[laguna_xs]="or-free/laguna-xs"
MODEL[deepseek]="opencode/deepseek-v4-flash-free"
MODEL[or_nemoultra]="or-free/nemotron-ultra"
MODEL[mimo]="opencode/mimo-v2.5-free"

PROMPT='TASK: scripts/audit_model_inventory.py 에 --json 출력 옵션을 추가한다. 계약 정본은 이 워크트리의 benchmarks/free_workers/builder_02/capsule.yaml 이다. 그 파일을 먼저 읽고 required_change 와 acceptance 를 그대로 따르라. 다른 문서를 읽지 마라. 작업이 끝나면 uv run pytest tests/test_audit_model_inventory.py -q 로 검증하고 이 브랜치에 커밋하라. 커밋까지 마치면 종료하라.'

launch() {
  local s=$1 rep=$2
  local wt="$W/b2-$s" model="${MODEL[$s]}" tag="${s}_r${rep}"
  # 회차마다 깨끗한 상태에서 시작합니다.
  git -C "$wt" reset --hard "$BASE" --quiet
  git -C "$wt" clean -fd --quiet -e .env
  local cmd
  if [[ "$model" == or-free/* ]]; then
    cmd="cd '$wt' && KIMI_CODE_HOME=${KIMI_CODE_HOME:?쓰기 권한 프로필 경로를 지정하십시오} '$KIMI' -m '$model' -p '$PROMPT'"
  else
    cmd="cd '$wt' && opencode run -m '$model' '$PROMPT'"
  fi
  # 창에 보이게 띄우고, 종료 코드와 소요 시간을 파일로 남깁니다.
  local full="s=\$SECONDS; { $cmd } 2>&1 | tee '$SP/logs/$tag.log'; echo \"\${pipestatus[1]} \$((SECONDS-s))\" > '$SP/$tag.exit'; echo '[$tag 종료]'"
  orca terminal create --worktree "path:$wt" --title "b2 $s r$rep" --command "$full" --json >/dev/null 2>&1
  echo "[투입] $tag  $model"
}

collect() {
  local s=$1 rep=$2 tag="${s}_r${rep}" wt="$W/b2-$s"
  cp "$wt/scripts/audit_model_inventory.py" "$SP/artifacts/$tag.py" 2>/dev/null
  local commits=$(git -C "$wt" log --oneline "$BASE"..HEAD 2>/dev/null | wc -l | tr -d ' ')
  echo "$tag\t$(cat "$SP/$tag.exit" 2>/dev/null || echo '124 timeout')\t$commits" >> "$SP/results.tsv"
  echo "[수집] $tag  커밋=$commits  $(cat "$SP/$tag.exit" 2>/dev/null)"
}

# 라운드로빈: rep 바깥, stack 안쪽
QUEUE=()
for rep in 1 2 3; do for s in $STACKS; do QUEUE+=("$s:$rep"); done; done

typeset -A START
RUNNING=()
: > "$SP/results.tsv"

while (( ${#QUEUE} > 0 || ${#RUNNING} > 0 )); do
  # 완료 회수
  for item in $RUNNING; do
    s=${item%%:*}; rep=${item##*:}; tag="${s}_r${rep}"
    if [[ -f "$SP/$tag.exit" ]]; then
      collect "$s" "$rep"
      RUNNING=("${(@)RUNNING:#$item}")
    elif (( $(date +%s) - START[$tag] > TIMEOUT )); then
      echo "124 $TIMEOUT" > "$SP/$tag.exit"
      echo "[시한초과] $tag"
      collect "$s" "$rep"
      RUNNING=("${(@)RUNNING:#$item}")
    fi
  done
  # 빈 슬롯 채우기. 같은 스택이 돌고 있으면 건너뜁니다(워크트리 충돌 방지).
  while (( ${#RUNNING} < CONC && ${#QUEUE} > 0 )); do
    picked=""
    for i in {1..${#QUEUE}}; do
      cand=${QUEUE[$i]}; cs=${cand%%:*}
      busy=0
      for r in $RUNNING; do [[ "${r%%:*}" == "$cs" ]] && busy=1; done
      (( busy )) || { picked=$cand; QUEUE=("${(@)QUEUE[1,i-1]}" "${(@)QUEUE[i+1,-1]}"); break; }
    done
    [[ -z "$picked" ]] && break
    ps=${picked%%:*}; pr=${picked##*:}
    launch "$ps" "$pr"
    START[${ps}_r${pr}]=$(date +%s)
    RUNNING+=("$picked")
  done
  sleep 20
done
echo "[전원 완료] $(wc -l < "$SP/results.tsv") 회"
