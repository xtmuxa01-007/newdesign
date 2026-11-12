import React from 'react';
import { LayoutDashboard, ShoppingBag, Truck, Users, Settings } from 'lucide-react';
import { miniAppTabs } from './miniapp-navigation';
import { isTelegramEntry } from './telegram';

const icons = {
  dashboard: LayoutDashboard,
  pos: ShoppingBag,
  suppliers: Truck,
  debts: Users,
  settings: Settings,
};

export function MiniAppBottomNav({ role, page, onNavigate }) {
  if (!isTelegramEntry()) return null;
  const tabs = miniAppTabs(role);
  if (!tabs.length) return null;
  return (
    <nav className="mini-app-bottom-nav" aria-label="Asosiy bo‘limlar">
      {tabs.map(({ id, label }) => {
        const Icon = icons[id];
        return (
          <button
            type="button"
            key={id}
            className={page === id ? 'selected' : undefined}
            aria-label={label}
            title={label}
            aria-current={page === id ? 'page' : undefined}
            onClick={() => onNavigate(id)}
          >
            <Icon size={24} aria-hidden="true" />
          </button>
        );
      })}
    </nav>
  );
}
