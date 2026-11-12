// Ranglar foydalanuvchi bo'yicha shu brauzerda saqlanadi; parol saqlanmaydi.
import { natureThemes, naturePalette } from './nature-themes.js';

const classicColors = [
  ['page', 'Dastur orqa foni', '#efe6ce'],
  ['surface', 'Kartochka va oynalar', '#fffdf7'],
  ['sidebar', 'Yon menyu foni', '#193f36'],
  ['topbar', 'Yuqori panel foni', '#234b40'],
  ['sidebar-text', 'Yon menyu matni', '#f6f2e7'],
  ['topbar-text', 'Yuqori panel matni', '#f6f2e7'],
  ['nav-active', 'Tanlangan menyu foni', '#dec68e'],
  ['nav-active-text', 'Tanlangan menyu matni', '#193f36'],
  ['field', 'Kiritish maydonlari foni', '#ffffff'],
  ['text', 'Asosiy matn', '#20382e'],
  ['muted', 'Izoh va yordamchi matn', '#526058'],
  ['heading', 'Sarlavhalar', '#153b2f'],
  ['green', 'Tugma va asosiy rang', '#155d50'],
  ['green-hover', 'Tugma ustiga kelgandagi rang', '#0b483d'],
  ['button-text', 'Asosiy tugma matni', '#ffffff'],
  ['soft', 'Tanlangan element foni', '#e5ebdd'],
  ['border', 'Chiziq va chegaralar', '#d7c8a5'],
  ['accent', 'Ajratilgan summa kartasi', '#195c4d'],
  ['accent-text', 'Ajratilgan karta matni', '#ffffff'],
  ['table', 'Jadval sarlavhasi foni', '#f3ecd9'],
  ['summary', 'Hisoblar paneli foni', '#e8ddbb'],
  ['danger', 'Xatolik matni', '#b15849'],
];
const classicDefaults = Object.fromEntries(classicColors.map(([key, , value]) => [key, value]));
export const defaults = naturePalette(natureThemes.find(({ id }) => id === 'emerald'));
export const colors = [
  ...classicColors,
  ['wave-light', 'To‘lqinlarning yorqin rangi'],
  ['wave-glow', 'To‘lqin atrofidagi nur'],
  ['wave-edge', 'Yaltirashning qo‘shimcha tusi'],
].map(([key, label]) => [key, label, defaults[key]]);

// Historical color fingerprints migrate saved choices; they are not selectable themes.
const previousPresets = [
  {
    id: 'gold',
    palette: {
      page: '#efe7d3',
      surface: '#fffcf3',
      sidebar: '#1d1d1b',
      topbar: '#292823',
      'sidebar-text': '#f8f1dd',
      'topbar-text': '#f8f1dd',
      'nav-active': '#e1c477',
      'nav-active-text': '#252118',
      text: '#302b21',
      muted: '#696044',
      heading: '#252118',
      green: '#80601c',
      'green-hover': '#654a13',
      soft: '#f0e5c6',
      border: '#d7c69c',
      accent: '#29251d',
      'accent-text': '#efd38d',
      table: '#f3ebd3',
      summary: '#e8d9af',
    },
  },
  {
    id: 'sky',
    palette: {
      page: '#eaf2fb',
      surface: '#fcfdff',
      sidebar: '#1b3656',
      topbar: '#25486e',
      'sidebar-text': '#edf6ff',
      'topbar-text': '#edf6ff',
      'nav-active': '#b8ddff',
      'nav-active-text': '#163650',
      text: '#253c50',
      muted: '#53687c',
      heading: '#193e60',
      green: '#246397',
      'green-hover': '#184d79',
      soft: '#dfedf9',
      border: '#bfd2e4',
      accent: '#245b88',
      'accent-text': '#ffffff',
      table: '#e9f1f9',
      summary: '#d8e8f7',
    },
  },
  {
    id: 'ocean',
    palette: {
      page: '#e3f0f1',
      surface: '#f9fdfd',
      sidebar: '#103945',
      topbar: '#174b59',
      'sidebar-text': '#e9f8fa',
      'topbar-text': '#e9f8fa',
      'nav-active': '#8fd6d4',
      'nav-active-text': '#143e47',
      text: '#24414a',
      muted: '#4f6b72',
      heading: '#153f4c',
      green: '#146574',
      'green-hover': '#0d4d5a',
      soft: '#d9eded',
      border: '#afcecf',
      accent: '#165c6c',
      'accent-text': '#ffffff',
      table: '#e1eff0',
      summary: '#cde5e5',
    },
  },
  {
    id: 'emerald',
    palette: {
      page: '#e8efe6',
      surface: '#fcfdf9',
      sidebar: '#203e32',
      topbar: '#2a4e3c',
      'sidebar-text': '#f0f6e9',
      'topbar-text': '#f0f6e9',
      'nav-active': '#c3dca9',
      'nav-active-text': '#263e26',
      text: '#2c4132',
      muted: '#566b56',
      heading: '#244b32',
      green: '#326843',
      'green-hover': '#244f32',
      soft: '#e0ebd9',
      border: '#c0d0b7',
      accent: '#2e5d3e',
      'accent-text': '#ffffff',
      table: '#e9f0e3',
      summary: '#dbe7cc',
    },
  },
  {
    id: 'lavender',
    palette: {
      page: '#eee9f3',
      surface: '#fdfbff',
      sidebar: '#362c49',
      topbar: '#47385e',
      'sidebar-text': '#f5efff',
      'topbar-text': '#f5efff',
      'nav-active': '#d5c2ed',
      'nav-active-text': '#38284e',
      text: '#41374f',
      muted: '#6b5d7c',
      heading: '#45325c',
      green: '#70508e',
      'green-hover': '#553a6f',
      soft: '#e9e0f1',
      border: '#d0c1dd',
      accent: '#5c4077',
      'accent-text': '#ffffff',
      table: '#efe8f6',
      summary: '#e2d5ee',
    },
  },
  {
    id: 'graphite',
    palette: {
      page: '#e9edf1',
      surface: '#fcfdfe',
      sidebar: '#282f39',
      topbar: '#343f4e',
      'sidebar-text': '#f1f5fa',
      'topbar-text': '#f1f5fa',
      'nav-active': '#cbd6e3',
      'nav-active-text': '#263443',
      text: '#313e4c',
      muted: '#5d6c7d',
      heading: '#28394b',
      green: '#495f78',
      'green-hover': '#35495e',
      soft: '#e0e6ed',
      border: '#c4ced9',
      accent: '#3c5068',
      'accent-text': '#ffffff',
      table: '#e9eef4',
      summary: '#dce3ec',
    },
  },
].map(({ palette, ...preset }) => ({ ...preset, palette: { ...classicDefaults, ...palette } }));

