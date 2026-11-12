// Tuzatish sababi va avvalgi versiya serverda tekshiriladi; noaniq javob ayni ID bilan qaytariladi.
import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Package, RotateCcw, Undo2, Wallet } from 'lucide-react';
import { api, query } from './api';
import { readPending, recoverablePost } from './recovery';
import { requestId } from './id';
import { Modal, Field, Loading, Amount, dateFmt, MoneyInput } from './components';
import { lineCents, decimal, safeCents } from './money';
import { zeroAsEmpty } from './money-input';
import './sale-edit.css';

const editableItem = (item) => ({
  item_id: item.id,
  product_id: item.product_id,
  kg: item.kg,
  price: item.price,
  discount: item.discount,
});

export function SaleEditModal({ saleId, user, notify, onClose, onSaved }) {
  const [sale, setSale] = useState(null),
    [products, setProducts] = useState([]);
  const [form, setForm] = useState(null),
    [busy, setBusy] = useState(false),
    [pending, setPending] = useState(null);
  const attempt = useRef(null);
  useEffect(() => {
    let stopped = false;
    (async () => {
      try {
        const s = await api(`/sales/${saleId}/edit`);
        const list = await api(
          '/products' + query({ branch_id: s.branch_id, include_archived: true }),
        );
        if (stopped) return;
        setProducts(list);
        setSale(s);
        setForm({
          version: s.edit_version,
          reason: '',
          customer: s.customer || '',
          cash: zeroAsEmpty(s.cash),
          card: zeroAsEmpty(s.card),
          debt_cash: zeroAsEmpty(s.debt?.payment?.cash),
          debt_card: zeroAsEmpty(s.debt?.payment?.card),
          items: s.items.map(editableItem),
        });
      } catch (e) {
        if (!stopped) {
          notify(e.message, true);
          onClose();
        }
      }
    })();
    return () => {
      stopped = true;
    };
  }, [saleId]);
  const set = (key, value) => setForm((f) => ({ ...f, [key]: value }));
  const line = (index, key, value) =>
    setForm((f) => ({
      ...f,
      items: f.items.map((i, n) => (n === index ? { ...i, [key]: value } : i)),
    }));
  let total = '0';
  let invalidTotal = false;
  try {
    if (form) {
      const cents =
        form.items.reduce((s, i) => s + lineCents(i.kg, i.price, i.discount), 0n) -
        safeCents(sale?.mini_discount?.amount);
      invalidTotal = cents < 0n || (!!sale?.mini_discount && cents === 0n);
      total = decimal(cents);
    }
  } catch {
    invalidTotal = true;
  }
  const paid = safeCents(form?.cash) + safeCents(form?.card);
  const donationTooLarge = paid - safeCents(total) > 1500000n;
  const extraPaid = paid > safeCents(total) ? decimal(paid - safeCents(total)) : '0';
  const removedItems =
    sale?.items.filter((item) => !form?.items.some((line) => line.item_id === item.id)) || [];
  const removeItem = (id) =>
    setForm((current) =>
      current.items.length > 1
        ? { ...current, items: current.items.filter((item) => item.item_id !== id) }
        : current,
    );
  const restoreItem = (item) =>
    setForm((current) => ({
      ...current,
      items: [...current.items, editableItem(item)].sort((a, b) => a.item_id - b.item_id),
    }));
  const singlePaymentMethod =
    safeCents(form?.cash) > 0n && safeCents(form?.card) === 0n
      ? 'cash'
      : safeCents(form?.card) > 0n && safeCents(form?.cash) === 0n
        ? 'card'
        : null;
  async function save(event) {
    event.preventDefault();
    if (busy) return;
    if (!pending && (invalidTotal || !form.items.length))
      return notify('Mahsulot miqdori, narxi va mini chegirmani tekshiring.', true);
    if (!pending && donationTooLarge)
      return notify(
        'Bir savdodagi ehson 15 000 so‘mdan oshmasin. Naqd va karta summalarini tekshiring.',
        true,
      );
    const payload = pending || {
      ...form,
      cash: form.cash || '0',
      card: form.card || '0',
      debt_cash: form.debt_cash || '0',
      debt_card: form.debt_card || '0',
      request_id: attempt.current || requestId(),
    };
    attempt.current = payload.request_id;
    setBusy(true);
    setPending(payload);
    try {
      await recoverablePost(user.id, `/sales/${saleId}/edit`, payload, `Savdo #${saleId} tahriri`);
      notify('Savdo tuzatildi. Ombor va hisoblar yangilandi.');
      onSaved();
    } catch (e) {
      notify(e.message, true);
      try {
        if (readPending(user.id)) {
          onClose();
          return;
        }
      } catch {
        // Preserve the current attempt if browser storage cannot be read.
      }
      if (e.status && e.status < 500 && e.code !== 'desktop_paused') {
        setPending(null);
        attempt.current = null;
      }
    } finally {
      setBusy(false);
    }
  }
  const expired = sale && Date.now() >= new Date(sale.editable_until).getTime();
  const archived =
    sale && sale.items.some((i) => products.some((p) => p.id === i.product_id && p.archived));
  const installmentPayment = !!sale?.debt?.has_active_installments;
  return (
    <Modal
      title={`Savdo #${saleId} ni tahrirlash`}
      className="sale-edit-modal"
      onClose={onClose}
      busy={busy}
    >
      {!form ? (
        <Loading />
      ) : (
        <form onSubmit={save}>
          <div className="sale-edit-intro">
            <span className="sale-edit-intro-icon">
              <Undo2 size={21} />
            </span>
            <div>
              <strong>Mahsulotni qaytarish yoki savdoni tuzatish</strong>
              <p>
                Qaytgan mahsulotni «Qaytarish» bilan olib tashlang. Qisman qaytsa, kilogrammini
                kamaytiring.
              </p>
              <small>
                Tahrirlash muddati: {dateFmt(sale.editable_until)} · Oldingi holat tarixda
                saqlanadi.
              </small>
            </div>
          </div>
          {archived && (
            <p role="alert">
              Savdoda arxivlangan mahsulot bor. Tahrirlash uchun avval Programmist uni omborda qayta
              tiklasin.
            </p>
          )}
          {installmentPayment && (
            <p className="notice" role="alert">
              Bu savdo qarziga qisman to‘lovlar qabul qilingan. Savdoni tuzatishdan oldin «Qarzlar»
              bo‘limida shu to‘lovlarni sabab bilan bekor qiling.
            </p>
          )}
          {pending && (
            <p role="status">
              Javob noaniq bo‘lsa, ayni tuzatishni qayta yuboring. Ikki marta hisoblanmaydi.
            </p>
          )}
          <fieldset
            disabled={busy || !!pending || expired || archived || installmentPayment}
            style={{ border: 0, padding: 0, margin: 0 }}
          >
            <Field label="Mijoz">
              <input
                value={form.customer}
                maxLength={120}
                onChange={(e) => set('customer', e.target.value)}
              />
            </Field>
            <div className="sale-edit-section-heading">
              <h3>
                <Package size={18} /> Savdodagi mahsulotlar
              </h3>
              <span>{form.items.length} ta</span>
            </div>
            {form.items.map((item, index) => (
              <section className="sale-edit-item" key={item.item_id}>
                <div className="sale-edit-item-heading">
                  <strong>Mahsulot {index + 1}</strong>
                  <button
                    type="button"
                    className="sale-return-button"
                    onClick={() => removeItem(item.item_id)}
                    disabled={form.items.length === 1}
                    title={
                      form.items.length === 1
                        ? 'Oxirgi mahsulotni qaytarish uchun savdoni to‘liq bekor qiling.'
                        : 'Bu mahsulotni savdodan olib tashlash'
                    }
                    aria-label={`${products.find((p) => p.id === item.product_id)?.name || `Mahsulot ${index + 1}`}ni qaytarish`}
                  >
                    <Undo2 size={16} /> Qaytarish
                  </button>
                </div>
                <Field label={`Mahsulot ${index + 1}`}>
                  <select
                    value={item.product_id}
                    onChange={(e) => line(index, 'product_id', Number(e.target.value))}
                  >
                    {products
                      .filter((p) => !p.archived || p.id === item.product_id)
                      .map((p) => (
                        <option key={p.id} value={p.id} disabled={p.archived}>
                          {p.name} · {p.sku}
                          {p.archived ? ' · Arxiv' : ''}
                        </option>
                      ))}
                  </select>
                </Field>
                <div className="sale-edit-item-fields">
                  <Field label="Kilogramm">
                    <input
                      type="number"
                      min="0.001"
                      step="0.001"
                      required
                      value={item.kg}
                      onChange={(e) => line(index, 'kg', e.target.value)}
                    />
                  </Field>
                  <Field label="Narx / kg">
                    <MoneyInput
                      min="0.01"
                      required
                      value={item.price}
                      onChange={(value) => line(index, 'price', value)}
                    />
                  </Field>
                  <Field label="Chegirma %">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.01"
                      required
                      value={item.discount}
                      onChange={(e) => line(index, 'discount', e.target.value)}
                    />
                  </Field>
                </div>
              </section>
            ))}
            {form.items.length === 1 && (
              <p className="sale-edit-hint">
                Barcha mahsulot qaytsa, «Savdolar va tarix»dagi «O‘chirish» orqali savdoni to‘liq
                bekor qiling.
              </p>
            )}
            {!!removedItems.length && (
              <section className="sale-edit-returns" aria-live="polite">
                <h3>Qaytariladigan mahsulotlar · {removedItems.length} ta</h3>
                <p>Saqlangach, bu mahsulotlar savdodan olinadi va omborga qaytadi.</p>
                {removedItems.map((item) => (
                  <div key={item.id} className="sale-edit-returned-item">
                    <span>
                      <strong>{item.name}</strong>
                      <small>
                        {item.kg} kg · SKU {item.sku}
                      </small>
                    </span>
                    <button
                      type="button"
                      className="text-btn"
                      onClick={() => restoreItem(item)}
                      aria-label={`${item.name}ni tiklash`}
                    >
                      <RotateCcw size={15} /> Tiklash
                    </button>
                  </div>
                ))}
              </section>
            )}
            <div className="sale-edit-total" aria-live="polite">
              <div>
                <span>Avvalgi jami</span>
                <strong>
                  <Amount value={sale.total} />
                </strong>
              </div>
              <ArrowRight size={20} aria-hidden="true" />
              <div>
                <span>Yangi jami</span>
                <strong>{invalidTotal ? '—' : <Amount value={total} />}</strong>
              </div>
            </div>
            {sale.mini_discount && (
              <p className="sale-edit-hint">
                Avvalgi mini chegirma saqlanadi: <Amount value={sale.mini_discount.amount} />.
              </p>
            )}
            {invalidTotal && (
              <p className="error" role="alert">
                {sale.mini_discount
                  ? 'Miqdor va narxni tekshiring. Qolgan mahsulotlar jami avvalgi mini chegirmadan katta bo‘lishi kerak.'
                  : 'Mahsulot miqdori, narxi va chegirmasini tekshiring.'}
              </p>
            )}
            <div className="sale-edit-section-heading">
              <h3>
                <Wallet size={18} /> To‘lovni tekshiring
              </h3>
            </div>
            {!!removedItems.length && (
              <p className="sale-edit-hint">
                Xaridorga qaytarilgan pulni naqd yoki kartadan kamaytiring. Qolgan to‘lov savdoda
                qolgan mahsulotlarga mos bo‘lsin.
              </p>
            )}
            {!sale.debt && !invalidTotal && singlePaymentMethod && paid !== safeCents(total) && (
              <button
                type="button"
                className="secondary compact sale-edit-match-payment"
                onClick={() => set(singlePaymentMethod, total)}
              >
                <RotateCcw size={15} /> {singlePaymentMethod === 'cash' ? 'Naqdni' : 'Kartani'}{' '}
                yangi jamiga moslash
              </button>
            )}
            <div className="form-grid">
              <Field label={sale.debt ? 'Dastlab olingan naqd' : 'Naqd'}>
                <MoneyInput value={form.cash} onChange={(value) => set('cash', value)} />
              </Field>
              <Field label={sale.debt ? 'Dastlab olingan karta' : 'Karta'}>
                <MoneyInput value={form.card} onChange={(value) => set('card', value)} />
              </Field>
            </div>
            {!sale.debt && !invalidTotal && safeCents(extraPaid) > 0n && (
              <p className="notice">
                Ortiqcha <Amount value={extraPaid} /> ehson hisoblanadi. Pul qaytarilgan bo‘lsa,
                to‘lov summasini kamaytiring.
              </p>
            )}
            {sale.debt?.payment && !installmentPayment && (
              <>
                <p>Bu qarz yopilgan. Qarz uchun olingan to‘lovni ham to‘g‘rilang:</p>
                <div className="form-grid">
                  <Field label="Qarz to‘lovi — naqd">
                    <MoneyInput
                      value={form.debt_cash}
                      onChange={(value) => set('debt_cash', value)}
                    />
                  </Field>
                  <Field label="Qarz to‘lovi — karta">
                    <MoneyInput
                      value={form.debt_card}
                      onChange={(value) => set('debt_card', value)}
                    />
                  </Field>
                </div>
              </>
            )}
            <Field label="Tuzatish sababi">
              <textarea
                required
                minLength={3}
                maxLength={500}
                placeholder="Masalan: xaridor ikkinchi mahsulotni qaytardi"
                value={form.reason}
                onChange={(e) => set('reason', e.target.value)}
              />
            </Field>
          </fieldset>
          {!pending && donationTooLarge && (
            <p className="error" role="alert">
              Bir savdodagi ehson 15 000 so‘mdan oshmasin. Naqd va karta summalarini tekshiring.
            </p>
          )}
          {expired ? (
            <p role="alert">72 soatlik tahrirlash muddati tugagan.</p>
          ) : (
            !archived && (
              <div className="form-footer">
                <button type="button" className="secondary" onClick={onClose} disabled={busy}>
                  Bekor qilish
                </button>
                <button
                  className="primary"
                  disabled={
                    busy || installmentPayment || (!pending && (donationTooLarge || invalidTotal))
                  }
                >
                  {busy
                    ? 'Saqlanmoqda…'
                    : pending
                      ? 'Ayni tuzatishni qayta yuborish'
                      : 'Tuzatishni saqlash'}
                </button>
              </div>
            )
          )}
        </form>
      )}
    </Modal>
  );
}
