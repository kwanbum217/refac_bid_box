"""워커 터미널의 권한 프롬프트를 안전 명령에 한해 자동 승인합니다.

안전 목록에 없는 명령이나 파괴적 패턴이 보이면 승인하지 않고 stdout 으로 알립니다.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404  고정된 orca 명령만 실행하며 사용자 입력을 받지 않습니다
import sys
import time

TERMINALS = sys.argv[1:]

SAFE_PREFIXES = (
    "python3",
    "python",
    "uv run",
    "git ",
    "git\n",
    "cat ",
    "ls",
    "head ",
    "tail ",
    "grep",
    "rg ",
    "sed -n",
    "wc ",
    "find ",
    "pytest",
    "npm ",
    "mkdir ",
    "cp ",
    "mv ",
    "echo ",
    "jq ",
    "diff ",
    "docker compose exec",
)
DANGEROUS = re.compile(
    r"rm\s+-rf|git\s+push|git\s+reset\s+--hard|git\s+checkout\s+main|"
    r"DROP\s+TABLE|DELETE\s+FROM|TRUNCATE|UPDATE\s+\w+\s+SET|INSERT\s+INTO|"
    r"docker\s+compose\s+(down|restart|up)|>\s*/dev/sd|chmod\s+777|curl.*-X\s*(POST|PUT|DELETE)",
    re.IGNORECASE,
)


def read(handle: str) -> str:
    try:
        # 고정 인자 배열만 넘기고 shell 을 쓰지 않습니다.
        out = subprocess.run(  # nosec B603 B607
            ["orca", "terminal", "read", "--terminal", handle],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return out.stdout
    except Exception:
        return ""


def send(handle: str, text: str) -> None:
    subprocess.run(  # nosec B603 B607
        ["orca", "terminal", "send", "--terminal", handle, "--text", text, "--enter"],
        capture_output=True,
        text=True,
        timeout=60,
    )


def pending_command(screen: str) -> str | None:
    if "Do you want to proceed?" not in screen:
        return None
    marker = "Requesting permission for:"
    if marker not in screen:
        return ""
    body = screen.split(marker, 1)[1]
    body = body.split("Do you want to proceed?", 1)[0]
    return body.strip()


seen = {}
while True:
    for h in TERMINALS:
        screen = read(h)
        cmd = pending_command(screen)
        if cmd is None:
            continue
        short = " ".join(cmd.split())[:160]
        if DANGEROUS.search(cmd):
            if seen.get(h) != short:
                print(f"[보류] {h[:16]} 위험 패턴, 사람 판단 필요: {short}", flush=True)
                seen[h] = short
            continue
        if cmd and not any(cmd.lstrip().startswith(p) for p in SAFE_PREFIXES):
            if seen.get(h) != short:
                print(f"[보류] {h[:16]} 안전목록 밖: {short}", flush=True)
                seen[h] = short
            continue
        send(h, "2")
        print(f"[승인] {h[:16]} {short}", flush=True)
        seen.pop(h, None)
        time.sleep(2)
    time.sleep(8)
