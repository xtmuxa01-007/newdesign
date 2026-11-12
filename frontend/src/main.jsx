import React, { useState, useEffect, useCallback } from 'react';
import { createRoot } from 'react-dom/client';
import {
  LayoutDashboard,
  ChartColumnIncreasing,
  Settings as SettingsIcon,
  ShoppingBag,
  Warehouse,
  Truck,
  HeartHandshake,
  History,
  Users,
  LogOut,
  ChevronDown,
  CircleCheck,
  X,
  Menu,
  RefreshCw,
  ArrowUpRight,
  Eye,
  EyeOff,
} from 'lucide-react';
import { api, post } from './api';
import { Loading } from './components';
import { Dashboard, Inventory, Suppliers, Donations, Reports, SalesAnalytics, Team } from './pages';
import { POS } from './pos';
import { uzDate } from './dates';
import { readPending } from './recovery';
import { RecoveryModal } from './RecoveryModal';
import './style.css';
import './workspace.css';
import './emerald-workspace.css';
import './emerald-pages.css';
import './login.css';
import { Debts } from './pages/Debts';
import { Notifications } from './Notifications';
import { Expenses } from './pages/Expenses';
import { Settings } from './pages/Settings';
import { readTheme, applyTheme, defaults } from './theme';
import { DesktopControls } from './DesktopControls';
import {
  initializeTelegram,
  isTelegramEntry,
  homeForRole,
  telegramBackDestination,
  bindTelegramBack,
} from './telegram';
import './telegram.css';
import { ExportDownloadSheet } from './ExportDownloadSheet';
import { MiniAppBottomNav } from './MiniAppBottomNav';
import './magical-themes.css';
import { OceanCardBackgrounds } from './OceanCardBackgrounds';
import { WorkspaceBackdrop } from './WorkspaceBackdrop';

const DESKTOP_PAUSED_MESSAGE =
  'EXE vaqtincha to‘xtatilgan. Web sahifa yoki Telegram Mini App orqali kiring.';

