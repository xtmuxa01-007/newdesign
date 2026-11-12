// Faqat boshliq uchun xodim va filiallarni boshqarish.
import React, { useCallback, useEffect, useState, useRef } from 'react';
import {
  Plus,
  Search,
  ArrowUpRight,
  Banknote,
  CreditCard,
  Warehouse,
  ShoppingBag,
  HeartHandshake,
  Truck,
  Download,
  RefreshCw,
  PackagePlus,
  Percent,
  ImagePlus,
  ChevronRight,
  ShieldCheck,
  Archive,
  RotateCcw,
} from 'lucide-react';
import { api, post, query } from '../api';
import { requestId } from '../id';
import { fmt, kgFmt, lineCents, decimal } from '../money';
import {
  Amount,
  Badge,
  Empty,
  Field,
  FormFooter,
  Loading,
  Modal,
  Pager,
  ProductImage,
  dateFmt,
} from '../components';

import {
  useData,
  DataState,
  PageActions,
  Metric,
  BranchField,
  Table,
  SaleRows,
  PaymentModal,
  PaymentTable,
} from './shared';

export function Team({ branches, notify, loadBranches, user, setPage, onAccountChanged }) {
  const [data, reload, error] = useData(() => api('/users'), [], notify);
  const [modal, setModal] = useState(null),
    [busy, setBusy] = useState(false),
    [role, setRole] = useState('cashier');
  const [branchAction, setBranchAction] = useState(null);
  const [branchView, setBranchView] = useState('active');
  async function changeBranch(e) {
    e.preventDefault();
    setBusy(true);
    const confirmation = new FormData(e.currentTarget).get('confirmation');
    try {
      await post(
        `/branches/${branchAction.branch.id}/${branchAction.restore ? 'restore' : 'archive'}`,
        { confirmation },
      );
      await loadBranches();
      setBranchAction(null);
      notify(
        branchAction.restore
          ? 'Filial qayta tiklandi.'
          : 'Filial arxivlandi. Savdo, qarz va ombor tarixi saqlandi.',
      );
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }
  async function submit(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    const f = Object.fromEntries(new FormData(e.currentTarget));
    try {
      if (modal.type === 'branch') {
        await post('/branches', f);
        await loadBranches();
      } else if (modal.type === 'account') {
        if (!f.password) delete f.password;
        await post(`/users/${modal.user.id}`, f, 'PATCH');
        const ownAccountChanged =
          modal.user.id === user.id &&
          (f.username.toLowerCase() !== modal.user.username.toLowerCase() || !!f.password);
        if (ownAccountChanged) {
          setModal(null);
          notify('Login/parol yangilandi. Yangi ma’lumotlar bilan qayta kiring.');
          onAccountChanged();
          window.alert('Login/parol yangilandi. Yangi ma’lumotlar bilan qayta kiring.');
          return;
        }
      } else {
        f.branch_id = f.role === 'boss' ? null : Number(f.branch_id);
        await post('/users', f);
      }
      setModal(null);
      await reload();
      notify('Ma’lumot saqlandi.');
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  async function toggle(u) {
    if (
      !window.confirm(
        `${u.name} hisobi ${u.active ? 'faolsizlantirilsinmi' : 'faollashtirilsinmi'}?`,
      )
    )
      return;
    setBusy(true);
    try {
      await post(`/users/${u.id}`, { active: !u.active }, 'PATCH');
      await reload();
      notify('Hisob holati o‘zgartirildi.');
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  if (!data) return <DataState error={error} reload={reload} />;
  return (
    <>
      <PageActions>
        <button className="secondary" onClick={() => setPage('expenses')}>
          Filial xarajatlari
        </button>
        <button className="secondary" onClick={() => setModal({ type: 'branch' })}>
          <Plus size={18} />
          Filial qo‘shish
        </button>
        <button
          className="primary"
          onClick={() => {
            setRole('cashier');
            setModal({ type: 'user' });
          }}
        >
          <Plus size={18} />
          Xodim qo‘shish
        </button>
      </PageActions>
      <div className="role-cards">
        {[
          ['Boshliq', 'Barcha filiallar, hisoblar va xodimlarni boshqaradi.'],
          ['Admin', 'O‘z filialidagi ombor, chegirma, savdo va to‘lovlarni boshqaradi.'],
          ['Kassir', 'O‘z filialidagi mahsulotlarni ko‘radi va savdo qiladi.'],
        ].map(([title, text]) => (
          <div key={title}>
            <ShieldCheck size={22} />
            <h3>{title}</h3>
            <p>{text}</p>
          </div>
        ))}
      </div>
      <section className="panel">
        <Table headers={['Xodim', 'Login', 'Rol', 'Filial', 'Holat', 'Amallar']}>
          {data.map((u) => (
            <tr key={u.id}>
              <td>
                <strong>{u.name}</strong>
              </td>
              <td>{u.username}</td>
              <td>
                {u.role_label || { boss: 'Boshliq', admin: 'Admin', cashier: 'Kassir' }[u.role]}
              </td>
              <td>{branches.find((b) => b.id === u.branch_id)?.name || 'Barcha filiallar'}</td>
              <td>
                <Badge
                  tone={
                    u.active && !branches.find((b) => b.id === u.branch_id)?.archived
                      ? 'green'
                      : 'gray'
                  }
                >
                  {!u.active
                    ? 'Faol emas'
                    : branches.find((b) => b.id === u.branch_id)?.archived
                      ? 'Filial arxivda'
                      : 'Faol'}
                </Badge>
              </td>
              <td>
                <div className="row-actions">
                  <button
                    className="text-btn"
                    disabled={busy || (u.is_programmer && u.id !== user.id)}
                    onClick={() => setModal({ type: 'account', user: u })}
                  >
                    Login va parol
                  </button>
                  <button
                    className="text-btn"
                    disabled={u.id === user.id || busy || u.is_programmer}
                    onClick={() => toggle(u)}
                  >
                    {u.active ? 'To‘xtatish' : 'Faollashtirish'}
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </Table>
      </section>
      <section className="panel section-gap">
        <div className="panel-head">
          <div>
            <h2>Filiallar</h2>
            <p>Arxivlangan filialning savdo, qarz va ombor tarixi saqlanadi.</p>
          </div>
          <div className="row-actions">
            <button
              className="secondary"
              aria-pressed={branchView === 'active'}
              onClick={() => setBranchView('active')}
            >
              Faol ({branches.filter((b) => !b.archived).length})
            </button>
            <button
              className="secondary"
              aria-pressed={branchView === 'archived'}
              onClick={() => setBranchView('archived')}
            >
              Arxiv ({branches.filter((b) => b.archived).length})
            </button>
          </div>
        </div>
        <div className="branch-tags">
          {branches
            .filter((b) => Boolean(b.archived) === (branchView === 'archived'))
            .map((b) => (
              <span key={b.id}>
                <Warehouse size={18} />
                <strong>{b.name}</strong>
                <small>#{b.id}</small>
                {b.archived && <Badge tone="gray">Arxiv</Badge>}
                {user.can_archive_branches && (
                  <button
                    className="text-btn"
                    disabled={busy}
                    aria-label={`${b.name} — ${b.archived ? 'qayta tiklash' : 'o‘chirish'}`}
                    onClick={() => setBranchAction({ branch: b, restore: Boolean(b.archived) })}
                  >
                    {b.archived ? <RotateCcw size={16} /> : <Archive size={16} />}
                    {b.archived ? 'Tiklash' : 'O‘chirish'}
                  </button>
                )}
              </span>
            ))}
          {!branches.some((b) => Boolean(b.archived) === (branchView === 'archived')) && (
            <p>
              {branchView === 'archived' ? 'Arxivlangan filiallar yo‘q.' : 'Faol filiallar yo‘q.'}
            </p>
          )}
        </div>
      </section>
      {branchAction && (
        <Modal
          title={branchAction.restore ? 'Filialni qayta tiklash' : 'Filialni o‘chirish — arxivlash'}
          busy={busy}
          onClose={() => setBranchAction(null)}
        >
          <form onSubmit={changeBranch}>
            <p>
              <strong>{branchAction.branch.name}</strong>
            </p>
            <p>
              {branchAction.restore
                ? 'Filial qayta faol bo‘ladi. Xodimlar yana kirib, savdo va boshqa amallarni bajarishi mumkin.'
                : 'Filial faol ro‘yxatdan olinadi va unda yangi amallar to‘xtaydi. Savdo, qarz, ombor va xodimlar tarixi saqlanadi. Keyin Arxiv bo‘limidan tiklash mumkin.'}
            </p>
            <Field label="Tasdiqlash uchun filial nomini yozing">
              <input
                name="confirmation"
                required
                maxLength={120}
                autoComplete="off"
                disabled={busy}
              />
            </Field>
            <FormFooter
              busy={busy}
              onClose={() => setBranchAction(null)}
              label={branchAction.restore ? 'Filialni tiklash' : 'Arxivlash'}
            />
          </form>
        </Modal>
      )}
      {modal && (
        <Modal
          title={
            modal.type === 'branch'
              ? 'Yangi filial'
              : modal.type === 'account'
                ? `${modal.user.name} — login va parol`
                : 'Yangi xodim'
          }
          busy={busy}
          onClose={() => setModal(null)}
        >
          <form onSubmit={submit}>
            {modal.type !== 'account' && (
              <Field label={modal.type === 'branch' ? 'Filial nomi' : 'Ism-familiya'}>
                <input name="name" required maxLength={120} />
              </Field>
            )}
            {['user', 'account'].includes(modal.type) && (
              <Field
                label="Login"
                hint="3–60 belgi: lotin harflari, raqamlar, nuqta, pastki chiziq yoki tire."
              >
                <input
                  name="username"
                  defaultValue={modal.type === 'account' ? modal.user.username : ''}
                  required
                  minLength={3}
                  maxLength={60}
                  pattern="[a-zA-Z0-9_.\-]+"
                  autoComplete="off"
                  disabled={busy}
                />
              </Field>
            )}
            {modal.type === 'user' && (
              <>
                <Field label="Rol">
                  <select name="role" value={role} onChange={(e) => setRole(e.target.value)}>
                    <option value="cashier">Kassir</option>
                    <option value="admin">Admin</option>
                    <option value="boss">Boshliq</option>
                  </select>
                </Field>
                {role !== 'boss' && <BranchField branches={branches} />}
              </>
            )}
            {modal.type !== 'branch' && (
              <Field
                label={modal.type === 'account' ? 'Yangi parol' : 'Parol'}
                hint={
                  modal.type === 'account'
                    ? 'Bo‘sh qoldirsangiz, joriy parol saqlanadi. Yangi parol kamida 10 ta belgi bo‘lsin.'
                    : 'Kamida 10 ta belgi. Parol yangilansa, eski seanslar yopiladi.'
                }
              >
                <input
                  name="password"
                  type="password"
                  required={modal.type === 'user'}
                  minLength={10}
                  maxLength={200}
                  autoComplete="new-password"
                  disabled={busy}
                />
              </Field>
            )}
            {modal.type === 'account' && (
              <p className="notice">
                Login yoki parol o‘zgarsa, shu xodimning barcha seanslari yopiladi. Keyingi kirishda
                yangi ma’lumotlardan foydalaniladi.
              </p>
            )}
            <FormFooter busy={busy} onClose={() => setModal(null)} />
          </form>
        </Modal>
      )}
    </>
  );
}
