import React, { useRef, useState } from 'react';
import { Field, Modal, dateFmt } from './components';
import { requestId } from './id';
import { readPending, recoverablePost } from './recovery';
import './operation-cancel.css';

export function OperationCancelModal({
  audit,
  branchName,
  user,
  notify,
  onClose,
  onSaved,
  children,
}) {
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const operationRequest = useRef(null);
  if (!operationRequest.current) operationRequest.current = requestId();
  const hasCurrentSnapshot = /^[a-f\d]{64}$/i.test(audit.operation.expected_fingerprint || '');
  const isSale = audit.operation.kind === 'sale';
  const isOpeningDebt = audit.operation.kind === 'opening_debt';
  const isOpeningPayment = audit.operation.kind === 'opening_debt_payment';
  const isOtherPayment = audit.operation.kind === 'other_payment';
  const isDebtPayment = ['debt_installment', 'debt_payment'].includes(audit.operation.kind);
  const cancellationPath = isOpeningDebt
    ? `/opening-debts/${audit.operation.id}/cancel`
    : isOpeningPayment
      ? `/opening-debts/payments/${audit.operation.id}/cancel`
      : audit.operation.kind === 'debt_installment'
        ? `/debt-installments/${audit.operation.id}/cancel`
        : `/operations/${audit.operation.kind}/${audit.operation.id}/cancel`;

  async function submit(event) {
    event.preventDefault();
    const cleanReason = reason.trim();
    if (busy || !confirmed || !hasCurrentSnapshot || cleanReason.length < 3) return;
    setBusy(true);
    setError('');
    try {
      await recoverablePost(
        user.id,
        cancellationPath,
        {
          request_id: operationRequest.current,
          reason: cleanReason,
          expected_fingerprint: audit.operation.expected_fingerprint,
        },
        `Amalni bekor qilish: ${audit.action} #${audit.operation.id} (${dateFmt(audit.created_at)})`,
      );
      notify('Amal bekor qilindi. Hisoblar yangilandi, bekor qilish sababi tarixga saqlandi.');
      onSaved();
    } catch (failure) {
      setError(failure.message);
      notify(failure.message, true);
      // Noma'lum javobdagi so'rov recovery'da o'z IDsi bilan qoladi.
      // Global «Natijani tekshirish» oynasi shu saqlangan so'rovni qayta yuboradi.
      try {
        if (readPending(user.id)) onClose();
      } catch {
        // Xotira xatosida formani saqlaymiz va yangi so'rov yaratmaymiz.
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={
        isOpeningDebt
          ? 'Oldingi qarzni bekor qilish'
          : isOpeningPayment || isDebtPayment
            ? 'Qarz to‘lovini bekor qilish'
            : isSale
              ? 'Savdoni o‘chirish'
              : isOtherPayment
                ? 'Boshqa pul topshirig‘ini bekor qilish'
                : 'Amalni bekor qilish'
      }
      onClose={onClose}
      busy={busy}
    >
      <p className="modal-description">Quyidagi amalni tekshiring va bekor qilishni tasdiqlang.</p>
      <dl className="details">
        <div>
          <dt>Amal</dt>
          <dd>
            {audit.action} · #{audit.operation.id}
          </dd>
        </div>
        <div>
          <dt>Sana va vaqt</dt>
          <dd>{dateFmt(audit.created_at)}</dd>
        </div>
        <div>
          <dt>Filial</dt>
          <dd>{branchName}</dd>
        </div>
        <div>
          <dt>Bajargan xodim</dt>
          <dd>{audit.actor}</dd>
        </div>
      </dl>
      {children}
      {!hasCurrentSnapshot && (
        <p className="error" role="alert">
          Amalning joriy holati olinmagan. Oynani yoping va tarixni yangilab, qayta tekshiring.
        </p>
      )}
      <p className="notice">
        {isOpeningDebt
          ? 'Kiritilgan oldingi qarz mijozning qarz hisobidan chiqariladi. Asl yozuv va sabab tarixda saqlanadi.'
          : isOpeningPayment || isDebtPayment
            ? 'Faqat tanlangan to‘lov summasi kassa hisobidan chiqariladi va qolgan qarzga qo‘shiladi. Boshqa to‘lovlar saqlanadi. Asl yozuv va sabab tarixda saqlanadi.'
            : isOtherPayment
              ? 'Topshirilgan summa tegishli naqd yoki karta hisobiga qaytariladi. Asl topshiriq va bekor qilish sababi tarixda saqlanadi.'
              : 'Bu amalning pul, qarz va ombor hisobiga ta’siri qaytariladi, tegishli qoldiqlar qayta hisoblanadi. Asl yozuv va bekor qilish sababi tarixda saqlanadi.'}
      </p>
      {isSale && (
        <p className="notice">
          №{audit.operation.id} savdo barcha mahsulotlari, mini chegirmasi, qarzi va shu qarz uchun
          olingan to‘lovlari bilan bekor qilinadi.
        </p>
      )}
      <form onSubmit={submit}>
        <Field label="Bekor qilish sababi" hint="Kamida 3 belgi yozing.">
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            minLength={3}
            maxLength={500}
            rows={3}
            required
            disabled={busy}
            placeholder="Qaysi ma’lumot xato kiritilgan?"
          />
        </Field>
        <label className="operation-cancel-confirm">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            disabled={busy}
            required
          />
          <span>
            {isSale
              ? 'Tanlangan savdoni o‘chirishni tasdiqlayman.'
              : 'Tanlangan amalni bekor qilishni tasdiqlayman.'}
          </span>
        </label>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <div className="form-footer">
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>
            Orqaga
          </button>
          <button
            className={isSale ? 'primary sale-delete-confirm' : 'primary'}
            disabled={busy || !confirmed || !hasCurrentSnapshot || reason.trim().length < 3}
          >
            {busy ? 'Bekor qilinmoqda…' : isSale ? 'Savdoni o‘chirish' : 'Amalni bekor qilish'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
