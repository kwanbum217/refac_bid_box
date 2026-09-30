import { useEffect, useState } from 'react';
import type { ChangeEvent } from 'react';

export type ScoreTableField = 'maxPriceScore' | 'multiplier' | 'passThreshold' | 'nonPriceScore';

export interface ScoreTableInputs {
  maxPriceScore: string;
  multiplier: string;
  passThreshold: string;
  nonPriceScore: string;
}

export interface ScoreFormulaCardProps {
  prediction: Record<string, unknown> | null;
  scoreTable: ScoreTableInputs;
  onChange: (field: ScoreTableField, value: string) => void;
  onRecalculate: () => void;
  isRecalculating?: boolean;
  bidId?: number | null;
}

const CARD_STYLE = {
  backgroundColor: '#1e293b',
  border: '1px solid #334155',
  borderRadius: '12px',
  padding: '20px',
  marginTop: '20px',
} as const;

const SECTION_STYLE = {
  backgroundColor: '#0f172a',
  border: '1px solid #334155',
  borderRadius: '10px',
  padding: '16px',
  marginTop: '16px',
} as const;

const SECTION_TITLE_STYLE = {
  color: '#38bdf8',
  fontSize: '14px',
  fontWeight: 600,
  margin: '0 0 12px',
} as const;

const TABLE_STYLE = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: '12px',
  textAlign: 'left',
} as const;

const TH_STYLE = {
  padding: '8px 10px',
  backgroundColor: '#1e293b',
  borderBottom: '1px solid #334155',
  color: '#94a3b8',
  fontWeight: 600,
  whiteSpace: 'nowrap',
} as const;

const TD_STYLE = {
  padding: '8px 10px',
  borderBottom: '1px solid #263449',
  color: '#e2e8f0',
} as const;

const ROW_STYLE = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: '12px',
  padding: '6px 0',
  borderBottom: '1px solid #263449',
  fontSize: '12px',
} as const;

const LABEL_STYLE = { color: '#94a3b8' } as const;
const VALUE_STYLE = { color: '#e2e8f0', fontWeight: 600 } as const;

const INPUT_STYLE = {
  width: '100%',
  padding: '8px 10px',
  backgroundColor: '#0f172a',
  border: '1px solid #334155',
  color: '#fff',
  borderRadius: '6px',
  fontSize: '13px',
} as const;

const NOTE_STYLE = {
  color: '#94a3b8',
  fontSize: '12px',
  lineHeight: 1.6,
  margin: '8px 0 0',
} as const;

const SCOPE_NOTE_STYLE = {
  color: '#fbbf24',
  backgroundColor: '#1f2937',
  border: '1px solid #7c5c1a',
  borderRadius: '8px',
  padding: '10px 12px',
  fontSize: '12px',
  lineHeight: 1.6,
  margin: '12px 0 0',
} as const;

const MATCHED_ROW_STYLE = {
  backgroundColor: '#1e3a5f',
} as const;

const isBlank = (value: unknown): boolean =>
  value === null || value === undefined || (typeof value === 'string' && value.trim() === '');

const asText = (value: unknown): string | null => {
  if (isBlank(value)) return null;
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : null;
  if (typeof value === 'string') return value.trim();
  return null;
};

const pick = (source: unknown, keys: string[]): unknown => {
  if (!source || typeof source !== 'object') return undefined;
  const record = source as Record<string, unknown>;
  for (const key of keys) {
    if (!isBlank(record[key])) return record[key];
  }
  return undefined;
};

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

interface RuleMetaState {
  status: 'loading' | 'ready' | 'error';
  scopeNote: string | null;
  rules: RuleMeta[];
  matchedRule: RuleMeta | null;
}

