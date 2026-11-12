import test from 'node:test';
import assert from 'node:assert/strict';
import { OCEAN_LAYERS, OCEAN_SPEED, OCEAN_STRENGTH, OCEAN_GOLD_THREADS, OCEAN_RESTING_SHADE, oceanThreadVisibility, oceanCardMotion, oceanWaveY, mixOceanColor, prepareOceanPalette, paintOcean } from '../src/ocean-waves.js';
import { natureThemes } from '../src/nature-themes.js';

const rgb = (hex) => [1, 3, 5].map((offset) => parseInt(hex.slice(offset, offset + 2), 16));
const themeOceanPalette = (theme) => ({
  surface: rgb(theme.surface), soft: rgb(theme.tint), highlight: rgb(theme.tint),
  primary: rgb(theme.primary), dark: rgb(theme.deep), bright: rgb(theme.light),
  glow: rgb(theme.glow), edge: rgb(theme.edge),
});
const blendRgb = (a, b, fraction) => a.map((channel, index) =>
  Math.round(channel + (b[index] - channel) * fraction));
const luminance = (channels) => {
  const linear = channels.map((channel) => channel / 255)
    .map((channel) => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
  return linear[0] * .2126 + linear[1] * .7152 + linear[2] * .0722;
};
const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05)
  / (Math.min(luminance(a), luminance(b)) + .05);

function recordingContext() {
  const gradients = [], strokes = [];
  const gradient = (kind) => {
    const result = { kind, stops: [], addColorStop(offset, color) { this.stops.push([offset, color]); } };
    gradients.push(result);
    return result;
  };
  return {
    gradients, strokes,
    createLinearGradient: () => gradient('linear'),
    createRadialGradient: () => gradient('radial'),
    stroke() { strokes.push(this.strokeStyle); },
    fillRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, closePath() {},
    fill() {}, save() {}, restore() {}, translate() {}, rotate() {}, ellipse() {},
  };
}

test('reference ocean uses seven layers at exactly 90 percent strength and double speed', () => {
  assert.equal(OCEAN_STRENGTH, .9);
  assert.equal(OCEAN_SPEED, 2);
  assert.equal(OCEAN_LAYERS.length, 7);
  assert.equal(OCEAN_LAYERS.filter((layer) => layer.gold).length, 1);
  for (const layer of OCEAN_LAYERS) {
    for (const p of [0, .25, .5, .75, 1]) {
      const base = layer.base + layer.slope * p;
      const y = oceanWaveY(p, layer, 0);
      assert.ok(Number.isFinite(y));
      assert.ok(Math.abs(y - base) <= layer.amp * OCEAN_STRENGTH + 1e-9);
    }
    assert.notEqual(oceanWaveY(.5, layer, 0), oceanWaveY(.5, layer, 1 * OCEAN_SPEED));
  }
});

test('light and highlighted cards blend theme colors without changing content', () => {
  assert.equal(mixOceanColor([255, 250, 240], [0, 84, 67], 0), 'rgba(255,250,240,1)');
  assert.equal(mixOceanColor([255, 250, 240], [0, 84, 67], 1), 'rgba(0,84,67,1)');
  assert.equal(mixOceanColor([0, 0, 0], [200, 100, 50], .5, .3), 'rgba(100,50,25,0.3)');
});

test('six gold threads trade visibility while one always remains fully lit', () => {
  assert.equal(OCEAN_GOLD_THREADS.length, 6);
  assert.equal(new Set(OCEAN_GOLD_THREADS.map(({ layer }) => layer)).size, 6);
  for (const { layer, phase } of OCEAN_GOLD_THREADS) {
    assert.ok(Number.isInteger(layer) && layer >= 0 && layer < OCEAN_LAYERS.length);
    assert.ok(Number.isFinite(phase));
  }
  assert.deepEqual(oceanThreadVisibility(0), [1, 0, 0, 0, 0, 0]);
  const visibleCounts = new Set();
  for (let step = 0; step <= 24 * 20; step++) {
    const time = step / 20;
    const opacities = oceanThreadVisibility(time);
    assert.equal(opacities.length, 6);
    for (const opacity of opacities) assert.ok(opacity >= 0 && opacity <= 1);
    assert.ok(Math.max(...opacities) >= .999, `all threads dimmed at ${time}`);
    visibleCounts.add(opacities.filter((opacity) => opacity > .1).length);
    const repeated = oceanThreadVisibility(time + 24);
    for (let index = 0; index < 6; index++) {
      assert.ok(Math.abs(opacities[index] - repeated[index]) < 1e-10);
    }
  }
  assert.deepEqual([...visibleCounts].sort(), [1, 2, 3, 4, 5, 6]);
});

test('gold threads fade continuously without random flicker or a loop-boundary flash', () => {
  for (let order = 0; order < 6; order++) {
    for (let step = 0; step <= 480; step++) {
      const time = step / 20;
      const before = oceanThreadVisibility(time, order);
      assert.deepEqual(oceanThreadVisibility(time, order), before);
      const after = oceanThreadVisibility(time + .001, order);
      const repeated = oceanThreadVisibility(time + 24, order);
      assert.ok(Math.max(...before) >= .999, `order ${order} lost every full-strength thread at ${time}`);
      for (let index = 0; index < 6; index++) {
        assert.ok(before[index] >= 0 && before[index] <= 1);
        assert.ok(Math.abs(after[index] - before[index]) < .01, `thread ${index} flashed at ${time}`);
        assert.ok(Math.abs(before[index] - repeated[index]) < 1e-10);
      }
    }
  }
});

