import React, { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowRight, ChartColumnIncreasing, Pencil, RefreshCw, Scale } from 'lucide-react';
import { api, query } from './api';
import {
  Amount,
  Badge,
  Field,
  Loading,
  Modal,
  MoneyInput,
  ProductImage,
  dateFmt,
} from './components';
import { Table } from './pages/shared';
import { decimal, fmt, kgFmt, safeCents } from './money';
import { zeroAsEmpty } from './money-input';
import { tashkentToday } from './debt-management';
import { requestId } from './id';
import { readPending, recoverablePost } from './recovery';
import { productChartBuckets, stockAdjustmentPreview } from './product-analysis';
import './product-analysis.css';

const shortDay = (day) => day.slice(8, 10) + '.' + day.slice(5, 7);

function ProductSalesChart({ daily, complete }) {
  const rows = useMemo(() => productChartBuckets(daily), [daily]);
  const [active, setActive] = useState(null);
  const maximum = rows.reduce((max, row) => {
    const value = safeCents(row.total);
    return value > max ? value : max;
  }, 0n);
  const selected = rows[active] || rows.at(-1);
  return (
    <section className="product-analysis-chart" aria-label="Mahsulot savdosi grafigi">
      <div className="product-section-heading">
        <h3>Savdo qiymati</h3>
        <span>{fmt(decimal(maximum))} so‘mgacha</span>
      </div>
      {maximum > 0n ? (
        <>
          <div className="product-chart-bars">
            {rows.map((row, index) => {
              const height = Number((safeCents(row.total) * 10000n) / maximum) / 100;
              const label =
                row.start === row.end
                  ? shortDay(row.start)
                  : `${shortDay(row.start)}–${shortDay(row.end)}`;
              return (
                <button
                  type="button"
                  key={row.start}
                  className={active === index ? 'selected' : ''}
                  aria-label={`${label}: ${fmt(row.total)} so‘m, ${kgFmt(row.kg)} kg`}
                  title={`${label}: ${fmt(row.total)} so‘m`}
                  onMouseEnter={() => setActive(index)}
                  onMouseLeave={() => setActive(null)}
                  onFocus={() => setActive(index)}
                  onBlur={() => setActive(null)}
                >
                  <span style={{ height: `${height > 0 ? Math.max(height, 2) : 0}%` }} />
                </button>
              );
            })}
          </div>
          <div className="product-chart-dates">
            <span>{shortDay(rows[0].start)}</span>
            <span>{shortDay(rows.at(-1).end)}</span>
          </div>
          <p className="product-chart-caption">
            {selected &&
              `${shortDay(selected.start)}${selected.end !== selected.start ? `–${shortDay(selected.end)}` : ''}: ${fmt(selected.total)} so‘m · ${kgFmt(selected.kg)} kg`}
            {rows.length < daily.length && ' · Kunlar guruhlangan.'}
          </p>
        </>
      ) : (
        <p className="product-analysis-empty">Tanlangan davrda bu mahsulotdan savdo bo‘lmagan.</p>
      )}
      {complete === false && (
        <p className="product-chart-caption">Faqat savdo bo‘lgan kunlar ko‘rsatilgan.</p>
      )}
    </section>
  );
}