const EMPTY_RULE_META: RuleMetaState = {
  status: 'loading',
  scopeNote: null,
  rules: [],
  matchedRule: null,
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' ? (value as Record<string, unknown>) : null;

const readText = (record: Record<string, unknown>, key: string): string => {
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

const parseRuleMetaState = (data: unknown): RuleMetaState => {
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

const readStringList = (source: unknown, keys: string[]): string[] => {
  const value = pick(source, keys);
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    const text = asText(item);
    if (text !== null) out.push(text);
  }
  return out;
};

const formatWon = (value: unknown): string | null => {
  const text = asText(value);
  if (text === null) return null;
  const number = Number(text);
  if (!Number.isFinite(number)) return null;
  return `${number.toLocaleString('ko-KR')} 원`;
};

const formatPass = (value: unknown): string | null => {
  if (value === true) return '통과 가능';
  if (value === false) return '통과 불가';
  return null;
};

export default function ScoreFormulaCard({
  prediction,
  scoreTable,
  onChange,
  onRecalculate,
  isRecalculating = false,
  bidId = null,
}: ScoreFormulaCardProps) {
  const [ruleMeta, setRuleMeta] = useState<RuleMetaState>(EMPTY_RULE_META);
  const verdict = extractVerdict(prediction);

  // 별표 메타는 카드가 직접 받아 산식 표를 채운다. 실패해도 점수 판정 카드는 그대로 둔다.
  useEffect(() => {
    let cancelled = false;
    const query = bidId === null ? '' : `?bid_id=${encodeURIComponent(String(bidId))}`;
    setRuleMeta((prev) => ({ ...prev, status: 'loading' }));
    fetch(`/api/v1/evaluations/rules${query}`)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data) => {
        if (cancelled) return;
        setRuleMeta(parseRuleMetaState(data));
      })
      .catch((err) => {
        if (cancelled) return;
        console.error('Rule meta fetch error:', err);
        setRuleMeta({ status: 'error', scopeNote: null, rules: [], matchedRule: null });
      });
    return () => {
      cancelled = true;
    };
  }, [bidId]);

  const missingInputs: string[] = [];
  if (isBlank(scoreTable.maxPriceScore)) missingInputs.push('가격 배점한도(B)');
  if (isBlank(scoreTable.multiplier)) missingInputs.push('평점 계수(k)');
  if (isBlank(scoreTable.passThreshold)) missingInputs.push('적격 통과점수(T)');

  const unavailableReasons = readStringList(verdict, ['unavailable_reasons', 'unavailableReasons']);
  const rangeReasons = readStringList(verdict, ['pass_range_reasons', 'passRangeReasons']);

  let verdictTitle: string;
  if (!verdict) {
    verdictTitle = '점수 판정 없음';
  } else if (missingInputs.length > 0) {
    verdictTitle = 'B·k·T 입력 필요';
  } else if (verdict.verifiable !== true) {
    verdictTitle = '판정 확인 불가';
  } else {
    verdictTitle = '';
  }

  const verdictReasons: string[] = [];
  if (!verdict) {
    verdictReasons.push('예측 응답에 점수 판정 필드가 없습니다 (구 모델 또는 백엔드 미연결).');
    if (missingInputs.length > 0) {
      verdictReasons.push(`입력하지 않은 배점표 값: ${missingInputs.join(', ')}`);
    }
  } else if (missingInputs.length > 0) {
    verdictReasons.push(`입력하지 않은 배점표 값: ${missingInputs.join(', ')}`);
    verdictReasons.push('공고문 적격심사 배점표 값을 입력해야 가격평점을 판정할 수 있습니다.');
    verdictReasons.push(...unavailableReasons);
  } else if (verdict.verifiable !== true) {
    verdictReasons.push(...unavailableReasons);
    if (unavailableReasons.length === 0) {
      verdictReasons.push('백엔드가 점수 판정 사유를 주지 않았습니다.');
    }
  }

  const optimalScore = verdict ? asText(verdict.optimal_price_score ?? verdict.optimalPriceScore) : null;
  const passText = verdict ? formatPass(verdict.optimal_price_passes ?? verdict.optimalPricePasses) : null;
  const rangeStatus = verdict ? asText(verdict.pass_range_status ?? verdict.passRangeStatus) : null;
  const rangeLow =
    formatWon(verdict?.effective_amount_low) ??
    formatWon(verdict?.pass_amount_low) ??
    formatWon(verdict?.effectiveAmountLow) ??
    formatWon(verdict?.passAmountLow);
  const rangeHigh =
    formatWon(verdict?.effective_amount_high) ??
    formatWon(verdict?.pass_amount_high) ??
    formatWon(verdict?.effectiveAmountHigh) ??
    formatWon(verdict?.passAmountHigh);
  const hasRange = rangeStatus === 'feasible' && rangeLow !== null && rangeHigh !== null;

  const uncertaintyNote = verdict ? asText(verdict.uncertainty_note ?? verdict.uncertaintyNote) : null;

  const handleInput = (field: ScoreTableField) => (event: ChangeEvent<HTMLInputElement>) =>
    onChange(field, event.target.value);

  return (
    <div style={CARD_STYLE}>
      <h3 style={{ margin: '0 0 4px', fontSize: '16px', color: '#f8fafc' }}>정량평가 산식과 점수 판정</h3>
      <p style={{ color: '#94a3b8', fontSize: '12px', margin: '0 0 4px' }}>
        조달청 일반용역 적격심사 별표의 기준비율·낙찰하한율과 예측 응답의 점수 판정 필드를 표시합니다.
      </p>

      {/* 카드 1: 적용 산식 */}
      <div style={SECTION_STYLE}>
        <h4 style={SECTION_TITLE_STYLE}>일반용역 적격심사 별표</h4>
        {ruleMeta.status === 'loading' && (
          <p style={NOTE_STYLE}>별표 규칙 정보를 불러오는 중입니다.</p>
        )}
        {ruleMeta.status === 'error' && (
          <p style={{ ...NOTE_STYLE, color: '#fca5a5' }}>
            별표 규칙 정보를 불러오지 못했습니다. 예측 결과와 점수 판정은 그대로 표시됩니다.
          </p>
        )}
        {ruleMeta.status === 'ready' && ruleMeta.rules.length === 0 && (
          <p style={NOTE_STYLE}>표시할 별표 규칙이 없습니다.</p>
        )}
        {ruleMeta.rules.length > 0 && (
          <div style={{ overflowX: 'auto' }}>
            <table style={TABLE_STYLE}>
              <thead>
                <tr>
                  <th style={TH_STYLE}>별표명</th>
                  <th style={TH_STYLE}>용역유형</th>
                  <th style={TH_STYLE}>기준비율</th>
                  <th style={TH_STYLE}>낙찰하한율</th>
                  <th style={TH_STYLE}>시행일</th>
                  <th style={TH_STYLE}>출처고시</th>
                </tr>
              </thead>
              <tbody>
                {ruleMeta.rules.map((row) => {
                  const isMatched = ruleMeta.matchedRule?.ruleId === row.ruleId;
                  return (
                    <tr key={row.ruleId} style={isMatched ? MATCHED_ROW_STYLE : undefined}>
                      <td style={TD_STYLE}>
                        {row.tableName}
                        {isMatched ? ' (선택 공고 적용)' : ''}
                      </td>
                      <td style={TD_STYLE}>{row.serviceType}</td>
                      <td style={TD_STYLE}>{row.baseRate}</td>
                      <td style={TD_STYLE}>{row.lwltRate}</td>
                      <td style={TD_STYLE}>{row.effectiveDate}</td>
                      <td style={TD_STYLE}>{row.source}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        {ruleMeta.scopeNote && <p style={SCOPE_NOTE_STYLE}>{ruleMeta.scopeNote}</p>}
      </div>

      {/* 카드 2: 가격평점 판정 */}
      <div style={SECTION_STYLE}>
        <h4 style={SECTION_TITLE_STYLE}>가격평점 판정</h4>

        {verdictTitle ? (
          <div>
            <div style={{ ...ROW_STYLE, borderBottom: 'none' }}>
              <span style={LABEL_STYLE}>판정 상태</span>
              <span style={{ color: '#f59e0b', fontWeight: 600 }}>{verdictTitle}</span>
            </div>
            <ul style={{ margin: '4px 0 0', paddingLeft: '18px', color: '#94a3b8', fontSize: '12px', lineHeight: 1.6 }}>
              {verdictReasons.map((reason, index) => (
                <li key={index}>{reason}</li>
              ))}
            </ul>
          </div>
        ) : (
          <div>
            <div style={ROW_STYLE}>
              <span style={LABEL_STYLE}>추천가 평점</span>
              <span style={VALUE_STYLE}>{optimalScore ?? '계산값 없음'}</span>
            </div>
            <div style={ROW_STYLE}>
              <span style={LABEL_STYLE}>추천가 통과 여부</span>
              <span style={VALUE_STYLE}>{passText ?? '확인 불가'}</span>
            </div>
            {hasRange ? (
              <>
                <div style={ROW_STYLE}>
                  <span style={LABEL_STYLE}>통과 가능 구간 하단</span>
                  <span style={VALUE_STYLE}>{rangeLow}</span>
                </div>
                <div style={ROW_STYLE}>
                  <span style={LABEL_STYLE}>통과 가능 구간 상단</span>
                  <span style={VALUE_STYLE}>{rangeHigh}</span>
                </div>
              </>
            ) : (
              <div style={ROW_STYLE}>
                <span style={LABEL_STYLE}>통과 가능 낙찰가 구간</span>
                <span style={VALUE_STYLE}>구간 없음</span>
              </div>
            )}
            {!hasRange && rangeReasons.length > 0 && (
              <ul style={{ margin: '6px 0 0', paddingLeft: '18px', color: '#94a3b8', fontSize: '12px', lineHeight: 1.6 }}>
                {rangeReasons.map((reason, index) => (
                  <li key={index}>{reason}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      {/* 카드 3: 배점표 입력 */}
      <div style={SECTION_STYLE}>
        <h4 style={SECTION_TITLE_STYLE}>적격심사 배점표 입력</h4>
        <p style={{ color: '#94a3b8', fontSize: '12px', margin: '0 0 12px' }}>
          B·k·T 는 공고 데이터에 없어 공고문 배점표에서 직접 입력합니다. 비우면 판정하지 않습니다.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '12px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '4px', color: '#cbd5e1', fontSize: '12px' }}>
              가격 배점한도 (B) [원]
            </label>
            <input
              type="number"
              inputMode="decimal"
              value={scoreTable.maxPriceScore}
              onChange={handleInput('maxPriceScore')}
              placeholder="공고문 배점표 값"
              style={INPUT_STYLE}
            />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '4px', color: '#cbd5e1', fontSize: '12px' }}>
              평점 계수 (k) [배수]
            </label>
            <input
              type="number"
              inputMode="decimal"
              value={scoreTable.multiplier}
              onChange={handleInput('multiplier')}
              placeholder="공고문 배점표 값"
              style={INPUT_STYLE}
            />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '4px', color: '#cbd5e1', fontSize: '12px' }}>
              적격 통과점수 (T) [점]
            </label>
            <input
              type="number"
              inputMode="decimal"
              value={scoreTable.passThreshold}
              onChange={handleInput('passThreshold')}
              placeholder="공고문 배점표 값"
              style={INPUT_STYLE}
            />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '4px', color: '#cbd5e1', fontSize: '12px' }}>
              비가격 정량점수 합계 (Q) [점]
            </label>
            <input
              type="number"
              inputMode="decimal"
              value={scoreTable.nonPriceScore}
              onChange={handleInput('nonPriceScore')}
              placeholder="미입력 시 0으로 가정"
              style={INPUT_STYLE}
            />
          </div>
        </div>
        <button
          type="button"
          onClick={onRecalculate}
          disabled={isRecalculating}
          style={{
            marginTop: '14px',
            backgroundColor: isRecalculating ? '#334155' : '#2563eb',
            color: '#fff',
            border: 'none',
            padding: '10px 18px',
            borderRadius: '6px',
            cursor: isRecalculating ? 'default' : 'pointer',
            fontWeight: 600,
            fontSize: '13px',
          }}
        >
          {isRecalculating ? '점수 계산 중...' : '점수 다시 계산'}
        </button>
      </div>

      {/* 카드 4: Q=0 가정 안내 (항상 표시) */}
      <div style={{ ...SECTION_STYLE, borderColor: '#7c5c1a', backgroundColor: '#1f2937' }}>
        <h4 style={{ ...SECTION_TITLE_STYLE, color: '#f59e0b' }}>Q=0 가정 안내</h4>
        <p style={{ color: '#e2e8f0', fontSize: '12px', lineHeight: 1.6, margin: 0 }}>
          비가격 정량점수 합계 Q 를 0 으로 가정해 통과 가능 구간을 계산합니다. 실제 수행능력 점수가
          반영되면 구간은 더 좁아지므로, 여기서 보이는 통과 가능 낙찰가 구간은 실제보다 넓을 수 있습니다.
        </p>
        {uncertaintyNote && (
          <p style={{ color: '#fbbf24', fontSize: '12px', lineHeight: 1.6, margin: '8px 0 0' }}>
            {uncertaintyNote}
          </p>
        )}
      </div>
    </div>
  );
}
