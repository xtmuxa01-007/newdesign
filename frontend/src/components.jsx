import React, { useEffect, useLayoutEffect, useRef } from 'react';
import { X, PackageOpen, LoaderCircle } from 'lucide-react';
import { fmt } from './money';
import { uzDate } from './dates';

export function Empty({
  title = 'Hozircha ma’lumot yo‘q',
  text = 'Yangi ma’lumot qo‘shilganda shu yerda ko‘rinadi.',
}) {
  return (
    <div className="empty">
      <PackageOpen size={36} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
export function Loading() {
  return (
    <div className="empty">
      <LoaderCircle className="spin" />
      <p>Yuklanmoqda…</p>
    </div>
  );
}
export function Modal({ title, children, onClose, busy, className }) {
  const ref = useRef(null);
  useEffect(() => {
    ref.current.showModal();
    const d = ref.current;
    return () => d.close();
  }, []);
  return (
    <dialog
      className={className}
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) onClose();
      }}
      onClick={(e) => {
        if (e.target === ref.current && !busy) onClose();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button className="icon-btn" disabled={busy} onClick={onClose} aria-label="Yopish">
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Field({ label, children, hint }) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
export function Amount({ value, unit = true }) {
  return (
    <>
      {fmt(value)}
      {unit && <span className="unit"> so‘m</span>}
    </>
  );
}
export function DateTime({ value }) {
  if (!value) return <span>—</span>;
  const [date, time] = uzDate(value).split(', ');
  return (
    <time dateTime={value} className="table-date-time">
      <span>{date}</span>
      <small>{time}</small>
    </time>
  );
}
export function Badge({ children, tone = 'green' }) {
  return <span className={'badge ' + tone}>{children}</span>;
}
export function FormFooter({ busy, submitDisabled = false, label = 'Saqlash', onClose }) {
  return (
    <div className="form-footer">
      <button type="button" className="secondary" onClick={onClose} disabled={busy}>
        Bekor qilish
      </button>
      <button className="primary" disabled={busy || submitDisabled}>
        {busy ? 'Saqlanmoqda…' : label}
      </button>
    </div>
  );
}
export function Pager({ offset, setOffset, count, pageSize = 100, total, pageToken, showTotal = false }) {
  const ref = useRef(null);
  const pending = useRef(null);
  function changePage(nextOffset) {
    pending.current = { offset: nextOffset, token: pageToken };
    setOffset(nextOffset);
  }
  useLayoutEffect(() => {
    const request = pending.current;
    if (!request || request.offset !== offset ||
        (pageToken !== undefined && request.token === pageToken)) return;
    pending.current = null;
    const section = ref.current?.closest('.change-history') || ref.current?.closest('section') || ref.current?.parentElement;
    section?.scrollIntoView({ block: 'start', behavior: 'instant' });
  }, [offset, pageToken]);
  return (
    <div className="pager" ref={ref}>
      <span>
        {offset + (count ? 1 : 0)}–{offset + count}
        {showTotal && total != null && ` / ${total} ta`}
      </span>
      <button
        type="button"
        className="secondary"
        disabled={!offset}
        onClick={() => changePage(Math.max(0, offset - pageSize))}
      >
        Oldingi
      </button>
      <button type="button" className="secondary" disabled={total == null ? count < pageSize : offset + count >= total} onClick={() => changePage(offset + pageSize)}>
        Keyingi
      </button>
    </div>
  );
}
export function ProductImage({ product, small = false }) {
  return product.image ? (
    <img
      className={small ? 'product-img small' : 'product-img'}
      src={product.image}
      alt={product.name}
      loading="lazy"
    />
  ) : (
    <div className={small ? 'product-img placeholder small' : 'product-img placeholder'}>
      <PackageOpen size={small ? 21 : 35} />
    </div>
  );
}
export { uzDate as dateFmt } from './dates';
export { MoneyInput } from './MoneyInput';
