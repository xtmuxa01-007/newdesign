import React, { useState } from 'react';
import { Modal, Amount } from './components';
import { retryPending } from './recovery';

export function RecoveryModal({ user, operation, notify, onResolved }) {
  const [busy, setBusy] = useState(false);
  async function retry() {
    setBusy(true);
    try {
      await retryPending(user.id);
      notify('Avvalgi amal tasdiqlandi. Takror yozuv yaratilmadi.');
      onResolved();
    } catch (error) {
      notify(error.message || 'Ulanishni tekshirib, qayta urinib ko‘ring.', true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Yuborilgan amalni tekshirish" busy onClose={() => {}}>
      <p className="modal-description">
        «{operation.label}» so‘rovi yuborilgan, lekin uning javobi olinmagan. Avval shu amalning
        natijasini tekshiramiz.
      </p>
      <dl className="details">
        {operation.payload.recipient && (
          <div>
            <dt>Qabul qiluvchi</dt>
            <dd>{operation.payload.recipient}</dd>
          </div>
        )}
        {operation.payload.amount && (
          <div>
            <dt>Summa</dt>
            <dd>
              <Amount value={operation.payload.amount} />
            </dd>
          </div>
        )}
        {operation.payload.kg && (
          <div>
            <dt>{operation.payload.expected_kg !== undefined ? 'Yangi qoldiq' : 'Kirim'}</dt>
            <dd>{operation.payload.kg} kg</dd>
          </div>
        )}
      </dl>
      <p className="notice">
        Bu tugma aynan avvalgi so‘rovni tekshiradi. Pul yoki kilogramm ikki marta yozilmaydi.
      </p>
      <button className="primary wide" disabled={busy} onClick={retry}>
        {busy ? 'Tekshirilmoqda…' : 'Natijani tekshirish'}
      </button>
    </Modal>
  );
}