const vividPalettes = {
  gold: { page: '#fff4dc', surface: '#fffdf6', sidebar: '#392c17', topbar: '#674819',
    'sidebar-text': '#fff5d6', 'topbar-text': '#fff5d6', 'nav-active': '#ffdb78', 'nav-active-text': '#49300d',
    text: '#48351c', muted: '#77613f', heading: '#513713', green: '#98651b', 'green-hover': '#76490d',
    soft: '#fff0c3', border: '#dec187', accent: '#845813', 'accent-text': '#ffffff', table: '#fff0c9', summary: '#ffe6a0' },
  sky: { page: '#edf6ff', surface: '#ffffff', sidebar: '#173f70', topbar: '#225c9b',
    'sidebar-text': '#edf7ff', 'topbar-text': '#f3f9ff', 'nav-active': '#b8e1ff', 'nav-active-text': '#123f72',
    text: '#203d60', muted: '#506b88', heading: '#174479', green: '#176fc6', 'green-hover': '#12569f',
    soft: '#e0f0ff', border: '#acd0ef', accent: '#155eac', 'accent-text': '#ffffff', table: '#e9f4ff', summary: '#cae7ff' },
  ocean: { page: '#e9fbfc', surface: '#fcffff', sidebar: '#104754', topbar: '#086275',
    'sidebar-text': '#eaffff', 'topbar-text': '#efffff', 'nav-active': '#91ece5', 'nav-active-text': '#09434e',
    text: '#21434d', muted: '#4c7078', heading: '#095260', green: '#087e8e', 'green-hover': '#05606e',
    soft: '#d8f6f3', border: '#9ad8d8', accent: '#066c7b', 'accent-text': '#ffffff', table: '#e0f9f6', summary: '#b8eee9' },
  emerald: { page: '#eff9e9', surface: '#fefff9', sidebar: '#174b36', topbar: '#22613e',
    'sidebar-text': '#f2ffe9', 'topbar-text': '#f4ffec', 'nav-active': '#c1ed95', 'nav-active-text': '#254719',
    text: '#284b32', muted: '#56754e', heading: '#205432', green: '#268144', 'green-hover': '#196334',
    soft: '#e1f3d2', border: '#aed391', accent: '#216c3d', 'accent-text': '#ffffff', table: '#ebf8df', summary: '#cdecac' },
  lavender: { page: '#f5efff', surface: '#fefcff', sidebar: '#462868', topbar: '#633b90',
    'sidebar-text': '#f8efff', 'topbar-text': '#fbf4ff', 'nav-active': '#e0c4ff', 'nav-active-text': '#48246d',
    text: '#4b3565', muted: '#79618d', heading: '#542b79', green: '#8446bd', 'green-hover': '#653193',
    soft: '#efe1ff', border: '#d1b1ec', accent: '#7436a8', 'accent-text': '#ffffff', table: '#f2e7ff', summary: '#e2cafa' },
  graphite: { page: '#f0f5fc', surface: '#ffffff', sidebar: '#293e59', topbar: '#3c587b',
    'sidebar-text': '#f0f6ff', 'topbar-text': '#f4f8ff', 'nav-active': '#c4def9', 'nav-active-text': '#254466',
    text: '#354a66', muted: '#607590', heading: '#2b486c', green: '#4b6d98', 'green-hover': '#36547c',
    soft: '#e3edf9', border: '#b8cce5', accent: '#3d5c85', 'accent-text': '#ffffff', table: '#ebf3fd', summary: '#d3e3f6' },
};
// Old palettes are used only to migrate saved selections, never shown as duplicates.
const savedPresetPalettes = [
  { id: 'emerald', palette: classicDefaults },
  ...previousPresets,
  ...previousPresets.map((preset) => ({ ...preset, palette: { ...preset.palette, ...vividPalettes[preset.id] } })),
];
const presetReplacements = { gold: 'sun', sky: 'ice', ocean: 'ocean', emerald: 'emerald', lavender: 'cosmic', graphite: 'night' };
export const presets = natureThemes.map(({ id, label, description, ...tokens }) => ({
  id, label, description, palette: naturePalette(tokens),
}));

