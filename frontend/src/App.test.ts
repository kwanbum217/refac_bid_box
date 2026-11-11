/**
 * React 앱이 투찰가 예측 불확실성 경고를 화면에 표시하는지 고정합니다.
 *
 * npm test 는 node --experimental-strip-types 로 돌기 때문에 JSX 를 변환하지
 * 못한다. 그래서 App.tsx 를 import 해 렌더할 수 없고, 렌더 구조를 소스 수준에서
 * 단언한다. 경고 문구가 사라지거나 조건이 뒤집히면 이 시험이 먼저 깨진다.
 */

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('./App.tsx', import.meta.url), 'utf8');

const WARNING_FIELDS = [
  'extreme_prediction_warning',
  'wide_interval_warning',
  'lwlt_missing',
  'uncertainty_warning',
];

test('predict-price 응답의 경고 4필드를 결과 타입에 담는다', () => {
  for (const field of WARNING_FIELDS) {
    assert.ok(source.includes(field), `PredictionResult 에 ${field} 가 없습니다`);
  }
});

test('extreme_prediction_warning 이면 경계값 근접 경고 문구를 그린다', () => {
  assert.ok(source.includes('if (prediction.extreme_prediction_warning) messages.push'));
  assert.ok(source.includes('모델 예측이 경계값에 가까워 신뢰도가 낮습니다'));
});

test('uncertainty_warning 문자열을 그대로 화면에 그린다', () => {
  assert.ok(source.includes('if (prediction.uncertainty_warning) messages.push'));
  assert.ok(source.includes('{predictionWarnings.map((warning)'));
});

test('wide_interval_warning 과 lwlt_missing 은 배지로 표시한다', () => {
  assert.ok(source.includes('if (prediction.wide_interval_warning) badges.push'));
  assert.ok(source.includes('if (prediction.lwlt_missing) badges.push'));
  assert.ok(source.includes('{predictionWarningBadgeList.map((badge)'));
});

test('경고가 하나도 없으면 경고 영역을 그리지 않는다', () => {
  assert.ok(
    source.includes('(predictionWarnings.length > 0 || predictionWarningBadgeList.length > 0) &&'),
    '경고 유무 조건 없이 영역을 항상 그립니다',
  );
});

test('경고 문구를 HTML 로 주입하지 않는다', () => {
  assert.ok(!source.includes('dangerouslySetInnerHTML'));
});
