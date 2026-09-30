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
}

const MISSING_LABEL = '미제공';

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

export interface RuleInfo {
  tableName: string | null;
  serviceType: string | null;
  baseRate: string | null;
  lwltRate: string | null;
  effectiveDate: string | null;
  source: string | null;
}

// 별표 규칙 값은 백엔드 응답에 실린 것만 읽는다. 프런트에서 수치를 만들지 않는다.
export const extractRuleInfo = (prediction: Record<string, unknown> | null): RuleInfo => {
  const root = prediction ?? {};
  const verdict = pick(root, ['score_verdict', 'scoreVerdict']);
  const rule = pick(root, [
    'evaluation_rule',
    'evaluationRule',
    'applied_rule',
    'appliedRule',
    'rule',
    'formula',
    'formula_rule',
  ]);
  const ruleObject = rule ?? pick(verdict, ['rule', 'evaluation_rule', 'evaluationRule']);
  const sources: unknown[] = [ruleObject, verdict, root];

  const first = (keys: string[]): string | null => {
    for (const source of sources) {
      const value = pick(source, keys);
      if (value !== undefined) return asText(value);
    }
    return null;
  };

  return {
    tableName: first(['table_name', 'tableName', 'rule_name', 'ruleName']),
    serviceType: first(['service_type', 'serviceType']),
    baseRate: first(['base_rate', 'baseRate']),
    lwltRate: first(['lwlt_rate', 'lwltRate', 'lower_bound_rate', 'lowerBoundRate']),
    effectiveDate: first(['effective_date', 'effectiveDate']),
    source: first(['source', 'source_notice', 'sourceNotice']),
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
}: ScoreFormulaCardProps) {
  const rule = extractRuleInfo(prediction);
  const verdict = extractVerdict(prediction);

  const hasRuleInfo = Object.values(rule).some((value) => value !== null);

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

  const formulaRows: { label: string; value: string }[] = [
    { label: '별표명', value: rule.tableName ?? MISSING_LABEL },
    { label: '용역유형', value: rule.serviceType ?? MISSING_LABEL },
    { label: '기준비율', value: rule.baseRate ?? MISSING_LABEL },
    { label: '낙찰하한율', value: rule.lwltRate ?? MISSING_LABEL },
    { label: '시행일', value: rule.effectiveDate ?? MISSING_LABEL },
    { label: '출처고시', value: rule.source ?? MISSING_LABEL },
  ];

  return (
    <div style={CARD_STYLE}>
      <h3 style={{ margin: '0 0 4px', fontSize: '16px', color: '#f8fafc' }}>정량평가 산식과 점수 판정</h3>
      <p style={{ color: '#94a3b8', fontSize: '12px', margin: '0 0 4px' }}>
        조달청 일반용역 적격심사 별표의 기준비율·낙찰하한율과 예측 응답의 점수 판정 필드를 표시합니다.
      </p>

      {/* 카드 1: 적용 산식 */}
      <div style={SECTION_STYLE}>
        <h4 style={SECTION_TITLE_STYLE}>적용 산식</h4>
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
              {hasRuleInfo ? (
                <tr>
                  {formulaRows.map((row) => (
                    <td key={row.label} style={TD_STYLE}>
                      {row.value}
                    </td>
                  ))}
                </tr>
              ) : (
                <tr>
                  <td colSpan={6} style={{ ...TD_STYLE, color: '#94a3b8' }}>
                    백엔드 응답에 별표 규칙 정보가 없어 적용 산식 값을 표시하지 못했습니다.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
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
