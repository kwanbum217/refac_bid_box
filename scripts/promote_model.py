"""
scripts/promote_model.py

챌린저 승격과 롤백을 실행하는 운영 도구.

승격은 의도적으로 자동화하지 않습니다. 2026-08-05 에 `num_leaves` 127 이
승격 게이트 4개를 전부 통과하고 홀드아웃에서 champion 을 이겼으나 운영 쌍대
비교에서 유의하게 나빴습니다(t=2.13). 자동 승격이었다면 서비스가 조용히
나빠졌을 것입니다.

수동이어야 한다는 것과 도구가 없어야 한다는 것은 다릅니다. 지금까지 승격
수단은 REPL 에 코드 두 줄을 붙여 넣는 것뿐이었고, 롤백은 백업 디렉터리를
사람이 직접 옮기는 것이었습니다. "즉시 롤백 가능" 이 비협상 원칙인데
(AGENTS.md) 그 실행이 손 절차에 걸려 있었습니다.

사용 예입니다.

    uv run python scripts/promote_model.py status
    uv run python scripts/promote_model.py promote --model servc_institution_v1 --category Servc
    uv run python scripts/promote_model.py rollback --model servc_institution_v1

`promote` 는 기본이 예행(dry-run)입니다. 실제 교체는 `--apply` 를 붙여야
일어납니다. 되돌리기 어려운 변경이라 오타 한 번으로 서빙이 바뀌면 안 됩니다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.timeutil import utcnow  # noqa: E402
from src.ml.model_registry import resolve_serving_tree  # noqa: E402
from src.ml.promotion import (  # noqa: E402
    AUDIT_LOG_PATH,
    BACKUP_ROOT,
    REGISTRY_ROOT,
    SERVING_ROOT,
    PromotionRejected,
    RollbackUnavailable,
    check_promotion_criteria,
    check_promotion_evidence,
    compute_artifact_checksum,
    latest_version,
    load_serving_metrics,
    promote,
    read_paired_verdict,
    rollback,
)

METRIC_KEYS = ("r2", "rmse", "mape")


def _read_metadata(path: Path) -> dict:
    target = resolve_serving_tree(path) if path.is_dir() else path
    meta = target / "metadata.json"
    if not meta.exists():
        return {}
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _format_metrics(metrics: dict | None) -> str:
    if not metrics:
        return "지표 없음"
    parts = []
    for key in METRIC_KEYS:
        value = metrics.get(key)
        if value is None:
            continue
        try:
            parts.append(f"{key.upper()} {float(value):.4f}")
        except (TypeError, ValueError):
            continue
    return " / ".join(parts) if parts else "지표 없음"


def _registry_models(registry_dir: Path) -> list[str]:
    if not registry_dir.exists():
        return []
    return sorted(p.name for p in registry_dir.iterdir() if p.is_dir())


def cmd_status(args: argparse.Namespace) -> int:
    """서빙본과 레지스트리 최신본을 나란히 보여 줍니다."""
    registry_dir = Path(args.registry_dir)
    serving_dir = Path(args.serving_dir)
    backup_root = Path(args.backup_dir)

    models = _registry_models(registry_dir)
    if args.model:
        models = [args.model]
    if not models:
        print(f"레지스트리에 학습 아티팩트가 없습니다: {registry_dir}")
        return 1

    for model_name in models:
        serving_meta = _read_metadata(serving_dir / model_name)
        # 원본 이식 모델은 metadata.json 이 체크섬 대상이라 지표를 못 넣습니다.
        # 실측 사이드카까지 함께 봐야 재학습 게이트와 같은 값을 보여 줍니다.
        _, serving_metrics = load_serving_metrics(model_name, serving_dir=serving_dir)
        print(f"\n[{model_name}]")
        print(
            f"  서빙   {serving_meta.get('version') or '없음':<28}"
            f" {_format_metrics(serving_metrics)}"
        )

        try:
            version = latest_version(model_name, registry_dir)
        except (FileNotFoundError, NotADirectoryError):
            print("  학습   없음")
            continue

        challenger_meta = _read_metadata(registry_dir / model_name / version)
        print(f"  학습   {version:<28} {_format_metrics(challenger_meta.get('metrics'))}")
        print(f"         표본 {challenger_meta.get('samples_count', 0):,}")

        reasons = check_promotion_criteria(challenger_meta, registry_dir=registry_dir)
        verdict_data = read_paired_verdict(model_name, version, registry_dir)
        if reasons:
            print("  판정   승격 불가")
            for reason in reasons:
                print(f"         - {reason}")
            if verdict_data and verdict_data.get("verdict") == "rejected":
                print("         (운영 쌍대검정 기각 -- force 로도 우회 불가)")
        elif serving_meta.get("version") == version:
            print("  판정   이미 서빙 중")
        else:
            print("  판정   승격 조건 통과. 운영 쌍대 비교 후 --apply 하십시오")
            print("         scripts/compare_servc_models_paired.py")

        backup_meta = _read_metadata(backup_root / model_name)
        if backup_meta:
            print(f"  롤백   {backup_meta.get('version') or '버전 미상'} 으로 되돌릴 수 있습니다")
        else:
            print("  롤백   되돌릴 백업본이 없습니다")
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    registry_dir = Path(args.registry_dir)
    version = args.version or latest_version(args.model, registry_dir)
    metadata = _read_metadata(registry_dir / args.model / version)
    if not metadata:
        print(f"학습 메타데이터를 읽지 못했습니다: {args.model}/{version}")
        return 1

    reasons = check_promotion_criteria(metadata, registry_dir=registry_dir)
    print(f"[{args.model}] {version}")
    print(f"  지표 {_format_metrics(metadata.get('metrics'))}")
    print(f"  표본 {metadata.get('samples_count', 0):,}")
    for reason in reasons:
        print(f"  거부 사유: {reason}")

    if not args.apply:
        verdict = "거부됨" if reasons else "통과"
        print(f"\n예행 결과: {verdict}. 실제 교체는 --apply 를 붙이십시오.")
        print("교체 전 운영 경로 쌍대 비교를 거치십시오: scripts/compare_servc_models_paired.py")
        evidence_reasons = check_promotion_evidence(metadata, registry_dir=registry_dir)
        return 1 if reasons and (not args.force or evidence_reasons) else 0

    try:
        result = promote(
            args.model,
            version,
            category_code=args.category,
            registry_dir=registry_dir,
            serving_dir=Path(args.serving_dir),
            backup_dir=Path(args.backup_dir),
            force=args.force,
            audit_log_path=Path(args.audit_log),
        )
    except PromotionRejected as exc:
        print(f"\n승격이 거부되었습니다.\n{exc}")
        return 1

    print("\n승격 완료")
    print(f"  서빙 경로 {result['promoted_to']}")
    print(f"  백업     {result['backup'] or '없음 (최초 승격)'}")
    print(f"  요구 특징 {len(result['required_features'])}종 / 범주 {result['category_levels']}종")
    print(f"\n되돌리려면: uv run python scripts/promote_model.py rollback --model {args.model}")
    return 0


def cmd_create_verdict(args: argparse.Namespace) -> int:
    """실제 아티팩트 해시를 채운 쌍대검정 판정 파일을 생성합니다."""
    registry_dir = Path(args.registry_dir)
    challenger_dir = registry_dir / args.model / args.version
    if not challenger_dir.is_dir():
        print(f"챌린저 아티팩트 디렉터리가 없습니다: {challenger_dir}")
        return 1
    champion_dir = registry_dir / args.model / args.champion_version
    if not champion_dir.is_dir():
        print(f"champion 아티팩트 디렉터리가 없습니다: {champion_dir}")
        return 1
    decided_at = args.decided_at or utcnow().isoformat()
    if args.verdict == "approved" and (
        not args.sample_hash or not args.code_commit or not decided_at
    ):
        print("approved 판정에는 --sample-hash, --code-commit, --decided-at 이 필요합니다")
        return 1

    challenger_checksum = compute_artifact_checksum(challenger_dir)
    champion_checksum = compute_artifact_checksum(champion_dir)
    verdict_path = challenger_dir / "paired_verdict.json"
    payload = {
        "verdict": args.verdict,
        "champion_version": args.champion_version,
        "challenger_version": args.version,
        "champion_checksum": champion_checksum,
        "challenger_checksum": challenger_checksum,
        "sample_hash": args.sample_hash,
        "code_commit": args.code_commit,
        "decided_at": decided_at,
        "evidence": args.evidence,
    }
    verdict_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"판정 파일 생성: {verdict_path}")
    print(f"  champion_checksum   {champion_checksum}")
    print(f"  challenger_checksum {challenger_checksum}")
    return 0


def cmd_rollback(args: argparse.Namespace) -> int:
    try:
        result = rollback(
            args.model,
            serving_dir=Path(args.serving_dir),
            backup_dir=Path(args.backup_dir),
        )
    except RollbackUnavailable as exc:
        print(str(exc))
        return 1

    print(f"[{args.model}] 롤백 완료")
    print(f"  복원 {result['restored_version'] or '버전 미상'}")
    print(f"  물러난 것 {result['replaced_version'] or '버전 미상'} (백업 자리로 이동)")
    print("  다시 되돌리려면 같은 명령을 한 번 더 실행하십시오.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="모델 승격·롤백 도구")
    parser.add_argument("--registry-dir", default=str(REGISTRY_ROOT))
    parser.add_argument("--serving-dir", default=str(SERVING_ROOT))
    parser.add_argument("--backup-dir", default=str(BACKUP_ROOT))
    parser.add_argument("--audit-log", default=str(AUDIT_LOG_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="서빙본과 학습 최신본 비교")
    status.add_argument("--model", default="")
    status.set_defaults(func=cmd_status)

    promote_cmd = sub.add_parser("promote", help="챌린저를 서빙 경로로 승격")
    promote_cmd.add_argument("--model", required=True)
    promote_cmd.add_argument("--version", default="")
    promote_cmd.add_argument("--category", default="")
    promote_cmd.add_argument("--apply", action="store_true", help="실제로 교체합니다")
    promote_cmd.add_argument("--force", action="store_true", help="승격 조건 위반을 무시합니다")
    promote_cmd.set_defaults(func=cmd_promote)

    verdict_cmd = sub.add_parser(
        "create-verdict",
        aliases=["write-verdict", "verdict"],
        help="실제 아티팩트 증거를 채운 쌍대검정 판정 파일 생성",
    )
    verdict_cmd.add_argument("--model", required=True)
    verdict_cmd.add_argument("--version", required=True)
    verdict_cmd.add_argument("--champion-version", required=True)
    verdict_cmd.add_argument("--verdict", choices=("approved", "rejected"), required=True)
    verdict_cmd.add_argument("--sample-hash", default="")
    verdict_cmd.add_argument("--code-commit", default="")
    verdict_cmd.add_argument("--decided-at", default="")
    verdict_cmd.add_argument("--evidence", default="")
    verdict_cmd.set_defaults(func=cmd_create_verdict)

    rollback_cmd = sub.add_parser("rollback", help="직전 서빙본으로 되돌리기")
    rollback_cmd.add_argument("--model", required=True)
    rollback_cmd.set_defaults(func=cmd_rollback)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "category", None) == "":
        args.category = None
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
