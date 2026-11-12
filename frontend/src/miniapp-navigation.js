const tabs = [
  { id: 'dashboard', label: 'Asosiy' },
  { id: 'pos', label: 'POS' },
  { id: 'suppliers', label: 'Ta’minotchilar' },
  { id: 'debts', label: 'Qarzlar' },
  { id: 'settings', label: 'Sozlamalar' },
];

export function miniAppTabs(role) {
  const allowed =
    role === 'boss' || role === 'admin'
      ? ['dashboard', 'pos', 'suppliers', 'settings']
      : role === 'cashier'
        ? ['pos', 'debts', 'settings']
        : [];
  return tabs.filter((tab) => allowed.includes(tab.id));
}
