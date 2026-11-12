// Color tokens from the user's nature-erp-themes.html; each family appears once.
export const natureThemes = [
  { id: 'cosmic', label: 'Cosmic', description: 'Ametist va kosmik nur', primary: '#7d36ba', deep: '#35105d', light: '#ac48f6', glow: '#d98aff', tint: '#ede1fa', page: '#f8f3fd', surface: '#fefcff', text: '#33283f', muted: '#6b5e79', border: '#e1cff0', edge: '#ffd78e' },
  { id: 'ice', label: 'Ice', description: 'Muz va billur', primary: '#086f9c', deep: '#063f67', light: '#24bdeb', glow: '#7eefff', tint: '#ddf2fa', page: '#f0f9fc', surface: '#fcffff', text: '#233e4a', muted: '#4d6873', border: '#cae4ec', edge: '#e5fbff' },
  { id: 'ocean', label: 'Ocean', description: 'Firuza va dengiz nuri', primary: '#007a87', deep: '#00465d', light: '#00c6c7', glow: '#35ffeb', tint: '#ddf4ef', page: '#f1faf7', surface: '#fcfffe', text: '#233f43', muted: '#506a6c', border: '#c9e7de', edge: '#ffe68c' },
  { id: 'earth', label: 'Earth', description: 'Barg va oltin', primary: '#4b752c', deep: '#193e20', light: '#8cc342', glow: '#bdfb76', tint: '#eaf2da', page: '#f7faf0', surface: '#fefff9', text: '#3d392e', muted: '#696350', border: '#d7e3bd', edge: '#ffe4a1' },
  { id: 'sun', label: 'Sun', description: 'Quyosh va asal', primary: '#a65b0b', deep: '#7e310b', light: '#ffc249', glow: '#ffd768', tint: '#fff0cf', page: '#fffaed', surface: '#fffdfa', text: '#4b3727', muted: '#755e48', border: '#f1dead', edge: '#fff2c5' },
  { id: 'night', label: 'Night', description: 'Safir va yulduzlar', primary: '#355daa', deep: '#11295d', light: '#6f8bf1', glow: '#a4bcff', tint: '#e4eafd', page: '#f3f5fe', surface: '#fcfdff', text: '#2c3d55', muted: '#56667d', border: '#d4def5', edge: '#d7e7ff' },
  { id: 'emerald', label: 'Emerald', description: 'Zumrad va oltin', primary: '#007458', deep: '#004631', light: '#00c78d', glow: '#23ffbb', tint: '#ddf3e7', page: '#f2faf1', surface: '#fcfff9', text: '#243f31', muted: '#526e5c', border: '#cbe7cf', edge: '#ffe58c' },
];

export function naturePalette(theme) {
  return {
    page: theme.page, surface: theme.surface, sidebar: theme.deep, topbar: theme.primary,
    'sidebar-text': '#ffffff', 'topbar-text': '#ffffff',
    'nav-active': theme.tint, 'nav-active-text': theme.deep, field: theme.surface,
    text: theme.text, muted: theme.muted, heading: theme.deep,
    green: theme.primary, 'green-hover': theme.deep, 'button-text': '#ffffff',
    soft: theme.tint, border: theme.border, accent: theme.primary, 'accent-text': '#ffffff',
    table: theme.tint, summary: theme.tint, danger: '#b15849',
    'wave-light': theme.light, 'wave-glow': theme.glow, 'wave-edge': theme.edge,
  };
}
