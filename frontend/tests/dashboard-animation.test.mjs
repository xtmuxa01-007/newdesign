import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
// Use the CSS parser already bundled with the project's Vite installation.
const postcss = createRequire(import.meta.resolve('vite'))('postcss');

test('dashboard animation keyframes are global so browsers can run star orbits', async () => {
  const css = await readFile(new URL('../src/emerald-dashboard.css', import.meta.url), 'utf8');
  const stylesheet = postcss.parse(css);
  const names = new Set();
  stylesheet.walkAtRules('keyframes', (rule) => {
    assert.equal(rule.parent.type, 'root', `${rule.params} must not be nested inside a selector`);
    names.add(rule.params);
  });
  for (const name of ['glint-card-orbit', 'glint-breathe', 'rim-travel', 'card-reveal']) {
    assert.ok(names.has(name), `${name} must have usable keyframes`);
  }
});
