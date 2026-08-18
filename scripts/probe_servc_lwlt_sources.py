#!/usr/bin/env python3
"""
용역 공고의 낙찰하한율을 담고 있는 다른 API 오퍼레이션이 있는지 찾습니다.

학습 데이터 결측 205,238건 중 76.8%가 `공고서참조` 낙찰방법에 있고, 이 방법은
같은 이름 안에서 79.4%가 하한율을 보유합니다. 제도상 비적용이 아니라 값을 공고
문서로 넘긴 표기 문제이므로, **원 공고 어딘가에는 값이 있을 가능성이 높습니다**
(`servc_lwlt_availability_20260804.md` 2.3).

예측은 개찰 전에 이루어지므로 개찰결과 계열은 후보가 아닙니다. 공고 계열만
봅니다. 기초금액·변경이력은 이미 확인해 필드 자체가 없었으므로 제외합니다.

각 오퍼레이션에 대해 두 가지를 봅니다.

- `sucsfbidLwltRate` 가 응답 스키마에 있는가
- 있다면 현행 수집 원천이 비워 두는 건에도 값이 차 있는가

사용법:
    .venv/bin/python scripts/probe_servc_lwlt_sources.py
    .venv/bin/python scripts/probe_servc_lwlt_sources.py --rows 200
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

# 수집기와 같은 함수를 씁니다. 키 이름 규칙이 갈리면 조사 결과를 믿을 수 없습니다.
from src.app.services.api_collector import get_service_key  # noqa: E402

BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"

# 공고 시점에 조회 가능한 용역 오퍼레이션입니다. 물품·공사 계열은 모집단이 달라
# 대조가 성립하지 않으므로 넣지 않습니다.
CURRENT = "공고 목록 (현행)"
OPERATIONS = {
    CURRENT: f"{BASE}/getBidPblancListInfoServc",
    "조달청 검색": f"{BASE}/getBidPblancListInfoServcPPSSrch",
    "면허 제한": f"{BASE}/getBidPblancListInfoLicenseLimit",
    "참가가능 지역": f"{BASE}/getBidPblancListInfoPrtcptPsblRgn",
}

TARGET_FIELD = "sucsfbidLwltRate"
KEY_FIELDS = ("bidNtceNo", "bidNtceOrd")


async def fetch(client: httpx.AsyncClient, url: str, rows: int, start: str, end: str) -> dict:
    params = {
        "serviceKey": get_service_key(),
        "pageNo": "1",
        "numOfRows": str(rows),
        "type": "json",
        "inqryDiv": "1",
        "inqryBgnDt": f"{start}0000",
        "inqryEndDt": f"{end}2359",
    }
    resp = await client.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def extract_items(payload: dict) -> list[dict]:
    body = (payload.get("response") or {}).get("body") or {}
    items = body.get("items") or []
    if isinstance(items, dict):
        items = items.get("item") or []
    return items if isinstance(items, list) else []


def notice_key(item: dict) -> tuple:
    return tuple(str(item.get(field) or "") for field in KEY_FIELDS)


def has_value(item: dict) -> bool:
    return str(item.get(TARGET_FIELD) or "").strip() not in ("", "0")


def summarize(name: str, items: list[dict], payload: dict) -> dict:
    if not items:
        header = (payload.get("response") or {}).get("header") or {}
        return {
            "오퍼레이션": name,
            "표본": 0,
            "필드 존재": "-",
            "값 보유": "-",
            "비고": str(header.get("resultMsg") or "응답 없음")[:40],
        }

    filled = sum(1 for item in items if has_value(item))
    return {
        "오퍼레이션": name,
        "표본": len(items),
        "필드 존재": "있음" if any(TARGET_FIELD in item for item in items) else "없음",
        "값 보유": filled,
        "비고": "" if any(TARGET_FIELD in item for item in items) else "스키마에 필드 없음",
    }


def cross_check(current: list[dict], other: list[dict], name: str) -> str:
    """현행이 비워 둔 공고를 다른 오퍼레이션이 채우는지 **같은 공고번호로** 봅니다.

    건수만 비교하면 두 오퍼레이션이 서로 다른 공고를 보고 있어도 같아 보입니다.
    보강 가치는 오직 "현행 결측 건에 값이 있는가" 로만 판정됩니다.
    """
    missing = {notice_key(i) for i in current if not has_value(i)}
    if not missing:
        return "현행 결측 없음"
    filled_elsewhere = {notice_key(i) for i in other if has_value(i)}
    recovered = missing & filled_elsewhere
    overlap = missing & {notice_key(i) for i in other}
    return (
        f"{name}: 현행 결측 {len(missing)}건 중 조회 겹침 {len(overlap)}건, "
        f"**값 확보 {len(recovered)}건**"
    )


async def run(rows: int, start: str, end: str) -> int:
    if not get_service_key():
        print(".env 에서 serviceKey 를 찾지 못했습니다.")
        return 1

    results = []
    collected: dict[str, list[dict]] = {}
    async with httpx.AsyncClient() as client:
        for name, url in OPERATIONS.items():
            try:
                payload = await fetch(client, url, rows, start, end)
                items = extract_items(payload)
                collected[name] = items
                results.append(summarize(name, items, payload))
            except Exception as exc:
                collected[name] = []
                results.append(
                    {
                        "오퍼레이션": name,
                        "표본": 0,
                        "필드 존재": "-",
                        "값 보유": "-",
                        "비고": f"{type(exc).__name__}: {str(exc)[:30]}",
                    }
                )
            print(f"  {name} 조회 완료", flush=True)

    import pandas as pd

    print(f"\n{'=' * 96}\n조회 기간 {start} ~ {end} / 요청 {rows}건\n{'=' * 96}")
    print(pd.DataFrame(results).to_string(index=False))

    print("\n공고번호 대조 (현행 결측 건을 다른 원천이 채우는가)")
    current = collected.get(CURRENT) or []
    recovered_total = 0
    for name, items in collected.items():
        if name == CURRENT or not items:
            continue
        line = cross_check(current, items, name)
        print(f"  {line}")
        recovered_total += (
            int(line.split("값 확보 ")[-1].split("건")[0]) if "값 확보" in line else 0
        )

    print()
    if recovered_total:
        print("현행이 비워 둔 공고를 채우는 원천이 있습니다. 수집 보강을 검토하십시오.")
    else:
        print("**목록 API 보강 경로는 닫힙니다.** 어느 오퍼레이션도 현행 결측을 채우지 못합니다.")
        print("남는 방향은 공고 첨부 문서 파싱이며, 비용이 크므로 별도 판단이 필요합니다.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100)
    parser.add_argument("--start", default="20260801")
    parser.add_argument("--end", default="20260804")
    args = parser.parse_args()
    return asyncio.run(run(args.rows, args.start, args.end))


if __name__ == "__main__":
    raise SystemExit(main())
