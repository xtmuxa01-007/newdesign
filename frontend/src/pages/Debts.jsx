// Qarz va to‘lov tarixi saqlanadi; qolgan qarz faqat haqiqiy to‘lov bilan kamayadi.
import React, { useEffect, useState } from 'react';
import {
  Banknote,
  CreditCard,
  ShieldCheck,
  CalendarDays,
  CircleX,
  History,
  MapPin,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Users,
} from 'lucide-react';
import { api, post, query } from '../api';
import { requestId } from '../id';
import { readPending, recoverablePost } from '../recovery';
import { OperationCancelModal } from '../OperationCancelModal';
import { DebtActionsMenu } from '../DebtActionsMenu';
import { uzDate } from '../dates';
import { fmt, safeCents, decimal } from '../money';
import {
  Amount,
  Badge,
  Empty,
  Field,
  FormFooter,
  Modal,
  Pager,
  dateFmt,
  MoneyInput,
} from '../components';
import {
  debtAmounts,
  debtPayments,
  paymentCancelled,
  paymentValidation,
  tashkentToday,
} from '../debt-management';
import '../debt-management.css';
import { useData, DataState, PageActions, BranchField, Table } from './shared';

function PersonFields({ person }) {
  return [
    ['first_name', 'Ism', 60],
    ['last_name', 'Familiya', 60],
    ['phone1', '1-telefon raqami', 30],
    ['phone2', '2-telefon raqami', 30],
    ['address', 'Yashash manzili', 500],
  ].map(([name, label, max]) => (
    <Field key={name} label={label}>
      <input
        name={name}
        type={name.startsWith('phone') ? 'tel' : 'text'}
        defaultValue={person?.[name] || ''}
        maxLength={max}
        required
      />
    </Field>
  ));
}