export function readTheme(id) {
  try {
    const key = `crm-theme-${id}`;
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    // Eski standart ranglarni yangi palitraga o'tkazamiz; shaxsiy tanlovlar qoladi.
    if (!localStorage.getItem(`${key}-gold-v1`)) {
      const old = {
        page: '#f6f7f9',
        surface: '#ffffff',
        sidebar: '#ffffff',
        topbar: '#ffffff',
        text: '#233b34',
        muted: '#82908b',
        heading: '#233b34',
        soft: '#eff5f1',
        border: '#e5eae7',
        table: '#fafbf9',
        summary: '#f4f4eb',
      };
      for (const [name, value] of Object.entries(old)) {
        if (saved[name]?.toLowerCase() === value) delete saved[name];
      }
      localStorage.setItem(key, JSON.stringify(saved));
      localStorage.setItem(`${key}-gold-v1`, '1');
    }
    // Faqat oldingi standart och panel ranglari ko'chadi; shaxsiy ranglar saqlanadi.
    if (!localStorage.getItem(`${key}-tin-v1`)) {
      for (const name of ['sidebar', 'topbar']) {
        if (saved[name]?.toLowerCase() === '#fcf8ed') delete saved[name];
      }
      localStorage.setItem(key, JSON.stringify(saved));
      localStorage.setItem(`${key}-tin-v1`, '1');
    }
    const resolved = { ...defaults, ...saved };
    const hasWaveSettings = ['wave-light', 'wave-glow', 'wave-edge'].some((name) => Object.hasOwn(saved, name));
    const previousPreset = !hasWaveSettings && savedPresetPalettes.find(({ palette }) =>
      Object.keys(classicDefaults).every((name) => resolved[name]?.toLowerCase() === palette[name]));
    if (previousPreset) {
      const updated = presets.find(({ id }) => id === presetReplacements[previousPreset.id]).palette;
      localStorage.setItem(key, JSON.stringify(updated));
      return { ...updated };
    }
    return resolved;
  } catch {
    return { ...defaults };
  }
}
export function applyTheme(theme) {
  const resolved = {};
  for (const [key, , fallback] of colors) {
    const value = /^#[0-9a-f]{6}$/i.test(theme[key]) ? theme[key] : fallback;
    resolved[key] = value.toLowerCase();
    document.documentElement.style.setProperty(`--${key}`, value);
  }
  // Every current preset, including the default Emerald, uses the full theme adapter.
  document.documentElement.dataset.magicTheme = 'custom';
  const [r, g, b] = [1, 3, 5].map((index) => parseInt(resolved.green.slice(index, index + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
  let hue = delta === 0 ? 0 : max === r ? ((g - b) / delta) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  hue = (hue * 60 + 360) % 360;
  document.documentElement.style.setProperty('--magic-art-hue', `${hue - 166}deg`);
  document.documentElement.style.setProperty('--magic-art-saturation', String(max === 0 ? 0 : delta / max));
}
