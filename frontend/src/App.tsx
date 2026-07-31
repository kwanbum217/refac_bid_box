import React, { useState, useEffect, useRef } from 'react';

interface HealthStatus {
  status: string;
  service: string;
  environment: string;
  framework: string;
  database: string;
  task_queue: string;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'prediction' | 'chatbot'>('dashboard');
  const [health, setHealth] = useState<HealthStatus | null>(null);

  // 예측 상태
  const [presumedPrice, setPresumedPrice] = useState<number>(500000000);
  const [basePrice, setBasePrice] = useState<number>(495000000);
  const [predictionResult, setPredictionResult] = useState<any>(null);

  // 챗봇 스트리밍 상태
  const [chatQuery, setChatQuery] = useState<string>('');
  const [chatStreamText, setChatStreamText] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [retrievedDocs, setRetrievedDocs] = useState<any[]>([]);

  useEffect(() => {
    fetch('/api/v1/health')
      .then((res) => res.json())
      .then((data) => setHealth(data))
      .catch((err) => console.error('Health check error:', err));
  }, []);

  // AI 낙찰가 예측 실행
  const handlePredict = async () => {
    try {
      const res = await fetch('/api/v1/predictions/predict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          presumed_price: presumedPrice,
          base_price: basePrice,
          category_code: 'Thng',
        }),
      });
      const data = await res.json();
      setPredictionResult(data);
    } catch (err) {
      console.error('Prediction error:', err);
    }
  };

  // 챗봇 SSE 스트리밍 실행
  const handleStreamChat = () => {
    if (!chatQuery.trim()) return;
    setChatStreamText('');
    setRetrievedDocs([]);
    setIsStreaming(true);

    const eventSource = new EventSource(`/api/v1/chatbot/stream?query=${encodeURIComponent(chatQuery)}`);

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'docs') {
          setRetrievedDocs(data.docs);
        } else if (data.type === 'token') {
          setChatStreamText((prev) => prev + data.text);
        } else if (data.type === 'done') {
          setIsStreaming(false);
          eventSource.close();
        }
      } catch (err) {
        console.error('SSE parse error:', err);
      }
    };

    eventSource.onerror = (err) => {
      console.error('SSE error:', err);
      setIsStreaming(false);
      eventSource.close();
    };
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1200px', margin: '0 auto' }}>
      {/* 헤더 */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px', borderBottom: '1px solid #334155', paddingBottom: '16px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '28px', background: 'linear-gradient(to right, #38bdf8, #818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            refac_bid_box
          </h1>
          <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '14px' }}>
            공공조달 입찰 예측 &amp; 하이브리드 RAG 챗봇 MLOps 플랫폼
          </p>
        </div>

        {health && (
          <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '8px 16px', fontSize: '13px', display: 'flex', gap: '16px' }}>
            <div><span style={{ color: '#4ade80' }}>●</span> {health.framework}</div>
            <div><span style={{ color: '#38bdf8' }}>DB:</span> {health.database}</div>
            <div><span style={{ color: '#a78bfa' }}>Queue:</span> {health.task_queue}</div>
          </div>
        )}
      </header>

      {/* 네비게이션 탭 */}
      <nav style={{ display: 'flex', gap: '12px', marginBottom: '24px' }}>
        <button
          onClick={() => setActiveTab('dashboard')}
          style={{
            backgroundColor: activeTab === 'dashboard' ? '#2563eb' : '#1e293b',
            color: '#fff',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          입찰 분석 대시보드
        </button>
        <button
          onClick={() => setActiveTab('prediction')}
          style={{
            backgroundColor: activeTab === 'prediction' ? '#2563eb' : '#1e293b',
            color: '#fff',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          AI 낙찰가 예측
        </button>
        <button
          onClick={() => setActiveTab('chatbot')}
          style={{
            backgroundColor: activeTab === 'chatbot' ? '#2563eb' : '#1e293b',
            color: '#fff',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 600,
          }}
        >
          하이브리드 RAG 챗봇 (SSE)
        </button>
      </nav>

      {/* 본문 콘텐츠 */}
      <main style={{ backgroundColor: '#1e293b', borderRadius: '12px', border: '1px solid #334155', padding: '24px' }}>
        {activeTab === 'dashboard' && (
          <div>
            <h2 style={{ marginTop: 0 }}>입찰 실시간 대시보드</h2>
            <p style={{ color: '#94a3b8' }}>FastAPI 비동기 API 기반 공공조달 입찰 수집 현황 및 통계를 시각화합니다.</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px', marginTop: '20px' }}>
              <div style={{ backgroundColor: '#0f172a', padding: '16px', borderRadius: '8px', border: '1px solid #334155' }}>
                <h4 style={{ margin: '0 0 8px', color: '#94a3b8' }}>수집된 공고 수</h4>
                <span style={{ fontSize: '24px', fontWeight: 'bold', color: '#38bdf8' }}>1,420,891 건</span>
              </div>
              <div style={{ backgroundColor: '#0f172a', padding: '16px', borderRadius: '8px', border: '1px solid #334155' }}>
                <h4 style={{ margin: '0 0 8px', color: '#94a3b8' }}>평균 예측 오차 (MAPE)</h4>
                <span style={{ fontSize: '24px', fontWeight: 'bold', color: '#4ade80' }}>1.42 %</span>
              </div>
              <div style={{ backgroundColor: '#0f172a', padding: '16px', borderRadius: '8px', border: '1px solid #334155' }}>
                <h4 style={{ margin: '0 0 8px', color: '#94a3b8' }}>RAG 지식베이스 (KB)</h4>
                <span style={{ fontSize: '24px', fontWeight: 'bold', color: '#a78bfa' }}>19 컬렉션 (ChromaDB)</span>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'prediction' && (
          <div>
            <h2 style={{ marginTop: 0 }}>AI 낙찰가 예측 시뮬레이터</h2>
            <p style={{ color: '#94a3b8' }}>LightGBM/CatBoost Champion 모델 기반 추론 (Single Source of Truth features.py 적용)</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '500px', marginTop: '20px' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '6px', color: '#cbd5e1' }}>추정가격 (원)</label>
                <input
                  type="number"
                  value={presumedPrice}
                  onChange={(e) => setPresumedPrice(Number(e.target.value))}
                  style={{ width: '100%', padding: '10px', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#fff', borderRadius: '6px' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '6px', color: '#cbd5e1' }}>기초금액 (원)</label>
                <input
                  type="number"
                  value={basePrice}
                  onChange={(e) => setBasePrice(Number(e.target.value))}
                  style={{ width: '100%', padding: '10px', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#fff', borderRadius: '6px' }}
                />
              </div>
              <button
                onClick={handlePredict}
                style={{ backgroundColor: '#10b981', color: '#fff', border: 'none', padding: '12px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, marginTop: '8px' }}
              >
                AI 최적 사투가 예측 실행
              </button>

              {predictionResult && (
                <div style={{ marginTop: '16px', backgroundColor: '#0f172a', padding: '16px', borderRadius: '8px', border: '1px solid #10b981' }}>
                  <h4 style={{ margin: '0 0 8px', color: '#10b981' }}>예측 결과 ({predictionResult.model_version})</h4>
                  <div>예측 사투가: <strong style={{ color: '#38bdf8' }}>{Math.round(predictionResult.predicted_price).toLocaleString()} 원</strong></div>
                  <div>예측 투찰률: <strong style={{ color: '#4ade80' }}>{predictionResult.predicted_rate.toFixed(4)} %</strong></div>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'chatbot' && (
          <div>
            <h2 style={{ marginTop: 0 }}>하이브리드 RAG 챗봇 (SSE 실시간 토큰 스트리밍)</h2>
            <p style={{ color: '#94a3b8' }}>Google Gemini LLM + ChromaDB 비동기 실시간 SSE 토큰 스트리밍</p>
            
            {/* 문서 검색 결과 표시 */}
            {retrievedDocs.length > 0 && (
              <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px', padding: '12px', marginBottom: '16px' }}>
                <h4 style={{ margin: '0 0 8px', color: '#a78bfa', fontSize: '13px' }}>참조 지식문서 ({retrievedDocs.length}건)</h4>
                {retrievedDocs.map((doc, idx) => (
                  <div key={idx} style={{ fontSize: '12px', color: '#94a3b8', marginBottom: '4px' }}>
                    • {doc.title || doc.content} (유사도: {doc.score})
                  </div>
                ))}
              </div>
            )}

            {/* 스트리밍 답변 창 */}
            <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px', padding: '16px', minHeight: '160px', marginBottom: '16px', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
              {chatStreamText ? (
                <span>{chatStreamText}{isStreaming && <span style={{ color: '#38bdf8', animation: 'blink 1s infinite' }}> |</span>}</span>
              ) : (
                <span style={{ color: '#64748b' }}>질문을 입력하고 전송을 누르시면 실시간 SSE 토큰 스트리밍 답변이 시작됩니다.</span>
              )}
            </div>

            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                type="text"
                value={chatQuery}
                onChange={(e) => setChatQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleStreamChat()}
                placeholder="공공조달 적격심사 기준이나 낙찰 확률을 물어보세요..."
                style={{ flex: 1, padding: '12px', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#fff', borderRadius: '6px' }}
              />
              <button
                onClick={handleStreamChat}
                disabled={isStreaming}
                style={{ backgroundColor: isStreaming ? '#475569' : '#6366f1', color: '#fff', border: 'none', padding: '0 24px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600 }}
              >
                {isStreaming ? '스트리밍 중...' : '전송'}
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
