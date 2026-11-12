// Wave geometry adapted from the user's emerald-ocean-card.html reference.
export const OCEAN_STRENGTH = 0.9;
export const OCEAN_SPEED = 2;
export const OCEAN_RESTING_SHADE = 0.3;
const RESTING_GOLD_STRENGTH = 0.65;
export const OCEAN_LAYERS = [
  { base: 0.67, slope: -0.54, amp: 0.12, freq: 1.04, rate: 0.55, phase: 0.2, alpha: 0.3 },
  { base: 0.82, slope: -0.43, amp: 0.14, freq: 1.25, rate: -0.67, phase: 2.3, alpha: 0.65 },
  { base: 0.94, slope: -0.37, amp: 0.13, freq: 1.12, rate: 0.82, phase: 4.4, alpha: 0.44 },
  { base: 0.99, slope: -0.34, amp: 0.115, freq: 1.42, rate: -0.9, phase: 1.2, alpha: 0.24 },
  {
    base: 1.04,
    slope: -0.39,
    amp: 0.12,
    freq: 1.1,
    rate: 0.71,
    phase: 3.5,
    alpha: 0.62,
    gold: true,
  },
  { base: 1.13, slope: -0.36, amp: 0.11, freq: 1.47, rate: -0.65, phase: 5.6, alpha: 0.4 },
  { base: 1.22, slope: -0.33, amp: 0.1, freq: 1.26, rate: 0.92, phase: 2.5, alpha: 0.42 },
];

export const OCEAN_GOLD_THREADS = [
  { layer: 4, phase: 0 },
  { layer: 2, phase: 2.1 },
  { layer: 1, phase: 4.3 },
  { layer: 0, phase: 1.3 },
  { layer: 3, phase: 3.4 },
  { layer: 5, phase: 5.5 },
];

// Each card keeps its own phases; theme changes never reset the animation clock.
export function oceanCardMotion(seed) {
  const index = (Math.trunc(seed) >>> 0) + 1;
  const fraction = (value) => value - Math.floor(value);
  return {
    waveOffset: fraction(index * 0.61803398875) * 80,
    threadOffset: fraction(index * 0.41421356237) * 24,
    threadOrder: (index - 1) % OCEAN_GOLD_THREADS.length,
  };
}

// Soft handoffs always keep one thread lit, with occasional overlaps of five or six.
export function oceanThreadVisibility(time, order = 0) {
  const t = ((time % 24) + 24) % 24;
  const fade = (start, end) => {
    const p = Math.max(0, Math.min(1, (t - start) / (end - start)));
    return p * p * (3 - 2 * p);
  };
  const visibility = [
    1 - fade(7, 10) + fade(15, 18),
    fade(3, 6) - fade(13, 16),
    fade(7, 10) - fade(18, 21),
    fade(2, 5) - fade(12, 15),
    fade(5, 8) - fade(17, 20),
    fade(6, 9) - fade(11, 14),
  ];
  const shift = ((Math.trunc(order) % visibility.length) + visibility.length) % visibility.length;
  return visibility.map((_, index) => visibility[(index + shift) % visibility.length]);
}

export function oceanWaveY(p, layer, time, pointerY = 0.5, hoverMix = 0) {
  const a = time * layer.rate + layer.phase;
  const swell =
    Math.sin(p * Math.PI * 2 * layer.freq - a) * 0.68 +
    Math.sin(p * Math.PI * 3.2 * layer.freq + a * 0.73) * 0.24 +
    Math.cos(p * Math.PI * 4.5 - a * 0.44) * 0.08;
  const mouse = Math.sin(p * Math.PI) * (pointerY - 0.5) * hoverMix * 0.07;
  return layer.base + layer.slope * p + swell * layer.amp * OCEAN_STRENGTH + mouse;
}

export function mixOceanColor(a, b, amount, alpha = 1) {
  const rgb = a.map((value, index) => Math.round(value + (b[index] - value) * amount));
  return `rgba(${rgb.join(',')},${alpha})`;
}

// Tint only the resting fill, once per palette change. Highlighted colors stay original.
export function prepareOceanPalette(palette) {
  const primary = palette.primary ?? palette.dark;
  const tint = (color) =>
    color.map((channel, index) =>
      Math.round(channel + (primary[index] - channel) * OCEAN_RESTING_SHADE),
    );
  return {
    ...palette,
    resting: {
      surface: tint(palette.surface),
      soft: tint(palette.soft),
      highlight: tint(palette.highlight),
    },
  };
}

