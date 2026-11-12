// Bo‘limlar uchun umumiy yuklash, jadval va to‘lov formasi.
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
  Trash2,
  Pencil,
} from 'lucide-react';
import { api, post, query } from '../api';
import { requestId } from '../id';
import { recoverablePost } from '../recovery';
import { fmt, kgFmt, lineCents, decimal, safeCents } from '../money';
import { debtAmounts } from '../debt-management';
import {
  Amount,
  Badge,
  Empty,
  Field,
  FormFooter,
  Loading,
  Modal,
  MoneyInput,
  Pager,
  ProductImage,
  dateFmt,
  DateTime,
} from '../components';
import '../sale-rows.css';
import '../sale-edit.css';

export function useData(loader, deps, notify, { keepPreviousData = false, dataScope } = {}) {
  const [data, setData] = useState(null),
    [error, setError] = useState('');
  const generation = useRef(0);
  const previousScope = useRef(dataScope);
  const load = useCallback(async () => {
    const id = ++generation.current;
    try {
      const value = await loader();
      if (id === generation.current) {
        setData(value);
        setError('');
      }
    } catch (e) {
      if (id === generation.current) {
        setError(e.message);
        notify(e.message, true);
      }
    }
  }, deps);
  useEffect(() => {
    if (!keepPreviousData || previousScope.current !== dataScope) setData(null);
    previousScope.current = dataScope;
    load();
    return () => {
      generation.current++;
    };
  }, [load, keepPreviousData, dataScope]);
  return [data, load, error];
}
export function DataState({ error, reload }) {
  return error ? (
    <div className="empty">
      <h3>Ma’lumot yuklanmadi</h3>
      <p>{error}</p>
      <button className="secondary" onClick={reload}>
        <RefreshCw size={16} />
        Qayta urinish
      </button>
    </div>
  ) : (
    <Loading />
  );
}
export function PageActions({ children }) {
  return children ? <div className="page-actions">{children}</div> : null;
}
export function Metric({ label, value, icon: Icon, note, accent = false, weight = false }) {
  return (
    <div className={'metric ' + (accent ? 'accent' : '')}>
      <div className="metric-top">
        <span>{label}</span>
        <Icon size={19} />
      </div>
      <strong>
        {weight ? kgFmt(value) : fmt(value)} <small>{weight ? 'kg' : 'so‘m'}</small>
      </strong>
      <span className="metric-note">{note}</span>
    </div>
  );
}
export function BranchField({ branch, branches }) {
  return (
    <Field label="Filial">
      <select
        name="branch_id"
        defaultValue={
          branches.some((b) => String(b.id) === String(branch) && !b.archived) ? branch : ''
        }
        required
      >
        <option value="" disabled>
          Filialni tanlang
        </option>
        {branches
          .filter((b) => !b.archived)
          .map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
      </select>
    </Field>
  );
}
export function Table({ headers, children }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}
export function SaleRows({ sales, branches, onDetail, onEdit, onCancel, cancelLoadingId = null }) {
  return sales.map((s) => (
    <tr
      key={s.id}
      className={onDetail ? 'sale-row-open' : undefined}
      tabIndex={onDetail ? 0 : undefined}
      aria-label={onDetail ? `Savdo #${s.id}: tafsilotlarni ochish` : undefined}
      onClick={
        onDetail
          ? (event) => {
              if (event.defaultPrevented) return;
              const control = event.target.closest?.(
                'a, button, input, select, textarea, label, summary, [role="button"], [role="link"], [tabindex], [contenteditable]',
              );
              if (control && control !== event.currentTarget) return;
              onDetail(s);
            }
          : undefined
      }
      onKeyDown={
        onDetail
          ? (event) => {
              if (
                event.target !== event.currentTarget ||
                event.defaultPrevented ||
                event.repeat ||
                event.altKey ||
                event.ctrlKey ||
                event.metaKey ||
                !['Enter', ' '].includes(event.key)
              )
                return;
              event.preventDefault();
              onDetail(s);
            }
          : undefined
      }
    >
      <td>
        <button
          type="button"
          className="text-btn"
          onClick={(event) => {
            event.stopPropagation();
            onDetail?.(s);
          }}
        >
          #{String(s.id).padStart(5, '0')}
        </button>
        <small>
          {s.debt
            ? `${s.debt.debtor.first_name} ${s.debt.debtor.last_name}`
            : s.customer || 'Oddiy savdo'}
        </small>
      </td>
      <td>
        <DateTime value={s.created_at} />
      </td>
      <td>{branches.find((b) => b.id === s.branch_id)?.name}</td>
      <td>{s.cashier || '—'}</td>
      <td className="number">
        <Amount
          value={decimal(
            safeCents(s.cash) +
              safeCents(s.card) +
              (s.debt ? safeCents(debtAmounts(s.debt).paid) : 0n),
          )}
        />
      </td>
      <td>
        <Badge>
          {s.debt
            ? s.debt.status === 'paid'
              ? 'Qarz yopilgan'
              : s.debt.status === 'partial'
                ? 'Qisman to‘langan qarz'
                : 'Qarzga'
            : Number(s.cash) && Number(s.card)
              ? 'Naqd + karta'
              : Number(s.card)
                ? 'Karta'
                : 'Naqd'}
        </Badge>
      </td>
      {(onEdit || onCancel) && (
        <td>
          <div className="sale-row-actions">
            {onEdit && (
              <button
                type="button"
                className="secondary compact"
                aria-label={`Savdo #${s.id}ni tahrirlash`}
                disabled={!s.editable_until || Date.now() >= new Date(s.editable_until).getTime()}
                title={
                  Date.now() >= new Date(s.editable_until).getTime()
                    ? '72 soatlik tahrirlash muddati tugagan'
                    : 'Mahsulotni qaytarish yoki savdoni tuzatish'
                }
                onClick={(event) => {
                  event.stopPropagation();
                  onEdit(s);
                }}
              >
                <Pencil size={15} /> Tahrirlash
              </button>
            )}
            {onCancel && (
              <button
                type="button"
                className="text-btn sale-delete"
                aria-label={`Savdo #${s.id}ni o‘chirish`}
                disabled={cancelLoadingId !== null}
                onClick={(event) => {
                  event.stopPropagation();
                  onCancel(s);
                }}
              >
                <Trash2 size={16} />
                {cancelLoadingId === s.id ? 'Tekshirilmoqda…' : 'O‘chirish'}
              </button>
            )}
          </div>
        </td>
      )}
    </tr>
  ));
}

export function PaymentModal({ supplier, branch, branches, onClose, notify, reload, user }) {
  const [busy, setBusy] = useState(false);
  const [id] = useState(requestId);
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    const f = Object.fromEntries(new FormData(e.currentTarget));
    f.branch_id = Number(f.branch_id);
    f.request_id = id;
    try {
      await recoverablePost(
        user.id,
        supplier ? `/suppliers/${supplier.id}/payments` : '/donations/payments',
        f,
        supplier ? `${supplier.name}: pul berish` : 'Ehson puli berish',
      );
      notify('To‘lov qayd etildi.');
      onClose();
      await reload();
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={supplier ? `${supplier.name} — to‘lov` : 'Ehson mablag‘ini berish'}
      busy={busy}
      onClose={onClose}
    >
      <form onSubmit={submit}>
        <p className="modal-description">
          {supplier ? `Qolgan haq: ${fmt(supplier.debt)} so‘m. ` : ''}Amalda berilgan pulni qayd
          eting.
        </p>
        <BranchField branch={branch} branches={branches} />
        <div className="form-grid">
          <Field
            label="Summa (so‘m)"
            hint={supplier ? undefined : 'Bir amalda eng ko‘pi 15 000 so‘m.'}
          >
            <MoneyInput name="amount" min="0.01" max={supplier ? undefined : '15000'} required />
          </Field>
          <Field label="Qaysi hisobdan">
            <select name="method">
              <option value="cash">Naqd</option>
              <option value="card">Karta</option>
            </select>
          </Field>
        </div>
        <Field label="Kimga berildi">
          <input
            name="recipient"
            placeholder="Qabul qiluvchining ism-familiyasi"
            maxLength={120}
            required
          />
        </Field>
        <Field label="Izoh / o‘tkazma ma’lumoti">
          <textarea name="note" maxLength={500} placeholder="Masalan: bank o‘tkazmasi raqami" />
        </Field>
        <FormFooter busy={busy} onClose={onClose} label="To‘lovni qayd etish" />
      </form>
    </Modal>
  );
}
export function PaymentTable({ entries, branches, suppliers = [] }) {
  return entries.length ? (
    <Table headers={['Qabul qiluvchi', 'Summa', 'Hisob', 'Filial', 'Qayd etgan', 'Sana / izoh']}>
      {entries.map((p) => (
        <tr key={p.id}>
          <td>
            <strong>{p.recipient}</strong>
            <small>{suppliers.find((s) => s.id === p.supplier_id)?.name || 'Ehson'}</small>
          </td>
          <td className="number">
            <Amount value={p.amount} />
          </td>
          <td>
            <Badge>{p.method === 'cash' ? 'Naqd' : 'Karta'}</Badge>
          </td>
          <td>{branches.find((b) => b.id === p.branch_id)?.name}</td>
          <td>{p.actor}</td>
          <td>
            {dateFmt(p.created_at)}
            <small>{p.note}</small>
          </td>
        </tr>
      ))}
    </Table>
  ) : (
    <Empty title="Hali to‘lov qayd etilmagan" />
  );
}
