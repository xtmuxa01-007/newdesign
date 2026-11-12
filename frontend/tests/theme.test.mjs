import test from 'node:test';
import assert from 'node:assert/strict';
import { applyTheme, colors, defaults, presets, readTheme } from '../src/theme.js';

test('every theme updates all palette colors and keeps magical artwork enabled', () => {
  const previous = globalThis.document;
  const properties = new Map();
  const root = { dataset: {}, style: { setProperty: (key, value) => properties.set(key, value) } };
  globalThis.document = { documentElement: root };
  try {
    for (const { palette } of presets) {
      applyTheme(palette);
      for (const [key] of colors) assert.equal(properties.get(`--${key}`), palette[key]);
      assert.equal(root.dataset.magicTheme, 'custom');
      assert.ok(Number.isFinite(parseFloat(properties.get('--magic-art-hue'))));
      const saturation = Number(properties.get('--magic-art-saturation'));
      assert.ok(saturation >= 0 && saturation <= 1);
    }
    applyTheme(defaults);
    assert.equal(root.dataset.magicTheme, 'custom');
    for (const [key] of colors) assert.equal(properties.get(`--${key}`), defaults[key]);
    applyTheme({ ...defaults, green: 'url(invalid)' });
    assert.equal(properties.get('--green'), defaults.green);
    assert.equal(root.dataset.magicTheme, 'custom');
    applyTheme({ ...defaults, green: '#8844aa' });
    assert.equal(root.dataset.magicTheme, 'custom');
    assert.equal(properties.get('--green'), '#8844aa');
  } finally {
    if (previous === undefined) delete globalThis.document;
    else globalThis.document = previous;
  }
});

test('saved preset upgrades to its distinct nature replacement while personal colors stay intact', () => {
  const oldSky = { ...defaults, field: '#ffffff', page: '#eaf2fb', surface: '#fcfdff', sidebar: '#1b3656', topbar: '#25486e',
    'sidebar-text': '#edf6ff', 'topbar-text': '#edf6ff', 'nav-active': '#b8ddff', 'nav-active-text': '#163650',
    text: '#253c50', muted: '#53687c', heading: '#193e60', green: '#246397', 'green-hover': '#184d79',
    soft: '#dfedf9', border: '#bfd2e4', accent: '#245b88', 'accent-text': '#ffffff', table: '#e9f1f9', summary: '#d8e8f7' };
  for (const key of ['wave-light', 'wave-glow', 'wave-edge']) delete oldSky[key];
  const previous = globalThis.localStorage;
  const stored = new Map([['crm-theme-fixture', JSON.stringify(oldSky)],
    ['crm-theme-fixture-gold-v1', '1'], ['crm-theme-fixture-tin-v1', '1']]);
  globalThis.localStorage = { getItem: (key) => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) };
  try {
    const expected = presets.find(({ id }) => id === 'ice').palette;
    assert.deepEqual(readTheme('fixture'), expected);
    assert.deepEqual(JSON.parse(stored.get('crm-theme-fixture')), expected);
    assert.deepEqual(readTheme('fixture'), expected);
    const removedLavender = { ...oldSky, page: '#f5efff', surface: '#fefcff', sidebar: '#462868', topbar: '#633b90',
      'sidebar-text': '#f8efff', 'topbar-text': '#fbf4ff', 'nav-active': '#e0c4ff', 'nav-active-text': '#48246d',
      text: '#4b3565', muted: '#79618d', heading: '#542b79', green: '#8446bd', 'green-hover': '#653193',
      soft: '#efe1ff', border: '#d1b1ec', accent: '#7436a8', table: '#f2e7ff', summary: '#e2cafa' };
    stored.set('crm-theme-fixture', JSON.stringify(removedLavender));
    assert.deepEqual(readTheme('fixture'), presets.find(({ id }) => id === 'cosmic').palette);
    const custom = { ...oldSky, green: '#8844aa' };
    stored.set('crm-theme-fixture', JSON.stringify(custom));
    assert.deepEqual(readTheme('fixture'), { ...defaults, ...custom });
  } finally {
    if (previous === undefined) delete globalThis.localStorage;
    else globalThis.localStorage = previous;
  }
});

test('only seven distinct nature themes are selectable with separate luminous wave colors', () => {
  assert.deepEqual(presets.map(({ id }) => id), ['cosmic', 'ice', 'ocean', 'earth', 'sun', 'night', 'emerald']);
  assert.equal(new Set(presets.map(({ palette }) => palette.green)).size, 7);
  assert.equal(new Set(presets.map(({ palette }) => palette['wave-glow'])).size, 7);
  assert.deepEqual(defaults, presets.find(({ id }) => id === 'emerald').palette);
  for (const { palette } of presets) {
    assert.deepEqual(Object.keys(palette).sort(), colors.map(([key]) => key).sort());
    for (const value of Object.values(palette)) assert.match(value, /^#[a-f0-9]{6}$/);
  }
});

test('vivid themes keep readable text and notification button contrast', () => {
  const luminance = (hex) => {
    const channels = [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255)
      .map((v) => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
    return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
  };
  const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
  for (const { id, palette } of presets) {
    assert.ok(luminance(palette.page) > .85, `${id} page stays bright`);
    for (const [foreground, background] of [['text', 'surface'], ['button-text', 'green'], ['accent-text', 'accent'], ['topbar-text', 'topbar']]) {
      assert.ok(contrast(palette[foreground], palette[background]) >= 4.5, `${id}: ${foreground} on ${background}`);
    }
  }
});