test('different cards get deterministic independent wave phases and thread orders', () => {
  const profiles = Array.from({ length: 12 }, (_, seed) => oceanCardMotion(seed));
  for (const profile of profiles) {
    assert.ok(Number.isFinite(profile.waveOffset));
    assert.ok(Number.isFinite(profile.threadOffset));
    assert.ok(Number.isInteger(profile.threadOrder));
  }
  profiles.forEach((profile, seed) => assert.deepEqual(oceanCardMotion(seed), profile));
  assert.equal(new Set(profiles.map((profile) => JSON.stringify(profile))).size, profiles.length);
  assert.ok(new Set(profiles.map(({ waveOffset }) => waveOffset)).size > 1);
  assert.ok(new Set(profiles.map(({ threadOffset }) => threadOffset)).size > 1);
  assert.ok(new Set(profiles.map(({ threadOrder }) => threadOrder)).size > 1);
  const states = profiles.map(({ threadOffset, threadOrder }) =>
    [0, 3, 8, 14].map((time) => oceanThreadVisibility(time + threadOffset, threadOrder)
      .map((opacity) => Number(opacity.toFixed(6)))));
  assert.ok(new Set(states.map((state) => JSON.stringify(state))).size > 1);
  const waves = profiles.map(({ waveOffset }) =>
    oceanWaveY(.5, OCEAN_LAYERS[0], waveOffset).toFixed(6));
  assert.ok(new Set(waves).size > 1);
});

test('every nature theme shades resting canvas colors 30 percent toward its own primary', () => {
  assert.equal(OCEAN_RESTING_SHADE, .3);
  assert.equal(natureThemes.length, 7);
  for (const theme of natureThemes) {
    const original = themeOceanPalette(theme);
    const snapshot = structuredClone(original);
    Object.values(original).forEach(Object.freeze);
    Object.freeze(original);
    const prepared = prepareOceanPalette(original);
    for (const key of ['surface', 'soft', 'highlight']) {
      assert.deepEqual(prepared.resting[key], blendRgb(original[key], original.primary, .3), `${theme.id}: ${key}`);
      assert.ok(luminance(prepared.resting[key]) < luminance(original[key]), `${theme.id}: ${key} remains lighter`);
    }
    for (const key of Object.keys(original)) assert.deepEqual(prepared[key], original[key]);
    assert.deepEqual(original, snapshot, `${theme.id}: palette input was mutated`);
  }
});

test('reusing or switching prepared palettes never accumulates resting darkening', () => {
  const palettes = natureThemes.map((theme) => prepareOceanPalette(themeOceanPalette(theme)));
  const snapshots = structuredClone(palettes);
  palettes.forEach((palette) => assert.deepEqual(prepareOceanPalette(palette), palette));
  assert.equal(new Set(palettes.map(({ resting }) => JSON.stringify(resting))).size, 7);
  for (let index = natureThemes.length - 1; index >= 0; index--) {
    assert.deepEqual(prepareOceanPalette(themeOceanPalette(natureThemes[index])), snapshots[index]);
  }
  assert.deepEqual(palettes, snapshots);
});

test('resting surfaces retain readable body text and strengthened muted labels in all themes', () => {
  for (const theme of natureThemes) {
    const { resting } = prepareOceanPalette(themeOceanPalette(theme));
    const body = rgb(theme.text);
    // Matches the resting-state CSS label blend: 75% body text, 25% muted.
    const label = blendRgb(body, rgb(theme.muted), .25);
    for (const [name, background] of Object.entries(resting)) {
      assert.ok(contrast(body, background) >= 6, `${theme.id}: body on ${name}`);
      assert.ok(contrast(label, background) >= 4.5, `${theme.id}: label on ${name}`);
    }
  }
});

test('renderer shades resting fills and waves while preserving highlighted colors and gold', () => {
  for (const theme of natureThemes) {
    const palette = prepareOceanPalette(themeOceanPalette(theme));
    const rgba = (channels, alpha = 1) => `rgba(${channels.join(',')},${alpha})`;
    for (const darkMix of [0, .5, 1]) {
      const ctx = recordingContext();
      paintOcean(ctx, { width: 420, height: 220, darkMix, hoverMix: darkMix, pointerX: .5, pointerY: .5 }, palette, 0);
      const color = (light, dark, alpha = 1) => mixOceanColor(light, dark, darkMix, alpha);
      assert.deepEqual(ctx.gradients[0].stops, [
        [0, color(palette.resting.surface, palette.dark)],
        [.45, color(palette.resting.soft, palette.dark)],
        [1, color(palette.resting.surface, palette.bright)],
      ]);
      assert.deepEqual(ctx.gradients[1].stops, [
        [0, color(palette.resting.highlight, palette.glow, .17)],
        [1, color(palette.resting.highlight, palette.glow, 0)],
      ]);
      OCEAN_LAYERS.forEach((layer, index) => {
        assert.deepEqual(ctx.gradients[index + 2].stops, [
          [0, color(index % 2 ? palette.resting.soft : palette.resting.highlight,
            index % 2 ? palette.dark : palette.bright, layer.alpha)],
          [1, color(palette.resting.soft, palette.dark, layer.alpha)],
        ]);
      });
      if (darkMix === 1) {
        assert.deepEqual(ctx.gradients[0].stops, [[0, rgba(palette.dark)], [.45, rgba(palette.dark)], [1, rgba(palette.bright)]]);
        assert.deepEqual(ctx.strokes.slice(0, 3), [
          'rgba(255,202,50,0.025)', 'rgba(255,202,50,0.055)', 'rgba(255,202,50,0.12)',
        ]);
        assert.equal(ctx.strokes[3].stops[2][1], mixOceanColor([255, 224, 119], palette.edge, .2, .95));
      }
    }
  }
});
