import React, { useState } from 'react';
import { Check, RotateCcw, ShoppingBag, Banknote, CreditCard, Warehouse } from 'lucide-react';
import { post } from '../api';
import { Field } from '../components';
import { colors, defaults, presets, readTheme, applyTheme } from '../theme';
import { DesktopControls } from '../DesktopControls';
import { DashboardMetric } from '../DashboardSurface';
import '../theme-preview.css';

export function Settings({ user, notify, onAccountChanged }) {
  const [theme, setTheme] = useState(() => readTheme(user.id));
  const [busy, setBusy] = useState(false);
  const matches = (palette) => colors.every(([key]) => theme[key]?.toLowerCase() === palette[key]);
  const selectedPreset = presets.find(({ palette }) => matches(palette));
  const isDefault = matches(defaults);
  function saveColors(next) {
    try {
      localStorage.setItem(`crm-theme-${user.id}`, JSON.stringify(next));
      setTheme(next);
      applyTheme(next);
    } catch {
      notify('Ranglarni brauzer xotirasiga saqlab bo‘lmadi.', true);
    }
  }
  async function saveAccount(event) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    if (data.new_password !== data.confirm_password)
      return notify('Yangi parollar mos emas.', true);
    delete data.confirm_password;
    if (!data.new_password) delete data.new_password;
    setBusy(true);
    try {
      await post('/auth/settings', data);
      onAccountChanged();
      window.alert('Login/parol yangilandi. Yangi ma’lumotlar bilan qayta kiring.');
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <DesktopControls />
      <section className="panel settings-panel">
        <h2>Ranglar</h2>
        <p>
          Tayyor dizaynni tanlang yoki ranglarni alohida sozlang. Tanlov shu brauzerda hisobingiz
          uchun saqlanadi.
        </p>
        <div className="theme-design-workbench">
          <fieldset className="theme-presets">
            <legend>Tayyor dizaynlar</legend>
            <div className="theme-preset-grid">
              {presets.map((preset) => {
                const active = selectedPreset?.id === preset.id;
                return (
                  <button
                    type="button"
                    key={preset.id}
                    className={'theme-preset' + (active ? ' selected' : '')}
                    aria-pressed={active}
                    aria-label={preset.label}
                    onClick={() => saveColors({ ...preset.palette })}
                    style={{
                      '--preview-page': preset.palette.page,
                      '--preview-sidebar': preset.palette.sidebar,
                      '--preview-topbar': preset.palette.topbar,
                      '--preview-accent': preset.palette['nav-active'],
                      '--preview-surface': preset.palette.surface,
                      '--preview-wave': preset.palette['wave-light'],
                    }}
                  >
                    <span className="theme-preview" aria-hidden="true">
                      <i />
                      <i />
                      <i />
                      <i />
                      <i />
                    </span>
                    <span className="theme-preset-caption">
                      <strong>{preset.label}</strong>
                      <small>{preset.description}</small>
                    </span>
                    {active && (
                      <Check className="theme-preset-check" size={18} aria-hidden="true" />
                    )}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              className="secondary theme-reset"
              disabled={isDefault}
              aria-label="Dastlabki ranglarni tiklash"
              onClick={() => saveColors({ ...defaults })}
            >
              <RotateCcw size={22} aria-hidden="true" />
              Standart Emerald temaga qaytish
            </button>
            <p className="theme-current" role="status">
              Joriy dizayn:{' '}
              <strong>
                {selectedPreset?.label || (isDefault ? 'Dastlabki' : 'Shaxsiy ranglar')}
              </strong>
            </p>
          </fieldset>
          <section
            className="theme-home-preview dashboard-overview"
            aria-label="Bosh sahifa kartalari sinovi"
          >
            <header className="theme-home-preview-heading">
              <span className="eyebrow">JONLI KO‘RINISH</span>
              <h3>Bosh sahifa kartalari</h3>
              <p>Sinov qiymatlari — barchasi 0. Rang va animatsiyani kartalar ustida ko‘ring.</p>
            </header>
            <div className="stats-grid">
              <DashboardMetric
                label="Bugungi savdo"
                value={0}
                icon={ShoppingBag}
                note="Bugungi tushum"
              />
              <DashboardMetric
                label="Shu oydagi savdo"
                value={0}
                icon={Banknote}
                note="Oyning boshidan bugungacha"
              />
              <DashboardMetric
                label="Kassadagi pullar"
                value={0}
                icon={CreditCard}
                note="Naqd: 0 so‘m · Karta: 0 so‘m"
                variant="stat-card--cash"
              />
              <DashboardMetric
                label="Ombordagi mahsulotlar"
                value={0}
                icon={Warehouse}
                note="0 ta mahsulot qoldig‘i"
                variant="stat-card--stock"
                weight
              />
            </div>
          </section>
        </div>
        <div className="color-grid">
          {colors.map(([key, label]) => (
            <Field key={key} label={label}>
              <input
                type="color"
                value={theme[key]}
                onInput={(e) => saveColors({ ...theme, [key]: e.target.value })}
                onChange={(e) => saveColors({ ...theme, [key]: e.target.value })}
              />
            </Field>
          ))}
        </div>
      </section>
      <section className="panel settings-panel section-gap">
        <h2>Login va parol</h2>
        <p>Login va parol shu lokal sinov bazasida almashtiriladi.</p>
        <p>
          Saqlangandan keyin barcha seanslaringiz yopiladi. Yangi parolni bo‘sh qoldirsangiz, faqat
          login o‘zgaradi.
        </p>
        <form onSubmit={saveAccount} className="account-settings-form">
          <Field
            label="Login"
            hint="3–60 belgi: lotin harflari, raqamlar, nuqta, pastki chiziq yoki tire."
          >
            <input
              name="username"
              defaultValue={user.username}
              required
              minLength={3}
              maxLength={60}
              pattern="[a-zA-Z0-9_.\-]{3,60}"
              autoComplete="username"
              disabled={busy}
            />
          </Field>
          <Field label="Joriy parol">
            <input
              name="current_password"
              type="password"
              required
              maxLength={200}
              autoComplete="current-password"
              disabled={busy}
            />
          </Field>
          <Field label="Yangi parol (kamida 10 belgi)">
            <input
              name="new_password"
              type="password"
              minLength={10}
              maxLength={200}
              autoComplete="new-password"
              disabled={busy}
            />
          </Field>
          <Field label="Yangi parolni takrorlang">
            <input
              name="confirm_password"
              type="password"
              minLength={10}
              maxLength={200}
              autoComplete="new-password"
              disabled={busy}
            />
          </Field>
          <button className="primary" disabled={busy}>
            {busy ? 'Saqlanmoqda…' : 'Login/parolni saqlash'}
          </button>
        </form>
      </section>
    </>
  );
}
