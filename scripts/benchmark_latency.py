import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import time
import numpy as np
from fastapi.testclient import TestClient
from src.app.main import app

client = TestClient(app)



def benchmark_predictions_latency(num_requests: int = 100) -> float:
    print(f"[1/2] AI 낙찰가 예측 API 레이턴시 벤치마크 ({num_requests}회 요청)...")
    latencies = []
    payload = {
        "presumed_price": 500000000,
        "base_price": 495000000,
        "category_code": "Thng",
    }

    for _ in range(num_requests):
        start = time.perf_counter()
        resp = client.post("/api/v1/predictions/predict", json=payload)
        end = time.perf_counter()
        if resp.status_code == 200:
            latencies.append((end - start) * 1000.0)

    p95 = float(np.percentile(latencies, 95))
    p50 = float(np.percentile(latencies, 50))
    print(f"      P50: {p50:.2f}ms | P95: {p95:.2f}ms | P99: {np.percentile(latencies, 99):.2f}ms")
    return p95


def benchmark_chatbot_latency(num_requests: int = 50) -> float:
    print(f"[2/2] 하이브리드 RAG 챗봇 API 레이턴시 벤치마크 ({num_requests}회 요청)...")
    latencies = []
    payload = {"query": "적격심사 기준 문의", "stream": False}

    for _ in range(num_requests):
        start = time.perf_counter()
        resp = client.post("/api/v1/chatbot/query", json=payload)
        end = time.perf_counter()
        if resp.status_code == 200:
            latencies.append((end - start) * 1000.0)

    p95 = float(np.percentile(latencies, 95))
    p50 = float(np.percentile(latencies, 50))
    print(f"      P50: {p50:.2f}ms | P95: {p95:.2f}ms | P99: {np.percentile(latencies, 99):.2f}ms")
    return p95


def main():
    print("=" * 60)
    print("refac_bid_box Phase 7 P95 레이턴시 벤치마크 검증")
    print("=" * 60)

    pred_p95 = benchmark_predictions_latency(100)
    chat_p95 = benchmark_chatbot_latency(50)

    print("-" * 60)
    if pred_p95 < 100.0 and chat_p95 < 300.0:
        print("P95 레이턴시 벤치마크 검증 통과 (G3 성능 최적화 달성)")
        return 0
    else:
        print("P95 레이턴시 벤치마크 미달")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
