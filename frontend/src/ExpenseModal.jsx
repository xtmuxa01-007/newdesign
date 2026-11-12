// POS va filiallar oynasi bir xil xarajat formasidan foydalanadi.
import React, { useEffect, useState } from 'react';
import { api, query } from './api';
import { requestId } from './id';
import { recoverablePost } from './recovery';
import { fmt } from './money';
import { Field, Modal, MoneyInput } from './components';

export function ExpenseModal({ user, branch, branches, notify, onClose, onSaved }) {
  const [selectedBranch, setBranch] = useState(
    String(
      user.role === 'boss'
        ? branches.some((b) => String(b.id) === String(branch) && !b.archived)
          ? branch
          : ''
        : user.branch_id,
    ),
  );
  const [method, setMethod] = useState('cash'),
    [supplier, setSupplier] = useState('');
  const [options, setOptions] = useState(null),
    [error, setError] = useState('');
  const [busy, setBusy] = useState(false),
    [id] = useState(requestId),
    [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setOptions(null);
    setError('');
    setSupplier('');
    if (selectedBranch)
      api('/expenses/options' + query({ branch_id: selectedBranch }))
        .then((value) => {
          if (active) setOptions(value);
        })
        .catch((e) => {
          if (active) setError(e.message);
        });
    return () => {
      active = false;
    };
  }, [selectedBranch, retry]);
  async function submit(e) {
    e.preventDefault();
    if (busy || !options) return;
    const f = Object.fromEntries(new FormData(e.currentTarget));
    setBusy(true);
    try {
      await recoverablePost(
        user.id,
        '/expenses',
        {
          request_id: id,
          branch_id: Number(selectedBranch),
          supplier_id: Number(supplier),
          method,
          amount: f.amount,
          reason: f.reason,
        },
        'Filial xarajati',
      );
      notify('Xarajat saqlandi. Kassa va ta’minotchining qolgan haqi yangilandi.');
      onClose();
      await onSaved?.();
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Filial xarajati" busy={busy} onClose={onClose}>
      <form onSubmit={submit}>
        <Field label="Filial">
          <select
            value={selectedBranch}
            disabled={user.role !== 'boss' || busy}
            onChange={(e) => setBranch(e.target.value)}
            required
          >
            <option value="">Filialni tanlang</option>
            {branches
              .filter((b) => !b.archived)
              .map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Pul turi">
          <select value={method} disabled={busy} onChange={(e) => setMethod(e.target.value)}>
            <option value="cash">Naqd</option>
            <option value="card">Karta</option>
          </select>
        </Field>
        {options && <p className="notice">Tanlangan hisobda: {fmt(options[method])} so‘m</p>}
        <Field label="Qaysi ta’minotchining pulidan">
          <select
            value={supplier}
            disabled={!options || busy}
            required
            onChange={(e) => setSupplier(e.target.value)}
          >
            <option value="">Ta’minotchini tanlang</option>
            {options?.suppliers.map((s) => (
              <option key={s.id} value={s.id} disabled={Number(s.debt) <= 0}>
                {s.name} · Qolgan haq: {fmt(s.debt)} so‘m
              </option>
            ))}
          </select>
        </Field>
        <Field label="Xarajat summasi">
          <MoneyInput name="amount" min="0.01" required disabled={busy} />
        </Field>
        <Field label="Nima uchun sarflandi">
          <textarea
            name="reason"
            required
            maxLength={500}
            rows={3}
            disabled={busy}
            placeholder="Masalan: filial uchun tozalash vositalari"
          />
        </Field>
        <p className="modal-description">
          Bu summa tanlangan kassadan va ta’minotchiga beriladigan haqdan ayriladi. Xarajat sababi,
          xodim va vaqt tarixda saqlanadi.
        </p>
        {error && (
          <p className="error">
            {error}{' '}
            <button type="button" className="text-btn" onClick={() => setRetry((v) => v + 1)}>
              Qayta yuklash
            </button>
          </p>
        )}
        {!!selectedBranch && !options && !error && <p>Hisoblar yuklanmoqda…</p>}
        <div className="form-footer">
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>
            Bekor qilish
          </button>
          <button className="primary" disabled={busy || !options || !supplier}>
            {busy ? 'Saqlanmoqda…' : 'Xarajatni saqlash'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