export function paintOcean(ctx, entry, palette, elapsed) {
  const { width: w, height: h, darkMix: dark, hoverMix, pointerX, pointerY } = entry;
  if (!w || !h) return;
  const resting = palette.resting ?? prepareOceanPalette(palette).resting;
  const time = elapsed + (entry.motion?.waveOffset ?? 0);
  const color = (light, shade, alpha = 1) => mixOceanColor(light, shade, dark, alpha);
  const background = ctx.createLinearGradient(0, h, w, 0);
  background.addColorStop(0, color(resting.surface, palette.dark));
  background.addColorStop(0.45, color(resting.soft, palette.dark));
  background.addColorStop(1, color(resting.surface, palette.bright));
  ctx.fillStyle = background;
  ctx.fillRect(0, 0, w, h);
  const glow = ctx.createRadialGradient(
    w * (0.72 + Math.sin(time * 0.22) * 0.2),
    h * 0.08,
    0,
    w * 0.6,
    0,
    w * 0.85,
  );
  glow.addColorStop(0, color(resting.highlight, palette.glow, 0.17));
  glow.addColorStop(1, color(resting.highlight, palette.glow, 0));
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, w, h);
  function trace(layer) {
    ctx.beginPath();
    for (let i = 0; i <= 100; i++) {
      const p = i / 100;
      const y =
        h * oceanWaveY(p, layer, time + hoverMix * (pointerX - 0.5) * 0.3, pointerY, hoverMix);
      if (!i) ctx.moveTo(0, y);
      else ctx.lineTo(p * w, y);
    }
  }
  OCEAN_LAYERS.forEach((layer, index) => {
    trace(layer);
    ctx.lineTo(w, h * 1.8);
    ctx.lineTo(0, h * 1.8);
    ctx.closePath();
    const fill = ctx.createLinearGradient(0, h * 0.35, w * 0.2, h * 1.2);
    fill.addColorStop(
      0,
      color(
        index % 2 ? resting.soft : resting.highlight,
        index % 2 ? palette.dark : palette.bright,
        layer.alpha,
      ),
    );
    fill.addColorStop(1, color(resting.soft, palette.dark, layer.alpha));
    ctx.fillStyle = fill;
    ctx.fill();
  });

  // Draw the luminous edges last, so the front waves cannot cover their light.
  const visibility = oceanThreadVisibility(
    elapsed + (entry.motion?.threadOffset ?? 0),
    entry.motion?.threadOrder ?? 0,
  );
  const scale = Math.max(0.8, Math.min(1.5, w / 420));
  OCEAN_GOLD_THREADS.forEach(({ layer, phase }, index) => {
    if (visibility[index] < 0.001) return;
    const goldLayer = OCEAN_LAYERS[layer];
    const lightStrength =
      (RESTING_GOLD_STRENGTH + dark * (1 - RESTING_GOLD_STRENGTH)) * visibility[index];
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    trace(goldLayer);
    // Layered translucent strokes give a soft halo without expensive blur filters.
    for (const [width, alpha] of [
      [11, 0.025],
      [7, 0.055],
      [3.8, 0.12],
    ]) {
      ctx.lineWidth = scale * width;
      ctx.strokeStyle = `rgba(255,202,50,${lightStrength * alpha})`;
      ctx.stroke();
    }
    const edge = ctx.createLinearGradient(0, 0, w, 0);
    edge.addColorStop(0, 'rgba(255,209,83,0)');
    edge.addColorStop(0.22, `rgba(234,180,49,${lightStrength * 0.5})`);
    edge.addColorStop(
      0.63,
      mixOceanColor([255, 224, 119], palette.edge, 0.2, lightStrength * 0.95),
    );
    edge.addColorStop(1, `rgba(255,209,83,${lightStrength * 0.25})`);
    ctx.strokeStyle = edge;
    ctx.lineWidth = scale * 1.1;
    ctx.stroke();

    const p = 0.48 + 0.4 * (0.5 + 0.5 * Math.sin(time * 0.45 + phase));
    const t = time + hoverMix * (pointerX - 0.5) * 0.3;
    const x = w * p;
    const y = h * oceanWaveY(p, goldLayer, t, pointerY, hoverMix);
    const pulse = 0.78 + 0.22 * Math.sin(time * 1.9 + phase * 1.7);
    const shimmer = ctx.createLinearGradient(x - w * 0.12, 0, x + w * 0.12, 0);
    shimmer.addColorStop(0, 'rgba(255,209,71,0)');
    shimmer.addColorStop(0.32, `rgba(255,205,65,${lightStrength * pulse * 0.8})`);
    shimmer.addColorStop(0.5, `rgba(255,255,228,${lightStrength * pulse})`);
    shimmer.addColorStop(0.68, `rgba(255,205,65,${lightStrength * pulse * 0.8})`);
    shimmer.addColorStop(1, 'rgba(255,209,71,0)');
    ctx.strokeStyle = shimmer;
    ctx.lineWidth = scale * 2.2;
    ctx.stroke();

    const halo = ctx.createRadialGradient(x, y, 0, x, y, scale * 24);
    halo.addColorStop(0, `rgba(255,255,216,${lightStrength * pulse * 0.7})`);
    halo.addColorStop(0.2, `rgba(255,226,110,${lightStrength * pulse * 0.38})`);
    halo.addColorStop(0.55, `rgba(255,205,50,${lightStrength * pulse * 0.12})`);
    halo.addColorStop(1, 'rgba(255,205,50,0)');
    ctx.fillStyle = halo;
    ctx.fillRect(x - scale * 24, y - scale * 24, scale * 48, scale * 48);
    const before = h * oceanWaveY(p - 0.003, goldLayer, t, pointerY, hoverMix);
    const after = h * oceanWaveY(p + 0.003, goldLayer, t, pointerY, hoverMix);
    ctx.translate(x, y);
    ctx.rotate(Math.atan2(after - before, w * 0.006));
    ctx.beginPath();
    ctx.ellipse(0, 0, scale * 7, scale * 1.1, 0, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(255,255,239,${lightStrength * pulse})`;
    ctx.fill();
    ctx.restore();
  });
}
