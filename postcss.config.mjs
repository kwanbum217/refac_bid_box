import tailwindcss from '@tailwindcss/postcss';

// Tailwind CSS 4 는 space-x-* / space-y-* 를 `:where(... > :not(:last-child))` 선택자와
// 논리 프로퍼티(margin-block-*, margin-inline-*)로 생성한다. 이 저장소의 화면은 bootstrap
// 과 daisyui 를 함께 쓰고, v3 산출물과 같은 캐스케이드 결과를 내야 한다. `:where()` 는
// 명시도가 0 이고 margin-side 가 v3 와 달라 flex/grid 배치에서 간격이 어긋난다. 입력 CSS
// 에서 같은 이름의 @utility 를 다시 정의하면 내장 규칙과 병존해 간격이 두 배가 되므로,
// 생성된 space 규칙을 v3 의 선택자/물리 프로퍼티 형태로 직접 변환한다.
const rewriteSpaceBetweenToV3 = () => ({
  postcssPlugin: 'rewrite-space-between-to-v3',
  Once(root) {
    root.walkRules((rule) => {
      const { selector } = rule;
      if (!/^:where\(.*\)$/s.test(selector) || !selector.includes(':last-child')) {
        return;
      }
      const isY = selector.includes('space-y-');
      const isX = selector.includes('space-x-');
      if (!isY && !isX) {
        return;
      }
      const nodes = rule.nodes ?? [];
      const expectedPrefix = isY ? 'margin-block-' : 'margin-inline-';
      if (!nodes.some((node) => node.type === 'decl' && node.prop.startsWith(expectedPrefix))) {
        return;
      }

      rule.selector = selector
        .replace(/^:where\((.*)\)$/s, '$1')
        .replace(/>\s*:not\(:last-child\)/, '>:not([hidden])~:not([hidden])');

      for (const node of nodes) {
        if (node.type !== 'decl') {
          continue;
        }
        if (node.prop === 'margin-block-start') {
          node.prop = 'margin-bottom';
        } else if (node.prop === 'margin-block-end') {
          node.prop = 'margin-top';
        } else if (node.prop === 'margin-inline-start') {
          node.prop = 'margin-right';
        } else if (node.prop === 'margin-inline-end') {
          node.prop = 'margin-left';
        }
      }
    });
  },
});
rewriteSpaceBetweenToV3.postcss = true;

// Tailwind CSS 4 는 @property 초기값 폴백을 `@layer properties` 블록에 담아 낸다. v3
// 산출물에는 @layer 선언이 0개였고, 레이어 안 규칙은 같은 화면의 bootstrap·daisyui
// (레이어 밖)에 항상 우선순위를 내준다. 캐스케이드를 v3 와 같게 만들기 위해 블록형
// @layer 는 내용만 남기고 풀고, 선언형(@layer a,b;)은 지운다. 규칙 순서는 유지한다.
const unwrapCascadeLayers = () => ({
  postcssPlugin: 'unwrap-cascade-layers',
  Once(root) {
    root.walkAtRules('layer', (atRule) => {
      if (atRule.nodes) {
        atRule.replaceWith(...atRule.nodes);
      } else {
        atRule.remove();
      }
    });
  },
});
unwrapCascadeLayers.postcss = true;

export default {
  plugins: [
    tailwindcss({ optimize: { minify: true } }),
    unwrapCascadeLayers(),
    rewriteSpaceBetweenToV3(),
  ],
};
