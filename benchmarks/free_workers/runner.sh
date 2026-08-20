#!/bin/zsh
REPO=/Users/kwanbum/Documents/korea_IT/lanhchain_ai_vision/refac_bid_box
W=/Users/kwanbum/orca/workspaces/refac_bid_box
SP=/private/tmp/claude-501/-Users-kwanbum-Documents-korea-IT-lanhchain-ai-vision-refac-bid-box/1bfa3543-376e-4f9c-8bdb-faabda368e81/scratchpad/bakeoff
KIMI=/Users/kwanbum/.kimi-code/bin/kimi
cd "$REPO"

ACTIVE=(laguna_s north_mini mimo)
LAGUNA_S_DEADLINE=$(( $(date +%s) + 600 ))   # 지금부터 10분 더 주고 종료

launch() {
  local m=$1 tid=$2 model=$3
  local pre
  pre=$(orca orchestration dispatch --task "$tid" --to "worker_bakeoff_$m" --return-preamble --json 2>&1 \
        | uv run python -c "import json,sys; print(json.load(sys.stdin)['result']['preamble'])")
  print -r -- "$pre" > "$SP/$m.preamble"
  (
    t0=$(date +%s)
    if [[ "$model" == or-free/* ]]; then
      ( cd "$W/bakeoff-$m" && KIMI_CODE_HOME=/Users/kwanbum/.kimi-openrouter-bakeoff \
          "$KIMI" -m "$model" -p "$(cat "$SP/$m.preamble")" ) > "$SP/$m.log" 2>&1
    else
      opencode run --dir "$W/bakeoff-$m" -m "$model" "$(cat "$SP/$m.preamble")" > "$SP/$m.log" 2>&1
    fi
    echo "$? $(( $(date +%s) - t0 ))" > "$SP/$m.exit"
  ) &
  echo "[투입] $m ($model)"
}

while :; do
  # laguna_s 시한 초과 통지. 종료는 코디네이터가 직접 합니다.
  # 이름으로 죽이면 같은 kimi-code 인 north_mini 까지 죽으므로 여기서 kill 하지 않습니다.
  if [[ ! -f "$SP/laguna_s.exit" && ! -f "$SP/laguna_s.overdue" ]] \
     && (( $(date +%s) > LAGUNA_S_DEADLINE )); then
    touch "$SP/laguna_s.overdue"
    echo "[시한초과] laguna_s  슬롯 점유 중. 코디네이터 종료 판단 필요"
  fi

  running=0
  for m in $ACTIVE; do [[ -f "$SP/$m.exit" ]] || (( running++ )); done

  while (( running < 3 )); do
    line=$(head -1 "$SP/queue.tsv" 2>/dev/null)
    [[ -z "$line" ]] && break
    tail -n +2 "$SP/queue.tsv" > "$SP/queue.tmp" && mv "$SP/queue.tmp" "$SP/queue.tsv"
    m=$(echo "$line" | cut -f1); tid=$(echo "$line" | cut -f2); model=$(echo "$line" | cut -f3)
    launch "$m" "$tid" "$model"
    ACTIVE+=("$m"); (( running++ ))
  done

  # 전원 종료 + 대기열 소진이면 끝
  if [[ ! -s "$SP/queue.tsv" ]]; then
    alldone=1
    for m in $ACTIVE; do [[ -f "$SP/$m.exit" ]] || alldone=0; done
    if (( alldone )); then
      echo "[전원 완료] ${ACTIVE}"
      break
    fi
  fi
  sleep 45
done
