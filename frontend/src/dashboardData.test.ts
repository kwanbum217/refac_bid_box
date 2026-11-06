import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  BIDS_ERROR_MESSAGE,
  COMPARE_STATS_ERROR_MESSAGE,
  STATS_ERROR_MESSAGE,
  buildBidsQuery,
  loadBids,
  loadCompareStats,
  loadStats,
  type CompareStats,
  type DashboardStats,
  type FetchLike,
} from './dashboardData.ts';

const stats: DashboardStats = {
  scope_label: '낙찰 결과',
  total_count: 3,
  total_amount: 1000,
  avg_rate: 88.5,
  latest_collected: null,
  by_agency: [],
  by_company: [],
  by_month: [],
};

const compareStats: CompareStats = {
  announce_count: 10,
  result_count: 3,
  matched_count: 2,
  announce_total_base_amount: 5000,
  result_total_amt: 4000,
};

const respond = (payload: unknown, ok = true): FetchLike => {
  return async () => ({ ok, status: ok ? 200 : 503, json: async () => payload });
};

const reject: FetchLike = async () => {
  throw new Error('network down');
};

test('loadStats returns data on success and an error result on HTTP failure', async () => {
  const success = await loadStats(respond(stats));
  assert.deepEqual(success, { data: stats, error: '' });

  const failure = await loadStats(respond({}, false));
  assert.deepEqual(failure, { data: null, error: STATS_ERROR_MESSAGE });
});

test('loadStats returns an error result when fetch rejects', async () => {
  const result = await loadStats(reject);
  assert.equal(result.data, null);
  assert.equal(result.error, STATS_ERROR_MESSAGE);
});

test('loadCompareStats exposes a distinct error message from the list/stats path', async () => {
  const success = await loadCompareStats(respond(compareStats));
  assert.deepEqual(success, { data: compareStats, error: '' });

  const failure = await loadCompareStats(respond({}, false));
  assert.equal(failure.data, null);
  assert.equal(failure.error, COMPARE_STATS_ERROR_MESSAGE);
  assert.notEqual(failure.error, STATS_ERROR_MESSAGE);
});

test('loadBids distinguishes an empty result from a failed request', async () => {
  const empty = await loadBids('', '', respond({ bids: [] }));
  assert.deepEqual(empty, { bids: [], error: '' });

  const noPayload = await loadBids('', '', respond({}));
  assert.deepEqual(noPayload, { bids: [], error: '' });

  const failure = await loadBids('', '', respond({}, false));
  assert.deepEqual(failure, { bids: [], error: BIDS_ERROR_MESSAGE });
});

test('buildBidsQuery encodes filters and always keeps the first page', () => {
  assert.equal(buildBidsQuery('', ''), '/api/v1/bids?page=1');
  assert.equal(buildBidsQuery('Servc', '노후 관로'), '/api/v1/bids?page=1&cat=Servc&q=%EB%85%B8%ED%9B%84+%EA%B4%80%EB%A1%9C');
});

test('loadBids forwards the built query to fetch', async () => {
  const requested: string[] = [];
  const fetchImpl: FetchLike = async (input) => {
    requested.push(input);
    return { ok: true, status: 200, json: async () => ({ bids: [] }) };
  };

  await loadBids('Thng', '컴퓨터', fetchImpl);

  assert.deepEqual(requested, [buildBidsQuery('Thng', '컴퓨터')]);
});
