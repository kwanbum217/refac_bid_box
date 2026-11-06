export interface BidNotice {
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

export interface DashboardStats {
  scope_label: string;
  total_count: number;
  total_amount: number;
  avg_rate: number;
  latest_collected: string | null;
  by_agency: { name: string; total_amt: number; count: number }[];
  by_company: { name: string; total_amt: number; count: number }[];
  by_month: { month: string; count: number }[];
}

export interface CompareStats {
  announce_count: number;
  result_count: number;
  matched_count: number;
  announce_total_base_amount: number;
  result_total_amt: number;
}

export interface StatsLoadResult<T> {
  data: T | null;
  error: string;
}

export interface BidsLoadResult {
  bids: BidNotice[];
  error: string;
}

export type FetchLike = (input: string) => Promise<{
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}>;

export const STATS_ERROR_MESSAGE = '통계를 불러오지 못했습니다.';
export const COMPARE_STATS_ERROR_MESSAGE = '비교 통계를 불러오지 못했습니다.';
export const BIDS_ERROR_MESSAGE = '입찰 공고 목록을 불러오지 못했습니다.';
export const BIDS_EMPTY_MESSAGE = '검색 조건에 일치하는 입찰 공고가 없습니다.';

const fetchJson = async <T>(url: string, fetchImpl: FetchLike): Promise<T> => {
  const res = await fetchImpl(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as T;
};

export const loadStats = async (
  fetchImpl: FetchLike = fetch,
): Promise<StatsLoadResult<DashboardStats>> => {
  try {
    const data = await fetchJson<DashboardStats>('/api/v1/bids/stats', fetchImpl);
    return { data, error: '' };
  } catch {
    return { data: null, error: STATS_ERROR_MESSAGE };
  }
};

export const loadCompareStats = async (
  fetchImpl: FetchLike = fetch,
): Promise<StatsLoadResult<CompareStats>> => {
  try {
    const data = await fetchJson<CompareStats>('/api/v1/bids/compare-stats', fetchImpl);
    return { data, error: '' };
  } catch {
    return { data: null, error: COMPARE_STATS_ERROR_MESSAGE };
  }
};

export const buildBidsQuery = (category: string, search: string): string => {
  const params = new URLSearchParams({ page: '1' });
  if (category) params.set('cat', category);
  if (search) params.set('q', search);
  return `/api/v1/bids?${params.toString()}`;
};

export const loadBids = async (
  category: string,
  search: string,
  fetchImpl: FetchLike = fetch,
): Promise<BidsLoadResult> => {
  try {
    const data = await fetchJson<{ bids?: BidNotice[] }>(
      buildBidsQuery(category, search),
      fetchImpl,
    );
    return { bids: data.bids ?? [], error: '' };
  } catch {
    return { bids: [], error: BIDS_ERROR_MESSAGE };
  }
};