function PersonForm({ person, branch, branches, notify, onClose, reload }) {
  const [busy, setBusy] = useState(false);
  async function submit(e) {
    e.preventDefault();
    const values = Object.fromEntries(new FormData(e.currentTarget));
    values.branch_id = Number(person?.branch_id || values.branch_id);
    setBusy(true);
    try {
      await post(person ? `/debtors/${person.id}` : '/debtors', values, person ? 'PUT' : 'POST');
      notify('Qarzdor ma’lumotlari saqlandi.');
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
      title={person ? 'Qarzdorni tahrirlash' : 'Qarzdor qo‘shish'}
      onClose={onClose}
      busy={busy}
    >
      <form onSubmit={submit}>
        {!person && <BranchField branch={branch} branches={branches} />}
        <PersonFields person={person} />
        <FormFooter onClose={onClose} busy={busy} />
      </form>
    </Modal>
  );
}

function OpeningDebtForm({ branch, branches, people, user, notify, onClose, reload }) {
  const activeBranches = branches.filter((item) => !item.archived);
  const [selectedBranch, setSelectedBranch] = useState(() =>
    activeBranches.some((item) => String(item.id) === String(branch)) ? String(branch) : '',
  );
  const [debtorId, setDebtorId] = useState('');
  const [amount, setAmount] = useState('');
  const [dueDate, setDueDate] = useState('');
  const [note, setNote] = useState('');
  const [addedPeople, setAddedPeople] = useState([]);
  const [newPerson, setNewPerson] = useState(false);
  const [busy, setBusy] = useState(false);
  const [id] = useState(requestId);
  const branchPeople = [...people, ...addedPeople].filter(
    (person, index, all) =>
      String(person.branch_id) === selectedBranch &&
      all.findIndex((item) => item.id === person.id) === index,
  );

  async function submitPerson(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const values = Object.fromEntries(new FormData(event.currentTarget));
      values.branch_id = Number(selectedBranch);
      const person = await post('/debtors', values);
      setAddedPeople((current) => [...current, person]);
      setDebtorId(String(person.id));
      setNewPerson(false);
      notify('Qarzdor qo‘shildi. Endi qarz summasini saqlang.');
      await reload();
    } catch (error) {
      notify(error.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    if (busy || safeCents(amount) <= 0n || !selectedBranch || !debtorId) return;
    setBusy(true);
    try {
      await recoverablePost(
        user.id,
        '/opening-debts',
        {
          request_id: id,
          branch_id: Number(selectedBranch),
          debtor_id: Number(debtorId),
          amount,
          ...(dueDate ? { due_date: dueDate } : {}),
          note,
        },
        `Oldingi qarz: ${branchPeople.find((person) => String(person.id) === debtorId)?.first_name || ''}`,
      );
      window.dispatchEvent(new Event('crm-debts-changed'));
      notify('Oldingi qarz saqlandi.');
      onClose();
      await reload();
    } catch (error) {
      notify(error.message, true);
      // Aloqa uzilganda aynan shu so‘rov «Natijani tekshirish»da qayta yuboriladi.
      try {
        if (readPending(user.id)) onClose();
      } catch {
        // Xotira xatosida yangi so‘rov yaratmay, formani saqlaymiz.
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={newPerson ? 'Qarzdor qo‘shish' : 'Oldingi qarzni kiritish'}
      onClose={onClose}
      busy={busy}
    >
      {newPerson ? (
        <form onSubmit={submitPerson}>
          <p className="modal-description">
            {activeBranches.find((item) => String(item.id) === selectedBranch)?.name}
          </p>
          <PersonFields />
          <FormFooter busy={busy} onClose={() => setNewPerson(false)} label="Qarzdorni qo‘shish" />
        </form>
      ) : (
        <form onSubmit={submit}>
          <p className="modal-description">
            Avval berilgan qarz summasini kiriting. Qaysi mahsulot olinganini yozish shart emas.
          </p>
          <Field label="Filial">
            <select
              value={selectedBranch}
              onChange={(event) => {
                setSelectedBranch(event.target.value);
                setDebtorId('');
              }}
              required
              disabled={busy}
            >
              <option value="" disabled>
                Filialni tanlang
              </option>
              {activeBranches.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Qarzdor">
            <select
              value={debtorId}
              onChange={(event) => setDebtorId(event.target.value)}
              required
              disabled={busy || !selectedBranch}
            >
              <option value="" disabled>
                Qarzdorni tanlang
              </option>
              {branchPeople.map((person) => (
                <option key={person.id} value={person.id}>
                  {person.first_name} {person.last_name} · {person.phone1}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="button"
            className="secondary"
            disabled={busy || !selectedBranch}
            onClick={() => setNewPerson(true)}
          >
            <Plus size={16} /> Yangi qarzdor qo‘shish
          </button>
          {selectedBranch && !branchPeople.length && (
            <p className="notice">Bu filialda qarzdor yo‘q. Yangi qarzdor qo‘shing.</p>
          )}
          <Field label="Qarz summasi (so‘m)">
            <MoneyInput value={amount} onChange={setAmount} min="0.01" required disabled={busy} />
          </Field>
          <Field label="Qaytarish sanasi" hint="Ixtiyoriy. Bo‘sh qolsa bugungi sana olinadi.">
            <input
              type="date"
              value={dueDate}
              onChange={(event) => setDueDate(event.target.value)}
              disabled={busy}
            />
          </Field>
          <Field label="Izoh" hint="Ixtiyoriy.">
            <textarea
              value={note}
              onChange={(event) => setNote(event.target.value)}
              maxLength={500}
              rows={2}
              disabled={busy}
            />
          </Field>
          <p className="notice">
            Faqat mijoz qarzi qayd etiladi. Kassa va ombor o‘zgarmaydi, yangi savdo yaratilmaydi.
          </p>
          <FormFooter onClose={onClose} busy={busy} label="Qarzni saqlash" />
        </form>
      )}
    </Modal>
  );
}

function PayForm({ debt, user, notify, onClose, reload }) {
  const [cash, setCash] = useState(''),
    [card, setCard] = useState('');
  const [nextDueDate, setNextDueDate] = useState('');
  const [busy, setBusy] = useState(false),
    [id] = useState(requestId);
  const { remaining } = debtAmounts(debt);
  const total = safeCents(cash) + safeCents(card);
  const afterPayment = safeCents(remaining) - total;
  const canManage = ['boss', 'admin'].includes(user.role);
  const effectiveDueDate = canManage && afterPayment > 0n ? nextDueDate : '';
  const validation = paymentValidation({ cash, card, remaining, nextDueDate: effectiveDueDate });
  async function submit(e) {
    e.preventDefault();
    if (busy || validation) return;
    setBusy(true);
    try {
      await recoverablePost(
        user.id,
        `${debt.origin === 'opening' ? '/opening-debts' : '/debts'}/${debt.id}/pay`,
        {
          request_id: id,
          cash: cash || '0',
          card: card || '0',
          ...(debt.management?.expected_fingerprint
            ? { expected_fingerprint: debt.management.expected_fingerprint }
            : {}),
          ...(effectiveDueDate ? { next_due_date: effectiveDueDate } : {}),
        },
        `${debt.origin === 'opening' ? 'Oldingi qarz' : 'Qarz'} #${debt.id}: to‘lov`,
      );
      window.dispatchEvent(new Event('crm-debts-changed'));
      notify(
        afterPayment === 0n
          ? 'To‘lov saqlandi. Qarz to‘liq yopildi.'
          : 'Qisman to‘lov saqlandi. Qolgan qarz yangilandi.',
      );
      onClose();
      await reload();
    } catch (e) {
      notify(e.message, true);
      try {
        if (readPending(user.id)) onClose();
      } catch {
        // Javobi noma’lum so‘rovni yangi ID bilan yubormaymiz.
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={`${debt.origin === 'opening' ? 'Oldingi qarz' : 'Qarz'} #${debt.id} — to‘lovni qabul qilish`}
      onClose={onClose}
      busy={busy}
      className="debt-payment-modal"
    >
      <form onSubmit={submit}>
        <div className="debt-payment-body">
        <div className="debt-payment-hero">
          <span className="payment-person-icon"><Users size={24} /></span>
          <div>
            <strong>{debt.debtor.first_name} {debt.debtor.last_name}</strong>
            <span>Qolgan qarz</span>
            <b><Amount value={remaining} /></b>
          </div>
        </div>
        <p className="payment-guidance">Haqiqatan qabul qilingan pulni kiriting.</p>
        <div className="debt-payment-inputs">
        <Field label={<><Banknote size={18} /> Naqd</>}>
          <MoneyInput value={cash} onChange={setCash} max={remaining} disabled={busy} />
        </Field>
        <Field label={<><CreditCard size={18} /> Karta</>}>
          <MoneyInput value={card} onChange={setCard} max={remaining} disabled={busy} />
        </Field>
        </div>
        <div className="debt-payment-shortcuts">
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => {
              setCash(remaining);
              setCard('');
            }}
          >
            <Banknote size={17} /> Qoldiqni to‘liq naqd
          </button>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={() => {
              setCash('');
              setCard(remaining);
            }}
          >
            <CreditCard size={17} /> Qoldiqni to‘liq karta
          </button>
        </div>
        <dl className="debt-payment-totals">
          <div>
            <dt>Hozirgi to‘lov</dt>
            <dd>
              <Amount value={decimal(total)} />
            </dd>
          </div>
          <div>
            <dt>To‘lovdan keyin qoladi</dt>
            <dd>
              <Amount value={decimal(afterPayment > 0n ? afterPayment : 0n)} />
            </dd>
          </div>
        </dl>
        {canManage && afterPayment > 0n && (
          <Field
            label="Qolgan qarzni qaytarish sanasi"
            hint={`Ixtiyoriy. Bo‘sh qolsa ${debt.due_date} sanasi saqlanadi.`}
          >
            <input
              type="date"
              value={nextDueDate}
              min={tashkentToday()}
              onChange={(event) => setNextDueDate(event.target.value)}
              disabled={busy}
            />
          </Field>
        )}
        <p className="notice debt-payment-note">
          <ShieldCheck size={20} />
          <span>Qisman yoki muddatidan oldin to‘lash mumkin. Har bir to‘lov tarixga yoziladi va pul kassaga qo‘shiladi.</span>
        </p>
        {validation && (cash || card || nextDueDate) && (
          <p className="error" role="alert">
            {validation}
          </p>
        )}
        </div>
        <FormFooter
          onClose={onClose}
          busy={busy}
          submitDisabled={!!validation}
          label="To‘lovni tasdiqlash"
        />
      </form>
    </Modal>
  );
}

function ReviseForm({ debt, people, editDetails, user, notify, onClose, reload }) {
  const [amount, setAmount] = useState(debt.amount);
  const [debtorId, setDebtorId] = useState(String(debt.debtor_id || debt.debtor.id));
  const [dueDate, setDueDate] = useState(debt.due_date);
  const [note, setNote] = useState(debt.note || '');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [id] = useState(requestId);
  const { paid, remaining } = debtAmounts(debt);
  const expectedFingerprint = debt.management?.expected_fingerprint;
  const branchPeople = people.filter((person) => person.branch_id === debt.branch_id);
  const changed =
    dueDate !== debt.due_date ||
    (editDetails &&
      (safeCents(amount) !== safeCents(debt.amount) ||
        debtorId !== String(debt.debtor_id || debt.debtor.id) ||
        note !== (debt.note || '')));
  const invalidAmount =
    editDetails && (safeCents(amount) <= 0n || safeCents(amount) < safeCents(paid));
  const invalidDate = !dueDate || (dueDate !== debt.due_date && dueDate < tashkentToday());
  const canSubmit =
    !!expectedFingerprint &&
    changed &&
    !invalidAmount &&
    !invalidDate &&
    (!editDetails || !!debtorId) &&
    reason.trim().length >= 3;

  async function submit(event) {
    event.preventDefault();
    if (busy || !canSubmit) return;
    setBusy(true);
    try {
      await recoverablePost(
        user.id,
        `${debt.origin === 'opening' ? '/opening-debts' : '/debts'}/${debt.id}/revise`,
        {
          request_id: id,
          expected_fingerprint: expectedFingerprint,
          reason: reason.trim(),
          due_date: dueDate,
          ...(editDetails ? { amount, debtor_id: Number(debtorId), note } : {}),
        },
        `${debt.origin === 'opening' ? 'Oldingi qarz' : 'Qarz'} #${debt.id}: ${editDetails ? 'ma’lumotni tuzatish' : 'muddatni o‘zgartirish'}`,
      );
      window.dispatchEvent(new Event('crm-debts-changed'));
      notify(
        editDetails
          ? 'Qarz ma’lumotlari tuzatildi. Sabab tarixga saqlandi.'
          : 'Yangi muddat saqlandi. Avvalgi sana tarixda saqlanadi.',
      );
      onClose();
      await reload();
    } catch (error) {
      notify(error.message, true);
      try {
        if (readPending(user.id)) onClose();
      } catch {
        // Aloqa uzilganda saqlangan so‘rovni tiklash orqali tekshiramiz.
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={editDetails ? 'Oldingi qarz ma’lumotlarini tuzatish' : 'Qarz muddatini o‘zgartirish'}
      onClose={onClose}
      busy={busy}
    >
      <form onSubmit={submit}>
        <p className="modal-description">
          {debt.debtor.first_name} {debt.debtor.last_name} · Qolgan qarz:{' '}
          <Amount value={remaining} />
        </p>
        {editDetails && (
          <>
            <Field label="Qarzdor">
              <select
                value={debtorId}
                onChange={(event) => setDebtorId(event.target.value)}
                required
                disabled={busy}
              >
                {branchPeople.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.first_name} {person.last_name} · {person.phone1}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              label="Jami qarz summasi (so‘m)"
              hint={`Hozirgacha ${fmt(paid)} so‘m to‘langan. Jami summa bundan kam bo‘lmasin.`}
            >
              <MoneyInput
                value={amount}
                onChange={setAmount}
                min={safeCents(paid) > 0n ? paid : '0.01'}
                required
                disabled={busy}
              />
            </Field>
            {invalidAmount && (
              <p className="error">
                Qarz summasi musbat bo‘lsin va to‘langan summadan kam bo‘lmasin.
              </p>
            )}
            <Field label="Izoh">
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={500}
                rows={2}
                disabled={busy}
              />
            </Field>
          </>
        )}
        <Field label="Qaytarish sanasi" hint={`Hozirgi muddat: ${debt.due_date}.`}>
          <input
            type="date"
            value={dueDate}
            onChange={(event) => setDueDate(event.target.value)}
            min={editDetails ? undefined : tashkentToday()}
            required
            disabled={busy}
          />
        </Field>
        {invalidDate && <p className="error">Yangi muddat bugungi sanadan oldin bo‘lmasin.</p>}
        <Field label="O‘zgartirish sababi" hint="Kamida 3 belgi yozing.">
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            minLength={3}
            maxLength={500}
            rows={3}
            required
            disabled={busy}
            placeholder="Mijoz bilan kelishilgan sana yoki xato kiritilgan ma’lumot"
          />
        </Field>
        <p className="notice">
          Avvalgi ma’lumotlar va to‘lovlar tarixda saqlanadi. Bu amal pul qabul qilmaydi.
        </p>
        {debt.origin !== 'opening' && (
          <p className="notice">
            Savdo summasi yoki mahsulotdagi xatoni «Savdolar va tarix» bo‘limidagi #{debt.sale_id}{' '}
            savdodan tuzating.
          </p>
        )}
        <FormFooter
          onClose={onClose}
          busy={busy}
          submitDisabled={!canSubmit}
          label="O‘zgarishni saqlash"
        />
      </form>
    </Modal>
  );
}

function DebtHistory({ debt, canManage, onCancel, onClose }) {
  const { original, paid, remaining } = debtAmounts(debt);
  const payments = debtPayments(debt);
  const revisions = debt.revisions || [];
  return (
    <Modal
      title={`${debt.origin === 'opening' ? 'Oldingi qarz' : 'Qarz'} #${debt.id} — tarix`}
      onClose={onClose}
    >
      <p className="modal-description">
        {debt.debtor.first_name} {debt.debtor.last_name}
      </p>
      <div className="debt-contact-details">
        <p>
          {debt.debtor.phone1}
          {debt.debtor.phone2 && ` · ${debt.debtor.phone2}`}
        </p>
        {debt.debtor.address && <p>Manzil: {debt.debtor.address}</p>}
        {debt.origin === 'opening' && debt.note && <p>Izoh: {debt.note}</p>}
      </div>
      <dl className="details">
        <div>
          <dt>Jami qarz</dt>
          <dd>
            <Amount value={original} />
          </dd>
        </div>
        <div>
          <dt>To‘langan</dt>
          <dd>
            <Amount value={paid} />
          </dd>
        </div>
        <div>
          <dt>Qolgan qarz</dt>
          <dd>
            <Amount value={remaining} />
          </dd>
        </div>
        <div>
          <dt>Hozirgi muddat</dt>
          <dd>{debt.due_date}</dd>
        </div>
      </dl>
      <h3>To‘lovlar</h3>
      {!payments.length && <p className="modal-description">Hali to‘lov qabul qilinmagan.</p>}
      {payments.map((payment, index) => (
        <div
          className={`debt-history-item${paymentCancelled(payment) ? ' debt-history-cancelled' : ''}`}
          key={`${payment.operation?.kind || 'payment'}:${payment.id || index}`}
        >
          <div className="debt-history-heading">
            <strong>
              <Amount value={decimal(safeCents(payment.cash) + safeCents(payment.card))} />
            </strong>
            {paymentCancelled(payment) && <Badge tone="gray">Bekor qilingan</Badge>}
          </div>
          <small>
            {dateFmt(payment.created_at)} · {payment.actor}
          </small>
          <small>
            Naqd: {fmt(payment.cash)} · Karta: {fmt(payment.card)}
          </small>
          {(payment.cancelled_at || payment.operation?.cancelled_at) && (
            <small>
              Bekor qilingan vaqt: {dateFmt(payment.cancelled_at || payment.operation.cancelled_at)}
            </small>
          )}
          {(payment.cancel_reason || payment.operation?.reason) && (
            <p>Bekor qilish sababi: {payment.cancel_reason || payment.operation.reason}</p>
          )}
          {canManage && payment.operation?.can_cancel && !paymentCancelled(payment) && (
            <button className="text-btn" onClick={() => onCancel(payment)}>
              <CircleX size={16} /> Noto‘g‘ri to‘lovni bekor qilish
            </button>
          )}
        </div>
      ))}
      <h3>Ma’lumot va muddat o‘zgarishlari</h3>
      {!revisions.length && (
        <p className="modal-description">Ma’lumot va muddat o‘zgartirilmagan.</p>
      )}
      {revisions.map((revision, index) => (
        <div className="debt-history-item" key={revision.id || index}>
          <small>
            {dateFmt(revision.created_at)} · {revision.actor}
          </small>
          {revision.before?.due_date !== revision.after?.due_date && (
            <p>
              Muddat: {revision.before?.due_date} → {revision.after?.due_date}
            </p>
          )}
          {revision.before?.amount !== revision.after?.amount && (
            <p>
              Qarz: <Amount value={revision.before?.amount} /> →{' '}
              <Amount value={revision.after?.amount} />
            </p>
          )}
          {revision.before?.debtor_id !== revision.after?.debtor_id && <p>Qarzdor tuzatildi.</p>}
          {revision.before?.note !== revision.after?.note && (
            <p>
              Izoh: {revision.before?.note || '—'} → {revision.after?.note || '—'}
            </p>
          )}
          <p>Sabab: {revision.reason}</p>
        </div>
      ))}
      <div className="form-footer">
        <button className="secondary" onClick={onClose}>
          Yopish
        </button>
      </div>
    </Modal>
  );
}

function paymentAudit(debt, payment) {
  return {
    action: debt.origin === 'opening' ? 'Oldingi qarz to‘lovi' : 'Qarz to‘lovi',
    operation: payment.operation,
    actor: payment.actor,
    created_at: payment.created_at,
    branch_id: debt.branch_id,
    debtor: debt.debtor,
    amount: decimal(safeCents(payment.cash) + safeCents(payment.card)),
  };
}

function DebtRow({ debt: d, branches, canManage, setModal, scope }) {
  const { original, paid, remaining } = debtAmounts(d);
  const open = safeCents(remaining) > 0n;
  const partial = open && safeCents(paid) > 0n;
  const name = `${d.debtor.first_name} ${d.debtor.last_name}`;
  const actionLabel = `${name}, ${d.origin === 'opening' ? 'oldingi qarz' : 'qarz'} #${d.id}`;
  const branchName = branches.find((branch) => branch.id === d.branch_id)?.name || '—';
  const actions = [];
  if (canManage && d.management?.can_revise) {
    if (open)
      actions.push({
        label: 'Muddatni o‘zgartirish',
        icon: CalendarDays,
        action: () => setModal({ type: 'revise', value: d }),
      });
    if (d.origin === 'opening')
      actions.push({
        label: 'Ma’lumotni tahrirlash',
        icon: Pencil,
        action: () => setModal({ type: 'revise', value: d, editDetails: true }),
      });
  }
  actions.push({
    label: 'To‘lov va o‘zgarishlar tarixi',
    icon: History,
    action: () => setModal({ type: 'history', value: d }),
  });
  if (d.origin === 'opening' && canManage && d.operation?.can_cancel)
    actions.push({
      label: 'Qarzni bekor qilish',
      icon: CircleX,
      danger: true,
      action: () =>
        setModal({
          type: 'cancel',
          value: {
            action: 'Oldingi qarz kiritildi',
            operation: d.operation,
            actor: d.created_by,
            created_at: d.created_at,
            branch_id: d.branch_id,
            debtor: d.debtor,
            amount: d.amount,
          },
        }),
    });
  const secondPhone =
    d.debtor.phone2?.replace(/\D/g, '') !== d.debtor.phone1?.replace(/\D/g, '')
      ? d.debtor.phone2
      : '';
  return (
    <tr
      className={`${open && d.overdue ? 'debt-row-overdue ' : ''}${open ? 'debt-row-payable' : ''}`}
      onClick={open ? (event) => {
        if (!event.currentTarget.contains(event.target) ||
            event.target.closest('button, a, input, select, textarea, [role="menu"]') ||
            window.getSelection()?.toString()) return;
        setModal({ type: 'pay', value: d });
      } : undefined}
    >
      <td className="debt-person-cell">
        <strong className="debt-person-name">{name}</strong>
        <small className="debt-row-meta">
          {d.origin === 'opening' ? `Oldingi qarz #${d.id}` : `Qarz #${d.id} · Savdo #${d.sale_id}`}
        </small>
        <small className="debt-branch-name">{branchName}</small>
        {d.origin === 'opening' && d.note && (
          <small className="debt-row-note" title={d.note}>
            {d.note}
          </small>
        )}
      </td>
      <td className="debt-contact-cell">
        <span className="debt-phone">{d.debtor.phone1}</span>
        {secondPhone && <small>{secondPhone}</small>}
        <small className="debt-address" title={d.debtor.address}>
          <MapPin size={12} />
          <span>{d.debtor.address}</span>
        </small>
      </td>
      <td className="debt-amounts">
        <strong>
          <Amount value={remaining} />
        </strong>
        <small>
          Jami: <Amount value={original} />
        </small>
        <small>
          To‘langan: <Amount value={paid} />
        </small>
      </td>
      <td className="debt-due-cell">
        <span className="debt-due-date">
          {d.due_date ? uzDate(`${d.due_date}T12:00:00Z`, false, true) : 'Belgilanmagan'}
        </span>
        <Badge tone={open ? (partial ? 'orange' : 'gray') : 'green'}>
          {open ? (partial ? 'Qisman to‘langan' : 'To‘lanmagan') : 'To‘langan'}
        </Badge>
        {open && d.overdue && <small className="debt-overdue-label">Muddati kelgan</small>}
      </td>
      <td>
        <div className="debt-actions">
          {open && (
            <button
              type="button"
              className="primary debt-pay-button"
              aria-label={`${actionLabel}: to‘lov qabul qilish`}
              title="To‘lov qabul qilish"
              onClick={() => setModal({ type: 'pay', value: d })}
            >
              To‘lov
            </button>
          )}
          <DebtActionsMenu label={`${actionLabel}: boshqa amallar`} items={actions} scope={scope} />
        </div>
      </td>
    </tr>
  );
}

export function Debts({ branch, branches, notify, user, initialDebt, onDebtOpened }) {
  const [status, setStatus] = useState('open'),
    [offset, setOffset] = useState(0);
  const [modal, setModal] = useState(null),
    [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search.trim());
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const canManage = ['boss', 'admin'].includes(user.role);
  const [data, reload, error] = useData(
    async () => {
      const [debts, people] = await Promise.all([
        api(
          '/debts' +
            query({ branch_id: branch, status: status === 'people' ? 'open' : status, offset, limit: 20, q: debouncedSearch }),
        ),
        api('/debtors' + query({ branch_id: branch })),
      ]);
      return { debts, people };
    },
    [branch, status, offset, debouncedSearch],
    notify,
    { keepPreviousData: true, dataScope: `${branch}:${status}` },
  );
  useEffect(() => {
    const timer = setInterval(reload, 30000);
    return () => clearInterval(timer);
  }, [reload]);
  useEffect(() => {
    if (!initialDebt || initialDebt.user_id !== user.id) return;
    setModal({ type: 'history', value: initialDebt.debt });
    onDebtOpened(initialDebt.token);
  }, [initialDebt, user.id, onDebtOpened]);
  if (!data) return <DataState error={error} reload={reload} />;
  const people = data.people.filter((p) =>
    `${p.first_name} ${p.last_name} ${p.phone1} ${p.phone2}`
      .toLocaleLowerCase()
      .includes(search.toLocaleLowerCase()),
  );
  return (
    <>
      <div className="debts-page-actions">
        <PageActions>
          <button className="secondary" onClick={reload}>
            <RefreshCw size={16} />
            Yangilash
          </button>
          {canManage && (
            <button className="primary" onClick={() => setModal({ type: 'opening' })}>
              <Plus size={18} />
              Oldingi qarzni kiritish
            </button>
          )}
          {canManage && (
            <button className="secondary" onClick={() => setModal({ type: 'person' })}>
              <Plus size={18} />
              Qarzdor qo‘shish
            </button>
          )}
        </PageActions>
      </div>
      {error && (
        <p className="error">Yangilash amalga oshmadi. Oxirgi yuklangan ma’lumot ko‘rsatilmoqda.</p>
      )}
      <section className="panel debts-overview">
          <div className="debts-heading">
            <span className="debt-heading-icon">
              <Users size={23} />
            </span>
            <div>
              <h2>{status === 'people' ? 'Qarzdorlar ro‘yxati' : 'Qarzlar ro‘yxati'}</h2>
              <p>Qoldiq, muddat va to‘lovlar bir joyda.</p>
            </div>
          </div>
          <div className="debts-total">
            <span>
              {status === 'people'
                ? 'Qarzdorlar'
                : status === 'paid'
                  ? 'To‘langan qarz'
                  : 'Qolgan qarz'}
            </span>
            <strong>
              {status === 'people' ? data.people.length : <Amount value={data.debts.amount} />}
            </strong>
            <small>{status === 'people' ? 'ta qarzdor' : `${data.debts.count} ta qarz`}</small>
          </div>
      </section>
      <section className="panel debts-panel">
        <div className="filter-row debts-toolbar">
          <Field label="Ko‘rinish">
            <select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setOffset(0);
              }}
            >
              <option value="open">To‘lanmagan qarzlar</option>
              <option value="due">Muddati kelgan</option>
              <option value="partial">Qisman to‘langan</option>
              <option value="paid">To‘langan</option>
              <option value="all">Barcha qarzlar</option>
              <option value="people">Qarzdorlar ro‘yxati</option>
            </select>
          </Field>
          <label className="debts-search">
            <Search size={18} aria-hidden="true" />
            <input
              type="search"
              aria-label="Ism, familiya yoki telefon bo‘yicha qidirish"
              placeholder="Ism, familiya yoki telefon..."
              maxLength={120}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          {status !== 'people' && (
            <span className="debt-view-count">
              {data.debts.items.length} ta yozuv ko‘rsatilmoqda
            </span>
          )}
        </div>
        {status === 'people' ? (
          <>
            <Table headers={['Ism familiya', 'Telefonlar', 'Manzil', 'Filial', 'Amal']}>
              {people.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.first_name} {p.last_name}
                  </td>
                  <td>
                    {p.phone1}
                    <small>{p.phone2}</small>
                  </td>
                  <td>{p.address}</td>
                  <td>{branches.find((b) => b.id === p.branch_id)?.name}</td>
                  <td>
                    {user.role !== 'cashier' && (
                      <button
                        className="text-btn"
                        onClick={() => setModal({ type: 'person', value: p })}
                      >
                        Tahrirlash
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
            {!people.length && <Empty title="Qarzdor topilmadi" />}
          </>
        ) : (
          <>
            <div className="debt-list-table">
              <Table
                headers={[
                  'Qarzdor / filial',
                  'Aloqa ma’lumotlari',
                  'Qarz qoldig‘i',
                  'Muddat / holat',
                  'Amallar',
                ]}
              >
                {data.debts.items.map((d) => (
                  <DebtRow
                    key={`${d.origin || 'sale'}:${d.id}`}
                    debt={d}
                    branches={branches}
                    canManage={canManage}
                    setModal={setModal}
                    scope={`${user.id}:${branch}:${status}:${offset}`}
                  />
                ))}
              </Table>
            </div>
            {!data.debts.items.length && <Empty title="Bu ko‘rinishda qarz yo‘q" />}
            <Pager offset={offset} setOffset={setOffset} count={data.debts.items.length} pageSize={20} total={data.debts.count} pageToken={data.debts} />
          </>
        )}
      </section>
      {modal?.type === 'person' && (
        <PersonForm
          person={modal.value}
          branch={branch}
          branches={branches}
          notify={notify}
          reload={reload}
          onClose={() => setModal(null)}
        />
      )}
      {modal?.type === 'pay' && (
        <PayForm
          debt={modal.value}
          user={user}
          notify={notify}
          reload={reload}
          onClose={() => setModal(null)}
        />
      )}
      {modal?.type === 'revise' && (
        <ReviseForm
          debt={modal.value}
          people={data.people}
          editDetails={modal.editDetails}
          user={user}
          notify={notify}
          reload={reload}
          onClose={() => setModal(null)}
        />
      )}
      {modal?.type === 'history' && (
        <DebtHistory
          debt={modal.value}
          canManage={canManage}
          onClose={() => setModal(null)}
          onCancel={(payment) =>
            setModal({ type: 'cancel', value: paymentAudit(modal.value, payment) })
          }
        />
      )}
      {modal?.type === 'opening' && (
        <OpeningDebtForm
          branch={branch}
          branches={branches}
          people={data.people}
          user={user}
          notify={notify}
          reload={reload}
          onClose={() => setModal(null)}
        />
      )}
      {modal?.type === 'cancel' && (
        <OperationCancelModal
          audit={modal.value}
          branchName={branches.find((item) => item.id === modal.value.branch_id)?.name || '—'}
          user={user}
          notify={notify}
          onClose={() => setModal(null)}
          onSaved={() => {
            setModal(null);
            window.dispatchEvent(new Event('crm-debts-changed'));
            reload();
          }}
        >
          <p className="notice">
            {modal.value.debtor.first_name} {modal.value.debtor.last_name} ·{' '}
            <Amount value={modal.value.amount} />
            {['opening_debt_payment', 'debt_installment', 'debt_payment'].includes(
              modal.value.operation.kind,
            )
              ? '. To‘lov bekor qilinsa, shu summa kassadan ayriladi va qolgan qarzga qo‘shiladi.'
              : '. Bu oldingi qarz bekor qilinadi; kassa va ombor o‘zgarmaydi.'}
          </p>
        </OperationCancelModal>
      )}
    </>
  );
}
