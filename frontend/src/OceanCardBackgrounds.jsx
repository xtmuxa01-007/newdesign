import { useEffect } from 'react';
import {
  OCEAN_SPEED,
  OCEAN_GOLD_THREADS,
  OCEAN_RESTING_SHADE,
  oceanCardMotion,
  prepareOceanPalette,
  paintOcean,
} from './ocean-waves';
import './ocean-card-backgrounds.css';

const CARD_SELECTOR = [
  '.dashboard-overview .emerald-card',
  '.dashboard-revenue-card',
  '.metrics > .metric',
  '.analytics-summary > div',
  '.analytics-finance-card',
  '.analytics-branch-total',
  '.analytics-branch-bar',
  '.debt-payment-hero',
  '.filtered-total',
  '.debt-payment-totals > div',
  '.debts-overview',
  '.summary-strip',
  '.notifications-overview',
  '.notification-card',
  '.other-payments-total',
].join(',');
const FIXED_DARK =
  '.debt-payment-hero, .filtered-total, .analytics-branch-total, .analytics-finance-card.inflow';
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

// One scheduler serves all visible cards; nothing is sent or stored outside the app.
export function OceanCardBackgrounds() {
  useEffect(() => {
    const root = document.querySelector('.app-shell.emerald-workspace');
    if (!root) return;
    const entries = new Map();
    let motionSeed = 0;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let frame = null,
      last = 0,
      paintedAt = 0,
      time = 0,
      palette,
      disposed = false;
    function readPalette() {
      const style = getComputedStyle(document.documentElement);
      const get = (name, fallback) => {
        const value = style.getPropertyValue(`--${name}`).trim();
        return rgb(/^#[\da-f]{6}$/i.test(value) ? value : fallback);
      };
      palette = prepareOceanPalette({
        surface: get('surface', '#fffdf7'),
        soft: get('soft', '#e5ebdd'),
        primary: get('green', '#007458'),
        highlight: get('nav-active', '#dec68e'),
        dark: get('green-hover', '#004b3c'),
        bright: get('wave-light', '#00c78d'),
        glow: get('wave-glow', '#23ffbb'),
        edge: get('wave-edge', '#ffe58c'),
      });
      for (const entry of entries.values()) entry.dirty = true;
      wake();
    }
    function updateActive() {
      const hovered = root.querySelector('.emerald-card:hover');
      const first = root.querySelector('.stats-grid > .stat-card:first-child');
      for (const [card, entry] of entries) {
        const hoveredOrFocused = card.matches(':hover') || card.contains(document.activeElement);
        let dark = card.matches(FIXED_DARK);
        if (card.matches('.emerald-card')) dark = card === hovered || (!hovered && card === first);
        if (card.matches('.metrics > .metric, .analytics-summary > div')) {
          dark =
            card.matches(':hover') ||
            (!card.parentElement.querySelector(':scope > :hover') &&
              card === card.parentElement.firstElementChild);
        }
        entry.dark = dark ? 1 : 0;
        const state = dark ? 'active' : 'resting';
        if (card.dataset.oceanState !== state) card.dataset.oceanState = state;
        if (!entry.width) entry.darkMix = entry.dark;
        entry.hover = hoveredOrFocused ? 1 : 0;
        entry.dirty = true;
      }
      wake();
    }
    function wake() {
      if (
        !disposed &&
        frame === null &&
        !document.hidden &&
        [...entries.values()].some((e) => e.visible)
      ) {
        frame = requestAnimationFrame(tick);
      }
    }
    function tick(now) {
      frame = null;
      if (disposed || document.hidden) {
        last = 0;
        return;
      }
      if (!reduced.matches && now - paintedAt < 1000 / 30) {
        wake();
        return;
      }
      const delta = last ? Math.min((now - last) / 1000, 0.1) : 0;
      last = paintedAt = now;
      if (!reduced.matches) time += delta * OCEAN_SPEED;
      let animate = false;
      for (const entry of entries.values()) {
        if (!entry.visible) continue;
        if (entry.needsResize && entry.width && entry.height) {
          const dpr = Math.min(
            devicePixelRatio || 1,
            1.5,
            Math.sqrt(500000 / (entry.width * entry.height)),
          );
          entry.canvas.width = Math.round(entry.width * dpr);
          entry.canvas.height = Math.round(entry.height * dpr);
          entry.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
          entry.needsResize = false;
        }
        const blend = reduced.matches ? 1 : 1 - Math.exp(-delta * 7);
        entry.darkMix += (entry.dark - entry.darkMix) * blend;
        entry.hoverMix += (entry.hover - entry.hoverMix) * blend;
        if (!reduced.matches || entry.dirty) paintOcean(entry.ctx, entry, palette, time);
        if (entry.width && entry.height && entry.canvas.style.opacity !== '1')
          entry.canvas.style.opacity = '1';
        entry.dirty = false;
        if (!reduced.matches) animate = true;
      }
      if (animate) wake();
    }
    const intersection = new IntersectionObserver((changes) => {
      for (const change of changes) {
        const entry = entries.get(change.target);
        if (entry) {
          entry.visible = change.isIntersecting;
          entry.dirty = true;
          if (!entry.visible) {
            entry.canvas.width = entry.canvas.height = 1;
            entry.canvas.style.opacity = '0';
            entry.needsResize = true;
          }
        }
      }
      last = 0;
      wake();
    });
    const resize = new ResizeObserver((changes) => {
      for (const { target } of changes) {
        const entry = entries.get(target);
        if (!entry) continue;
        const rect = target.getBoundingClientRect();
        entry.width = Math.max(1, rect.width - 2);
        entry.height = Math.max(1, rect.height - 2);
        entry.needsResize = true;
        entry.dirty = true;
      }
      wake();
    });
    function remove(card, entry) {
      intersection.unobserve(card);
      resize.unobserve(card);
      card.removeEventListener('pointermove', entry.move);
      entry.canvas.remove();
      card.removeAttribute('data-ocean-wave');
      card.removeAttribute('data-ocean-state');
      for (const name of ['--ocean-star-phase', '--ocean-orbit-phase', '--ocean-rim-phase']) {
        card.style.removeProperty(name);
      }
      entries.delete(card);
    }
    function scan() {
      if (disposed) return;
      for (const [card, entry] of entries) {
        if (!root.contains(card) || !card.matches(CARD_SELECTOR) || !entry.canvas.isConnected)
          remove(card, entry);
      }
      for (const card of root.querySelectorAll(CARD_SELECTOR)) {
        if (entries.has(card)) continue;
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = 1;
        canvas.style.opacity = '0';
        const ctx = canvas.getContext('2d', { alpha: false });
        if (!ctx) continue;
        canvas.className = 'ocean-card-waves';
        canvas.setAttribute('aria-hidden', 'true');
        canvas.dataset.strength = '90';
        canvas.dataset.speed = '2';
        canvas.dataset.restingShade = String(OCEAN_RESTING_SHADE * 100);
        const motion = oceanCardMotion(motionSeed++);
        canvas.dataset.goldThreads = String(OCEAN_GOLD_THREADS.length);
        canvas.dataset.waveOffset = motion.waveOffset.toFixed(3);
        canvas.dataset.threadOffset = motion.threadOffset.toFixed(3);
        canvas.dataset.threadOrder = String(motion.threadOrder);
        card.style.setProperty('--ocean-star-phase', `${-motion.threadOffset}s`);
        card.style.setProperty('--ocean-orbit-phase', `${-motion.waveOffset}s`);
        card.style.setProperty('--ocean-rim-phase', `${-motion.waveOffset}s`);
        const entry = {
          canvas,
          ctx,
          width: 0,
          height: 0,
          visible: false,
          dark: 0,
          darkMix: card.matches(FIXED_DARK) ? 1 : 0,
          hover: 0,
          hoverMix: 0,
          pointerX: 0.5,
          pointerY: 0.5,
          dirty: true,
          needsResize: true,
          motion,
        };
        entry.move = (event) => {
          const rect = card.getBoundingClientRect();
          entry.pointerX = (event.clientX - rect.left) / rect.width;
          entry.pointerY = (event.clientY - rect.top) / rect.height;
        };
        entries.set(card, entry);
        card.setAttribute('data-ocean-wave', '');
        card.appendChild(canvas);
        card.addEventListener('pointermove', entry.move, { passive: true });
        intersection.observe(card);
        resize.observe(card);
      }
      updateActive();
    }
    const mutations = new MutationObserver(scan);
    const themes = new MutationObserver(readPalette);
    const visibility = () => {
      last = 0;
      wake();
    };
    const motion = () => {
      for (const entry of entries.values()) entry.dirty = true;
      last = 0;
      wake();
    };
    readPalette();
    scan();
    mutations.observe(root, { childList: true, subtree: true });
    themes.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['style', 'data-magic-theme'],
    });
    root.addEventListener('pointerover', updateActive);
    root.addEventListener('pointerout', updateActive);
    root.addEventListener('focusin', updateActive);
    root.addEventListener('focusout', updateActive);
    reduced.addEventListener('change', motion);
    document.addEventListener('visibilitychange', visibility);
    return () => {
      disposed = true;
      if (frame !== null) cancelAnimationFrame(frame);
      mutations.disconnect();
      themes.disconnect();
      for (const [card, entry] of entries) remove(card, entry);
      intersection.disconnect();
      resize.disconnect();
      root.removeEventListener('pointerover', updateActive);
      root.removeEventListener('pointerout', updateActive);
      root.removeEventListener('focusin', updateActive);
      root.removeEventListener('focusout', updateActive);
      reduced.removeEventListener('change', motion);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, []);
  return null;
}
