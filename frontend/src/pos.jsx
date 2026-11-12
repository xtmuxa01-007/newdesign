import React, { useEffect, useState, useCallback, useRef } from 'react';
import {
  Search,
  Plus,
  Minus,
  X,
  Pause,
  ShoppingBag,
  Banknote,
  CreditCard,
  ArrowRight,
  Clock3,
  RotateCcw,
  Trash2,
  Image as ImageIcon,
  ImageOff,
} from 'lucide-react';
import { api, post, query } from './api';
import { requestId } from './id';
import { fmt, kgFmt, lineCents, decimal, safeCents, scaled } from './money';
import { Empty, ProductImage, Badge, Modal, Field, FormFooter, MoneyInput } from './components';
import { zeroAsEmpty } from './money-input';

export function POS({ branch, user, notify }) {
  const [hideImages, setHideImages] = useState(() => {
    try {
      return localStorage.getItem('marva-pos-hide-images') === 'true';
    } catch {
      return false;
    }
  });
  const storageKey = `marva-draft:${user.id}:${branch}`;
  const [draft] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(storageKey)) || {};
    } catch {
      return {};
    }
  });
  const [products, setProducts] = useState([]),
    [carts, setCarts] = useState([]),
    [search, setSearch] = useState(''),
    [stockFilter, setStockFilter] = useState('active');
  const [items, setItems] = useState(draft.items || []),
    [customer, setCustomer] = useState(draft.customer || ''),
    [cash, setCash] = useState(zeroAsEmpty(draft.cash)),
    [card, setCard] = useState(zeroAsEmpty(draft.card));
  const [activeCart, setActiveCart] = useState(draft.activeCart || null),
    [pending, setPending] = useState(draft.pending || null);
  const [busy, setBusy] = useState(false),
    [hold, setHold] = useState(false),
    [viewCarts, setViewCarts] = useState(false),
    [loaded, setLoaded] = useState(false);
  const [storageError, setStorageError] = useState(false);
  const [debtors, setDebtors] = useState([]);
  const [credit, setCredit] = useState(draft.credit || false);
  const [debtorId, setDebtorId] = useState(draft.debtorId || '');
  const [dueDate, setDueDate] = useState(draft.dueDate || '');
  const [miniApproval, setMiniApproval] = useState(draft.miniApproval || null);
  const locked = !!pending || busy;
  useEffect(() => {
    try {
      localStorage.setItem('marva-pos-hide-images', String(hideImages));
    } catch {
      // Ko‘rinish sozlamasi saqlanmasa ham POS ishlashda davom etadi.
    }
  }, [hideImages]);
  const load = useCallback(async () => {
    if (!branch) return;
    try {
      const [p, c, d] = await Promise.all([
        api('/products' + query({ branch_id: branch })),
        api('/carts' + query({ branch_id: branch })),
        api('/debtors' + query({ branch_id: branch })),
      ]);
      setProducts(p);
      setCarts(c);
      setDebtors(d);
      setLoaded(true);
    } catch (e) {
      notify(e.message, true);
    }
  }, [branch, notify]);
  useEffect(() => {
    load();
    const timer = setInterval(load, 30000);
    return () => clearInterval(timer);
  }, [load]);
  useEffect(() => {
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          items,
          customer,
          cash,
          card,
          activeCart,
          pending,
          credit,
          debtorId,
          dueDate,
          miniApproval,
        }),
      );
      setStorageError(false);
    } catch {
      setStorageError(true);
    }
  }, [
    items,
    customer,
    cash,
    card,
    activeCart,
    pending,
    storageKey,
    credit,
    debtorId,
    dueDate,
    miniApproval,
  ]);
  useEffect(() => {
    const warn = (e) => {
      if (items.length) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [items]);
  const lines = items.map((item) => {
    const product = products.find((p) => p.id === item.product_id);
    let cents = 0n;
    let invalid = !product;
    try {
      cents = lineCents(item.kg, product?.price || 0, product?.discount || 0);
      invalid ||= scaled(item.kg, 3) <= 0n || scaled(item.kg, 3) > scaled(product.kg, 3);
    } catch {
      invalid = true;
    }
    return { ...item, product, cents, invalid };
  });
  const total = lines.reduce((n, i) => n + i.cents, 0n),
    paid = safeCents(cash) + safeCents(card),
    excess = paid > total ? paid - total : 0n;
  const donationTooLarge = excess > 1500000n;
  // Tasdiq aynan shu savat va to‘lovga tegishli; o‘zgarsa chegirma qayta tanlanadi.
  const miniKey = JSON.stringify({ items, total: decimal(total), cash, card });
  const shortfall = total > paid ? total - paid : 0n;
  const miniAllowed = !credit && shortfall > 0n && shortfall <= 500000n && paid % 100000n === 0n;
  const miniApplied = miniAllowed && miniApproval === miniKey;
  function add(product) {
    if (locked) return;
    setItems((old) => {
      const found = old.find((i) => i.product_id === product.id);
      if (found)
        return old.map((i) =>
          i.product_id === product.id
            ? { ...i, kg: String(Math.min(Number(product.kg), Number(i.kg || 0) + 1)) }
            : i,
        );
      return [...old, { product_id: product.id, kg: String(Math.min(1, Number(product.kg))) }];
    });
  }
  function reset() {
    setItems([]);
    setCustomer('');
    setCash('');
    setCard('');
    setActiveCart(null);
    setPending(null);
    setCredit(false);
    setDebtorId('');
    setDueDate('');
    setMiniApproval(null);
  }
  async function save(e) {
    e.preventDefault();
    if (!items.length || lines.some((i) => i.invalid))
      return notify('Mahsulot kilogrammlarini tekshiring.', true);
    setBusy(true);
    try {
      const data = {
        branch_id: Number(branch),
        label: customer.trim() || `Mijoz ${carts.length + 1}`,
        items,
        ...(activeCart ? { version: activeCart.version } : {}),
      };
      await post(
        activeCart ? `/carts/${activeCart.id}` : '/carts',
        data,
        activeCart ? 'PUT' : 'POST',
      );
      reset();
      setHold(false);
      await load();
      notify('Savdo xotirada. Keyingi mijozni boshlashingiz mumkin.');
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  function restore(cart) {
    if (items.length)
      return notify('Avval joriy savdoni xotiraga saqlang yoki savatni tozalang.', true);
    setItems(cart.items);
    setCustomer(cart.label);
    setActiveCart({ id: cart.id, version: cart.version });
    setCash('');
    setCard('');
    setViewCarts(false);
    setCredit(false);
    setDebtorId('');
    setDueDate('');
  }
  async function checkout() {
    if (busy) return;
    if (!pending && donationTooLarge)
      return notify(
        'Bir savdodagi ehson 15 000 so‘mdan oshmasin. Naqd va karta summalarini tekshiring.',
        true,
      );
    const data = pending || {
      branch_id: Number(branch),
      request_id: requestId(),
      customer,
      items,
      cash: cash || '0',
      card: card || '0',
      expected_total: decimal(total),
      saved_cart_id: activeCart?.id || null,
      saved_cart_version: activeCart?.version || null,
      debtor_id: credit ? Number(debtorId) : null,
      due_date: credit ? dueDate : null,
      mini_discount: miniApplied ? decimal(shortfall) : '0',
    };
    // So‘rovni yuborishdan OLDIN yozamiz: internet uzilsa aynan shu savdo qayta tekshiriladi.
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          items,
          customer,
          cash,
          card,
          activeCart,
          pending: data,
          credit,
          debtorId,
          dueDate,
          miniApproval,
        }),
      );
    } catch {
      notify(
        'Brauzer xotirasi yozilmayapti. Savdoni xavfsiz yuborish uchun xotiraga ruxsat bering.',
        true,
      );
      return;
    }
    setPending(data);
    setBusy(true);
    try {
      const sale = await post('/sales', data);
      window.dispatchEvent(new Event('crm-debts-changed'));
      reset();
      await load();
      notify(
        `Savdo #${sale.id} yakunlandi. ${fmt(sale.total)} so‘m${sale.mini_discount ? ` · Mini chegirma: ${fmt(sale.mini_discount.amount)} so‘m` : ''}${sale.debt ? ` · Qarz: ${fmt(sale.debt.amount)} so‘m` : ''}${Number(sale.donation) ? ` · Ehson: ${fmt(sale.donation)} so‘m` : ''}`,
      );
    } catch (e) {
      if (e.status && e.status < 500 && e.code !== 'desktop_paused') setPending(null);
      notify(
        e.status
          ? e.message
          : 'Ulanish uzildi. «Natijani tekshirish» orqali shu savdoni xavfsiz qayta tekshiring.',
        true,
      );
      if (e.code !== 'desktop_paused') await load();
    } finally {
      setBusy(false);
    }
  }
  const searchTerm = search.trim().toLocaleLowerCase();
  const visible = products.filter((p) => {
    if (searchTerm) return (p.name + ' ' + p.sku).toLocaleLowerCase().includes(searchTerm);
    return stockFilter === 'all' || (stockFilter === 'active' ? p.active : !p.active);
  });
  return (
    <>
      <div className="pos-toolbar">
        <div className="catalog-tools">
          <label className="search">
            <Search size={22} />
            <input
              aria-label="Mahsulot qidirish"
              placeholder="Mahsulot nomi yoki SKU bo‘yicha qidirish…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <button className="icon-btn" aria-label="Mahsulotlarni yangilash" onClick={load}>
            <RotateCcw size={18} />
          </button>
        </div>
        <button className="secondary" onClick={() => setViewCarts(true)} disabled={locked}>
          <Clock3 size={18} />
          Xotiradagi savdolar <span className="count">{carts.length}</span>
        </button>
      </div>
      {storageError && (
        <div className="error">
          Brauzer xotirasi mavjud emas. Sahifadan chiqishdan oldin savdoni xotiraga saqlang.
        </div>
      )}
      <div className="pos-layout">
        <section className="catalog">
          <div className="catalog-controls">
            <div className="catalog-filters" role="group" aria-label="Mahsulot mavjudligi">
              {[
                ['active', 'Omborda bor'],
                ['inactive', 'Omborda yo‘q'],
                ['all', 'Hammasi'],
              ].map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  className={stockFilter === value ? 'primary' : 'secondary'}
                  aria-pressed={stockFilter === value}
                  onClick={() => setStockFilter(value)}
                >
                  {label}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="secondary catalog-image-toggle"
              aria-pressed={hideImages}
              onClick={() => setHideImages((hidden) => !hidden)}
            >
              {hideImages ? <ImageIcon size={18} /> : <ImageOff size={18} />}
              {hideImages ? 'Rasmlarni ko‘rsatish' : 'Rasmlarni yashirish'}
            </button>
            {searchTerm && <span className="filter-hint">Qidiruv barcha mahsulotlar bo‘yicha</span>}
          </div>
          <div className="section-caption">
            <span>
              Mahsulotlar <b>{visible.length}</b>
            </span>
            <span>Narxlar 1 kg uchun</span>
          </div>
          <div className={'product-grid' + (hideImages ? ' product-grid-compact' : '')}>
            {visible.map((p) => (
              <button
                key={p.id}
                className={'product-card ' + (!p.active ? 'inactive' : '')}
                onClick={() => add(p)}
                disabled={!p.active || locked}
              >
                {!hideImages && (
                  <div className="product-visual">
                    <ProductImage product={p} />
                    {Number(p.discount) > 0 && (
                      <span className="discount-label">−{fmt(p.discount)}%</span>
                    )}
                    <span className="product-add">
                      <Plus size={18} />
                    </span>
                  </div>
                )}
                <span className="product-meta">
                  <span className="product-sku">
                    {p.sku} · {p.supplier}
                  </span>
                  {hideImages && Number(p.discount) > 0 && (
                    <span className="product-discount">−{fmt(p.discount)}%</span>
                  )}
                </span>
                <strong>{p.name}</strong>
                <div className="product-price">
                  {fmt(decimal(lineCents('1', p.price, p.discount)))} <small>so‘m / kg</small>
                </div>
                <span className={'stock-caption ' + (!p.active ? 'sold-out' : '')}>
                  <span className="status-dot" />
                  {p.active ? `${kgFmt(p.kg)} kg mavjud` : 'Tugagan'}
                </span>
                {hideImages && (
                  <span className="product-compact-add" aria-hidden="true">
                    <Plus size={18} />
                  </span>
                )}
              </button>
            ))}
          </div>
          {!visible.length && (
            <Empty
              title={loaded ? 'Mahsulot topilmadi' : 'Mahsulotlar yuklanmoqda'}
              text={
                searchTerm
                  ? 'Boshqa nom yoki SKU bilan qidiring.'
                  : stockFilter === 'active'
                    ? '«Hammasi» filtrini tanlang yoki omborga mahsulot kirim qiling.'
                    : 'Boshqa filtrni tanlang yoki mahsulot nomi bilan qidiring.'
              }
            />
          )}
        </section>
        <section className="cart-panel">
          <div className="cart-head">
            <div>
              <ShoppingBag size={19} />
              <h2>{activeCart ? customer : 'Joriy savdo'}</h2>
              <span className="count">{items.length}</span>
            </div>
            <button
              className="icon-btn"
              aria-label="Savatni tozalash"
              disabled={locked || !items.length}
              onClick={() => {
                if (window.confirm('Joriy savat tozalansinmi? Xotirada saqlangan nusxa qoladi.'))
                  reset();
              }}
            >
              <Trash2 size={17} />
            </button>
          </div>
          <div className="cart-lines">
            {!items.length ? (
              <Empty title="Savatingiz bo‘sh" text="Chapdan mahsulot tanlab savdoni boshlang." />
            ) : (
              lines.map((i) => (
                <div className={'cart-line ' + (i.invalid ? 'invalid' : '')} key={i.product_id}>
                  <div className="cart-line-title">
                    <strong>{i.product?.name || 'Mavjud bo‘lmagan mahsulot'}</strong>
                    <button
                      className="icon-btn"
                      aria-label="Mahsulotni olib tashlash"
                      disabled={locked}
                      onClick={() => setItems(items.filter((x) => x.product_id !== i.product_id))}
                    >
                      <X size={16} />
                    </button>
                  </div>
                  <span className="muted">
                    {i.product?.sku} · {fmt(i.product?.price)} so‘m/kg
                    {Number(i.product?.discount) > 0 && ` · −${fmt(i.product.discount)}%`}
                  </span>
                  <div className="cart-line-bottom">
                    <label className="kg-input">
                      <input
                        aria-label={`${i.product?.name} kilogrammi`}
                        type="number"
                        min="0.001"
                        step="0.001"
                        max={i.product?.kg}
                        value={i.kg}
                        disabled={locked}
                        onChange={(e) =>
                          setItems(
                            items.map((x) =>
                              x.product_id === i.product_id ? { ...x, kg: e.target.value } : x,
                            ),
                          )
                        }
                      />
                      <span>kg</span>
                    </label>
                    <b>
                      {fmt(decimal(i.cents))} <small>so‘m</small>
                    </b>
                  </div>
                  {i.invalid && (
                    <small className="red">
                      Kilogrammni tekshiring. Qoldiq: {kgFmt(i.product?.kg)} kg
                    </small>
                  )}
                </div>
              ))
            )}
          </div>
          <div className="cart-payment">
            <div className="cart-total">
              <span>Jami summa</span>
              <strong>
                {fmt(decimal(total))}
                <small> so‘m</small>
              </strong>
            </div>
            <div className="payment-fields">
              <label>
                <button
                  type="button"
                  aria-label="Naqd bilan qolgan summani to‘ldirish"
                  disabled={locked}
                  onClick={() =>
                    setCash(decimal(total > safeCents(card) ? total - safeCents(card) : 0n))
                  }
                >
                  <Banknote size={18} />
                  Naqd
                </button>
                <MoneyInput
                  aria-label="Naqd summa"
                  value={cash}
                  disabled={locked}
                  onChange={setCash}
                />
              </label>
              <label>
                <button
                  type="button"
                  aria-label="Karta bilan qolgan summani to‘ldirish"
                  disabled={locked}
                  onClick={() =>
                    setCard(decimal(total > safeCents(cash) ? total - safeCents(cash) : 0n))
                  }
                >
                  <CreditCard size={18} />
                  Karta
                </button>
                <MoneyInput
                  aria-label="Karta summa"
                  value={card}
                  disabled={locked}
                  onChange={setCard}
                />
              </label>
            </div>
            <div className="payment-info">
              <span>Qabul qilingan</span>
              <b>{fmt(decimal(paid))} so‘m</b>
            </div>
            <button
              type="button"
              className={credit ? 'primary wide' : 'secondary wide'}
              aria-pressed={credit}
              disabled={locked}
              onClick={() => {
                setCredit(!credit);
                setMiniApproval(null);
              }}
            >
              {credit ? 'Qarzga savdo tanlangan' : 'Qarzga berish'}
            </button>
            {credit && (
              <div className="credit-fields">
                <Field label="Qarzdor">
                  <select
                    value={debtorId}
                    disabled={locked}
                    onChange={(e) => setDebtorId(e.target.value)}
                  >
                    <option value="">Qarzdorni tanlang</option>
                    {debtors.map((d) => (
                      <option key={d.id} value={d.id}>
                        {d.last_name} {d.first_name} · {d.phone1}
                      </option>
                    ))}
                  </select>
                </Field>
                {!debtors.length && (
                  <p className="notice">
                    Avval admin yoki boshliq «Qarzlar» bo‘limida qarzdorni kiritsin.
                  </p>
                )}
                <Field label="Qaytarish sanasi">
                  <input
                    type="date"
                    value={dueDate}
                    disabled={locked}
                    onChange={(e) => setDueDate(e.target.value)}
                  />
                </Field>
                <p className="cart-hint">
                  Hozir olingan pulni naqd/kartaga kiriting. Qolgan summa qarz bo‘ladi.
                </p>
              </div>
            )}
            {excess > 0n && (
              <div className="donation-info">
                <span>Ehson hisobiga</span>
                <b>+{fmt(decimal(excess))} so‘m</b>
              </div>
            )}
            {!pending && donationTooLarge && (
              <p className="error" role="alert">
                Bir savdodagi ehson 15 000 so‘mdan oshmasin. Naqd va karta summalarini tekshiring.
              </p>
            )}
            {paid < total && (
              <div className="payment-info">
                <span>
                  {credit ? 'Qarzga qoladi' : miniApplied ? 'Mini chegirma' : 'Yetishmaydi'}
                </span>
                <b className="red">{fmt(decimal(total - paid))} so‘m</b>
              </div>
            )}
            {!credit && shortfall > 0n && (
              <>
                <button
                  className={miniApplied ? 'primary wide' : 'secondary wide'}
                  type="button"
                  disabled={locked || !miniAllowed}
                  aria-pressed={miniApplied}
                  onClick={() => setMiniApproval(miniApplied ? null : miniKey)}
                >
                  {miniApplied ? 'Mini chegirmani bekor qilish' : 'Qolganini chegirma qilish'}
                </button>
                <p className="cart-hint">
                  {miniApplied
                    ? `${fmt(decimal(shortfall))} so‘m mini chegirma tanlandi.`
                    : `To‘lovni minglikda kiriting, masalan ${fmt(decimal((total / 100000n) * 100000n))} so‘m. Faqat tugmani bossangiz farq chegirma bo‘ladi; eng ko‘pi 5 000 so‘m.`}
                </p>
              </>
            )}
            {pending && (
              <p className="notice">
                Savdo yuborilgan. Natijani tekshirish qayta savdo yaratmaydi.
              </p>
            )}
            {miniApplied && (
              <div className="payment-info">
                <span>Chegirmadan keyin to‘lov</span>
                <b>{fmt(decimal(paid))} so‘m</b>
              </div>
            )}
            <button
              className="primary wide checkout"
              disabled={
                busy ||
                (!pending &&
                  (!items.length ||
                    !loaded ||
                    donationTooLarge ||
                    lines.some((i) => i.invalid) ||
                    (credit
                      ? !debtorId || !dueDate || paid >= total
                      : paid < total && !miniApplied)))
              }
              onClick={checkout}
            >
              {busy ? 'Bajarilmoqda…' : pending ? 'Natijani tekshirish' : 'Savdoni yakunlash'}
              <ArrowRight size={18} />
            </button>
            <button
              className="secondary wide"
              disabled={locked || !items.length}
              onClick={() => setHold(true)}
            >
              <Pause size={17} />
              Xotiraga saqlash
            </button>
            <p className="cart-hint">
              Naqd va kartani birga kiritsangiz, jami avtomatik hisoblanadi.
            </p>
          </div>
        </section>
      </div>
      {hold && (
        <Modal title="Savdoni xotiraga saqlash" busy={busy} onClose={() => setHold(false)}>
          <form onSubmit={save}>
            <p className="modal-description">
              Bu mijozga keyin qaytishingiz mumkin. Mahsulotlar ombordan hozircha ayrilmaydi.
              {credit && ' Xotiradan ochgach qarzdor va qaytarish sanasini qayta tanlang.'}
            </p>
            <Field label="Mijoz nomi yoki belgi">
              <input
                value={customer}
                maxLength={120}
                placeholder="Masalan: Malika opa"
                onChange={(e) => setCustomer(e.target.value)}
                autoFocus
              />
            </Field>
            <FormFooter busy={busy} onClose={() => setHold(false)} />
          </form>
        </Modal>
      )}
      {viewCarts && (
        <Modal title="Xotiradagi savdolar" busy={busy} onClose={() => setViewCarts(false)}>
          <p className="modal-description">Faqat o‘zingiz saqlagan, shu filialdagi savdolar.</p>
          {!carts.length && <Empty title="Xotirada savdo yo‘q" />}
          {carts.map((c) => (
            <div className="saved-cart" key={c.id}>
              <div>
                <strong>{c.label}</strong>
                <small>
                  {c.items.length} ta mahsulot · #{c.id}
                </small>
              </div>
              <button className="secondary" disabled={locked} onClick={() => restore(c)}>
                Davom etish
                <ArrowRight size={15} />
              </button>
              <button
                className="icon-btn"
                aria-label="Saqlangan savdoni o‘chirish"
                disabled={busy}
                onClick={async () => {
                  if (!window.confirm(`${c.label} savdosi xotiradan o‘chirilsinmi?`)) return;
                  setBusy(true);
                  try {
                    await api(`/carts/${c.id}?version=${c.version}`, { method: 'DELETE' });
                    if (activeCart?.id === c.id) setActiveCart(null);
                    await load();
                  } catch (e) {
                    notify(e.message, true);
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
        </Modal>
      )}
    </>
  );
}
