import React, { useState, useEffect } from 'react';

interface HealthStatus {
  status: string;
  service: string;
  environment: string;
  framework: string;
  database: string;
  task_queue: string;
}

interface BidNotice {
  id: number;
  bid_ntce_no: string;
  bid_ntce_ord: string;
  bid_ntce_nm: string;
  dminstt_nm: string;
  ntce_instt_nm: string;
  category: string;
  presmpt_prce: number;
  base_amount: number;
  bid_ntce_dt: string;
  category_label?: string;
  prediction_reference_amount?: number | null;
}

interface DashboardStats {
  scope_label: string;
  total_count: number;
  total_amount: number;
  avg_rate: number;
  latest_collected: string | null;
  by_agency: { name: string; total_amt: number; count: number }[];
  by_company: { name: string; total_amt: number; count: number }[];
  by_month: { month: string; count: number }[];
}

interface CompareStats {
  announce_count: number;
  result_count: number;
  matched_count: number;
  announce_total_base_amount: number;
  result_total_amt: number;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'prediction' | 'chatbot'>('dashboard');
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [healthError, setHealthError] = useState<string>('');

  // 대시보드 실집계 (원본 bids/api/stats, api/compare-stats 대응)
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [compareStats, setCompareStats] = useState<CompareStats | null>(null);

  // 공고 목록 및 필터 상태
  const [bids, setBids] = useState<BidNotice[]>([]);
  const [categoryFilter, setCategoryFilter] = useState<string>('');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [isLoadingBids, setIsLoadingBids] = useState<boolean>(false);

  // AI 예측 상태
  const [selectedBid, setSelectedBid] = useState<BidNotice | null>(null);
  const [presumedPrice, setPresumedPrice] = useState<number>(500000000);
  const [basePrice, setBasePrice] = useState<number>(495000000);
  const [categoryCode, setCategoryCode] = useState<string>('Thng');
  const [predictionResult, setPredictionResult] = useState<any>(null);
  const [isPredicting, setIsPredicting] = useState<boolean>(false);

