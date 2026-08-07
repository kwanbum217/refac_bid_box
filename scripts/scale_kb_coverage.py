"""KB 커버리지 확대 색인을 실행합니다.

증분 색인이므로 중단 후 같은 명령을 다시 실행하면 이미 임베딩된 문서는
본문 해시가 같아 건너뛰고 남은 분량부터 이어갑니다.

사용 예:

    KB_MAX_DOCUMENTS=500000 uv run python scripts/scale_kb_coverage.py

전제 조건: 호스트 Ollama 가 떠 있고 bge-m3:latest 가 있어야 합니다.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app.core.db import SessionLocal
from src.app.services.kb_builder import rebuild_knowledge_base


def main() -> int:
    run_id = os.getenv("KB_PIPELINE_RUN_ID", "kb_scale_500k")
    started = time.time()
    result = rebuild_knowledge_base(SessionLocal(), pipeline_run_id=run_id)
    print(f"elapsed_sec {time.time() - started:.1f}")
    print(f"result {result}")
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
