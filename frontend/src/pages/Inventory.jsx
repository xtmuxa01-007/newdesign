// Katalog, bir martalik rasm, yangi yuk va chegirma boshqaruvi.
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
  Pencil,
  Scale,
  ChartColumnIncreasing,
} from 'lucide-react';
import { ProductAnalysisModal } from '../ProductAnalysisModal';
import { InventoryStatusFilter } from '../InventoryStatusFilter';
import { api, post, query } from '../api';
import { requestId } from '../id';
import { recoverablePost } from '../recovery';
import { fmt, kgFmt, lineCents, decimal, scaled } from '../money';
import { zeroAsEmpty } from '../money-input';
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

export function Inventory({ branch, branches, notify, user }) {
  const [analysisProduct, setAnalysisProduct] = useState(null);
  const [data, reload, error] = useData(
    async () => {
      if (!branch) return { products: [], suppliers: [], receipts: [], adjustments: [] };
      const [products, suppliers, receipts, adjustments] = await Promise.all([
        api('/products' + query({ branch_id: branch, include_archived: true })),
        api('/suppliers' + query({ branch_id: branch })),
        api('/receipts' + query({ branch_id: branch })),
        api('/stock-adjustments' + query({ branch_id: branch })),
      ]);
      return { products, suppliers, receipts, adjustments };
    },
    [branch],
    notify,
  );
  const [search, setSearch] = useState(''),
    [filter, setFilter] = useState('all'),
    [modal, setModal] = useState(null),
    [busy, setBusy] = useState(false),
    [tab, setTab] = useState('stock'),
    [newProduct, setNewProduct] = useState(null);
  const close = () => {
    setModal(null);
    setNewProduct(null);
  };
  const receiptRequest = useRef(null);
  useEffect(() => {
    receiptRequest.current = requestId();
  }, [modal]);
  async function submit(e) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    if (modal.type === 'receipt') {
      try {
        const kg = scaled(form.get('kg'), 3);
        if (kg <= 0n || kg > 200000n)
          return notify(
            'Bir kirimda 0 dan katta va ko‘pi bilan 200 kg kiriting. Katta yukni bir nechta kirimga ajrating.',
            true,
          );
      } catch {
        return notify('Kirim kilogrammini tekshiring. Eng ko‘pi 200 kg.', true);
      }
    }
    setBusy(true);
    try {
      if (modal.type === 'product') {
        let p = newProduct;
        if (!p) {
          p = await post('/products', {
            name: form.get('name'),
            sku: form.get('sku'),
            supplier_id: Number(form.get('supplier_id')),
          });
          setNewProduct(p);
        }
        const image = form.get('image');
        if (image?.size) {
          const f = new FormData();
          f.append('file', image);
          await api(`/products/${p.id}/image`, { method: 'POST', body: f });
        }
        notify('Mahsulot yaratildi. Endi «Yangi kirim» orqali kilogramm va narxni kiriting.');
      } else if (modal.type === 'receipt') {
        await recoverablePost(
          user.id,
          '/receipts',
          {
            request_id: receiptRequest.current,
            branch_id: Number(branch),
            product_id: Number(form.get('product_id')),
            kg: form.get('kg'),
            price: form.get('price'),
            note: form.get('note'),
          },
          'Omborga kirim',
        );
        notify('Yangi yuk omborga qo‘shildi.');
      } else if (modal.type === 'discount') {
        await post(
          `/stocks/${modal.product.stock_id}/discount`,
          { discount: form.get('discount') },
          'PATCH',
        );
        notify('Chegirma yangilandi.');
      } else if (modal.type === 'sku') {
        await post(
          `/products/${modal.product.id}/sku`,
          {
            expected_sku: modal.product.sku,
            sku: form.get('sku'),
          },
          'PATCH',
        );
        notify('SKU barcha filiallarda yangilandi.');
      } else if (modal.type === 'quantity') {
        await recoverablePost(
          user.id,
          `/stocks/${modal.product.stock_id}/adjustments`,
          {
            request_id: receiptRequest.current,
            expected_kg: modal.product.kg,
            kg: form.get('kg'),
            reason: form.get('reason'),
          },
          'Ombor qoldig‘ini tuzatish',
        );
        notify('Qoldiq tuzatildi. Oldingi va yangi miqdor tarixga saqlandi.');
      } else if (modal.type === 'image') {
        const f = new FormData();
        f.append('file', form.get('image'));
        await api(`/products/${modal.product.id}/image`, { method: 'POST', body: f });
        notify('Rasm qo‘shildi.');
      } else if (['archive', 'restore'].includes(modal.type)) {
        await post(`/products/${modal.product.id}/${modal.type}`, {
          confirmation: form.get('confirmation'),
        });
        notify(
          modal.type === 'archive'
            ? 'Mahsulot arxivlandi. Tarixi va qoldig‘i saqlandi.'
            : 'Mahsulot qayta tiklandi.',
        );
      }
      close();
      await reload();
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  if (!data) return <DataState error={error} reload={reload} />;
  const products = data.products.filter(
    (p) =>
      (p.name + ' ' + p.sku + ' ' + p.supplier).toLowerCase().includes(search.toLowerCase()) &&
      (filter === 'archived'
        ? p.archived
        : !p.archived && (filter === 'all' || (filter === 'active' ? p.active : !p.active))),
  );
  const kg = data.products.reduce((n, p) => n + Number(p.kg), 0),
    value = data.products.reduce((n, p) => n + lineCents(p.kg, p.price, p.discount), 0n);
  return (
    <>
      <PageActions>
        <button className="secondary" onClick={() => setModal({ type: 'product' })}>
          <Plus size={18} />
          Yangi mahsulot
        </button>
        <button
          className="primary"
          disabled={!branch}
          onClick={() => setModal({ type: 'receipt' })}
        >
          <PackagePlus size={18} />
          Yangi kirim
        </button>
      </PageActions>
      <div className="summary-strip">
        <div>
          <span>Mahsulot turlari · arxivsiz</span>
          <strong>{data.products.filter((p) => !p.archived).length}</strong>
        </div>
        <div>
          <span>Ombordagi qoldiq · arxiv bilan</span>
          <strong>
            {kgFmt(kg)} <small>kg</small>
          </strong>
        </div>
        <div>
          <span>Joriy sotuv qiymati</span>
          <strong>
            <Amount value={decimal(value)} />
          </strong>
        </div>
        <div>
          <span>Tugagan mahsulotlar</span>
          <strong>{data.products.filter((p) => !p.archived && !p.active).length}</strong>
        </div>
      </div>
      <section className="panel">
        <div className="list-toolbar">
          <div className="tabs">
            <button className={tab === 'stock' ? 'selected' : ''} onClick={() => setTab('stock')}>
              Mahsulotlar
            </button>
            <button
              className={tab === 'receipts' ? 'selected' : ''}
              onClick={() => setTab('receipts')}
            >
              So‘nggi kirimlar
            </button>
            <button
              className={tab === 'adjustments' ? 'selected' : ''}
              onClick={() => setTab('adjustments')}
            >
              Qoldiq tuzatishlari
            </button>
          </div>
          <button className="icon-btn" onClick={reload} aria-label="Yangilash">
            <RefreshCw size={17} />
          </button>
        </div>
        {tab === 'stock' ? (
          <>
            <div className="filter-row">
              <label className="search">
                <Search size={18} />
                <input
                  placeholder="Nom, SKU yoki ta’minotchi…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
              <InventoryStatusFilter value={filter} onChange={setFilter} />
            </div>
            {products.length ? (
              <Table
                headers={[
                  'Mahsulot',
                  'Ta’minotchi',
                  'Narx / kg',
                  'Qoldiq',
                  'Chegirma',
                  'Holat',
                  'Amallar',
                ]}
              >
                {products.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <div className="product-cell">
                        <ProductImage product={p} small />
                        <div>
                          <strong>{p.name}</strong>
                          <small>{p.sku}</small>
                        </div>
                      </div>
                    </td>
                    <td>{p.supplier}</td>
                    <td>
                      <Amount value={p.price} />
                    </td>
                    <td className="number">{kgFmt(p.kg)} kg</td>
                    <td>{fmt(p.discount)}%</td>
                    <td>
                      <Badge tone={p.active ? 'green' : 'gray'}>
                        {p.archived ? 'Arxiv' : p.active ? 'Faol' : 'Tugagan'}
                      </Badge>
                    </td>
                    <td>
                      <div className="row-actions">
                        <button
                          type="button"
                          className="secondary product-analysis-open"
                          aria-label={`${p.name}: mahsulot tahlili`}
                          onClick={() => setAnalysisProduct(p)}
                        >
                          <ChartColumnIncreasing size={17} />
                          Tahlil
                        </button>
                        {!p.archived && (
                          <>
                            {user.can_edit_inventory && (
                              <>
                                <button
                                  className="icon-btn"
                                  title="SKU tahriri"
                                  aria-label={`${p.name}: SKU tahriri`}
                                  onClick={() => setModal({ type: 'sku', product: p })}
                                >
                                  <Pencil size={17} />
                                </button>
                                <button
                                  className="icon-btn"
                                  title={
                                    p.stock_id ? 'Qoldiqni tuzatish' : 'Avval yangi kirim qo‘shing'
                                  }
                                  aria-label={`${p.name}: qoldiqni tuzatish`}
                                  disabled={!p.stock_id}
                                  onClick={() =>
                                    setModal({
                                      type: 'quantity',
                                      product: p,
                                      branchName: branches.find((b) => b.id === Number(branch))
                                        ?.name,
                                    })
                                  }
                                >
                                  <Scale size={17} />
                                </button>
                              </>
                            )}
                            <button
                              className="icon-btn"
                              title="Kirim qo‘shish"
                              aria-label={`${p.name}: kirim qo‘shish`}
                              onClick={() => setModal({ type: 'receipt', product: p })}
                            >
                              <PackagePlus size={18} />
                            </button>
                            <button
                              className="icon-btn"
                              title="Chegirma"
                              aria-label={`${p.name}: chegirma`}
                              disabled={!p.stock_id}
                              onClick={() => setModal({ type: 'discount', product: p })}
                            >
                              <Percent size={17} />
                            </button>
                            {!p.image && (
                              <button
                                className="icon-btn"
                                title="Rasm qo‘shish"
                                aria-label={`${p.name}: rasm qo‘shish`}
                                onClick={() => setModal({ type: 'image', product: p })}
                              >
                                <ImagePlus size={17} />
                              </button>
                            )}
                          </>
                        )}
                        {user.can_archive_products && (
                          <button
                            className="secondary branch-action"
                            aria-label={`${p.name}: ${p.archived ? 'qayta tiklash' : 'o‘chirish'}`}
                            onClick={() =>
                              setModal({ type: p.archived ? 'restore' : 'archive', product: p })
                            }
                          >
                            {p.archived ? <RotateCcw size={16} /> : <Archive size={16} />}
                            {p.archived ? 'Tiklash' : 'O‘chirish'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </Table>
            ) : (
              <Empty
                title={
                  filter === 'archived' ? 'Arxivlangan mahsulotlar yo‘q' : 'Mahsulotlar topilmadi'
                }
                text="Qidiruv va holat filtrini tekshiring yoki yangi mahsulot qo‘shing."
              />
            )}
          </>
        ) : tab === 'adjustments' ? (
          data.adjustments.length ? (
            <>
              <p className="notice">So‘nggi 100 ta tuzatish. Farq ombordagi miqdorga tegishli.</p>
              <Table
                headers={['Mahsulot', 'Oldingi qoldiq', 'Yangi qoldiq', 'Farq', 'Kim / qachon']}
              >
                {data.adjustments.map((a) => (
                  <React.Fragment key={a.id}>
                    <tr>
                      <td>
                        <strong>{a.product_name}</strong>
                        <small>#{a.id}</small>
                      </td>
                      <td>{kgFmt(a.before_kg)} kg</td>
                      <td>{kgFmt(a.kg)} kg</td>
                      <td>
                        {Number(a.difference) > 0 ? '+' : ''}
                        {kgFmt(a.difference)} kg
                      </td>

                      <td>
                        {a.actor}
                        <small>{dateFmt(a.created_at)}</small>
                      </td>
                    </tr>
                    <tr className="table-note-row">
                      <td colSpan={5}>
                        <strong>Sabab:</strong> {a.reason || '—'}
                      </td>
                    </tr>
                  </React.Fragment>
                ))}
              </Table>
            </>
          ) : (
            <Empty title="Qoldiq tuzatishlari yo‘q" />
          )
        ) : data.receipts.length ? (
          <Table headers={['Mahsulot', 'Kilogramm', 'Kirim narxi / kg', 'Sana']}>
            {data.receipts.map((r) => (
              <React.Fragment key={r.id}>
                <tr>
                  <td>
                    <strong>{r.product_name}</strong>
                    <small>#{r.id}</small>
                  </td>
                  <td>{kgFmt(r.kg)} kg</td>
                  <td>
                    <Amount value={r.price} />
                  </td>
                  <td>{dateFmt(r.created_at)}</td>
                </tr>
                <tr className="table-note-row">
                  <td colSpan={4}>
                    <strong>Izoh:</strong> {r.note || '—'}
                  </td>
                </tr>
              </React.Fragment>
            ))}
          </Table>
        ) : (
          <Empty title="Kirimlar yo‘q" />
        )}
      </section>
      {analysisProduct && (
        <ProductAnalysisModal
          key={`${branch}:${analysisProduct.id}`}
          productId={analysisProduct.id}
          branch={branch}
          branchName={branches.find((item) => String(item.id) === String(branch))?.name}
          user={user}
          notify={notify}
          onClose={() => setAnalysisProduct(null)}
          onSaved={reload}
        />
      )}
      {modal && (
        <Modal
          title={
            {
              product: 'Yangi mahsulot',
              receipt: 'Omborga yangi kirim',
              discount: 'Mahsulot chegirmasi',
              image: 'Mahsulot rasmi',
              archive: 'Mahsulotni o‘chirish — arxivlash',
              restore: 'Mahsulotni qayta tiklash',
              sku: 'SKU kodini tahrirlash',
              quantity: 'Ombor qoldig‘ini tuzatish',
            }[modal.type]
          }
          onClose={close}
          busy={busy}
        >
          <form onSubmit={submit}>
            {modal.type === 'sku' && (
              <>
                <p>
                  <strong>{modal.product.name}</strong> · {modal.product.sku}
                </p>
                <Field label="Yangi SKU kodi">
                  <input
                    name="sku"
                    defaultValue={modal.product.sku}
                    maxLength={60}
                    required
                    disabled={busy}
                  />
                </Field>
                <p className="notice">
                  Kod barcha filiallarda yangilanadi. Oldingi savdolarda sotilgan paytdagi SKU
                  saqlanadi.
                </p>
              </>
            )}
            {modal.type === 'quantity' && (
              <>
                <p>
                  <strong>{modal.product.name}</strong> · {modal.product.sku}
                </p>
                <p>
                  Filial: <strong>{modal.branchName}</strong>
                  <br />
                  Hozirgi qoldiq: <strong>{kgFmt(modal.product.kg)} kg</strong>
                </p>
                <Field label="Ombordagi haqiqiy jami qoldiq (kg)">
                  <input
                    name="kg"
                    type="number"
                    min="0"
                    max="99999999999.999"
                    step="0.001"
                    defaultValue={modal.product.kg}
                    required
                    disabled={busy}
                  />
                </Field>
                <Field label="Tuzatish sababi">
                  <textarea
                    name="reason"
                    minLength={3}
                    maxLength={500}
                    required
                    disabled={busy}
                    placeholder="Masalan: sanash natijasida aniqlangan farq"
                  />
                </Field>
                <p className="notice">
                  Shu filialdagi jami qoldiqni kiriting. Narx, eski kirim va savdolar saqlanadi.
                  Tuzatish sabab va vaqt bilan tarixga yoziladi.
                </p>
              </>
            )}
            {['archive', 'restore'].includes(modal.type) && (
              <>
                <p>
                  <strong>
                    {modal.product.name} · {modal.product.sku}
                  </strong>
                </p>
                <p>
                  {modal.type === 'archive'
                    ? 'Mahsulot barcha filiallarda sotuv va yangi kirim ro‘yxatidan olinadi. Qoldiq, eski savdo, qarz va ombor tarixi saqlanadi. Arxivdan keyin tiklash mumkin.'
                    : 'Mahsulot barcha filiallarda yana sotuv va yangi kirim uchun ochiladi. Saqlangan qoldiq bilan ishlash davom etadi.'}
                </p>
                <Field label={`Tasdiqlash uchun SKU kodini yozing: ${modal.product.sku}`}>
                  <input
                    name="confirmation"
                    required
                    maxLength={60}
                    autoComplete="off"
                    disabled={busy}
                  />
                </Field>
              </>
            )}
            {modal.type === 'product' && (
              <>
                {newProduct && (
                  <div className="notice">
                    Mahsulot yaratildi. Rasmni qayta tanlab yuklashingiz mumkin.
                  </div>
                )}
                <Field label="Mahsulot nomi">
                  <input
                    name="name"
                    required
                    maxLength={120}
                    placeholder="Masalan: Paxtali sochiq"
                    disabled={!!newProduct}
                  />
                </Field>
                <div className="form-grid">
                  <Field label="SKU">
                    <input
                      name="sku"
                      required
                      maxLength={60}
                      placeholder="SCH-001"
                      disabled={!!newProduct}
                    />
                  </Field>
                  <Field label="Ta’minotchi">
                    <select name="supplier_id" required defaultValue="" disabled={!!newProduct}>
                      <option value="" disabled>
                        Tanlang
                      </option>
                      {data.suppliers.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                {!data.suppliers.length && (
                  <p className="notice">Avval «Ta’minotchilar» bo‘limida ta’minotchi yarating.</p>
                )}
              </>
            )}
            {['product', 'image'].includes(modal.type) && (
              <Field
                label="Mahsulot rasmi"
                hint="JPG, PNG yoki WebP · ko‘pi bilan 5 MB. Bir marta yuklanadi."
              >
                <input
                  name="image"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  required={modal.type === 'image'}
                />
              </Field>
            )}
            {modal.type === 'receipt' && (
              <>
                <Field label="Mahsulot">
                  <select name="product_id" defaultValue={modal.product?.id || ''} required>
                    <option value="" disabled>
                      Mahsulotni tanlang
                    </option>
                    {data.products
                      .filter((p) => !p.archived)
                      .map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} · {p.sku}
                        </option>
                      ))}
                  </select>
                </Field>
                <div className="form-grid">
                  <Field
                    label="Kelgan kilogramm"
                    hint="Bir kirimda eng ko‘pi 200 kg. Katta yukni bir nechta kirimga ajrating."
                  >
                    <input
                      name="kg"
                      type="number"
                      min="0.001"
                      max="200"
                      step="0.001"
                      required
                      placeholder="0.000"
                    />
                  </Field>
                  <Field label="Narx — 1 kg uchun (so‘m)">
                    <MoneyInput
                      name="price"
                      min="0.01"
                      defaultValue={zeroAsEmpty(modal.product?.price)}
                      required
                    />
                  </Field>
                </div>
                <p className="notice">
                  Kiritilgan narx shu filialdagi mahsulotning barcha qolgan kilogrammiga ham
                  qo‘llanadi. Qoldiq tugagan bo‘lsa, oldingi chegirma bekor bo‘ladi.
                </p>
                <Field label="Izoh">
                  <textarea
                    name="note"
                    maxLength={500}
                    placeholder="Yuk haqidagi qo‘shimcha ma’lumot"
                  />
                </Field>
              </>
            )}
            {modal.type === 'discount' && (
              <>
                <p className="modal-description">
                  {modal.product.name} · {fmt(modal.product.price)} so‘m/kg
                </p>
                <Field label="Chegirma foizi">
                  <input
                    name="discount"
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    defaultValue={modal.product.discount}
                    required
                  />
                </Field>
                <p className="notice">
                  Chegirma ta’minotchiga yoziladigan haqni ham kamaytiradi. Bekor qilish uchun 0
                  kiriting.
                </p>
              </>
            )}
            <FormFooter
              busy={busy}
              onClose={close}
              label={
                modal.type === 'archive'
                  ? 'Arxivlash'
                  : modal.type === 'restore'
                    ? 'Mahsulotni tiklash'
                    : 'Saqlash'
              }
            />
          </form>
        </Modal>
      )}
    </>
  );
}
