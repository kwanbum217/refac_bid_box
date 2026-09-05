#!/usr/bin/env python3
"""refac_bid_box 통합 백업 및 복원 도구 (Backup & Recovery Tool)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# scripts/ 는 패키지가 아니라서 직접 실행하면 sys.path 에 저장소 루트가 없습니다.
# 2026-09-03 모듈 분할 이후 runbook 이 안내하는 python3 scripts/backup_recovery.py 가
# ModuleNotFoundError 로 죽었습니다. verify_migration.py 와 같은 방식으로 루트를 넣습니다.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.backup_recovery_core import (  # noqa: E402
    DEFAULT_SNAPSHOTS_DIR,
    EXPECTED_MANIFEST_SCHEMA,
    MANIFEST_FILENAME,
    PROJECT_ROOT,
    REQUIRED_BACKUP_ASSETS,
    REQUIRED_MODEL_SOURCE_PATH,
    REQUIRED_SOURCE_ASSETS,
    BackupAssetError,
    cleanup_drill_target_dir,
    create_mysql_database,
    create_tar_archive,
    drop_mysql_database,
    dump_mysql_database,
    evaluate_row_counts,
    extract_tar_archive,
    get_asset_state,
    get_chroma_source_path,
    get_db_config,
    get_head_commit_sha,
    get_model_source_paths,
    query_db_row_counts,
    restore_mysql_database,
    sha256_file,
    validate_backup_output,
)
from scripts.backup_snapshots import (  # noqa: E402
    list_snapshots,
    prune_snapshots,
    verify_snapshot,
)

__all__ = [
    "DEFAULT_SNAPSHOTS_DIR",
    "EXPECTED_MANIFEST_SCHEMA",
    "MANIFEST_FILENAME",
    "PROJECT_ROOT",
    "REQUIRED_BACKUP_ASSETS",
    "REQUIRED_MODEL_SOURCE_PATH",
    "REQUIRED_SOURCE_ASSETS",
    "BackupAssetError",
    "cleanup_drill_target_dir",
    "create_mysql_database",
    "create_tar_archive",
    "drop_mysql_database",
    "dump_mysql_database",
    "evaluate_row_counts",
    "execute_backup",
    "execute_restore",
    "extract_tar_archive",
    "get_chroma_source_path",
    "get_db_config",
    "get_head_commit_sha",
    "get_model_source_paths",
    "list_snapshots",
    "mask_secret",
    "prune_snapshots",
    "query_db_row_counts",
    "restore_mysql_database",
    "run_drill_g1_verification",
    "run_post_restore_verification",
    "run_restore_drill",
    "sha256_file",
    "verify_snapshot",
]


def mask_secret(value: str) -> str:
    """비밀번호 등 시크릿 문자열을 마스킹 처리합니다."""
    return "******" if value else "<empty>"


def execute_backup(
    output_dir: Path | None = None,
    execute: bool = False,
    project_root: Path | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """운영 DB, ChromaDB, 서빙 모델을 단일 복구 단위로 백업합니다."""
    root = project_root or PROJECT_ROOT
    db_config, chroma_path, model_paths = (
        get_db_config(),
        get_chroma_source_path(root),
        get_model_source_paths(root),
    )
    asset_states = {
        k: get_asset_state(p)
        for k, p in (("chroma_db", chroma_path), ("models", root / REQUIRED_MODEL_SOURCE_PATH))
    }
    missing_assets = [f"{n} ({s})" for n, s in asset_states.items() if s != "available"]

    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target_dir = output_dir or (DEFAULT_SNAPSHOTS_DIR / f"snapshot_{ts}")
    print(
        "=" * 60
        + f"\nrefac_bid_box 통합 백업 | {'[EXECUTE]' if execute else '[DRY-RUN]'}\n대상: {target_dir}\n"
        + "=" * 60
    )
    if not execute:
        print("[DRY-RUN] 백업 대상 확인 완료. 파일 쓰기는 수행되지 않았습니다.")
        ret = {
            "mode": "dry-run",
            "target_dir": str(target_dir),
            "db_target": f"{db_config['user']}@{db_config['host']}:{db_config['port']}/{db_config['name']}",
            "chroma_path": str(chroma_path),
            "model_paths": [str(p) for p in model_paths],
            "required_assets": asset_states,
        }
        return ret
    if missing_assets and not allow_partial:
        raise BackupAssetError("필수 백업 자산을 확인할 수 없습니다: " + ", ".join(missing_assets))
    target_dir.mkdir(parents=True, exist_ok=True)
    head_commit = get_head_commit_sha(root)
    db_dump_file = target_dir / "db_dump.sql.gz"
    db_dump_started_at = datetime.now(UTC).isoformat()
    dump_mysql_database(db_config, db_dump_file)
    db_dump_finished_at = datetime.now(UTC).isoformat()
    db_size, db_sha256 = validate_backup_output(db_dump_file, "database")
    row_counts_queried_at = datetime.now(UTC).isoformat()
    row_counts = query_db_row_counts(db_config)
    row_count_status, _row_count_msg = evaluate_row_counts(row_counts)
    has_row_count_evidence = row_count_status == "verified"
    recovery_trusted = (not missing_assets) and has_row_count_evidence

    def _dump_asset(key, paths, out_name):
        f, sz, sha = target_dir / out_name, None, None
        if asset_states[key] == "available":
            create_tar_archive(paths, f, base_dir=root)
            sz, sha = validate_backup_output(f, key)
        return f, sz, sha

    chroma_dump_file, chroma_size, chroma_sha256 = _dump_asset(
        "chroma_db", [chroma_path], "chroma_db.tar.gz"
    )
    models_dump_file, models_size, models_sha256 = _dump_asset(
        "models", model_paths, "models.tar.gz"
    )

    manifest_data = {
        "schema": EXPECTED_MANIFEST_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "head_commit": head_commit,
        "partial_backup": bool(missing_assets) or not has_row_count_evidence,
        "recovery_trusted": recovery_trusted,
        "required_assets": list(REQUIRED_BACKUP_ASSETS),
        "missing_assets": missing_assets,
        "row_count_status": row_count_status,
        "row_count_evidence": "verified" if has_row_count_evidence else "unverified",
        "consistency_window": {
            "db_dump_started_at": db_dump_started_at,
            "db_dump_finished_at": db_dump_finished_at,
            "row_counts_queried_at": row_counts_queried_at,
            "file_assets_collected_at": datetime.now(UTC).isoformat(),
            "timing_note": "덤프 완료 후 별도 조회한 행 수는 쓰기 중인 DB 의 덤프 시점 행 수와 다를 수 있습니다.",
        },
        "components": {
            "database": {
                "path": db_dump_file.name,
                "size_bytes": db_size,
                "sha256": db_sha256,
                "row_counts": row_counts,
                "row_count_status": row_count_status,
                "row_count_evidence": "verified" if has_row_count_evidence else "unverified",
                "timing_note": "덤프 완료 후 별도 조회한 행 수는 쓰기 중인 DB 의 덤프 시점 행 수와 다를 수 있습니다.",
            },
            "chroma_db": {
                "path": chroma_dump_file.name if chroma_size else None,
                "size_bytes": chroma_size,
                "sha256": chroma_sha256,
                "status": asset_states["chroma_db"],
                "source_path": str(chroma_path.relative_to(root))
                if chroma_path.is_relative_to(root)
                else str(chroma_path),
            },
            "models": {
                "path": models_dump_file.name if models_size else None,
                "size_bytes": models_size,
                "sha256": models_sha256,
                "status": asset_states["models"],
                "source_paths": [
                    str(p.relative_to(root)) if p.is_relative_to(root) else str(p)
                    for p in model_paths
                ],
            },
        },
    }
    manifest_file = target_dir / MANIFEST_FILENAME
    manifest_file.write_text(
        json.dumps(manifest_data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"통합 백업 완료: {target_dir} ({manifest_file.name})")
    return manifest_data


def run_drill_g1_verification(
    target_dir: Path,
    drill_db_config: dict[str, Any],
    report_path: Path | None = None,
    project_root: Path | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    root = project_root or PROJECT_ROOT
    script = root / "scripts" / "verify_migration.py"
    if not script.exists():
        return False, f"검증 스크립트 없음: {script}", {}
    rep = report_path or (target_dir / "drill_g1_verification_report.json")
    env = {
        **os.environ,
        "DB_NAME": str(drill_db_config["name"]),
        "DB_HOST": str(drill_db_config["host"]),
        "DB_PORT": str(drill_db_config["port"]),
        "DB_USER": str(drill_db_config["user"]),
        "DATA_ASSET_ROOT": str(target_dir),
        "CHROMA_DB_PATH": str(target_dir / "chroma_db"),
        "MODEL_FILES_DIR": str(target_dir / "data" / "model_files"),
        "MODEL_BACKUPS_DIR": str(target_dir / "data" / "model_backups"),
    }
    if drill_db_config.get("password"):
        env["DB_PASSWORD"] = str(drill_db_config["password"])
    proc = subprocess.run(
        [sys.executable, str(script), "--report-path", str(rep)],
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )  # nosec B603, B607
    try:
        rep_data = json.loads(rep.read_text(encoding="utf-8")) if rep.exists() else {}
    except Exception:
        rep_data = {}
    return (
        proc.returncode == 0,
        (
            "G1 무손실 검증 통과"
            if proc.returncode == 0
            else (proc.stderr or proc.stdout or "G1 검증 실패").strip()
        ),
        rep_data,
    )


def _measure_rpo(manifest: dict[str, Any], st: datetime) -> dict[str, Any]:
    w, c = manifest.get("consistency_window", {}), manifest.get("created_at")

    def _diff(s: str | None) -> float | None:
        return (st - datetime.fromisoformat(s)).total_seconds() if s else None

    return {
        "snapshot_created_at": c,
        "consistency_window": w,
        "drill_started_at": st.isoformat(),
        "created_at_to_drill_start_seconds": _diff(c),
        "db_dump_finished_to_drill_start_seconds": _diff(w.get("db_dump_finished_at")),
        "file_assets_to_drill_start_seconds": _diff(w.get("file_assets_collected_at")),
    }


def _record_timing(
    timings: dict[str, Any],
    name: str,
    start: datetime,
    end: datetime,
    status: str,
    err: Exception | None = None,
) -> None:
    timings[name] = {
        "started_at": start.isoformat(),
        "finished_at": end.isoformat(),
        "duration_seconds": (end - start).total_seconds(),
        "status": status,
        **({"error": str(err)} if err else {}),
    }


def run_restore_drill(
    snapshot_dir: Path,
    target_dir: Path,
    drill_db_config: dict[str, Any] | None = None,
    keep_artifacts: bool = False,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """격리 대상에 대해 아카이브 해제, DB import, G1 무손실 검증을 실제로 수행하는 복원 리허설 도구입니다."""
    raw_target = str(target_dir).strip()
    if not raw_target or raw_target in (".", "./", "..", "../"):
        raise ValueError("복원 리허설 대상 디렉토리를 지정해야 합니다.")
    real_root, cwd, target = PROJECT_ROOT.resolve(), Path.cwd().resolve(), target_dir.resolve()
    for root in (real_root, cwd, project_root.resolve() if project_root else None):
        if root and (target == root or root in target.parents or target in root.parents):
            raise ValueError("복원 리허설 대상은 프로젝트 루트 밖의 격리 디렉토리여야 합니다.")
    prod_db = get_db_config()
    drill_db = (
        drill_db_config.copy()
        if drill_db_config
        else {**prod_db, "name": f"{prod_db['name']}_restore_drill"}
    )
    d_name, p_name = str(drill_db.get("name", "")).strip(), str(prod_db.get("name", "")).strip()
    if not d_name:
        raise ValueError("복원 리허설 대상 DB 이름을 지정해야 합니다.")
    if d_name == p_name or (
        str(drill_db.get("host")) == str(prod_db.get("host"))
        and int(drill_db.get("port", 3306)) == int(prod_db.get("port", 3306))
        and d_name == p_name
    ):
        raise ValueError("복원 리허설 대상 DB는 운영 DB와 동일할 수 없습니다.")

    drill_start = datetime.now(UTC)
    timings: dict[str, Any] = {}
    errors: list[str] = []
    v_st = datetime.now(UTC)
    valid, v_errs, manifest = verify_snapshot(snapshot_dir)
    errors.extend(v_errs)
    if manifest.get("partial_backup") or manifest.get("recovery_trusted") is not True:
        errors.append("부분 백업은 복구용으로 신뢰할 수 없습니다.")
        valid = False
    db_comp = manifest.get("components", {}).get("database", {})
    rc = db_comp.get("row_counts", {})
    r_status = db_comp.get("row_count_status") or manifest.get("row_count_status")
    if (
        valid
        and not (bool(rc) and all(v is not None for v in rc.values()))
        and r_status != "verified"
    ):
        print(
            "      [주의] 백업 매니페스트에 완전한 행 수 증거가 없습니다 (과거 백업 또는 미완 상태)."
        )
    _record_timing(
        timings, "snapshot_verification", v_st, datetime.now(UTC), "PASS" if valid else "FAIL"
    )
    rpo, comps = _measure_rpo(manifest, drill_start), manifest.get("components", {})

    def _drill_rep(ok: bool, g1_v: dict[str, Any], ext: list[str]) -> dict[str, Any]:
        return {
            "schema": "RESTORE_DRILL_REPORT_V2",
            "snapshot_dir": str(snapshot_dir),
            "target_dir": str(target),
            "drill_db": {k: drill_db.get(k) for k in ("host", "port", "name", "user")},
            "snapshot_valid": valid,
            "components": sorted(comps),
            "extracted_components": ext,
            "timings": timings,
            "total_duration_seconds": (datetime.now(UTC) - drill_start).total_seconds(),
            "rpo_measurements": rpo,
            "g1_verification": g1_v,
            "keep_artifacts": keep_artifacts,
            "errors": errors,
            "success": ok,
        }

    if not valid:
        return _drill_rep(
            False, {"success": False, "message": "스냅샷 무결성 검증 실패로 건너뜀"}, []
        )

    extracted, g1_res, success, created_db = [], {}, False, False
    target.mkdir(parents=True, exist_ok=True)
    try:

        def _exec_step(name: str, fn: Any) -> None:
            st = datetime.now(UTC)
            try:
                fn()
                _record_timing(timings, name, st, datetime.now(UTC), "PASS")
            except Exception as exc:
                _record_timing(timings, name, st, datetime.now(UTC), "FAIL", exc)
                errors.append(f"{name} 실패: {exc}")
                raise

        def _do_extract():
            for k in ("chroma_db", "models"):
                if comps.get(k, {}).get("path"):
                    extract_tar_archive(snapshot_dir / comps[k]["path"], target_base_dir=target)
                    extracted.append(k)

        def _do_import():
            nonlocal created_db
            create_mysql_database(drill_db)
            created_db = True
            if not comps.get("database", {}).get("path"):
                raise ValueError("매니페스트에 database 아카이브 경로가 없습니다.")
            restore_mysql_database(drill_db, snapshot_dir / comps["database"]["path"])

        def _do_g1():
            nonlocal g1_res, success
            ok, msg, rep = run_drill_g1_verification(
                target, drill_db, target / "g1_drill_verify_report.json", project_root=project_root
            )
            g1_res = {"success": ok, "message": msg, "report": rep}
            if not ok:
                raise RuntimeError(f"G1 무손실 검증 실패: {msg}")
            success = True

        _exec_step("archive_extraction", _do_extract)
        _exec_step("database_import", _do_import)
        _exec_step("g1_verification", _do_g1)
    except Exception:
        success = False

    finally:
        c_st, c_status = datetime.now(UTC), "KEPT" if keep_artifacts else "PASS"
        if not keep_artifacts:
            try:
                if created_db:
                    drop_mysql_database(drill_db, prod_config=prod_db)
                cleanup_drill_target_dir(target, project_root=project_root)
            except Exception as exc:
                c_status = "FAIL"
                errors.append(f"리허설 산출물 정리 실패: {exc}")
        _record_timing(timings, "cleanup", c_st, datetime.now(UTC), c_status)

    return _drill_rep(success and (len(errors) == 0), g1_res, extracted)


def run_post_restore_verification(project_root: Path | None = None) -> bool:
    """복원 후 scripts/verify_migration.py 를 실행하여 데이터 무손실 검증을 수행합니다."""
    root = project_root or PROJECT_ROOT
    script = root / "scripts" / "verify_migration.py"
    if not script.exists():
        return False
    return subprocess.run([sys.executable, str(script)], cwd=str(root), check=False).returncode == 0  # nosec B603, B607


def execute_restore(
    snapshot_dir: Path,
    execute: bool = False,
    confirm: bool = False,
    skip_verify: bool = False,
    project_root: Path | None = None,
) -> bool:
    """단일 복구 단위 스냅샷으로부터 DB, ChromaDB, 모델을 복원합니다."""
    root = project_root or PROJECT_ROOT
    db = get_db_config()
    valid, errors, m = verify_snapshot(snapshot_dir)

    if not valid or m.get("partial_backup") or m.get("recovery_trusted") is not True:
        err_msg = ", ".join(errors) if errors else "복원 신뢰 플래그(recovery_trusted) 미충족"
        print(f"[오류] 스냅샷 무결성 실패 또는 비신뢰: {err_msg}")
        return False
    db_comp = m.get("components", {}).get("database", {})
    rc = db_comp.get("row_counts", {})
    r_status = db_comp.get("row_count_status") or m.get("row_count_status")
    if not (bool(rc) and all(v is not None for v in rc.values())) and r_status != "verified":
        print(
            "[경고] 과거 백업 매니페스트: 행 수 증거가 없어 무손실 검증이 미완료 상태입니다. 복원을 계속 진행합니다."
        )
    if not execute:
        print("[DRY-RUN] 복원 계획 점검 완료.")
        return True
    if not confirm:
        print("[오류] 복원 실행을 위해 --confirm 플래그가 필요합니다.")
        return False
    restore_mysql_database(db, snapshot_dir / m["components"]["database"]["path"])
    for k in ("chroma_db", "models"):
        extract_tar_archive(snapshot_dir / m["components"][k]["path"], target_base_dir=root)
    return True if skip_verify else run_post_restore_verification(root)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="refac_bid_box 통합 백업 및 복원 도구")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--execute", action="store_true")
    b.add_argument("--output-dir", type=Path, default=None)
    b.add_argument("--allow-partial", action="store_true")
    r = sub.add_parser("restore")
    for a in ("--execute", "--confirm", "--skip-verify"):
        r.add_argument(a, action="store_true")
    r.add_argument("--snapshot-dir", type=Path, required=True)
    sub.add_parser("verify").add_argument("--snapshot-dir", type=Path, required=True)
    sub.add_parser("list")
    d = sub.add_parser("drill")
    d.add_argument("--snapshot-dir", type=Path, required=True)
    d.add_argument("--target-dir", type=Path, required=True)
    d.add_argument("--report-path", type=Path, default=None)
    d.add_argument("--db-name", type=str, default=None)
    d.add_argument("--keep-artifacts", action="store_true")
    pr = sub.add_parser("prune")
    pr.add_argument("--snapshots-dir", type=Path, default=DEFAULT_SNAPSHOTS_DIR)
    pr.add_argument("--retain-count", type=int, default=7)
    pr.add_argument("--delete", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    c = args.command
    if c == "backup":
        execute_backup(
            output_dir=args.output_dir, execute=args.execute, allow_partial=args.allow_partial
        )
        return 0
    if c == "restore":
        return (
            0
            if execute_restore(args.snapshot_dir, args.execute, args.confirm, args.skip_verify)
            else 1
        )
    if c == "verify":
        ok, _, _ = verify_snapshot(args.snapshot_dir)
        print(f"스냅샷 검증: {'[PASS]' if ok else '[FAIL]'}")
        return 0 if ok else 1
    if c == "list":
        list_snapshots()
        return 0
    if c == "drill":
        db = {**get_db_config(), "name": args.db_name} if args.db_name else None
        try:
            rep = run_restore_drill(
                args.snapshot_dir,
                args.target_dir,
                drill_db_config=db,
                keep_artifacts=args.keep_artifacts,
            )
        except ValueError as exc:
            print(f"[오류] {exc}")
            return 1
        if args.report_path:
            args.report_path.parent.mkdir(parents=True, exist_ok=True)
            args.report_path.write_text(
                json.dumps(rep, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
        print(json.dumps(rep, indent=2, ensure_ascii=False))
        return 0 if rep.get("success") else 1
    if c == "prune":
        try:
            prune_snapshots(args.snapshots_dir, args.retain_count, args.delete)
            return 0
        except ValueError as exc:
            print(f"[오류] {exc}")
            return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
