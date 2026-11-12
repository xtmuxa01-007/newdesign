import React, { useEffect, useState } from 'react';
import { Download, RefreshCw } from 'lucide-react';
import './desktop-controls.css';

export function DesktopControls() {
  const desktop = window.tinDesktop;
  const [state, setState] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!desktop) return;
    let alive = true;
    const refresh = async () => {
      try {
        const next = await desktop.updateStatus();
        if (alive && next.ok) setState(next);
      } catch {
        /* Oyna almashayotganida eski so'rov natijasi kerak emas. */
      }
    };
    refresh();
    const timer = setInterval(refresh, 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [desktop]);
  if (!desktop) return null;
  async function run(action) {
    setBusy(true);
    setError('');
    try {
      const next = await desktop[action]();
      if (!next.ok) throw new Error(next.error);
      if (next.phase) setState(next);
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }
  const working = ['checking', 'downloading', 'installing'].includes(state?.phase);
  const message = {
    checking: 'Yangilanish tekshirilmoqda…',
    downloading: `Yangi ${state?.version} versiya yuklanmoqda: ${state?.percent || 0}%`,
    ready: `${state?.version} tayyor. O‘rnatishda dastur qayta ochiladi, ma’lumotlar saqlanadi.`,
    current: 'Sizda oxirgi versiya o‘rnatilgan.',
    installing: 'Baza zaxiralanmoqda va yangilanish o‘rnatilmoqda…',
  }[state?.phase];
  return (
    <section className="desktop-controls" aria-label="EXE boshqaruvi">
      <div className="desktop-update-row">
        <small>EXE {state?.current || ''}</small>
        <button
          type="button"
          className="desktop-link"
          disabled={busy || working}
          onClick={() => run(state?.phase === 'ready' ? 'installUpdate' : 'checkUpdate')}
        >
          {state?.phase === 'ready' ? <Download size={16} /> : <RefreshCw size={16} />}
          {state?.phase === 'ready' ? 'Qayta ishga tushirib o‘rnatish' : 'Yangilanishni tekshirish'}
        </button>
      </div>
      {desktop.mode === 'online' && (
        <small>Web va barcha EXElar umumiy bazada ishlaydi. Savdo uchun internet kerak.</small>
      )}
      {state?.phase === 'downloading' && (
        <progress value={state.percent} max="100" aria-label="Yangilanish yuklanishi" />
      )}
      {message && <small role="status">{message}</small>}
      {(error || state?.error) && (
        <small className="desktop-error" role="alert">
          {error || state.error}
        </small>
      )}
    </section>
  );
}