  // 챗봇 스트리밍 상태
  const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'assistant'; text: string; docs?: any[] }[]>([]);
  const [chatInput, setChatInput] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [currentStreamText, setCurrentStreamText] = useState<string>('');
  const [currentDocs, setCurrentDocs] = useState<any[]>([]);

  // 헬스체크, 대시보드 통계, 공고 목록 데이터 로드
  useEffect(() => {
    fetch('/api/v1/health')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        return res.json();
      })
      .then((data) => setHealth(data))
      .catch((err) => {
        // 연결 실패를 정상 상태로 위장하지 않는다. 실패는 실패로 표시한다.
        console.error('Health check error:', err);
        setHealth(null);
        setHealthError(String(err));
      });

    fetch('/api/v1/bids/stats')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data) => setStats(data))
      .catch((err) => console.error('Dashboard stats error:', err));

    fetch('/api/v1/bids/compare-stats')
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data) => setCompareStats(data))
      .catch((err) => console.error('Compare stats error:', err));

    fetchBids();
  }, []);

  const fetchBids = (cat: string = categoryFilter, search: string = searchQuery) => {
    setIsLoadingBids(true);
    const params = new URLSearchParams({ page: '1' });
    if (cat) params.set('cat', cat);
    if (search) params.set('q', search);

    fetch(`/api/v1/bids?${params.toString()}`)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        return res.json();
      })
      .then((data) => {
        setBids(data.bids ?? []);
        setIsLoadingBids(false);
      })
      .catch((err) => {
        console.error('Fetch bids error:', err);
        setBids([]);
        setIsLoadingBids(false);
      });
  };

  const handleCategoryChange = (cat: string) => {
    setCategoryFilter(cat);
    fetchBids(cat, searchQuery);
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    fetchBids(categoryFilter, searchQuery);
  };

  // 공고 선택 후 AI 예측 탭으로 이동 및 자동 입력
  const handleSelectBidForPrediction = (bid: BidNotice) => {
    setSelectedBid(bid);
    // 기초금액이 미수집이면 원본과 동일하게 예측 기준 금액(prediction_reference_amount)으로 대체한다.
    const reference = bid.prediction_reference_amount ?? bid.presmpt_prce ?? 0;
    setPresumedPrice(bid.presmpt_prce || reference);
    setBasePrice(bid.base_amount ?? reference);
    setCategoryCode(bid.category);
    setActiveTab('prediction');
  };

  // AI 사투가 예측 실행
  const handlePredict = async () => {
    setIsPredicting(true);
    try {
      // 공고가 선택된 경우 원본 predict_price_api 경로를 쓴다.
      // 공고명/기관명이 전달돼야 quantum_leap 모델의 업종 판별과 지역 승수가 적용된다.
      if (selectedBid) {
        const res = await fetch('/api/v1/predictions/predict-price', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ bid_id: selectedBid.id, user_price: String(basePrice) }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        setPredictionResult({
          model_version: data.model_name,
          predicted_price: data.optimal_price,
          predicted_rate: data.prediction_rate,
          confidence: data.confidence,
          message: data.message,
        });
        return;
      }

      const res = await fetch('/api/v1/predictions/predict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          presumed_price: presumedPrice,
          base_price: basePrice,
          category_code: categoryCode,
        }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setPredictionResult(await res.json());
    } catch (err) {
      console.error('Prediction error:', err);
      setPredictionResult(null);
    } finally {
      setIsPredicting(false);
    }
  };

  // 챗봇 SSE 스트리밍
  const handleSendChat = () => {
    if (!chatInput.trim() || isStreaming) return;
    const userQ = chatInput.trim();
    setChatMessages((prev) => [...prev, { role: 'user', text: userQ }]);
    setChatInput('');
    setCurrentStreamText('');
    setCurrentDocs([]);
    setIsStreaming(true);

    const eventSource = new EventSource(`/api/v1/chatbot/stream?query=${encodeURIComponent(userQ)}`);

    // 상태 변수는 이 콜백 클로저에 고정되므로 누적은 지역 변수로 처리한다.
    let accumulated = '';
    let accumulatedDocs: any[] = [];

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'docs') {
          accumulatedDocs = data.docs ?? [];
          setCurrentDocs(accumulatedDocs);
        } else if (data.type === 'token') {
          accumulated += data.text;
          setCurrentStreamText(accumulated);
        } else if (data.type === 'done') {
          setIsStreaming(false);
          eventSource.close();
          setChatMessages((prev) => [
            ...prev,
            { role: 'assistant', text: accumulated || '분석이 완료되었습니다.', docs: accumulatedDocs },
          ]);
          setCurrentStreamText('');
          setCurrentDocs([]);
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

  const formatNumber = (value: number) => new Intl.NumberFormat('ko-KR').format(value ?? 0);

  // 값이 없는 것(NULL)과 0원을 구분한다. 미수집 컬럼을 0으로 보여주면 오해를 부른다.
  const formatAmountCell = (value: number | null | undefined) =>
    value === null || value === undefined ? '미수집' : `${formatNumber(Math.round(value))} 원`;

  const formatEok = (value: number) => {
    const amount = Number(value ?? 0);
    if (amount >= 1e12) return `${(amount / 1e12).toFixed(1)}조원`;
    if (amount >= 1e8) return `${(amount / 1e8).toFixed(0)}억원`;
    return `${formatNumber(amount)}원`;
  };

  const categoryNameMap: Record<string, string> = {
    Thng: '물품',
    Servc: '용역',
    Cnstwk: '공사',
    Frgcpt: '외자',
  };

  return (
    <div style={{ padding: '24px', maxWidth: '1280px', margin: '0 auto', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      {/* 상단 헤더 */}
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', borderBottom: '1px solid #334155', paddingBottom: '16px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '26px', background: 'linear-gradient(to right, #38bdf8, #818cf8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            refac_bid_box
          </h1>
          <p style={{ margin: '4px 0 0', color: '#94a3b8', fontSize: '13px' }}>
            조달청 입찰가 예측 &amp; 하이브리드 RAG 챗봇 MLOps 플랫폼 (원본 bid_box 1:1 매핑)
          </p>
        </div>

        {health ? (
          <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', padding: '8px 16px', fontSize: '12px', display: 'flex', gap: '16px' }}>
            <div><span style={{ color: '#4ade80' }}>●</span> {health.framework}</div>
            <div><span style={{ color: '#38bdf8' }}>DB:</span> {health.database}</div>
            <div><span style={{ color: '#a78bfa' }}>Queue:</span> {health.task_queue}</div>
          </div>
        ) : (
          <div style={{ backgroundColor: '#3f1d1d', border: '1px solid #7f1d1d', borderRadius: '8px', padding: '8px 16px', fontSize: '12px', color: '#fca5a5' }}>
            <span style={{ color: '#f87171' }}>●</span> 백엔드 연결 실패 {healthError && `(${healthError})`}
          </div>
        )}
      </header>

      {/* 대시보드 통계 메트릭 카드 4종 (전부 실집계 API 값) */}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '24px' }}>
        <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '10px', padding: '16px' }}>
          <div style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 600 }}>수집된 입찰 공고</div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#38bdf8', marginTop: '4px' }}>
            {compareStats ? `${formatNumber(compareStats.announce_count)} 건` : '집계 중...'}
          </div>
          <div style={{ fontSize: '11px', color: '#4ade80', marginTop: '4px' }}>bid_announcements 실집계</div>
        </div>

        <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '10px', padding: '16px' }}>
          <div style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 600 }}>낙찰 결과</div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#4ade80', marginTop: '4px' }}>
            {stats ? `${formatNumber(stats.total_count)} 건` : '집계 중...'}
          </div>
          <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
            {stats ? stats.scope_label : 'bid_results'}
          </div>
        </div>

        <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '10px', padding: '16px' }}>
          <div style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 600 }}>평균 낙찰률</div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#f59e0b', marginTop: '4px' }}>
            {stats ? `${stats.avg_rate} %` : '집계 중...'}
          </div>
          <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>
            {stats ? `누적 낙찰액 ${formatEok(stats.total_amount)}` : 'sucsf_bid_rate 평균'}
          </div>
        </div>

        <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '10px', padding: '16px' }}>
          <div style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 600 }}>공고 대비 낙찰 매칭</div>
          <div style={{ fontSize: '24px', fontWeight: 'bold', color: '#a78bfa', marginTop: '4px' }}>
            {compareStats ? `${formatNumber(compareStats.matched_count)} 건` : '집계 중...'}
          </div>
          <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px' }}>최근 1년 공고번호 조인</div>
        </div>
      </section>

      {stats && (
        <section style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '24px' }}>
          <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '10px', padding: '16px' }}>
            <div style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 600, marginBottom: '10px' }}>
              수요기관 TOP 5 (최근 1년 낙찰액)
            </div>
            {stats.by_agency.slice(0, 5).map((row) => (
              <div key={row.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', padding: '4px 0', borderBottom: '1px solid #263449' }}>
                <span style={{ color: '#e2e8f0' }}>{row.name}</span>
                <span style={{ color: '#38bdf8' }}>{formatEok(row.total_amt)} / {formatNumber(row.count)}건</span>
              </div>
            ))}
          </div>

          <div style={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '10px', padding: '16px' }}>
            <div style={{ color: '#94a3b8', fontSize: '12px', fontWeight: 600, marginBottom: '10px' }}>
              월별 낙찰 건수 (최근 1년)
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: '6px', height: '120px' }}>
              {stats.by_month.map((row) => {
                const max = Math.max(...stats.by_month.map((m) => m.count), 1);
                return (
                  <div key={row.month} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
                    <div style={{ fontSize: '9px', color: '#64748b' }}>{formatNumber(row.count)}</div>
                    <div style={{ width: '100%', height: `${(row.count / max) * 90}px`, backgroundColor: '#38bdf8', borderRadius: '3px 3px 0 0' }} />
                    <div style={{ fontSize: '9px', color: '#64748b' }}>{row.month.slice(2)}</div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* 네비게이션 탭 */}
      <nav style={{ display: 'flex', gap: '8px', marginBottom: '20px', borderBottom: '1px solid #334155', paddingBottom: '12px' }}>
        <button
          onClick={() => setActiveTab('dashboard')}
          style={{
            backgroundColor: activeTab === 'dashboard' ? '#2563eb' : 'transparent',
            color: activeTab === 'dashboard' ? '#fff' : '#94a3b8',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: '14px',
          }}
        >
          입찰 공고 대시보드
        </button>

        <button
          onClick={() => setActiveTab('prediction')}
          style={{
            backgroundColor: activeTab === 'prediction' ? '#2563eb' : 'transparent',
            color: activeTab === 'prediction' ? '#fff' : '#94a3b8',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: '14px',
          }}
        >
          AI 낙찰가 예측 시뮬레이터
        </button>

        <button
          onClick={() => setActiveTab('chatbot')}
          style={{
            backgroundColor: activeTab === 'chatbot' ? '#2563eb' : 'transparent',
            color: activeTab === 'chatbot' ? '#fff' : '#94a3b8',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 600,
            fontSize: '14px',
          }}
        >
          하이브리드 RAG 챗봇 (SSE 실시간)
        </button>
      </nav>

      {/* 탭 1: 입찰 공고 대시보드 */}
      {activeTab === 'dashboard' && (
        <section style={{ backgroundColor: '#1e293b', borderRadius: '12px', border: '1px solid #334155', padding: '24px' }}>
          {/* 필터 및 검색 컨트롤 */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={() => handleCategoryChange('')}
                style={{
                  backgroundColor: categoryFilter === '' ? '#38bdf8' : '#0f172a',
                  color: categoryFilter === '' ? '#0f172a' : '#94a3b8',
                  border: '1px solid #334155',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '13px',
                }}
              >
                전체
              </button>
              <button
                onClick={() => handleCategoryChange('Thng')}
                style={{
                  backgroundColor: categoryFilter === 'Thng' ? '#38bdf8' : '#0f172a',
                  color: categoryFilter === 'Thng' ? '#0f172a' : '#94a3b8',
                  border: '1px solid #334155',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '13px',
                }}
              >
                물품 (Thng)
              </button>
              <button
                onClick={() => handleCategoryChange('Servc')}
                style={{
                  backgroundColor: categoryFilter === 'Servc' ? '#38bdf8' : '#0f172a',
                  color: categoryFilter === 'Servc' ? '#0f172a' : '#94a3b8',
                  border: '1px solid #334155',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '13px',
                }}
              >
                용역 (Servc)
              </button>
              <button
                onClick={() => handleCategoryChange('Cnstwk')}
                style={{
                  backgroundColor: categoryFilter === 'Cnstwk' ? '#38bdf8' : '#0f172a',
                  color: categoryFilter === 'Cnstwk' ? '#0f172a' : '#94a3b8',
                  border: '1px solid #334155',
                  padding: '6px 14px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '13px',
                }}
              >
                공사 (Cnstwk)
              </button>
            </div>

            <form onSubmit={handleSearchSubmit} style={{ display: 'flex', gap: '8px' }}>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="공고명 또는 수요기관명 검색..."
                style={{ padding: '8px 12px', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#fff', borderRadius: '6px', fontSize: '13px', width: '240px' }}
              />
              <button type="submit" style={{ backgroundColor: '#2563eb', color: '#fff', border: 'none', padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}>
                검색
              </button>
            </form>
          </div>

          {/* 공고 데이터 테이블 */}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px', textAlign: 'left' }}>
              <thead>
                <tr style={{ backgroundColor: '#0f172a', borderBottom: '1px solid #334155', color: '#94a3b8' }}>
                  <th style={{ padding: '12px' }}>입찰공고번호</th>
                  <th style={{ padding: '12px' }}>업무구분</th>
                  <th style={{ padding: '12px' }}>입찰공고명</th>
                  <th style={{ padding: '12px' }}>수요기관명</th>
                  <th style={{ padding: '12px', textAlign: 'right' }}>추정가격 (presmpt_prce)</th>
                  <th style={{ padding: '12px', textAlign: 'right' }}>기초금액 (base_amount)</th>
                  <th style={{ padding: '12px', textAlign: 'center' }}>AI 사투가 예측</th>
                </tr>
              </thead>
              <tbody>
                {isLoadingBids ? (
                  <tr>
                    <td colSpan={7} style={{ padding: '32px', textAlign: 'center', color: '#94a3b8' }}>
                      bid_announcements 데이터를 로딩 중입니다...
                    </td>
                  </tr>
                ) : bids.length === 0 ? (
                  <tr>
                    <td colSpan={7} style={{ padding: '32px', textAlign: 'center', color: '#94a3b8' }}>
                      검색 조건에 일치하는 입찰 공고가 없습니다.
                    </td>
                  </tr>
                ) : (
                  bids.map((bid) => (
                    <tr key={bid.id} style={{ borderBottom: '1px solid #334155' }}>
                      <td style={{ padding: '12px', color: '#38bdf8', fontFamily: 'monospace' }}>{bid.bid_ntce_no}</td>
                      <td style={{ padding: '12px' }}>
                        <span
                          style={{
                            padding: '2px 8px',
                            borderRadius: '4px',
                            fontSize: '11px',
                            fontWeight: 600,
                            backgroundColor: bid.category === 'Thng' ? '#1e1b4b' : bid.category === 'Servc' ? '#064e3b' : '#451a03',
                            color: bid.category === 'Thng' ? '#818cf8' : bid.category === 'Servc' ? '#34d399' : '#fb923c',
                            border: `1px solid ${bid.category === 'Thng' ? '#4338ca' : bid.category === 'Servc' ? '#059669' : '#b45309'}`,
                          }}
                        >
                          {categoryNameMap[bid.category] || bid.category}
                        </span>
                      </td>
                      <td style={{ padding: '12px', color: '#f8fafc', fontWeight: 500 }}>{bid.bid_ntce_nm}</td>
                      <td style={{ padding: '12px', color: '#cbd5e1' }}>{bid.dminstt_nm}</td>
                      <td style={{ padding: '12px', textAlign: 'right', color: '#cbd5e1' }}>{formatAmountCell(bid.presmpt_prce)}</td>
                      <td style={{ padding: '12px', textAlign: 'right', color: '#38bdf8', fontWeight: 600 }}>{formatAmountCell(bid.base_amount)}</td>
                      <td style={{ padding: '12px', textAlign: 'center' }}>
                        <button
                          onClick={() => handleSelectBidForPrediction(bid)}
                          style={{ backgroundColor: '#10b981', color: '#fff', border: 'none', padding: '6px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '12px', fontWeight: 600 }}
                        >
                          예측하기
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* 탭 2: AI 낙찰가 예측 시뮬레이터 */}
      {activeTab === 'prediction' && (
        <section style={{ backgroundColor: '#1e293b', borderRadius: '12px', border: '1px solid #334155', padding: '24px' }}>
          <h2 style={{ marginTop: 0, fontSize: '20px' }}>AI 최적 사투가 예측 시뮬레이터</h2>
          <p style={{ color: '#94a3b8', fontSize: '14px' }}>
            Single Source of Truth (<code style={{ color: '#38bdf8' }}>src/ml/features.py</code>) 52차원 단일 특징 산출 연동
          </p>

          {selectedBid && (
            <div style={{ backgroundColor: '#0f172a', padding: '12px 16px', borderRadius: '8px', border: '1px solid #38bdf8', marginBottom: '20px', fontSize: '13px' }}>
              <span style={{ color: '#38bdf8', fontWeight: 600 }}>선택된 공고:</span> {selectedBid.bid_ntce_nm} ({selectedBid.bid_ntce_no}) — <strong style={{ color: '#4ade80' }}>{selectedBid.dminstt_nm}</strong>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '6px', color: '#cbd5e1', fontSize: '13px' }}>추정가격 presmpt_prce (원)</label>
                <input
                  type="number"
                  value={presumedPrice}
                  onChange={(e) => setPresumedPrice(Number(e.target.value))}
                  style={{ width: '100%', padding: '10px', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#fff', borderRadius: '6px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '6px', color: '#cbd5e1', fontSize: '13px' }}>기초금액 base_amount (원)</label>
                <input
                  type="number"
                  value={basePrice}
                  onChange={(e) => setBasePrice(Number(e.target.value))}
                  style={{ width: '100%', padding: '10px', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#fff', borderRadius: '6px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', marginBottom: '6px', color: '#cbd5e1', fontSize: '13px' }}>업무구분 category</label>
                <select
                  value={categoryCode}
                  onChange={(e) => setCategoryCode(e.target.value)}
                  style={{ width: '100%', padding: '10px', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#fff', borderRadius: '6px' }}
                >
                  <option value="Thng">물품 (Thng)</option>
                  <option value="Servc">용역 (Servc)</option>
                  <option value="Cnstwk">공사 (Cnstwk)</option>
                  <option value="Frgcpt">외자 (Frgcpt)</option>
                </select>
              </div>

              <button
                onClick={handlePredict}
                disabled={isPredicting}
                style={{ backgroundColor: '#10b981', color: '#fff', border: 'none', padding: '12px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, fontSize: '14px', marginTop: '8px' }}
              >
                {isPredicting ? 'AI 최적 사투가 계산 중...' : 'AI 최적 사투가 예측 실행'}
              </button>
            </div>

            {/* 예측 결과 표시 창 */}
            <div>
              {predictionResult ? (
                <div style={{ backgroundColor: '#0f172a', padding: '20px', borderRadius: '10px', border: '1px solid #10b981' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <h3 style={{ margin: 0, color: '#10b981', fontSize: '16px' }}>AI 최적 사투가 산출 결과</h3>
                    <span style={{ fontSize: '11px', backgroundColor: '#064e3b', color: '#34d399', padding: '2px 8px', borderRadius: '4px' }}>
                      {predictionResult.model_version}
                    </span>
                  </div>

                  <div style={{ marginBottom: '16px', paddingBottom: '16px', borderBottom: '1px solid #334155' }}>
                    <div style={{ color: '#94a3b8', fontSize: '12px' }}>AI 추천 최적 사투가</div>
                    <div style={{ fontSize: '28px', fontWeight: 'bold', color: '#38bdf8', marginTop: '4px' }}>
                      {Math.round(predictionResult.predicted_price).toLocaleString()} 원
                    </div>
                  </div>

                  <div style={{ marginBottom: '16px', paddingBottom: '16px', borderBottom: '1px solid #334155' }}>
                    <div style={{ color: '#94a3b8', fontSize: '12px' }}>AI 예측 투찰률</div>
                    <div style={{ fontSize: '22px', fontWeight: 'bold', color: '#4ade80', marginTop: '4px' }}>
                      {predictionResult.predicted_rate.toFixed(4)} %
                    </div>
                  </div>

                  <div>
                    <div style={{ color: '#94a3b8', fontSize: '12px', marginBottom: '8px' }}>산출에 사용된 핵심 특징 (features.py)</div>
                    <pre style={{ backgroundColor: '#1e293b', padding: '12px', borderRadius: '6px', fontSize: '11px', color: '#a78bfa', margin: 0, overflowX: 'auto' }}>
                      {JSON.stringify(predictionResult.features_used, null, 2)}
                    </pre>
                  </div>
                </div>
              ) : (
                <div style={{ backgroundColor: '#0f172a', padding: '32px', borderRadius: '10px', border: '1px dashed #334155', textAlign: 'center', color: '#64748b', height: '100%', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
                  좌측 공고 정보 입력 후 'AI 최적 사투가 예측 실행'을 누르시면 LightGBM/CatBoost Champion 모델 기반 추론 결과가 시각화됩니다.
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {/* 탭 3: 하이브리드 RAG 챗봇 */}
      {activeTab === 'chatbot' && (
        <section style={{ backgroundColor: '#1e293b', borderRadius: '12px', border: '1px solid #334155', padding: '24px' }}>
          <h2 style={{ marginTop: 0, fontSize: '20px' }}>하이브리드 RAG 챗봇 (Ollama gemma4:e4b + ChromaDB)</h2>
          <p style={{ color: '#94a3b8', fontSize: '14px', marginBottom: '20px' }}>
            ChromaDB 19개 지식베이스 비동기 검색 및 실시간 SSE 토큰 스트리밍
          </p>

          {/* 대화 내역 창 */}
          <div style={{ backgroundColor: '#0f172a', border: '1px solid #334155', borderRadius: '8px', padding: '16px', height: '360px', overflowY: 'auto', marginBottom: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {chatMessages.length === 0 && !currentStreamText && (
              <div style={{ textAlign: 'center', color: '#64748b', margin: 'auto' }}>
                공공조달 적격심사 세부기준, 낙찰 확률, 법률 조항 등을 질문해 보세요.
              </div>
            )}

            {chatMessages.map((msg, idx) => (
              <div key={idx} style={{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '80%' }}>
                <div
                  style={{
                    backgroundColor: msg.role === 'user' ? '#2563eb' : '#1e293b',
                    color: '#fff',
                    padding: '10px 14px',
                    borderRadius: '10px',
                    border: msg.role === 'assistant' ? '1px solid #334155' : 'none',
                    fontSize: '13px',
                    lineHeight: 1.5,
                  }}
                >
                  {msg.text}
                </div>
              </div>
            ))}

            {/* 스트리밍 중인 답변 */}
            {isStreaming && (
              <div style={{ alignSelf: 'flex-start', maxWidth: '80%' }}>
                {currentDocs.length > 0 && (
                  <div style={{ marginBottom: '6px', fontSize: '11px', color: '#a78bfa' }}>
                    참조 문서 {currentDocs.length}건 검색 완료
                  </div>
                )}
                <div style={{ backgroundColor: '#1e293b', border: '1px solid #38bdf8', color: '#fff', padding: '10px 14px', borderRadius: '10px', fontSize: '13px', lineHeight: 1.5 }}>
                  {currentStreamText || '지식베이스 검색 및 스트리밍 답변 생성 중...'}
                  <span style={{ color: '#38bdf8', animation: 'blink 1s infinite' }}> |</span>
                </div>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendChat()}
              placeholder="예: 물품구매 적격심사 입찰가격 평점산식을 설명해줘"
              style={{ flex: 1, padding: '12px', backgroundColor: '#0f172a', border: '1px solid #334155', color: '#fff', borderRadius: '6px', fontSize: '13px' }}
            />
            <button
              onClick={handleSendChat}
              disabled={isStreaming}
              style={{ backgroundColor: isStreaming ? '#475569' : '#6366f1', color: '#fff', border: 'none', padding: '0 24px', borderRadius: '6px', cursor: 'pointer', fontWeight: 600, fontSize: '13px' }}
            >
              {isStreaming ? '전송 중' : '전송'}
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