function Logo({ workspace = false, onClick }) {
  const Tag = workspace ? 'button' : 'div';
  return (
    <Tag
      className={workspace ? 'workspace-brand' : 'logo'}
      type={workspace ? 'button' : undefined}
      aria-label={workspace ? 'TIN — bosh sahifa' : undefined}
      onClick={onClick}
    >
      {workspace ? (
        <span className="workspace-logo-mark" aria-hidden="true">
          <img src="/tin-logo.png" alt="" />
        </span>
      ) : (
        <img src="/tin-logo.png" alt="" />
      )}
      <span className={workspace ? 'workspace-brand-copy' : undefined}>
        TIN
        {workspace && <small>Savdo va filiallar hisobi</small>}
      </span>
    </Tag>
  );
}
function Login({ onLogin }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError('');
    const form = new FormData(e.currentTarget);
    try {
      onLogin(await post('/auth/login', Object.fromEntries(form)));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login">
      <section className="login-story">
        <Logo />
        <div className="login-quote">
          <h1>
            <span>Mijoz narxni unutishi mumkin.</span>
            <em>Samimiy munosabat esa yodda qoladi.</em>
          </h1>
        </div>
        <span className="login-foot">
          TIN Company <span>Lokal dizayn sinovi</span>
        </span>
      </section>
      <section className="login-side">
        <form onSubmit={submit}>
          <span className="eyebrow">LOKAL SINOV MUHITI</span>
          <h2>Ishni boshlaymiz</h2>
          <p>Hisobingizga kiring va ishni davom ettiring.</p>
          <label className="field">
            <span>Login</span>
            <input
              name="username"
              autoComplete="username"
              placeholder="Loginingizni kiriting"
              required
              autoFocus={!isTelegramEntry()}
            />
          </label>
          <div className="field">
            <label className="login-password-label" htmlFor="login-password">
              Parol
            </label>
            <div className="login-password-field">
              <input
                id="login-password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete="current-password"
                placeholder="Parolingizni kiriting"
                required
              />
              {/* Tugma faqat ko'rinishni almashtiradi; formani yubormaydi. */}
              <button
                type="button"
                className="password-toggle"
                aria-label={showPassword ? 'Parolni yashirish' : 'Parolni ko‘rsatish'}
                aria-pressed={showPassword}
                aria-controls="login-password"
                onClick={() => setShowPassword((visible) => !visible)}
              >
                {showPassword ? (
                  <EyeOff size={20} aria-hidden="true" />
                ) : (
                  <Eye size={20} aria-hidden="true" />
                )}
              </button>
            </div>
          </div>
          {error && (
            <div role="alert" className="error">
              {error}
            </div>
          )}
          <button className="primary wide" disabled={busy}>
            {busy ? 'Tekshirilmoqda…' : 'Tizimga kirish'}
            <ArrowUpRight size={18} />
          </button>
          <small className="login-note">Kirish ma’lumotlarini boshliqdan oling.</small>
          <DesktopControls />
        </form>
      </section>
    </main>
  );
}
const nav = [
  ['dashboard', 'Umumiy ko‘rinish', LayoutDashboard],
  ['pos', 'Savdo / POS', ShoppingBag],
  ['debts', 'Qarzlar', Users],
  ['inventory', 'Ombor', Warehouse],
  ['expenses', 'Filiallar va xarajatlar', Warehouse],
  ['suppliers', 'Ta’minotchilar', Truck],
  ['donations', 'Ehson hisobi', HeartHandshake],
  ['reports', 'Savdolar va tarix', History],
  ['analytics', 'Savdolar analizi', ChartColumnIncreasing],
  ['team', 'Jamoa va filiallar', Users],
  ['settings', 'Sozlamalar', SettingsIcon],
];
function App() {
  const [telegram, setTelegram] = useState(null);
  const [operation, setOperation] = useState(null);
  const [initialChange, setInitialChange] = useState(null);
  const [initialDebt, setInitialDebt] = useState(null);
  const [revision, setRevision] = useState(0);
  const [user, setUser] = useState(null),
    [initial, setInitial] = useState(true),
    [connectionError, setConnectionError] = useState(''),
    [desktopPaused, setDesktopPaused] = useState('');
  const [branches, setBranches] = useState([]),
    [branch, setBranch] = useState(''),
    [page, setPage] = useState('dashboard'),
    [toast, setToast] = useState(null),
    [mobile, setMobile] = useState(false);
  const notify = useCallback(
    (message, error = false) => setToast({ message, error, id: Date.now() }),
    [],
  );
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [page]);
  useEffect(() => {
    let alive = true;
    let controller;
    initializeTelegram().then((value) => {
      controller = value;
      if (alive) setTelegram(value);
      else value?.dispose();
    });
    return () => {
      alive = false;
      controller?.dispose();
    };
  }, []);
  useEffect(() => {
    const destination = user
      ? telegramBackDestination({ menuOpen: mobile, page, role: user.role })
      : null;
    return bindTelegramBack(telegram, destination, () => {
      const dialog = document.querySelector('dialog[open]');
      if (dialog) {
        dialog.dispatchEvent(new Event('cancel', { cancelable: true }));
        return;
      }
      if (destination === 'menu') setMobile(false);
      else if (destination) setPage(destination);
    });
  }, [telegram, user?.role, page, mobile]);
  const changeOpened = useCallback((id) => {
    setInitialChange((current) => (current?.id === id ? null : current));
    if (id) window.dispatchEvent(new CustomEvent('crm-change-opened', { detail: { id } }));
  }, []);
  const debtOpened = useCallback((token) => {
    setInitialDebt((current) => (current?.token === token ? null : current));
  }, []);
  const openDebt = useCallback(
    (debt) => {
      setInitialDebt({
        debt,
        user_id: user?.id,
        token: crypto.getRandomValues(new Uint32Array(2)).join('-'),
      });
      if (debt.branch_id) setBranch(String(debt.branch_id));
      setPage('debts');
      setMobile(false);
    },
    [user?.id],
  );
  const openChange = useCallback(
    (entry) => {
      setInitialChange({
        id: entry?.id ?? null,
        branch_id: entry?.branch_id,
        created_at: entry?.created_at,
        user_id: user?.id,
        token: crypto.getRandomValues(new Uint32Array(2)).join('-'),
      });
      if (entry?.branch_id) setBranch(String(entry.branch_id));
      setPage('reports');
      setMobile(false);
    },
    [user?.id],
  );
  const loadSession = useCallback(async () => {
    setConnectionError('');
    setDesktopPaused('');
    setInitial(true);
    try {
      if (window.tinDesktop) {
        const status = await api('/desktop/status');
        if (status.enabled !== true || status.paused !== false) {
          setUser(null);
          setDesktopPaused(
            typeof status.detail === 'string' && status.detail
              ? status.detail
              : DESKTOP_PAUSED_MESSAGE,
          );
          return;
        }
      }
      setUser(await api('/auth/me'));
    } catch (e) {
      if ([503, 423].includes(e.status) && e.code === 'desktop_paused') {
        setUser(null);
        setDesktopPaused(e.message);
      } else if (e.status !== 401)
        setConnectionError('Serverga ulanib bo‘lmadi. Ulanishni tekshirib, qayta urinib ko‘ring.');
    } finally {
      setInitial(false);
    }
  }, []);
  useEffect(() => {
    applyTheme(user ? readTheme(user.id) : defaults);
    telegram?.updateColors();
  }, [user?.id, telegram]);
  useEffect(() => {
    loadSession();
    const ended = () => {
      setUser(null);
      notify('Seans tugadi. Qayta kiring.', true);
    };
    const paused = (event) => {
      setUser(null);
      setDesktopPaused(
        typeof event.detail === 'string' && event.detail ? event.detail : DESKTOP_PAUSED_MESSAGE,
      );
      setConnectionError('');
      setInitial(false);
    };
    window.addEventListener('session-ended', ended);
    window.addEventListener('desktop-paused', paused);
    return () => {
      window.removeEventListener('session-ended', ended);
      window.removeEventListener('desktop-paused', paused);
    };
  }, [loadSession, notify]);
  const loadBranches = useCallback(
    () =>
      api('/branches?include_archived=true')
        .then(setBranches)
        .catch((e) => notify(e.message, true)),
    [notify],
  );
  useEffect(() => {
    if (user) {
      setInitialChange(null);
      setInitialDebt(null);
      loadBranches();
      setBranch(user.branch_id ? String(user.branch_id) : '');
      setPage(homeForRole(user.role));
    }
  }, [user, loadBranches]);
  useEffect(() => {
    const syncOperation = () => {
      try {
        setOperation(user ? readPending(user.id) : null);
      } catch {
        notify('Brauzer xotirasidagi yuborilgan amalni o‘qib bo‘lmadi.', true);
      }
    };
    syncOperation();
    window.addEventListener('crm-operation-changed', syncOperation);
    return () => window.removeEventListener('crm-operation-changed', syncOperation);
  }, [user, notify]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 6500);
    return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    if (!mobile) return;
    const close = (event) => {
      if (event.key === 'Escape') setMobile(false);
    };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [mobile]);
  if (desktopPaused)
    return (
      <main className="empty" aria-label="EXE faoliyati to‘xtatilgan">
        <h2>EXE vaqtincha to‘xtatilgan</h2>
        <p>{desktopPaused}</p>
        <p>Davom etish uchun brauzerda tincrm.uz saytini yoki Telegram Mini Appni oching.</p>
      </main>
    );
  if (initial) return <Loading />;
  if (connectionError)
    return (
      <div className="empty">
        <h2>Ulanish mavjud emas</h2>
        <p>{connectionError}</p>
        <button className="primary" onClick={loadSession}>
          <RefreshCw size={18} />
          Qayta urinish
        </button>
      </div>
    );
  if (!user) return <Login onLogin={setUser} />;
  const requiresBranch =
    ['pos', 'inventory', 'reports'].includes(page) ||
    (page === 'analytics' && user.role !== 'boss');
  const availableBranches = ['pos', 'inventory'].includes(page)
    ? branches.filter((b) => !b.archived)
    : ['reports', 'analytics'].includes(page) && user.role !== 'boss'
      ? branches.filter((b) => b.id === user.branch_id)
      : branches;
  const selectedBranch = availableBranches.some((b) => String(b.id) === branch)
    ? branch
    : requiresBranch
      ? String(availableBranches.find((b) => !b.archived)?.id || availableBranches[0]?.id || '')
      : '';
  const archivedBranch = branches.find((b) => String(b.id) === selectedBranch)?.archived;
  const props = {
    user,
    branch: selectedBranch,
    branches,
    notify,
    setPage,
    setBranch,
    loadBranches,
    initialChange: initialChange?.user_id === user.id ? initialChange : null,
    onChangeOpened: changeOpened,
    initialDebt: initialDebt?.user_id === user.id ? initialDebt : null,
    onDebtOpened: debtOpened,
    onAccountChanged: () => setUser(null),
  };
  const Current = {
    dashboard: Dashboard,
    pos: POS,
    debts: Debts,
    expenses: Expenses,
    inventory: Inventory,
    suppliers: Suppliers,
    donations: Donations,
    reports: Reports,
    analytics: SalesAnalytics,
    team: Team,
    settings: Settings,
  }[page];
  return (
    <div className="app-shell emerald-workspace">
      <OceanCardBackgrounds />
      {mobile && (
        <button
          className="sidebar-backdrop"
          aria-label="Menyuni yopish"
          onClick={() => setMobile(false)}
        />
      )}
      <aside
        id="workspace-navigation"
        className={'sidebar ' + (mobile ? 'open' : '')}
        aria-label="Asosiy menyu"
      >
        <div className="sidebar-header">
          <Logo
            workspace
            onClick={() => {
              setPage(homeForRole(user.role));
              setMobile(false);
            }}
          />
          <button
            className="icon-btn sidebar-close"
            aria-label="Yon menyuni yopish"
            onClick={() => setMobile(false)}
          >
            <X size={20} />
          </button>
          <div className="workspace-company">
            <span />
            MARWA COMPANY
          </div>
        </div>
        <div className="sidebar-scroll">
          <div className="workspace-label">ISH MAYDONI</div>
          <nav aria-label="Bo‘limlar">
            {nav
              .filter(([id]) =>
                user.role === 'cashier'
                  ? ['pos', 'debts', 'settings'].includes(id)
                  : id !== 'team' || user.role === 'boss',
              )
              .map(([id, label, Icon]) => (
                <button
                  key={id}
                  className={page === id ? 'active' : ''}
                  aria-current={page === id ? 'page' : undefined}
                  onClick={() => {
                    setPage(id);
                    setMobile(false);
                  }}
                >
                  <Icon size={19} />
                  <span className="nav-label">{label}</span>
                  {page === id && <span className="nav-mark" />}
                </button>
              ))}
          </nav>
        </div>
        <div className="sidebar-bottom">
          <div className="branch-note">
            <span className="status-dot" />
            Lokal sinov muhiti
            <small>{branches.filter((b) => !b.archived).length} ta faol filial</small>
          </div>
          <div className="profile">
            <div className="avatar">{user.name.slice(0, 1)}</div>
            <div>
              <strong>{user.name}</strong>
              <small>
                {user.role_label ||
                  { boss: 'Boshliq', admin: 'Admin', cashier: 'Kassir' }[user.role]}
              </small>
            </div>
            <button
              className="icon-btn"
              aria-label="Chiqish"
              onClick={async () => {
                try {
                  await post('/auth/logout', {});
                  setUser(null);
                } catch (e) {
                  notify(e.message, true);
                }
              }}
            >
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      <div className="app-content">
        <WorkspaceBackdrop />
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-btn mobile-toggle"
              onClick={() => setMobile(!mobile)}
              aria-label="Menyu"
              aria-controls="workspace-navigation"
              aria-expanded={mobile}
            >
              <Menu />
            </button>
            <span>Ish maydoni</span>
            <span className="slash">/</span>
            <strong>{nav.find((n) => n[0] === page)?.[1]}</strong>
          </div>
          <div className="topbar-right">
            <Notifications
              key={`${user.id}:${user.role}`}
              user={user}
              branch={selectedBranch}
              branches={branches}
              notify={notify}
              onOpenChange={openChange}
              onOpenHistory={() => openChange(null)}
              onOpenDebt={openDebt}
              onOpenDebts={() => setPage('debts')}
            />
            <span className="today-label">{uzDate(new Date(), false)}</span>
            {page !== 'team' && (
              <label className="branch-picker">
                <Warehouse size={16} />
                <select
                  aria-label="Filial"
                  value={selectedBranch}
                  disabled={user.role !== 'boss'}
                  onChange={(e) => setBranch(e.target.value)}
                >
                  {!requiresBranch && <option value="">Barcha filiallar</option>}
                  {availableBranches.map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.name}
                      {b.archived ? ' — Arxiv' : ''}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} />
              </label>
            )}
          </div>
        </header>
        <main className={'main ' + (page === 'pos' ? 'pos-main' : '')}>
          {archivedBranch && (
            <p className="branch-archive-notice" role="status">
              Bu filial arxivlangan. Tarix va hisoblar saqlangan. Yangi amal uchun Programmist
              filialni tiklashi kerak.
            </p>
          )}
          <Current
            key={page + ':' + (page === 'analytics' ? '' : selectedBranch) + ':' + revision}
            {...props}
          />
        </main>
        <footer className="app-footer">
          <strong>
            TIN <span>tomonidan ishlab chiqilgan</span>
          </strong>
          <span>Faqat lokal · Sun’iy sinov ma’lumotlari</span>
        </footer>
      </div>
      <MiniAppBottomNav
        role={user.role}
        page={page}
        onNavigate={(destination) => {
          setPage(destination);
          setMobile(false);
          window.scrollTo(0, 0);
        }}
      />
      {operation && (
        <RecoveryModal
          user={user}
          operation={operation}
          notify={notify}
          onResolved={() => setRevision((value) => value + 1)}
        />
      )}
      {isTelegramEntry() && <ExportDownloadSheet />}
      {toast && (
        <div
          className={'toast ' + (toast.error ? 'bad' : '')}
          role={toast.error ? 'alert' : 'status'}
        >
          <CircleCheck size={20} />
          <span>{toast.message}</span>
          <button className="icon-btn" onClick={() => setToast(null)} aria-label="Yopish">
            <X size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById('root')).render(<App />);
