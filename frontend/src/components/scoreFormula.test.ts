import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  extractVerdict,
  formatPass,
  formatWon,
  loadRuleMeta,
  normalizeRuleMeta,
  parseRuleMetaState,
  type FetchLike,
} from './scoreFormula.ts';

const fetchJson = (payload: unknown, ok = true): FetchLike => {
  return async () => ({ ok, status: ok ? 200 : 500, json: async () => payload });
};

test('normalizeRuleMeta maps rule fields and drops entries without rule_id', () => {
  const rule = normalizeRuleMeta({
    rule_id: 'servc-general',
    service_type: '일반용역',
    table_name: '별표 1',
    description: '적격심사',
    effective_date: '2026-01-01',
    source: '조달청 고시',
    base_rate: '0.9',
    lwlt_rate: '0.8',
  });

  assert.deepEqual(rule, {
    ruleId: 'servc-general',
    serviceType: '일반용역',
    tableName: '별표 1',
    description: '적격심사',
    effectiveDate: '2026-01-01',
    source: '조달청 고시',
    baseRate: '0.9',
    lwltRate: '0.8',
  });

  assert.equal(normalizeRuleMeta({ service_type: '일반용역' }), null);
  assert.equal(normalizeRuleMeta(null), null);
  assert.equal(normalizeRuleMeta('rule'), null);
});

test('parseRuleMetaState keeps only valid rules and reads scope/matched metadata', () => {
  const state = parseRuleMetaState({
    scope_note: '용역 범위',
    rules: [{ rule_id: 'a' }, { rule_id: '' }, null, { rule_id: 2 }],
    matched_rule: { rule_id: 'a' },
  });

  assert.equal(state.status, 'ready');
  assert.equal(state.scopeNote, '용역 범위');
  assert.deepEqual(state.rules.map((rule) => rule.ruleId), ['a', '2']);
  assert.equal(state.matchedRule?.ruleId, 'a');
});

test('parseRuleMetaState degrades to empty metadata for an unexpected payload', () => {
  const state = parseRuleMetaState(null);

  assert.equal(state.status, 'ready');
  assert.equal(state.scopeNote, null);
  assert.deepEqual(state.rules, []);
  assert.equal(state.matchedRule, null);
});

test('extractVerdict reads score_verdict and ignores non-object values', () => {
  assert.deepEqual(extractVerdict({ score_verdict: { verifiable: true } }), { verifiable: true });
  assert.deepEqual(extractVerdict({ scoreVerdict: { verifiable: false } }), { verifiable: false });
  assert.equal(extractVerdict({ score_verdict: 'none' }), null);
  assert.equal(extractVerdict(null), null);
});

test('format helpers distinguish missing, zero and invalid values', () => {
  assert.equal(formatWon(1234567), '1,234,567 원');
  assert.equal(formatWon(0), '0 원');
  assert.equal(formatWon(null), null);
  assert.equal(formatWon('not-a-number'), null);

  assert.equal(formatPass(true), '통과 가능');
  assert.equal(formatPass(false), '통과 불가');
  assert.equal(formatPass(undefined), null);
});

test('loadRuleMeta returns parsed rules and appends the bid filter', async () => {
  const requested: string[] = [];
  const fetchImpl: FetchLike = async (input) => {
    requested.push(input);
    return {
      ok: true,
      status: 200,
      json: async () => ({ rules: [{ rule_id: 'rule-1' }], scope_note: '안내' }),
    };
  };

  const state = await loadRuleMeta(42, fetchImpl);

  assert.deepEqual(requested, ['/api/v1/evaluations/rules?bid_id=42']);
  assert.equal(state.status, 'ready');
  assert.equal(state.scopeNote, '안내');
  assert.deepEqual(state.rules.map((rule) => rule.ruleId), ['rule-1']);
});

test('loadRuleMeta reports an error state when the response is not ok', async (t) => {
  t.mock.method(console, 'error', () => {});

  const state = await loadRuleMeta(null, fetchJson({}, false));

  assert.equal(state.status, 'error');
  assert.deepEqual(state.rules, []);
  assert.equal(state.matchedRule, null);
});

test('loadRuleMeta reports an error state when the request rejects', async (t) => {
  t.mock.method(console, 'error', () => {});
  const fetchImpl: FetchLike = async () => {
    throw new Error('network down');
  };

  const state = await loadRuleMeta(7, fetchImpl);

  assert.equal(state.status, 'error');
  assert.equal(state.scopeNote, null);
});
