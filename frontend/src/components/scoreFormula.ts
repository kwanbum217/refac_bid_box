export interface RuleMeta {
  ruleId: string;
  serviceType: string;
  tableName: string;
  description: string;
  effectiveDate: string;
  source: string;
  baseRate: string;
  lwltRate: string;
}

export interface RuleMetaState {
  status: 'loading' | 'ready' | 'error';
  scopeNote: string | null;
  rules: RuleMeta[];
  matchedRule: RuleMeta | null;
}

export const EMPTY_RULE_META: RuleMetaState = {
  status: 'loading',
  scopeNote: null,
  rules: [],
  matchedRule: null,
};

export const RULE_META_ERROR: RuleMetaState = {
  status: 'error',
  scopeNote: null,
  rules: [],
  matchedRule: null,
};

export type FetchLike = (input: string) => Promise<{
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
}>;

export const isBlank = (value: unknown): boolean =>
  value === null || value === undefined || (typeof value === 'string' && value.trim() === '');

export const asText = (value: unknown): string | null => {
  if (isBlank(value)) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : null;
  if (typeof value === 'string') return value.trim();
  return null;
};

export const pick = (source: unknown, keys: string[]): unknown => {
  if (!source || typeof source !== 'object') return undefined;
  const record = source as Record<string, unknown>;
  for (const key of keys) {
    if (!isBlank(record[key])) return record[key];
  }
  return undefined;
};

export const asRecord = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null;

export const readText = (record: Record<string, unknown>, key: string): string => {
  const value = record[key];
  if (value === null || value === undefined) return '';
  return typeof value === 'string' ? value : String(value);
};

// 별표 규칙 값은 /api/v1/evaluations/rules 응답에서만 읽는다. 프런트에서 수치를 만들지 않는다.
// 응답 필드명이 확정됐으므로 여러 후보 키를 훑는 탐색은 두지 않는다.
export const normalizeRuleMeta = (value: unknown): RuleMeta | null => {
  const record = asRecord(value);
  if (!record) return null;
  const ruleId = readText(record, 'rule_id');
  if (ruleId === '') return null;
  return {
    ruleId,
    serviceType: readText(record, 'service_type'),
    tableName: readText(record, 'table_name'),
    description: readText(record, 'description'),
    effectiveDate: readText(record, 'effective_date'),
    source: readText(record, 'source'),
    baseRate: readText(record, 'base_rate'),
    lwltRate: readText(record, 'lwlt_rate'),
  };
};

export const parseRuleMetaState = (data: unknown): RuleMetaState => {
  const record = asRecord(data) ?? {};
  const rawRules = Array.isArray(record.rules) ? record.rules : [];
  const rules: RuleMeta[] = [];
  for (const item of rawRules) {
    const rule = normalizeRuleMeta(item);
    if (rule) rules.push(rule);
  }
  return {
    status: 'ready',
    scopeNote: typeof record.scope_note === 'string' ? record.scope_note : null,
    rules,
    matchedRule: normalizeRuleMeta(record.matched_rule),
  };
};

export const extractVerdict = (
  prediction: Record<string, unknown> | null,
): Record<string, unknown> | null => {
  const verdict = pick(prediction ?? {}, ['score_verdict', 'scoreVerdict']);
  return verdict && typeof verdict === 'object' ? (verdict as Record<string, unknown>) : null;
};

export const readStringList = (source: unknown, keys: string[]): string[] => {
  const value = pick(source, keys);
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    const text = asText(item);
    if (text !== null) out.push(text);
  }
  return out;
};

export const formatWon = (value: unknown): string | null => {
  const text = asText(value);
  if (text === null) return null;
  const number = Number(text);
  if (!Number.isFinite(number)) return null;
  return `${number.toLocaleString('ko-KR')} 원`;
};

export const formatPass = (value: unknown): string | null => {
  if (value === true) return '통과 가능';
  if (value === false) return '통과 불가';
  return null;
};

export const loadRuleMeta = async (
  bidId: number | null,
  fetchImpl: FetchLike = fetch,
): Promise<RuleMetaState> => {
  const query = bidId === null ? '' : `?bid_id=${encodeURIComponent(String(bidId))}`;
  try {
    const res = await fetchImpl(`/api/v1/evaluations/rules${query}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return parseRuleMetaState(await res.json());
  } catch (err) {
    console.error('Rule meta fetch error:', err);
    return RULE_META_ERROR;
  }
};
