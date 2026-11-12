// Savdolar, o‘zbekcha audit tafsilotlari va JSON eksport.
import React, { useEffect, useRef, useState } from 'react';
import { Search, Download, RefreshCw, ChevronRight, CircleX, Trash2, Pencil, ChartColumnIncreasing } from 'lucide-react';
import { api, apiBlob, query } from '../api';
import { deliverExport } from '../downloads';
import { SaleEditModal } from '../SaleEditModal';
import { OperationCancelModal } from '../OperationCancelModal';
import { ChangeHistory } from '../ChangeHistory';
import { fmt, kgFmt } from '../money';
import { debtPayments, paymentCancelled } from '../debt-management';
import { Amount, Badge, Empty, Field, Modal, Pager, dateFmt } from '../components';

import { useData, DataState, PageActions, Table, SaleRows } from './shared';

const detailLabels = {
  sale_id: 'Savdo',
  product_id: 'Mahsulot',
  supplier_id: 'Ta’minotchi',
  kg: 'Kilogramm',
  before_kg: 'Oldingi kilogramm',
  price: 'Narx',
  discount: 'Chegirma',
  total: 'Jami',
  cash: 'Naqd',
  card: 'Karta',
  donation: 'Ehson',
  before: 'Oldingi holat',
  reason: 'Tuzatish sababi',
  customer: 'Mijoz',
  debt: 'Qarz summasi',
  debt_id: 'Qarz',
  debtor_id: 'Qarzdor',
  opening_debt_id: 'Oldingi qarz',
  due_date: 'Qaytarish sanasi',
  next_due_date: 'Yangi qaytarish sanasi',
  paid_amount: 'To‘langan summa',
  remaining_amount: 'Qolgan qarz',
  installment_id: 'Qarz to‘lovi',
  revision_id: 'Qarz ma’lumoti tuzatishi',
  origin: 'Qarz turi',
  debt_cash: 'Qarz uchun naqd to‘lov',
  debt_card: 'Qarz uchun karta to‘lovi',
  mini_discount: 'Mini chegirma',
  after: 'Yangi holat',
  items: 'Mahsulotlar',
  amount: 'Summa',
  balance_before: 'Topshirishdan oldingi kassa qoldig‘i',
  balance_after: 'Topshirishdan keyingi kassa qoldig‘i',
  unrecorded_amount: 'Tizimdagi qoldiqdan ortiq topshirilgan',
  method: 'Hisob',
  recipient: 'Qabul qiluvchi',
  note: 'Izoh',
  name: 'Nom',
  sku: 'SKU',
  receipt_id: 'Kirim',
  payment_id: 'To‘lov',
  cart_id: 'Xotiradagi savdo',
  label: 'Belgi',
  role: 'Rol',
  active: 'Faol',
  version: 'Versiya',
  user_id: 'Xodim',
  target_id: 'Xodim',
  username: 'Login',
  previous_username: 'Oldingi login',
  password_changed: 'Parol o‘zgardi',
  count: 'Soni',
  start: 'Boshlanish',
  end: 'Tugash',
};
function Detail({ value }) {
  return typeof value === 'object' && value !== null ? (
    Array.isArray(value) ? (
      <div className="detail-list">
        {value.map((v, i) => (
          <div key={i}>
            <Detail value={v} />
          </div>
        ))}
      </div>
    ) : (
      <dl className="details">
        {Object.entries(value).map(([k, v]) => (
          <div key={k}>
            <dt>{detailLabels[k] || k}</dt>
            <dd>
              <Detail value={v} />
            </dd>
          </div>
        ))}
      </dl>
    )
  ) : (
    <span>
      {value === true
        ? 'Ha'
        : value === false
          ? 'Yo‘q'
          : value === 'cash'
            ? 'Naqd'
            : value === 'card'
              ? 'Karta'
              : (value ?? '—')}
    </span>
  );
}
export function Reports({
  branch,
  branches,
  notify,
  user,
  setBranch,
  initialChange,
  onChangeOpened,
}) {
  const [editing, setEditing] = useState(null);
  const [cancelling, setCancelling] = useState(null);
  const [cancelLoadingId, setCancelLoadingId] = useState(null);
  const cancellationGeneration = useRef(0);
  const canManageSales = ['boss', 'admin'].includes(user?.role);
  useEffect(() => {
    setCancelling(null);
    setCancelLoadingId(null);
    return () => {
      cancellationGeneration.current++;
    };
  }, [branch, user?.id, user?.role]);
  const [auditAll, setAuditAll] = useState(false);
  const [changesRevision, setChangesRevision] = useState(0);
  const [focusedChange, setFocusedChange] = useState(null);
  const lastChangeRequest = useRef(null);
  const [tab, setTab] = useState('sales'),
    [start, setStart] = useState(''),
    [end, setEnd] = useState(''),
    [offset, setOffset] = useState(0),
    [detail, setDetail] = useState(null),
    [search, setSearch] = useState(''),
    [exporting, setExporting] = useState(false);
  const auditAllActive = ['audit', 'changes'].includes(tab) && user?.role === 'boss' && auditAll;
  useEffect(() => { setOffset(0); }, [branch]);
  useEffect(() => {
    if (!initialChange || lastChangeRequest.current === initialChange) return;
    lastChangeRequest.current = initialChange;
    setTab('changes');
    setOffset(0);
    setDetail(null);
    setEditing(null);
    setCancelling(null);
    if (initialChange.id) {
      setAuditAll(false);
      if (initialChange.branch_id != null) setBranch(String(initialChange.branch_id));
      setStart('');
      setEnd('');
      setFocusedChange({ ...initialChange, userKey: `${user?.id}:${user?.role}` });
    } else {
      if (user?.role === 'boss') setAuditAll(true);
      setFocusedChange(null);
      onChangeOpened?.(null);
    }
  }, [initialChange, onChangeOpened, setBranch, user?.id, user?.role]);
  useEffect(() => {
    if (
      focusedChange &&
      (focusedChange.userKey !== `${user?.id}:${user?.role}` ||
        (focusedChange.branch_id != null && String(focusedChange.branch_id) !== String(branch)))
    )
      setFocusedChange(null);
  }, [branch, focusedChange, user?.id, user?.role]);
  const exportGeneration = useRef(0);
  const exportScope = `${branch}:${start}:${end}`;
  const currentExportScope = useRef(exportScope);
  currentExportScope.current = exportScope;
  useEffect(() => {
    exportGeneration.current++;
    setExporting(false);
    return () => {
      exportGeneration.current++;
    };
  }, [branch, start, end]);
  const [data, reload, error] = useData(
    () =>
      tab === 'changes'
        ? Promise.resolve(null)
        : branch || auditAllActive
          ? api(
              (tab === 'sales' ? '/sales' : '/audit') +
                query({
                  ...(auditAllActive ? {} : { branch_id: branch }),
                  ...(tab === 'sales' ? { start, end } : { q: search }),
                  offset,
                  limit: 21,
                }),
            )
          : Promise.resolve(null),
    [branch, tab, auditAllActive, start, end, search, offset],
    notify,
    { keepPreviousData: true, dataScope: `${branch}:${tab}:${auditAllActive}:${start}:${end}:${search}` },
  );
  function changeTab(t) {
    setTab(t);
    setOffset(0);
    setFocusedChange(null);
  }
  async function openSaleCancellation(sale) {
    if (!canManageSales || cancelLoadingId !== null) return;
    const generation = ++cancellationGeneration.current;
    setCancelLoadingId(sale.id);
    try {
      const current = await api(`/sales/${sale.id}/cancellation`);
      if (generation !== cancellationGeneration.current) return;
      if (!current.operation?.can_cancel) {
        notify(current.operation?.reason || 'Bu savdoni hozir o‘chirib bo‘lmaydi.', true);
        return;
      }
      setDetail(null);
      setCancelling(current);
    } catch (failure) {
      if (generation === cancellationGeneration.current) notify(failure.message, true);
    } finally {
      if (generation === cancellationGeneration.current) setCancelLoadingId(null);
    }
  }
  const validDates = !start || !end || start <= end;
  async function download(format = 'json') {
    if (!branch || exporting || !validDates) return;
    const generation = ++exportGeneration.current;
    const capturedScope = exportScope;
    const captured = { branch_id: branch, start, end };
    setExporting(true);
    try {
      const filter = query(captured);
      const result =
        format === 'xlsx'
          ? await apiBlob('/sales/export.xlsx' + filter)
          : await api('/sales/export' + filter);
      if (generation !== exportGeneration.current || capturedScope !== currentExportScope.current)
        return;
      const blob =
        format === 'xlsx'
          ? result
          : new Blob([JSON.stringify(result, null, 2)], { type: 'application/json;charset=utf-8' });
      const filename = `marwa-savdolar-filial-${captured.branch_id}-${captured.start || 'boshi'}-${captured.end || 'bugun'}-${new Date().toISOString().slice(0, 10)}.${format}`;
      const delivery = deliverExport(blob, filename);
      notify(
        delivery === 'prepared'
          ? 'Hisobot tayyor. Saqlash yoki ulashish usulini tanlang.'
          : format === 'xlsx'
            ? 'Savdolar Excel fayli yuklandi.'
            : 'Savdolar JSON fayli yuklandi.',
      );
    } catch (e) {
      if (generation === exportGeneration.current && capturedScope === currentExportScope.current)
        notify(e.message, true);
    } finally {
      if (generation === exportGeneration.current && capturedScope === currentExportScope.current)
        setExporting(false);
    }
  }
  const loadedEntries = tab === 'sales' ? data?.items || [] : Array.isArray(data) ? data : [];
  const entries = loadedEntries.slice(0, 20);
  return (
    <>
      <PageActions>
        <button
          className="secondary"
          onClick={() => (tab === 'changes' ? setChangesRevision((value) => value + 1) : reload())}
          disabled={tab !== 'audit' && !validDates}
          aria-label="Tarixni yangilash"
        >
          <RefreshCw size={17} />
        </button>
        <button
          className="secondary"
          disabled={exporting || !branch || !validDates}
          onClick={() => download('json')}
        >
          <Download size={17} />
          {exporting ? 'Tayyorlanmoqda…' : 'Savdolarni JSON yuklash'}
        </button>
        <button
          className="primary"
          disabled={exporting || !branch || !validDates}
          onClick={() => download('xlsx')}
        >
          <Download size={17} />
          Excel yuklash
        </button>
      </PageActions>
      <section className="panel">
        {user?.role === 'boss' && (
          <div className="list-toolbar">
            <div
              className="tabs report-branch-tabs"
              role="group"
              aria-label={tab === 'sales' ? 'Filial savdo tarixi' : 'Amallar tarixi doirasi'}
            >
              {['audit', 'changes'].includes(tab) && (
                <button
                  className={auditAllActive ? 'selected' : ''}
                  aria-pressed={auditAllActive}
                  onClick={() => {
                    setAuditAll(true);
                    setOffset(0);
                  }}
                >
                  {tab === 'changes' ? 'Barcha filiallar' : 'Barcha filiallar va umumiy amallar'}
                </button>
              )}
              {branches.map((item) => (
                <button
                  key={item.id}
                  className={
                    !auditAllActive && String(item.id) === String(branch) ? 'selected' : ''
                  }
                  aria-pressed={!auditAllActive && String(item.id) === String(branch)}
                  onClick={() => {
                    setAuditAll(false);
                    setOffset(0);
                    setBranch(String(item.id));
                  }}
                >
                  {item.name}
                  {item.archived ? ' — Arxiv' : ''}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="list-toolbar">
          <div className="tabs">
            <button
              className={tab === 'sales' ? 'selected' : ''}
              onClick={() => changeTab('sales')}
            >
              Savdolar
            </button>
            <button
              className={tab === 'audit' ? 'selected' : ''}
              onClick={() => changeTab('audit')}
            >
              Barcha amallar
            </button>
            <button
              className={tab === 'changes' ? 'selected' : ''}
              onClick={() => changeTab('changes')}
            >
              O‘zgarishlar
            </button>
          </div>
        </div>
        {tab !== 'audit' ? (
          <div className="filter-row report-filters">
            <Field label="Boshlanish sanasi">
              <input
                type="date"
                value={start}
                max={end || undefined}
                aria-invalid={!validDates}
                onChange={(e) => {
                  setStart(e.target.value);
                  setOffset(0);
                }}
              />
            </Field>
            <Field label="Tugash sanasi">
              <input
                type="date"
                value={end}
                min={start}
                aria-invalid={!validDates}
                onChange={(e) => {
                  setEnd(e.target.value);
                  setOffset(0);
                }}
              />
            </Field>
            {tab === 'sales' && (
              <div className="filtered-total">
                <span className="report-total-icon" aria-hidden="true"><ChartColumnIncreasing size={23} /></span>
                <div className="report-total-copy">
                  <span>Tanlangan davr savdosi</span>
                  <strong><Amount value={data?.total || 0} /></strong>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="filter-row">
            <label className="search">
              <Search size={18} />
              <input
                aria-label="Tarixdan qidirish"
                placeholder="Amal yoki xodim nomi…"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setOffset(0);
                }}
              />
            </label>
          </div>
        )}
        {!branch && !auditAllActive ? (
          <Empty title="Filial topilmadi" />
        ) : tab === 'changes' ? (
          <ChangeHistory
            key={`${user?.id}:${user?.role}:${auditAllActive ? 'all' : branch}`}
            branch={auditAllActive ? null : branch}
            start={start}
            end={end}
            revision={changesRevision}
            initialChange={
              focusedChange &&
              (focusedChange.userKey !== `${user?.id}:${user?.role}` ||
                (focusedChange.branch_id != null &&
                  String(focusedChange.branch_id) !== String(branch)))
                ? null
                : focusedChange
            }
            onChangeOpened={(id) => {
              setFocusedChange(null);
              onChangeOpened?.(id);
            }}
          />
        ) : !data ? (
          <DataState error={error} reload={reload} />
        ) : !entries.length ? (
          <Empty title="Bu davrda yozuv yo‘q" />
        ) : tab === 'sales' ? (
          <Table
            headers={[
              'Savdo',
              'Sana va vaqt',
              'Filial',
              'Kassir',
              'Jami olingan',
              'To‘lov',
              ...(canManageSales ? ['Amallar'] : []),
            ]}
          >
            <SaleRows
              sales={entries}
              branches={branches}
              onDetail={(s) => setDetail({ type: 'sale', value: s })}
              onEdit={canManageSales ? (s) => setEditing(s.id) : undefined}
              onCancel={canManageSales ? openSaleCancellation : undefined}
              cancelLoadingId={cancelLoadingId}
            />
          </Table>
        ) : (
          <Table headers={['Amal', 'Xodim', 'Filial', 'Vaqt', 'Tafsilot']}>
            {entries.map((a) => (
              <tr key={a.id}>
                <td>
                  <strong>{a.action}</strong>
                  <small>#{a.id}</small>
                  {a.operation?.cancelled && <Badge tone="gray">Bekor qilingan</Badge>}
                </td>
                <td>{a.actor}</td>
                <td>{branches.find((b) => b.id === a.branch_id)?.name || 'Umumiy'}</td>
                <td>{dateFmt(a.created_at)}</td>
                <td>
                  <button
                    className="text-btn"
                    onClick={() => setDetail({ type: 'audit', value: a })}
                  >
                    Ko‘rish
                    <ChevronRight size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </Table>
        )}
        {tab !== 'changes' && (
          <Pager offset={offset} setOffset={setOffset} count={entries.length}
            pageSize={20} total={offset + loadedEntries.length} pageToken={data} />
        )}
      </section>
      {detail && (
        <Modal
          title={detail.type === 'sale' ? `Savdo #${detail.value.id}` : detail.value.action}
          onClose={() => setDetail(null)}
        >
          {detail.type === 'sale' ? (
            <>
              <p className="modal-description">
                {dateFmt(detail.value.created_at)} · {detail.value.cashier} ·{' '}
                {detail.value.customer || 'Oddiy savdo'}
              </p>
              {['boss', 'admin'].includes(user?.role) && (
                <div className="sale-edit-entry">
                  <div>
                    <strong>Mahsulot qaytdimi yoki savdoda xato bormi?</strong>
                    <p>
                      {Date.now() < new Date(detail.value.editable_until).getTime()
                        ? 'Savdodan keyin 72 soat ichida tuzatish mumkin.'
                        : 'Tahrirlash muddati tugagan.'}
                    </p>
                  </div>
                  <button
                    className="primary"
                    disabled={Date.now() >= new Date(detail.value.editable_until).getTime()}
                    onClick={() => {
                      setEditing(detail.value.id);
                      setDetail(null);
                    }}
                  >
                    <Pencil size={16} /> Savdoni tahrirlash
                  </button>
                </div>
              )}
              <Table headers={['Mahsulot', 'Kg', 'Narx/kg', 'Chegirma', 'Mini chegirma', 'Jami']}>
                {detail.value.items.map((i) => (
                  <tr key={i.id}>
                    <td>
                      {i.name}
                      <small>{i.sku}</small>
                    </td>
                    <td>{kgFmt(i.kg)}</td>
                    <td>{fmt(i.price)}</td>
                    <td>{fmt(i.discount)}%</td>
                    <td>{fmt(i.mini_discount || 0)}</td>
                    <td>{fmt(i.total)}</td>
                  </tr>
                ))}
              </Table>
              <dl className="details">
                {detail.value.mini_discount && (
                  <div>
                    <dt>Mini chegirma (ta’minotchidan)</dt>
                    <dd>
                      <Amount value={detail.value.mini_discount.amount} />
                    </dd>
                  </div>
                )}
                {detail.value.debt && (
                  <>
                    <div>
                      <dt>Dastlabki qarz</dt>
                      <dd>
                        <Amount value={detail.value.debt.amount} />
                      </dd>
                    </div>
                    <div>
                      <dt>Qarz uchun to‘langan</dt>
                      <dd>
                        <Amount value={detail.value.debt.paid_amount || 0} />
                      </dd>
                    </div>
                    <div>
                      <dt>Qolgan qarz · {detail.value.debt.due_date}</dt>
                      <dd>
                        <Amount
                          value={detail.value.debt.remaining_amount ?? detail.value.debt.amount}
                        />{' '}
                        ·{' '}
                        {detail.value.debt.status === 'paid'
                          ? 'Yopilgan'
                          : detail.value.debt.status === 'partial'
                            ? 'Qisman to‘langan'
                            : 'To‘lanmagan'}
                      </dd>
                    </div>
                  </>
                )}
                <div>
                  <dt>Jami savdo</dt>
                  <dd>
                    <Amount value={detail.value.total} />
                  </dd>
                </div>
                <div>
                  <dt>Naqd</dt>
                  <dd>
                    <Amount value={detail.value.cash} />
                  </dd>
                </div>
                <div>
                  <dt>Karta</dt>
                  <dd>
                    <Amount value={detail.value.card} />
                  </dd>
                </div>
                <div>
                  <dt>Ehson</dt>
                  <dd>
                    <Amount value={detail.value.donation} />
                  </dd>
                </div>
              </dl>
              {detail.value.debt && debtPayments(detail.value.debt).length > 0 && (
                <>
                  <h3>Qarz to‘lovlari</h3>
                  <Table headers={['Sana / xodim', 'Naqd', 'Karta', 'Holat']}>
                    {debtPayments(detail.value.debt).map((payment) => (
                      <tr
                        key={`${payment.source || payment.operation?.kind || 'legacy'}-${payment.id}`}
                      >
                        <td>
                          {dateFmt(payment.created_at)}
                          <small>{payment.actor || '—'}</small>
                        </td>
                        <td>
                          <Amount value={payment.cash} />
                        </td>
                        <td>
                          <Amount value={payment.card} />
                        </td>
                        <td>{paymentCancelled(payment) ? 'Bekor qilingan' : 'Qabul qilingan'}</td>
                      </tr>
                    ))}
                  </Table>
                </>
              )}
              {canManageSales && (
                <div className="sale-delete-panel">
                  <p>
                    Savdo hisoblardan chiqariladi, mahsulotlar omborga qaytariladi. Asl nusxa va
                    o‘chirish sababi tarixda saqlanadi.
                  </p>
                  <button
                    type="button"
                    className="secondary sale-delete"
                    disabled={cancelLoadingId !== null}
                    onClick={() => openSaleCancellation(detail.value)}
                  >
                    <Trash2 size={17} />
                    {cancelLoadingId === detail.value.id ? 'Tekshirilmoqda…' : 'Savdoni o‘chirish'}
                  </button>
                </div>
              )}
            </>
          ) : (
            <>
              <p className="modal-description">
                {detail.value.actor} · {dateFmt(detail.value.created_at)}
              </p>
              {detail.value.operation?.cancelled && (
                <p className="notice">
                  <strong>Amal bekor qilingan.</strong>{' '}
                  {detail.value.operation.cancelled_at &&
                    dateFmt(detail.value.operation.cancelled_at)}
                  {detail.value.operation.reason && <> · Sabab: {detail.value.operation.reason}</>}
                </p>
              )}
              <Detail value={detail.value.detail} />
              {detail.value.operation?.can_cancel && ['boss', 'admin'].includes(user?.role) && (
                <div className="form-footer">
                  <button
                    className="secondary"
                    onClick={() => {
                      setCancelling(detail.value);
                      setDetail(null);
                    }}
                  >
                    <CircleX size={17} /> Amalni bekor qilish
                  </button>
                </div>
              )}
            </>
          )}
        </Modal>
      )}
      {editing && (
        <SaleEditModal
          saleId={editing}
          user={user}
          notify={notify}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      )}
      {cancelling && (
        <OperationCancelModal
          audit={cancelling}
          branchName={branches.find((item) => item.id === cancelling.branch_id)?.name || 'Umumiy'}
          user={user}
          notify={notify}
          onClose={() => setCancelling(null)}
          onSaved={() => {
            setCancelling(null);
            setDetail(null);
            window.dispatchEvent(new Event('crm-debts-changed'));
            reload();
          }}
        >
          {cancelling.operation.summary && (
            <p className="modal-description">Amalning hozirgi holati</p>
          )}
          <Detail value={cancelling.operation.summary || cancelling.detail} />
        </OperationCancelModal>
      )}
    </>
  );
}
