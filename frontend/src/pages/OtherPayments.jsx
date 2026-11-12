import React, { useEffect, useState } from 'react';
import { ArrowUpRight, Banknote, RefreshCw, Undo2, Wallet } from 'lucide-react';
import { api, query } from '../api';
import { requestId } from '../id';
import { readPending, recoverablePost } from '../recovery';
import { decimal, safeCents } from '../money';
import { OperationCancelModal } from '../OperationCancelModal';
import { Amount, Badge, Empty, Field, FormFooter, Modal, MoneyInput, Pager, dateFmt } from '../components';
import { DataState, Table, useData } from './shared';
import './other-payments.css';

function signedCents(value) {
  const amount = String(value ?? '0');
  return amount.startsWith('-') ? -safeCents(amount.slice(1)) : safeCents(amount);
}

function OtherPaymentModal({ branch, branches, user, notify, onClose, onSaved }) {
  const activeBranches = branches.filter((item) =>
    !item.archived && (user.role === 'boss' || String(item.id) === String(user.branch_id)));
  const [selectedBranch, setSelectedBranch] = useState(() => {
    if (activeBranches.some((item) => String(item.id) === String(branch))) return String(branch);
    return activeBranches.length === 1 ? String(activeBranches[0].id) : '';
  });
  const [method, setMethod] = useState('cash');
  const [amount, setAmount] = useState('');
  const [balance, setBalance] = useState(null);
  const [balanceError, setBalanceError] = useState('');
  const [busy, setBusy] = useState(false);
  const [id] = useState(requestId);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setBalance(null);
    setBalanceError('');
    if (selectedBranch) {
      api('/dashboard' + query({ branch_id: selectedBranch }), { signal: controller.signal })
        .then((value) => { if (current) setBalance(value); })
        .catch((failure) => {
          if (current && failure.name !== 'AbortError') setBalanceError(failure.message);
        });
    }
    return () => { current = false; controller.abort(); };
  }, [selectedBranch, refresh]);
  const before = balance ? signedCents(balance[method]) : null;
  const available = before === null ? null : decimal(before);
  const amountCents = safeCents(amount);
  const after = before === null ? null : before - amountCents;
  const unrecorded = before === null ? 0n : amountCents - (before > 0n ? before : 0n);
  async function submit(event) {
    event.preventDefault();
    if (busy || !selectedBranch || !balance) return;
    const values = Object.fromEntries(new FormData(event.currentTarget));
    if (!values.recipient.trim() || values.note.trim().length < 3) {
      notify('Qabul qiluvchi va kamida 3 belgili topshirish sababini kiriting.', true);
      return;
    }
    setBusy(true);
    try {
      await recoverablePost(user.id, '/other-payments', {
        request_id: id,
        branch_id: Number(selectedBranch),
        amount: values.amount,
        method,
        recipient: values.recipient.trim(),
        note: values.note.trim(),
      }, 'Boshqa pullar: pul topshirish');
      notify('Boshqa pul topshirig‘i qayd etildi. Kassa qoldig‘i yangilandi.');
      onClose();
      await onSaved();
    } catch (failure) {
      notify(failure.message, true);
      try { if (readPending(user.id)) onClose(); } catch { /* Preserve the form if storage is unavailable. */ }
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Boshqa pullar — pul topshirish" busy={busy} onClose={onClose} className="other-payment-modal">
      <form onSubmit={submit}>
        <p className="modal-description">
          Eski qarzlardan tushgan va boshqa mablag‘larni topshirish.
          Bu to‘lov ta’minotchining qolgan haqqidan ayirilmaydi.
        </p>
        <Field label="Filial">
          <select name="branch_id" value={selectedBranch} required disabled={busy}
            onChange={(event) => setSelectedBranch(event.target.value)}>
            <option value="" disabled>Filialni tanlang</option>
            {activeBranches.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </Field>
        <div className="other-payment-balance" aria-live="polite">
          <div className="other-payment-balance-icon"><Wallet size={22} /></div>
          <div>
            <span>{method === 'cash' ? 'Tizimdagi naqd pul qoldig‘i' : 'Tizimdagi karta qoldig‘i'}</span>
            <strong>{available !== null ? <Amount value={available} /> : selectedBranch ? 'Tekshirilmoqda…' : 'Avval filialni tanlang'}</strong>
          </div>
          {selectedBranch && <button className="icon-btn" type="button" aria-label="Kassa qoldig‘ini yangilash"
            disabled={busy} onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={17} /></button>}
        </div>
        {balanceError && <p className="error">Kassa qoldig‘i yuklanmadi: {balanceError}</p>}
        <div className="form-grid">
          <Field label="Qaysi hisobdan">
            <select name="method" value={method} disabled={busy} onChange={(event) => setMethod(event.target.value)}>
              <option value="cash">Naqd</option>
              <option value="card">Karta</option>
            </select>
          </Field>
          <Field label="Summa (so‘m)" hint="Ta’minotchi haqi va tizimdagi kassa qoldig‘i bilan cheklanmaydi.">
            <MoneyInput name="amount" min="0.01" required
              value={amount} onChange={setAmount} disabled={busy} />
          </Field>
        </div>
        <div className="other-payment-fill">
          <button className="text-btn" type="button" disabled={busy || before === null || before <= 0n}
            onClick={() => setAmount(available)}>Barchasini qo‘yish <ArrowUpRight size={15} /></button>
        </div>
        {after !== null && amountCents > 0n && (
          <div className={after < 0n ? 'other-payment-warning' : 'other-payment-after'} aria-live="polite">
            {after < 0n ? <>
              Tizimdagi mavjud mablag‘dan <strong><Amount value={decimal(unrecorded)} /></strong> ko‘p topshirilmoqda.
              {' '}Kassa hisobi <strong><Amount value={decimal(after)} /></strong> bo‘ladi. Sababini izohda yozing.
            </> : <>Topshirilgandan keyingi qoldiq: <strong><Amount value={decimal(after)} /></strong></>}
          </div>
        )}
        <Field label="Kimga topshirildi">
          <input name="recipient" maxLength={120} required disabled={busy} placeholder="Masalan: Marwa" />
        </Field>
        <Field label="Topshirish sababi / izoh">
          <textarea name="note" minLength={3} maxLength={500} required disabled={busy} placeholder="Masalan: oldingi qarzlardan yig‘ilgan pul" />
        </Field>
        <FormFooter busy={busy} submitDisabled={!selectedBranch || !balance} onClose={onClose} label="Pul berishni qayd etish" />
      </form>
    </Modal>
  );
}

export function OtherPayments({ branch, branches, user, notify, open, onClose, onOpen }) {
  const scope = String(branch ?? '');
  const [paging, setPaging] = useState({ scope, offset: 0 });
  const offset = paging.scope === scope ? paging.offset : 0;
  const [cancelling, setCancelling] = useState(null);
  const [data, reload, error] = useData(
    () => api('/payments' + query({ branch_id: branch, others_offset: offset, others_limit: 20 })),
    [branch, offset], notify,
    { keepPreviousData: true, dataScope: scope },
  );
  const entries = data?.others || [];
  const count = data?.others_count ?? entries.length;
  return (
    <section className="panel section-gap other-payments-panel">
      <div className="panel-head other-payments-head">
        <div className="other-payments-heading">
          <span className="other-payments-icon"><Banknote size={23} /></span>
          <div><h2>Boshqa pullar</h2><p>Eski qarzlardan tushgan va boshqa topshirilgan mablag‘lar.</p></div>
        </div>
        <button type="button" className="secondary compact" onClick={onOpen}>
          Pul topshirish <ArrowUpRight size={16} />
        </button>
      </div>
      {!data ? <DataState error={error} reload={reload} /> : <>
        <div className="other-payments-total">
          <div><span>Jami topshirilgan boshqa pullar</span><strong><Amount value={data.other_paid || 0} /></strong></div>
          <Badge tone="gray">{count} ta topshirish</Badge>
        </div>
        {error && <p className="error other-payments-error">Yangilash amalga oshmadi: {error}</p>}
        {entries.length ? <Table headers={['Kimga topshirildi', 'Summa', 'Hisob', 'Filial', 'Xodim', 'Sana / izoh', 'Amal']}>
          {entries.map((payment) => <tr key={payment.id}>
            <td><strong>{payment.recipient}</strong><small>Boshqa pullar · #{payment.id}</small></td>
            <td className="number"><Amount value={payment.amount} /></td>
            <td><Badge>{payment.method === 'cash' ? 'Naqd' : 'Karta'}</Badge></td>
            <td>{branches.find((item) => item.id === payment.branch_id)?.name || '—'}</td>
            <td>{payment.actor}</td>
            <td>{dateFmt(payment.created_at)}<small>{payment.note || '—'}</small></td>
            <td>{payment.operation?.can_cancel && ['boss', 'admin'].includes(user.role) ?
              <button type="button" className="text-btn" onClick={() => setCancelling({
                ...payment, action: 'Boshqa pul berildi', detail: {
                  recipient: payment.recipient, amount: payment.amount, method: payment.method, note: payment.note,
                },
              })}><Undo2 size={15} /> Bekor qilish</button> : '—'}</td>
          </tr>)}
        </Table> : <Empty title="Hali boshqa pul topshirilmagan" text="Eski qarzdan yig‘ilgan va boshqa mablag‘larni topshirish shu yerda qayd etiladi." />}
        <Pager offset={offset} setOffset={(nextOffset) => setPaging({ scope, offset: nextOffset })}
          count={entries.length} pageSize={20} total={count} pageToken={data} showTotal />
      </>}
      {open && <OtherPaymentModal branch={branch} branches={branches} user={user} notify={notify}
        onClose={onClose} onSaved={reload} />}
      {cancelling && <OperationCancelModal audit={cancelling} user={user} notify={notify}
        branchName={branches.find((item) => item.id === cancelling.branch_id)?.name || '—'}
        onClose={() => setCancelling(null)} onSaved={() => { setCancelling(null); reload(); }}>
        <dl className="details">
          <div><dt>Kimga topshirilgan</dt><dd>{cancelling.recipient}</dd></div>
          <div><dt>Topshirilgan summa</dt><dd><Amount value={cancelling.amount} /></dd></div>
          <div><dt>Hisob</dt><dd>{cancelling.method === 'cash' ? 'Naqd' : 'Karta'}</dd></div>
          <div><dt>Asl topshirish izohi</dt><dd>{cancelling.note}</dd></div>
        </dl>
      </OperationCancelModal>}
    </section>
  );
}
