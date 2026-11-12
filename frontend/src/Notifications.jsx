import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Banknote,
  Bell,
  CalendarClock,
  Warehouse,
  CheckCheck,
  ChevronRight,
  PackageCheck,
  RefreshCw,
  Tag,
  Trash2,
} from 'lucide-react';
import { api, post, query } from './api';
import { Amount, Empty, Modal, dateFmt } from './components';
import { kgFmt } from './money';
import { uzDate } from './dates';
import './notifications.css';

export function Notifications({
  user,
  branch,
  branches,
  notify,
  onOpenChange,
  onOpenHistory,
  onOpenDebt,
  onOpenDebts,
}) {
  const canUseChanges = user.role === 'boss';
  const [category, setCategory] = useState('all');
  const [debtData, setDebtData] = useState(null);
  const [debtError, setDebtError] = useState('');
  const debtController = useRef(null);
  const debtGeneration = useRef(0);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [readError, setReadError] = useState('');
  const [open, setOpen] = useState(false);
  const [marking, setMarking] = useState(false);
  const live = useRef(false);
  const generation = useRef(0);
  const controller = useRef(null);
  const previousCount = useRef(null);
  const queue = useRef(Promise.resolve());
  const pending = useRef(0);
  const notifyRef = useRef(notify);
  notifyRef.current = notify;

  const load = useCallback(
    async (announce = true) => {
      if (!canUseChanges || !live.current || (announce && pending.current)) return;
      const current = ++generation.current;
      controller.current?.abort();
      const request = new AbortController();
      controller.current = request;
      try {
        const value = await api('/notifications/changes', { signal: request.signal });
        if (!live.current || current !== generation.current) return;
        const before = previousCount.current;
        previousCount.current = value.unread_count;
        setData(value);
        setError('');
        if (announce && value.unread_count > (before ?? 0)) {
          const message =
            before === null
              ? `${value.unread_count} ta o‘qilmagan o‘zgarish bor.`
              : `${value.unread_count - before} ta yangi bildirishnoma: narx, qoldiq, savdo yoki pul topshirish.`;
          notifyRef.current?.(message);
        }
      } catch (failure) {
        if (live.current && current === generation.current && failure.name !== 'AbortError')
          setError(failure.message);
      }
    },
    [canUseChanges],
  );

  const acknowledge = useCallback(
    (ids) => {
      const eventIds = [...new Set(ids)].filter((id) => Number.isSafeInteger(id) && id > 0);
      if (!eventIds.length || !live.current) return;
      pending.current++;
      generation.current++;
      controller.current?.abort();
      setMarking(true);
      setReadError('');
      queue.current = queue.current
        .catch(() => {})
        .then(async () => {
          if (!live.current) return;
          try {
            await post('/notifications/changes/read', { event_ids: eventIds });
            if (live.current) {
              window.dispatchEvent(
                new CustomEvent('crm-change-read', { detail: { ids: eventIds } }),
              );
              await load(false);
            }
          } catch (failure) {
            if (!live.current) return;
            const message = failure.status
              ? failure.message
              : 'O‘qilgan belgi tasdiqlanmadi. Ro‘yxatni yangilab, qayta urinib ko‘ring.';
            setReadError(message);
            notifyRef.current?.(message, true);
          }
        })
        .finally(() => {
          pending.current--;
          if (live.current && !pending.current) setMarking(false);
        });
    },
    [load],
  );

  useEffect(() => {
    if (!canUseChanges) return;
    live.current = true;
    const refresh = () => load(true);
    const detailOpened = (event) => acknowledge([event.detail?.id]);
    refresh();
    const timer = setInterval(refresh, 15000);
    window.addEventListener('focus', refresh);
    window.addEventListener('crm-changes-changed', refresh);
    window.addEventListener('crm-change-opened', detailOpened);
    return () => {
      live.current = false;
      generation.current++;
      controller.current?.abort();
      clearInterval(timer);
      window.removeEventListener('focus', refresh);
      window.removeEventListener('crm-changes-changed', refresh);
      window.removeEventListener('crm-change-opened', detailOpened);
    };
  }, [canUseChanges, load, acknowledge]);

  const loadDebts = useCallback(async () => {
    const generation = ++debtGeneration.current;
    debtController.current?.abort();
    const controller = new AbortController();
    debtController.current = controller;
    try {
      const result = await api('/notifications/debts' + query({ branch_id: branch }), {
        signal: controller.signal,
      });
      if (generation !== debtGeneration.current || controller.signal.aborted) return;
      setDebtData(result);
      setDebtError('');
    } catch (failure) {
      if (generation === debtGeneration.current && failure.name !== 'AbortError')
        setDebtError(failure.message);
    }
  }, [branch]);
  useEffect(() => {
    setDebtData(null);
    setDebtError('');
    setOpen(false);
    loadDebts();
    const timer = setInterval(loadDebts, 30000);
    window.addEventListener('crm-debts-changed', loadDebts);
    window.addEventListener('focus', loadDebts);
    return () => {
      debtGeneration.current++;
      debtController.current?.abort();
      clearInterval(timer);
      window.removeEventListener('crm-debts-changed', loadDebts);
      window.removeEventListener('focus', loadDebts);
    };
  }, [loadDebts]);
  const changeCount = canUseChanges ? (data?.unread_count ?? 0) : 0;
  const debtCount = debtData?.count ?? 0;
  const total = changeCount + debtCount;
  const failure = (canUseChanges && error) || debtError;
  const loading = (!debtData && !debtError) || (canUseChanges && !data && !error);
  const changes = canUseChanges && category !== 'debts' ? (data?.items ?? []) : [];
  const debts = category !== 'changes' ? (debtData?.items ?? []) : [];
  const visibleCount = changes.length + debts.length;
  const filteredCount =
    category === 'changes' ? changeCount : category === 'debts' ? debtCount : total;
  const go = (callback, entry) => {
    setOpen(false);
    callback(entry);
  };

  return (
    <>
      <button
        type="button"
        className={`secondary notification-trigger${total > 0 ? ' has-notifications' : ''}${failure ? ' notification-error' : ''}`}
        aria-label={`Bildirishnomalar: ${total}${failure ? ', yangilashda xato' : ''}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={`${changeCount} ta o‘qilmagan o‘zgarish · ${debtCount} ta muddati kelgan qarz`}
        onClick={() => {
          setOpen(true);
          load(false);
          loadDebts();
        }}
      >
        <Bell size={19} />
        <span className="notification-label">Bildirishnomalar</span>
        <span className="count" aria-live="polite" aria-atomic="true">
          {total || (failure ? '!' : loading ? '…' : 0)}
        </span>
      </button>
      {open && (
        <Modal
          title="Bildirishnomalar"
          className="notifications-modal"
          onClose={() => setOpen(false)}
        >
          <div className="notifications-toolbar">
            <div className="notifications-overview">
              <span className="notifications-summary-icon">
                <Bell size={22} />
              </span>
              <div>
                <strong>{total} ta xabar</strong>
                <p>Xabarni bosing — tegishli tafsilot ochiladi.</p>
              </div>
              <button
                type="button"
                className="secondary"
                aria-label="Bildirishnomalarni yangilash"
                onClick={() => {
                  load(false);
                  loadDebts();
                }}
              >
                <RefreshCw size={18} />
              </button>
            </div>
            <div className="notifications-filters" role="group" aria-label="Bildirishnoma turi">
              {[
                ['all', 'Barchasi', total],
                ...(canUseChanges ? [['changes', 'O‘zgarishlar', changeCount]] : []),
                ['debts', 'Qarzlar', debtCount],
              ].map(([id, label, count]) => (
                <button
                  type="button"
                  key={id}
                  aria-pressed={category === id}
                  onClick={() => setCategory(id)}
                >
                  {label}
                  <span>{count}</span>
                </button>
              ))}
            </div>
            <div className="notifications-navigation">
              <button type="button" className="text-btn" onClick={() => go(onOpenDebts)}>
                Qarzlar ro‘yxati <ChevronRight size={15} />
              </button>
              {canUseChanges && (
                <button type="button" className="text-btn" onClick={() => go(onOpenHistory)}>
                  O‘zgarishlar tarixi <ChevronRight size={15} />
                </button>
              )}
            </div>
            {filteredCount > visibleCount && (
              <p className="notifications-limit">
                {filteredCount} ta xabardan {visibleCount} tasi ko‘rsatilmoqda. Qolganlari tegishli
                ro‘yxatda.
              </p>
            )}
            {changes.length > 0 && (
              <button
                type="button"
                className="secondary wide"
                disabled={marking}
                onClick={() => acknowledge(changes.map((entry) => entry.id))}
              >
                <CheckCheck size={17} />
                {marking ? 'Belgilanmoqda…' : 'Ko‘rsatilgan o‘zgarishlarni o‘qildi deb belgilash'}
              </button>
            )}
          </div>
          <div className="notifications-body">
            {canUseChanges && error && (
              <p className="error" role="alert">
                O‘zgarishlar yangilanmadi: {error}
              </p>
            )}
            {debtError && (
              <p className="error" role="alert">
                Qarzlar yangilanmadi: {debtError}
              </p>
            )}
            {readError && (
              <p className="error" role="alert">
                {readError}
              </p>
            )}
            {loading && <p>Bildirishnomalar yuklanmoqda…</p>}
            {!loading && !failure && visibleCount === 0 && (
              <Empty
                title="Bildirishnoma yo‘q"
                text="Yangi o‘zgarishlar va muddati kelgan qarzlar shu yerda ko‘rinadi."
              />
            )}
            <div className="notifications-list">
              {changes.map((entry) => (
                <button
                  type="button"
                  className="notification-card change-notification-item"
                  key={`change:${entry.id}`}
                  disabled={marking}
                  onClick={() => {
                    setOpen(false);
                    onOpenChange(entry);
                  }}
                >
                  <span
                    className={`change-notification-icon ${entry.kind.endsWith('_cancelled') ? 'cancelled' : ''}`}
                  >
                    {entry.stock ? (
                      <PackageCheck size={19} />
                    ) : entry.kind === 'price_change' ? (
                      <Tag size={19} />
                    ) : entry.payment ? (
                      <Banknote size={19} />
                    ) : (
                      <Trash2 size={19} />
                    )}
                  </span>
                  <span className="change-notification-copy">
                    <strong>{entry.title}</strong>
                    <span>
                      {entry.actor} · {entry.branch_name}
                    </span>
                    {entry.stock ? (
                      <>
                        <span>
                          {entry.stock.name} · {kgFmt(entry.stock.before)} →{' '}
                          {kgFmt(entry.stock.after)} kg
                        </span>
                        <span>
                          Farq: {Number(entry.stock.difference) > 0 ? '+' : ''}
                          {kgFmt(entry.stock.difference)} kg
                        </span>
                        <span>Sabab: {entry.reason}</span>
                        {entry.stock.cancelled && <span>Tuzatish bekor qilingan</span>}
                      </>
                    ) : entry.price ? (
                      <span>
                        {entry.price.name} · <Amount value={entry.price.before} /> →{' '}
                        <Amount value={entry.price.after} />
                      </span>
                    ) : entry.sale ? (
                      <span>
                        Savdo #{entry.sale.id} · <Amount value={entry.sale.total} />
                      </span>
                    ) : entry.payment ? (
                      <>
                        <span>
                          {entry.payment.recipient} · <Amount value={entry.payment.amount} />
                        </span>
                        {Number(entry.payment.unrecorded_amount) > 0 && (
                          <span>
                            Hisobdagi qoldiqdan ortiq:{' '}
                            <Amount value={entry.payment.unrecorded_amount} />
                          </span>
                        )}
                        <span>Izoh: {entry.reason}</span>
                      </>
                    ) : null}
                    <small>{dateFmt(entry.created_at)}</small>
                  </span>
                  <ChevronRight size={17} />
                </button>
              ))}
              {debts.map((debt) => (
                <button
                  type="button"
                  className="notification-card debt-notification-card"
                  key={`debt:${debt.origin || 'sale'}:${debt.id}`}
                  onClick={() => go(onOpenDebt, debt)}
                >
                  <span className="notification-card-icon">
                    <CalendarClock size={22} />
                  </span>
                  <span className="notification-card-copy">
                    <span className="notification-card-heading">
                      <strong>
                        {debt.debtor.first_name} {debt.debtor.last_name}
                      </strong>
                      <span className="notification-kind">
                        {debt.origin === 'opening' ? 'Oldingi qarz' : 'Qarz'} #{debt.id}
                      </span>
                    </span>
                    <span className="notification-card-meta">
                      <Warehouse size={14} />
                      {branches.find((b) => b.id === debt.branch_id)?.name || 'Filial'}
                      <span>·</span>
                      {uzDate(debt.due_date + 'T07:00:00Z', false, true)}
                    </span>
                    <span className="notification-card-bottom">
                      <span className="notification-card-amount">
                        <small>Qolgan qarz</small>
                        <strong>
                          <Amount value={debt.remaining_amount ?? debt.amount} />
                        </strong>
                      </span>
                      <span className="notification-due-label">
                        {debt.overdue ? 'Muddati o‘tgan' : 'Muddati kelgan'}
                      </span>
                    </span>
                  </span>
                  <ChevronRight className="notification-card-arrow" size={19} />
                </button>
              ))}
            </div>
          </div>
        </Modal>
      )}
    </>
  );
}