export function ProductAnalysisModal({
  productId,
  branch,
  branchName,
  user,
  notify,
  onClose,
  onSaved,
}) {
  const today = tashkentToday();
  const [start, setStart] = useState(today.slice(0, 7) + '-01');
  const [end, setEnd] = useState(today);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [tab, setTab] = useState('analysis');
  const [edit, setEdit] = useState(null);
  const [quantityEdit, setQuantityEdit] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const editRequest = useRef(null);
  const quantityRequest = useRef(null);
  const quantitySaving = useRef(false);
  const manager = ['boss', 'admin'].includes(user?.role);
  const editing = !!edit || !!quantityEdit;
  const quantityPreview = quantityEdit
    ? stockAdjustmentPreview(quantityEdit.expected_kg, quantityEdit.kg)
    : null;
  const disabledEditReasons = data
    ? [
        ...new Set(
          [
            !data.permissions.can_edit_price &&
              (data.permissions.price_edit_reason ||
                'Bu mahsulotning narxini hozir o‘zgartirib bo‘lmaydi.'),
            manager &&
              !data.permissions.can_adjust_stock &&
              data.permissions.adjustment_disabled_reason,
          ].filter(Boolean),
        ),
      ]
    : [];

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setData(null);
    setError('');
    if (!start || !end || start > end) {
      setLoading(false);
      setError('Boshlanish va tugash sanalarini to‘g‘ri tanlang.');
      return () => {
        current = false;
        controller.abort();
      };
    }
    setLoading(true);
    api(`/products/${productId}/analytics` + query({ branch_id: branch, start, end }), {
      signal: controller.signal,
    })
      .then((result) => {
        if (current) setData(result);
      })
      .catch((failure) => {
        if (current && failure.name !== 'AbortError') setError(failure.message);
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [productId, branch, start, end, revision]);

  function beginPriceEdit() {
    if (!manager || !data?.permissions?.can_edit_price || saving || editing) return;
    editRequest.current = requestId();
    setEdit({
      stock_id: data.current_stock.stock_id,
      expected_price: data.current_stock.price,
      price: zeroAsEmpty(data.current_stock.price),
      reason: '',
    });
    setSaveError('');
    setTab('price');
  }

  function beginQuantityEdit() {
    if (!manager || !data?.permissions?.can_adjust_stock || saving || editing) return;
    quantityRequest.current = requestId();
    setQuantityEdit({
      stock_id: data.current_stock.stock_id,
      expected_kg: data.current_stock.kg,
      kg: data.current_stock.kg,
      reason: '',
    });
    setSaveError('');
    setTab('analysis');
  }

  async function saveQuantity(event) {
    event.preventDefault();
    if (
      saving ||
      quantitySaving.current ||
      !quantityEdit ||
      !quantityPreview?.changed ||
      quantityEdit.reason.trim().length < 3
    )
      return;
    quantitySaving.current = true;
    setSaving(true);
    setSaveError('');
    try {
      await recoverablePost(
        user.id,
        `/stocks/${quantityEdit.stock_id}/adjustments`,
        {
          request_id: quantityRequest.current,
          expected_kg: quantityEdit.expected_kg,
          kg: quantityPreview.kg,
          reason: quantityEdit.reason.trim(),
        },
        `${data.product.name}: reviziya bo‘yicha qoldiqni tuzatish`,
      );
      setQuantityEdit(null);
      setRevision((value) => value + 1);
      await onSaved?.();
      notify('Kilogramm qoldig‘i tuzatildi. Boshliqlar uchun bildirishnoma va tarix saqlandi.');
    } catch (failure) {
      setSaveError(failure.message);
      notify(failure.message, true);
      try {
        if (readPending(user.id)) {
          onClose();
          return;
        }
      } catch {
        // Saqlanmagan so‘rov qayta yuborilmaydi; shu oynadagi ID saqlanadi.
      }
      if (failure.status === 409) {
        setQuantityEdit(null);
        setRevision((value) => value + 1);
        await onSaved?.();
      }
    } finally {
      quantitySaving.current = false;
      setSaving(false);
    }
  }

  async function savePrice(event) {
    event.preventDefault();
    if (
      saving ||
      !edit ||
      safeCents(edit.price) <= 0n ||
      safeCents(edit.price) === safeCents(edit.expected_price) ||
      edit.reason.trim().length < 3
    )
      return;
    setSaving(true);
    setSaveError('');
    try {
      await recoverablePost(
        user.id,
        `/stocks/${edit.stock_id}/price`,
        {
          request_id: editRequest.current,
          expected_price: edit.expected_price,
          price: edit.price,
          reason: edit.reason.trim(),
        },
        `${data.product.name}: narxni o‘zgartirish`,
      );
      setEdit(null);
      setRevision((value) => value + 1);
      await onSaved?.();
      notify('Narx yangilandi. Eski savdo va kirim narxlari saqlandi.');
    } catch (failure) {
      setSaveError(failure.message);
      notify(failure.message, true);
      try {
        if (readPending(user.id)) {
          onClose();
          return;
        }
      } catch {
        // Xotira xatosida yangi so‘rov yaratmaymiz; yozilmagan amal yuborilmagan.
      }
      if (failure.status === 409) {
        setEdit(null);
        setRevision((value) => value + 1);
        await onSaved?.();
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={data ? `${data.product.name} — mahsulot tahlili` : 'Mahsulot tahlili'}
      className="product-analysis-modal"
      busy={saving}
      onClose={onClose}
    >
      <div className="product-analysis-tabs" role="group" aria-label="Mahsulot tafsilotlari">
        <button
          type="button"
          aria-pressed={tab === 'analysis'}
          disabled={saving || editing}
          onClick={() => setTab('analysis')}
        >
          <ChartColumnIncreasing size={17} /> Tahlil
        </button>
        <button
          type="button"
          aria-pressed={tab === 'price'}
          disabled={saving || editing}
          onClick={() => setTab('price')}
        >
          <Pencil size={16} /> Narx va tarix
        </button>
      </div>
      {tab === 'analysis' && (
        <div className="product-analysis-filters">
          <Field label="Boshlanish sanasi">
            <input
              type="date"
              value={start}
              onChange={(event) => setStart(event.target.value)}
              disabled={saving || editing}
            />
          </Field>
          <Field label="Tugash sanasi">
            <input
              type="date"
              min={start}
              value={end}
              onChange={(event) => setEnd(event.target.value)}
              disabled={saving || editing}
            />
          </Field>
          <button
            type="button"
            className="secondary"
            disabled={saving || editing || loading}
            onClick={() => setRevision((value) => value + 1)}
            aria-label="Mahsulot tahlilini yangilash"
          >
            <RefreshCw size={17} />
          </button>
        </div>
      )}
      {loading ? (
        <Loading />
      ) : error ? (
        <div className="error" role="alert">
          {error}
        </div>
      ) : (
        data && (
          <>
            <div className="product-analysis-identity">
              <ProductImage product={data.product} small />
              <div>
                <strong>
                  {data.product.sku} · {data.product.supplier}
                </strong>
                <span>{branchName || 'Tanlangan filial'}</span>
              </div>
              {data.product.archived && <Badge tone="gray">Arxivlangan</Badge>}
            </div>
            <section className="product-current-stock">
              <div className="product-section-heading">
                <h3>Hozirgi ombor holati</h3>
                {manager && (
                  <div className="product-current-actions">
                    <button
                      type="button"
                      className="secondary"
                      onClick={beginQuantityEdit}
                      disabled={saving || editing || !data.permissions.can_adjust_stock}
                      title={data.permissions.adjustment_disabled_reason || undefined}
                    >
                      <Scale size={17} /> Kilogramni tuzatish
                    </button>
                    <button
                      type="button"
                      className="primary"
                      onClick={beginPriceEdit}
                      disabled={saving || editing || !data.permissions.can_edit_price}
                    >
                      <Pencil size={16} /> Narxni o‘zgartirish
                    </button>
                  </div>
                )}
              </div>
              <div className="product-current-values">
                <div>
                  <span>Qoldiq</span>
                  <strong>
                    {kgFmt(data.current_stock.kg)} <small>kg</small>
                  </strong>
                </div>
                <div>
                  <span>Belgilangan narx · 1 kg</span>
                  <strong>
                    <Amount value={data.current_stock.price} />
                  </strong>
                  <small>
                    {fmt(data.current_stock.discount)}% chegirma · sotuvda{' '}
                    {fmt(data.current_stock.effective_price)} so‘m/kg
                  </small>
                </div>
                <div>
                  <span>Qoldiq sotuv qiymati</span>
                  <strong>
                    <Amount value={data.current_stock.retail_value} />
                  </strong>
                </div>
              </div>
              <p>Bu ko‘rsatkichlar joriy holatga tegishli, tanlangan sana davriga bog‘liq emas.</p>
              {disabledEditReasons.map((reason) => (
                <p className="notice" key={reason}>
                  {reason}
                </p>
              ))}
              {quantityEdit && (
                <form className="product-quantity-editor" onSubmit={saveQuantity}>
                  <div className="product-quantity-heading">
                    <span className="product-quantity-icon">
                      <Scale size={21} />
                    </span>
                    <div>
                      <h3>Reviziya bo‘yicha qoldiqni tuzatish</h3>
                      <p>Omborda sanalgan haqiqiy kilogramni kiriting.</p>
                    </div>
                  </div>
                  <div className="product-quantity-fields">
                    <Field
                      label="Yangi qoldiq (kg)"
                      hint="0 yoki undan katta son · 0,001 kg aniqlikda."
                    >
                      <input
                        name="adjusted_kg"
                        type="text"
                        inputMode="decimal"
                        pattern="[0-9]+([.,][0-9]{1,3})?"
                        maxLength={18}
                        required
                        autoFocus
                        value={quantityEdit.kg}
                        disabled={saving}
                        onChange={(event) =>
                          setQuantityEdit((old) => ({ ...old, kg: event.target.value }))
                        }
                      />
                    </Field>
                    <div className="product-quantity-preview" aria-live="polite">
                      <div>
                        <span>Oldingi qoldiq</span>
                        <strong>
                          {kgFmt(quantityEdit.expected_kg)} <small>kg</small>
                        </strong>
                      </div>
                      <ArrowRight size={18} aria-hidden="true" />
                      <div>
                        <span>Farq</span>
                        <strong
                          className={
                            quantityPreview?.difference.startsWith('-') ? 'decrease' : 'increase'
                          }
                        >
                          {quantityPreview
                            ? `${!quantityPreview.difference.startsWith('-') && quantityPreview.changed ? '+' : ''}${kgFmt(quantityPreview.difference)}`
                            : '—'}
                          <small> kg</small>
                        </strong>
                      </div>
                    </div>
                  </div>
                  <Field
                    label="Tuzatish sababi"
                    hint="Boshliqlarga yuboriladi va tarixda saqlanadi. Kamida 3 belgi."
                  >
                    <textarea
                      name="adjustment_reason"
                      rows={2}
                      minLength={3}
                      maxLength={500}
                      required
                      value={quantityEdit.reason}
                      disabled={saving}
                      onChange={(event) =>
                        setQuantityEdit((old) => ({ ...old, reason: event.target.value }))
                      }
                      placeholder="Masalan: reviziyada 1,250 kg kam chiqdi"
                    />
                  </Field>
                  <p className="notice">
                    Tuzatish shu filialdagi ombor qoldig‘iga qo‘llanadi. Sababi, oldingi va yangi
                    kilogram boshliqlarga bildirishnomada ko‘rinadi.
                  </p>
                  <div className="form-footer">
                    <button
                      type="button"
                      className="secondary"
                      disabled={saving}
                      onClick={() => setQuantityEdit(null)}
                    >
                      Bekor qilish
                    </button>
                    <button
                      className="primary"
                      disabled={
                        saving || !quantityPreview?.changed || quantityEdit.reason.trim().length < 3
                      }
                    >
                      {saving ? 'Saqlanmoqda…' : 'Qoldiqni saqlash'}
                    </button>
                  </div>
                </form>
              )}
            </section>
            {saveError && (
              <p className="error" role="alert">
                {saveError}
              </p>
            )}
            {tab === 'price' ? (
              <>
                {edit && (
                  <form className="product-price-editor" onSubmit={savePrice}>
                    <h3>Narxni o‘zgartirish</h3>
                    <p className="product-price-before">
                      Oldingi narx: <strong>{fmt(edit.expected_price)} so‘m / kg</strong>
                      <ArrowRight size={17} />
                    </p>
                    <div className="product-price-fields">
                      <Field label="Yangi narx — 1 kg uchun (so‘m)">
                        <MoneyInput
                          value={edit.price}
                          onChange={(value) => setEdit((old) => ({ ...old, price: value }))}
                          min="0.01"
                          max="999999999999.99"
                          required
                          disabled={saving}
                        />
                      </Field>
                      <Field label="O‘zgartirish sababi" hint="Kamida 3 belgi yozing.">
                        <textarea
                          value={edit.reason}
                          onChange={(event) =>
                            setEdit((old) => ({ ...old, reason: event.target.value }))
                          }
                          minLength={3}
                          maxLength={500}
                          required
                          rows={2}
                          disabled={saving}
                          placeholder="Masalan: yangi sotuv narxi belgilandi"
                        />
                      </Field>
                    </div>
                    <p className="notice">
                      Yangi narx shu filialdagi qolgan mahsulotga va keyingi savdolarga qo‘llanadi.
                      Qoldiq, chegirma, oldingi savdo va kirim narxlari saqlanadi.
                    </p>
                    <div className="form-footer">
                      <button
                        type="button"
                        className="secondary"
                        disabled={saving}
                        onClick={() => setEdit(null)}
                      >
                        Bekor qilish
                      </button>
                      <button
                        className="primary"
                        disabled={
                          saving ||
                          safeCents(edit.price) <= 0n ||
                          safeCents(edit.price) === safeCents(edit.expected_price) ||
                          edit.reason.trim().length < 3
                        }
                      >
                        {saving ? 'Saqlanmoqda…' : 'Narxni saqlash'}
                      </button>
                    </div>
                  </form>
                )}
                <section className="product-analysis-section">
                  <h3>Qo‘lda o‘zgartirilgan narxlar tarixi</h3>
                  <p>
                    So‘nggi 20 ta o‘zgarish · barcha sanalar bo‘yicha. Yangi kirim ham joriy narxni
                    yangilashi mumkin.
                  </p>
                  {data.price_history.length ? (
                    <Table headers={['Oldingi narx', 'Yangi narx', 'Sabab', 'Xodim / vaqt']}>
                      {data.price_history.map((entry) => (
                        <tr key={entry.id}>
                          <td>
                            <Amount value={entry.before} />
                          </td>
                          <td>
                            <strong>
                              <Amount value={entry.after} />
                            </strong>
                          </td>
                          <td>{entry.reason}</td>
                          <td>
                            {entry.actor}
                            <small>{dateFmt(entry.created_at)}</small>
                          </td>
                        </tr>
                      ))}
                    </Table>
                  ) : (
                    <p className="product-analysis-empty">Narx hali alohida o‘zgartirilmagan.</p>
                  )}
                </section>
              </>
            ) : (
              <>
                <div className="product-period-stats">
                  <div>
                    <span>Sotilgan</span>
                    <strong>
                      {kgFmt(data.summary.sold_kg)} <small>kg</small>
                    </strong>
                    <small>{data.summary.sales_count} ta savdo</small>
                  </div>
                  <div>
                    <span>Mahsulot savdosi</span>
                    <strong>
                      <Amount value={data.summary.sales_total} />
                    </strong>
                    <small>Chegirmalar hisobga olingan</small>
                  </div>
                  <div>
                    <span>Kirim qilingan</span>
                    <strong>
                      {kgFmt(data.summary.received_kg)} <small>kg</small>
                    </strong>
                    <small>{data.summary.receipt_count} ta kirim</small>
                  </div>
                  <div>
                    <span>O‘rtacha sotuv narxi / kg</span>
                    <strong>
                      <Amount value={data.summary.average_price_per_kg} />
                    </strong>
                    <small>
                      {fmt(data.summary.mini_discount)} so‘m mini chegirma hisobga olingan
                    </small>
                  </div>
                </div>
                <p className="product-analysis-explanation">
                  Tanlangan davr bo‘yicha. Savdo qiymati kassa qoldig‘i yoki foyda emas; ehson va
                  qarz to‘lovlari unga qo‘shilmaydi.
                </p>
                <ProductSalesChart daily={data.daily} complete={data.series?.daily_complete} />
                <div className="product-history-grid">
                  <section className="product-analysis-section">
                    <h3>So‘nggi savdolar</h3>
                    <p>Tanlangan davrdagi so‘nggi 20 ta mahsulot qatori.</p>
                    {data.recent_sales.length ? (
                      <Table headers={['Savdo / sana', 'Kg', 'Narx / kg', 'Jami']}>
                        {data.recent_sales.map((entry, index) => (
                          <tr key={entry.id || `${entry.sale_id}:${index}`}>
                            <td>
                              <strong>#{entry.sale_id}</strong>
                              <small>{dateFmt(entry.created_at)}</small>
                              <small>{entry.cashier}</small>
                            </td>
                            <td>{kgFmt(entry.kg)}</td>
                            <td>
                              <Amount value={entry.price} />
                              <small>{fmt(entry.discount)}% chegirma</small>
                            </td>
                            <td>
                              <Amount value={entry.total} />
                            </td>
                          </tr>
                        ))}
                      </Table>
                    ) : (
                      <p className="product-analysis-empty">Bu davrda savdo yo‘q.</p>
                    )}
                  </section>
                  <section className="product-analysis-section">
                    <h3>So‘nggi kirimlar</h3>
                    <p>Yozuvdagi narx saqlanadi · tanlangan davr.</p>
                    {data.recent_receipts.length ? (
                      <Table headers={['Sana / xodim', 'Kg', 'Kirim narxi / kg']}>
                        {data.recent_receipts.map((entry) => (
                          <tr key={entry.id}>
                            <td>
                              {dateFmt(entry.created_at)}
                              <small>{entry.actor}</small>
                              {entry.note && <small>{entry.note}</small>}
                            </td>
                            <td>{kgFmt(entry.kg)}</td>
                            <td>
                              <Amount value={entry.price} />
                            </td>
                          </tr>
                        ))}
                      </Table>
                    ) : (
                      <p className="product-analysis-empty">Bu davrda kirim yo‘q.</p>
                    )}
                  </section>
                </div>
              </>
            )}
          </>
        )
      )}
    </Modal>
  );
}
