"""OpenCode 워커를 다른 CLI 워커와 같은 방식으로 터미널에 붙이는 런처.

OpenCode CLI 와 그 포크인 Kilo CLI(--binary kilo)를 Orca 워커로 씁니다. 터미널을 런처를 명령으로 지정해 먼저 만들고,
런처는 preamble 파일이 나타날 때까지 기다렸다가 opencode 를 기동합니다.

대화형 모드는 opencode --standalone --prompt [prompt] 로 기동하며 os.execvpe 로
제어권을 넘깁니다. opencode v2.0.32 의 최상위 TUI 에는 --model 과 --agent 가 없으므로
모델은 OPENCODE_CONFIG_CONTENT 환경변수({"model": <provider/model>})로 주입합니다.
같은 환경변수가 이미 있으면 덮어쓰지 않고 거부합니다. --one-shot 을 주면
opencode run --model [provider/model#variant] [message] 단발 실행으로 바뀌며,
subprocess.run 으로 완주시킨 뒤 대화형 셸로 이어받아 터미널 창을 유지합니다.

    orca terminal create --worktree path:<워크트리> --title "<섹션명>" \
      --command "uv run python scripts/orca_opencode_launch.py --model openai/gpt-5.6-turbo"
    orca orchestration dispatch --task <task_id> --to <handle> --return-preamble --json

추론 등급(--variant)은 두 CLI 모두 모르는 값을 오류 없이 무시하므로 허용 값을 여기서
제한합니다. opencode 단발은 run --model 의 모델 ID 뒤에 #variant 를 붙이며 --variant
플래그를 넘기지 않습니다. opencode 대화형은 OPENCODE_CONFIG_CONTENT 의 build 에이전트에
model·variant 를 함께 넣어 고정하며, variant 목록을 확인한 OPENCODE_MODEL_VARIANTS 의
모델에만 허용합니다(2026-11-23 opencode v2.3.2 의 GET /api/model 과 debug agents 로 확인).
그 모델들은 --variant 를 생략하면 OPENCODE_DEFAULT_VARIANT(high)로 기동합니다.
OPENCODE_CONFIG_CONTENT 만으로는 부족합니다. opencode TUI 는 전역 상태 파일
~/.local/state/opencode/model.json 에 모델별로 기억한 variant 를 우선하므로, 런처는
등록 모델 대화형 워커마다 작업 디렉터리 아래 .orca/opencode-state/<식별자>/ 를 만들어
확정 variant 를 담은 opencode/model.json 을 두고 XDG_STATE_HOME 을 그곳으로 돌립니다.
전역 상태와 XDG_DATA_HOME, XDG_CONFIG_HOME 은 건드리지 않습니다.
kilo 는 KILO_CONFIG_CONTENT 로 model·variant 를 고정한 전용 에이전트를 주입하고
--agent 로 선택하며, 단발은 run --variant 로 넘깁니다.
사용자가 왼쪽 워크트리에서 TUI 로 진행을 볼 수 있습니다.

    --binary kilo --model openrouter/stealth/space-bunny-alpha --variant max

--auto 는 호환을 위해 인자만 남아 있고 opencode 에 전달되지 않습니다.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - 코디네이터가 만든 고정 인자 목록으로만 opencode 를 호출합니다
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import orca_worker_launch_common as common  # noqa: E402

PERMISSION_SETUP_FLAG = common.PERMISSION_SETUP_FLAG
DEFAULT_PREAMBLE = common.DEFAULT_PREAMBLE
DEFAULT_SHELL = "/bin/bash"
SUPPORTED_BINARIES = ("opencode", "kilo")
SUPPORTED_VARIANTS = ("low", "medium", "high", "xhigh", "max")
KILO_AGENT_NAME = "orca-worker"
KILO_CONFIG_ENV = "KILO_CONFIG_CONTENT"
OPENCODE_CONFIG_ENV = "OPENCODE_CONFIG_CONTENT"
OPENCODE_BUILD_AGENT = "build"
OPENCODE_STATE_HOME_ENV = "XDG_STATE_HOME"
OPENCODE_STATE_DIRNAME = "opencode"
OPENCODE_MODEL_STATE_FILE = "model.json"
ORCA_WORKER_STATE_DIR = Path(".orca") / "opencode-state"
# 대화형에서 variant 를 고정할 수 있는 모델과 그 모델이 실제로 제공하는 variant 입니다.
# medium 이 없습니다. 목록 밖 값은 opencode 가 조용히 무시하므로 여기서 거부합니다.
OPENCODE_MODEL_VARIANTS: dict[str, tuple[str, ...]] = {
    "opencode-go/deepseek-v4.1-flash": ("low", "high", "max"),
    "opencode-go/glm-5.3-flash": ("low", "high", "max"),
}
OPENCODE_DEFAULT_VARIANT = "high"
# 등록 모델(컨텍스트 100만) 워커에만 넣는 토큰 절약 설정입니다. 비용은 스텝마다 다시
# 읽는 컨텍스트 크기에 비례하므로(2026-11-23 실측 스텝당 캐시 읽기 평균 약 11만)
# 도구 출력 상한을 낮추고 약 20만에서 압축합니다. buffer 는 창 대비 여유 토큰이라
# 창이 작은 모델에 넣으면 매 턴 압축되므로 등록 모델에만 씁니다.
OPENCODE_WORKER_PROFILE: dict[str, object] = {
    "compaction": {"auto": True, "buffer": 800000, "keep": {"tokens": 20000}},
    "tool_output": {"max_lines": 400, "max_bytes": 16384},
    "update": "disable",
    "snapshots": False,
}
# 리뷰어 스텝 상한입니다. 마지막 스텝은 도구 없이 요약을 강제합니다.
OPENCODE_REVIEWER_STEPS = 150
COMMIT_NOTICE = common.COMMIT_NOTICE
REVIEWER_NOTICE = common.REVIEWER_NOTICE

wait_for_preamble = common.wait_for_preamble


def build_command(
    model: str,
    prompt: str,
    *,
    one_shot: bool = False,
    auto: bool = False,
    binary: str = "opencode",
    variant: str | None = None,
) -> list[str]:
    """opencode 기동 명령 배열을 조립합니다.

    opencode v2.0.32 기준입니다. 대화형은 opencode --standalone --prompt [prompt] 이고
    모델은 build_env 가 OPENCODE_CONFIG_CONTENT 로 주입합니다. 최상위 TUI 에는
    --model, --agent, --variant 가 없습니다. 단발은
    opencode run --model [provider/model#variant] [message] 이며 --variant 플래그를
    넘기지 않고 모델 ID 뒤에 #variant 를 붙입니다.

    kilo 경로는 종전과 같습니다. 대화형 등급은 --agent [주입 에이전트] 로 고르고,
    단발 등급은 run --variant 로 넘깁니다.

    auto 인자는 호환을 위해 남겨 두지만 opencode 에 --auto 를 넘기지 않습니다.
    --auto 는 명시 deny 가 아닌 모든 승인 요청을 자동 승인하므로(opencode --help:
    "auto-approve permissions that are not explicitly denied (dangerous!)")
    승인 대화창을 감시기 판정 경로로 되돌립니다. 권한은 opencode.json 의
    permission 블록(deny)이 담당합니다.
    """
    if (
        variant is not None
        and not one_shot
        and binary != "kilo"
        and model not in OPENCODE_MODEL_VARIANTS
    ):
        raise ValueError(
            "opencode 대화형 모드의 --variant 는 OPENCODE_MODEL_VARIANTS 모델에만 쓸 수 있습니다"
        )
    if one_shot:
        model_arg = f"{model}#{variant}" if binary == "opencode" and variant is not None else model
        cmd = [binary, "run", "--model", model_arg]
        if variant is not None and binary != "opencode":
            cmd.extend(["--variant", variant])
        cmd.append(prompt)
        return cmd

    if binary == "opencode":
        cmd = [binary, "--standalone"]
    elif variant is not None:
        cmd = [binary, "--agent", KILO_AGENT_NAME]
    else:
        cmd = [binary, "--model", model]
    cmd.extend(["--prompt", prompt])
    return cmd


def worker_state_key(model: str, variant: str) -> str:
    """모델·등급에서 워커 전용 상태 디렉터리 이름을 만듭니다."""
    raw = f"{model}-{variant}"
    return "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in raw)


def worker_state_home(model: str, variant: str, *, cwd: Path | None = None) -> Path:
    """워커 전용 XDG 상태 디렉터리 경로를 돌려줍니다."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ORCA_WORKER_STATE_DIR / worker_state_key(model, variant)


def pin_variant_state(model: str, variant: str, *, cwd: Path | None = None) -> Path:
    """전역 대신 쓸 상태 디렉터리에 확정 variant 를 담은 opencode/model.json 을 씁니다.

    opencode TUI 는 전역 상태의 모델별 variant 기억값을 우선하므로, 워커 전용
    디렉터리에 확정 등급만 담아 두고 XDG_STATE_HOME 으로 그곳을 가리킵니다.
    """
    state_home = worker_state_home(model, variant, cwd=cwd)
    target = state_home / OPENCODE_STATE_DIRNAME / OPENCODE_MODEL_STATE_FILE
    provider, _, model_id = model.partition("/")
    payload = {
        "recent": [{"providerID": provider, "modelID": model_id}],
        "favorite": [],
        "variant": {model: variant},
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as err:
        raise ValueError(
            f"워커 전용 상태 디렉터리를 만들 수 없습니다: {state_home} ({err})"
        ) from err
    return state_home


def build_env(
    env: dict[str, str],
    model: str,
    *,
    one_shot: bool = False,
    binary: str = "opencode",
    variant: str | None = None,
    role: str = "auto",
    cwd: Path | None = None,
) -> dict[str, str]:
    """기동 환경에 모델 설정을 주입합니다.

    opencode 대화형은 최상위 TUI 에 --model 이 없어 OPENCODE_CONFIG_CONTENT 에
    {"model": <provider/model>} 를 넣습니다. 이미 값이 있으면 덮어쓰지 않고
    거부합니다. 등록 모델이면 확정 variant 를 담은 워커 전용 상태 디렉터리를
    작업 디렉터리 아래에 만들고 XDG_STATE_HOME 을 그곳으로 돌려, TUI 가 전역
    model.json 의 variant 기억값을 쓰지 않게 합니다. kilo 대화형에서 등급을 쓰면
    model·variant 를 고정한 전용 에이전트를 KILO_CONFIG_CONTENT 로 주입합니다.
    단발은 모델이 명령 인자로 나가므로 환경을 바꾸지 않습니다.
    """
    if one_shot:
        return env
    if binary == "kilo":
        if variant is None:
            return env
        if env.get(KILO_CONFIG_ENV):
            raise ValueError(
                f"{KILO_CONFIG_ENV} 가 이미 설정되어 있어 에이전트를 주입할 수 없습니다"
            )
        agent = {"model": model, "variant": variant, "mode": "primary", "description": "Orca 워커"}
        return {**env, KILO_CONFIG_ENV: json.dumps({"agent": {KILO_AGENT_NAME: agent}})}

    if env.get(OPENCODE_CONFIG_ENV):
        raise ValueError(f"{OPENCODE_CONFIG_ENV} 가 이미 설정되어 있어 모델을 주입할 수 없습니다")
    config: dict[str, object] = {"model": model}
    build_agent: dict[str, object] = {}
    if variant is not None:
        build_agent.update({"model": model, "variant": variant})
    if model in OPENCODE_MODEL_VARIANTS:
        config.update(OPENCODE_WORKER_PROFILE)
        if role == "reviewer":
            build_agent["steps"] = OPENCODE_REVIEWER_STEPS
    if build_agent:
        config["agent"] = {OPENCODE_BUILD_AGENT: build_agent}
    resolved_env = {**env, OPENCODE_CONFIG_ENV: json.dumps(config)}
    if model in OPENCODE_MODEL_VARIANTS:
        pinned = variant or OPENCODE_DEFAULT_VARIANT
        resolved_env[OPENCODE_STATE_HOME_ENV] = str(pin_variant_state(model, pinned, cwd=cwd))
    return resolved_env


def resolve_variant(model: str, variant: str | None, *, binary: str, one_shot: bool) -> str | None:
    """opencode 등급을 확정합니다. 등록 모델은 생략 시 기본 등급, 목록 밖 값은 거부합니다."""
    if binary != "opencode":
        return variant
    allowed = OPENCODE_MODEL_VARIANTS.get(model)
    if allowed is None:
        return variant
    if variant is None:
        return OPENCODE_DEFAULT_VARIANT
    if variant not in allowed:
        raise ValueError(
            f"{model} 의 variant 는 {', '.join(allowed)} 중 하나여야 합니다: {variant}"
        )
    return variant


def build_completion_message(exit_code: int, model: str) -> str:
    """opencode 종료 후 터미널에 남길 완료 안내 문구를 조립합니다."""
    return f"\n---\nOpenCode 작업 완료 (종료 코드: {exit_code})\n---\n"


def resolve_shell(env: dict[str, str]) -> str:
    return env.get("SHELL") or DEFAULT_SHELL


def run_opencode(cmd: list[str], env: dict[str, str]) -> int:
    """opencode 를 자식 프로세스로 실행하고 표준 입출력은 터미널에 그대로 둡니다."""
    completed = subprocess.run(cmd, env=env)  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
    return completed.returncode


def open_interactive_shell(env: dict[str, str]) -> None:
    """대화형 셸로 프로세스를 대체해 터미널 창을 유지합니다."""
    shell = resolve_shell(env)
    os.execvpe(shell, [shell], env)  # noqa: S606  # nosec B606 - 터미널 유지를 위한 대화형 셸 교체 호출입니다


def spawn_permission_setup(
    launcher_script: str | Path,
    terminal: str,
    model: str,
    *,
    popen=subprocess.Popen,
) -> None:
    common.spawn_permission_setup(
        launcher_script,
        terminal,
        model,
        popen=popen,
    )


def main(argv: list[str] | None = None) -> int:
    # 자식 모드: 부모가 실행된 뒤 독립 세션에서 승인 설정만 수행합니다.
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw and raw[0] == PERMISSION_SETUP_FLAG:
        return common.run_permission_setup_child(
            raw,
            cli_type="opencode",
            launcher=str(Path(__file__).resolve().parent.name + "/" + Path(__file__).name),
        )

    parser = argparse.ArgumentParser(description="OpenCode 워커 런처")
    parser.add_argument(
        "--model",
        required=True,
        help="OpenCode 모델 ID (provider/model 형태, 예: openai/gpt-5.6-turbo, anthropic/claude-3-7-sonnet)",
    )
    parser.add_argument(
        "--binary",
        choices=SUPPORTED_BINARIES,
        default="opencode",
        help="실행할 CLI (opencode 또는 kilo. 기본 opencode)",
    )
    parser.add_argument(
        "--variant",
        choices=SUPPORTED_VARIANTS,
        default=None,
        help=(
            "추론 등급. opencode 대화형은 OPENCODE_MODEL_VARIANTS 모델만(생략 시 high), "
            "그 밖의 opencode 모델은 --one-shot 과 함께만, kilo 는 대화형에서도 씁니다."
        ),
    )
    parser.add_argument("--preamble", type=Path, default=DEFAULT_PREAMBLE)
    parser.add_argument("--timeout-sec", type=float, default=300.0)
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="opencode run [message] 단발 실행으로 기동합니다. 완료 후 셸로 이어받아 출력을 보존합니다.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="호환용 인자입니다. opencode 에 --auto 를 넘기지 않습니다.",
    )
    parser.add_argument(
        "--role",
        choices=["auto", "builder", "reviewer"],
        default="auto",
        help="워커 역할 (auto, builder, reviewer. 기본 auto)",
    )
    parser.add_argument(
        "--no-commit-notice",
        action="store_true",
        help="커밋 고지문을 붙이지 않습니다.",
    )
    parser.add_argument(
        "--no-keep-open",
        action="store_true",
        help="단발 실행 종료 후 셸로 이어받지 않고 종료 코드를 그대로 반환합니다.",
    )
    args = parser.parse_args(argv)
    try:
        args.variant = resolve_variant(
            args.model, args.variant, binary=args.binary, one_shot=args.one_shot
        )
    except ValueError as err:
        parser.error(str(err))
    if (
        args.variant is not None
        and not args.one_shot
        and args.binary != "kilo"
        and args.model not in OPENCODE_MODEL_VARIANTS
    ):
        parser.error("opencode 대화형에서는 --variant 를 --one-shot 과 함께만 쓸 수 있습니다")

    print(f"preamble 대기 중: {args.preamble} (최대 {args.timeout_sec:.0f}초)", flush=True)
    try:
        prompt = wait_for_preamble(args.preamble, args.timeout_sec)
    except (TimeoutError, ValueError) as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2

    prompt = common.append_role_notice(
        prompt,
        role=args.role,
        no_commit_notice=args.no_commit_notice,
    )

    try:
        env = build_env(
            dict(os.environ),
            args.model,
            one_shot=args.one_shot,
            binary=args.binary,
            variant=args.variant,
            role=args.role,
        )
    except ValueError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2
    cmd = build_command(
        args.model,
        prompt,
        one_shot=args.one_shot,
        auto=args.auto,
        binary=args.binary,
        variant=args.variant,
    )

    common.schedule_permission_setup(
        Path(__file__).resolve(),
        args.model,
        spawn_fn=spawn_permission_setup,
    )

    mode = "run 단발" if args.one_shot else "대화형"
    if not args.one_shot and args.binary == "opencode":
        print(
            f"기동: opencode --standalone (모델 {args.model} 주입, variant {args.variant or '기본'}, "
            f"{mode}, 지시문 {len(prompt)}자)",
            flush=True,
        )
    else:
        print(
            f"기동: {args.binary} --model {args.model} ({mode}, 지시문 {len(prompt)}자)", flush=True
        )

    if args.one_shot:
        exit_code = run_opencode(cmd, env)
        if args.no_keep_open:
            return exit_code
        print(build_completion_message(exit_code, args.model), end="", flush=True)
        open_interactive_shell(env)
        return exit_code

    os.execvpe(cmd[0], cmd, env)  # noqa: S606  # nosec B606 - 셸을 거치지 않고 코디네이터가 만든 인자로 프로세스를 교체합니다
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
