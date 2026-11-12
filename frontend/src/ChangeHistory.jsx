import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, ChevronRight, RefreshCw } from 'lucide-react';
import { api, query } from './api';
import { Amount, Badge, Empty, Field, Loading, Modal, Pager, DateTime, dateFmt } from './components';
import { fmt, kgFmt } from './money';
import { Table } from './pages/shared';
import './change-history.css';

const PAGE_SIZE = 20;
const changeTitle = (entry) =>
  ({
    price_change: 'Mahsulot narxi o‘zgartirildi',
    stock_adjustment: 'Ombor qoldig‘i tuzatildi',
    sale_cancelled: 'Savdo o‘chirildi',
    other_payment: 'Boshqa pul topshirildi',
    other_payment_cancelled: 'Boshqa pul topshirig‘i bekor qilindi',
  })[entry.kind] || entry.title;
const eventDate = (value) => (value ? dateFmt(value) : '—');

function ChangeSummary({ entry }) {
  if (entry.stock)
    return (
      <div className="change-price-summary">
        <div>
          <span className="change-amount">{kgFmt(entry.stock.before)}</span>
          <ArrowRight size={19} aria-hidden="true" />
          <strong className="change-amount">{kgFmt(entry.stock.after)} kg</strong>
        </div>
        <small>
          Farq: {Number(entry.stock.difference) > 0 ? '+' : ''}
          {kgFmt(entry.stock.difference)} kg
        </small>
        {entry.stock.cancelled && <Badge tone="gray">Bekor qilingan</Badge>}
      </div>
    );
  if (entry.payment)
    return (
      <div>
        <strong className="change-amount">
          <Amount value={entry.payment.amount} />
        </strong>
        <small>
          {entry.payment.recipient} · {entry.payment.method === 'cash' ? 'Naqd' : 'Karta'}
        </small>
        {entry.payment.cancelled && <Badge tone="gray">Bekor qilingan</Badge>}
      </div>
    );
  return entry.kind === 'price_change' ? (
    <div className="change-price-summary">
      <div>
        <span className="change-amount">{fmt(entry.price?.before)}</span>
        <ArrowRight size={19} aria-hidden="true" />
        <strong className="change-amount">{fmt(entry.price?.after)}</strong>
      </div>
      <small>so‘m / kg</small>
    </div>
  ) : (
    <div>
      <strong className="change-amount">
        <Amount value={entry.sale?.total} />
      </strong>
      <small>O‘chirilgan savdo summasi</small>
    </div>
  );
}

function ChangeDetail({ entry, onClose }) {
  const sale = entry.sale;
  return (
    <Modal title={changeTitle(entry)} className="change-history-modal" onClose={onClose}>
      <dl className="details change-event-details">
        <div>
          <dt>Filial</dt>
          <dd>{entry.branch_name || '—'}</dd>
        </div>
        <div>
          <dt>
            {entry.stock
              ? 'Qoldiqni tuzatgan xodim'
              : entry.payment
                ? 'Qayd etgan xodim'
                : sale
                  ? 'O‘chirgan xodim'
                  : 'Narxni o‘zgartirgan xodim'}
          </dt>
          <dd>{entry.actor || '—'}</dd>
        </div>
        <div>
          <dt>O‘zgarish vaqti</dt>
          <dd>{eventDate(entry.created_at)}</dd>
        </div>
        <div>
          <dt>Sabab</dt>
          <dd className="change-history-reason">{entry.reason || 'Sabab yozilmagan'}</dd>
        </div>
      </dl>
      {entry.stock ? (
        <section className="change-price-detail">
          <h3>{entry.stock.name || 'Mahsulot'}</h3>
          <p>SKU: {entry.stock.sku || '—'}</p>
          {entry.stock.cancelled && <Badge tone="gray">Tuzatish bekor qilingan</Badge>}
          <div className="change-price-comparison">
            <div>
              <span>Oldingi qoldiq</span>
              <strong>{kgFmt(entry.stock.before)} kg</strong>
            </div>
            <ArrowRight aria-hidden="true" size={22} />
            <div>
              <span>Yangi qoldiq</span>
              <strong>{kgFmt(entry.stock.after)} kg</strong>
            </div>
          </div>
          <p>
            <strong>
              Farq: {Number(entry.stock.difference) > 0 ? '+' : ''}
              {kgFmt(entry.stock.difference)} kg
            </strong>
          </p>
          <p>
            Bu yozuv tuzatish vaqtidagi qoldiqni ko‘rsatadi. Sabab va asl kilogramlar tarixda
            saqlanadi.
          </p>
          {entry.stock.labels_source === 'current_product' && (
            <p className="notice">
              Bu eski yozuvda mahsulot nomi va SKU saqlanmagan. Ular joriy katalogdan, kilogramlar
              esa asl tuzatishdan ko‘rsatilgan.
            </p>
          )}
        </section>
      ) : entry.payment ? (
        <section className="change-price-detail">
          <h3>Boshqa pullar · #{entry.payment.id}</h3>
          {entry.payment.cancelled && <Badge tone="gray">Bekor qilingan</Badge>}
          <dl className="details change-sale-totals">
            <div>
              <dt>Kimga topshirilgan</dt>
              <dd>{entry.payment.recipient}</dd>
            </div>
            <div>
              <dt>Topshirilgan summa</dt>
              <dd>
                <Amount value={entry.payment.amount} />
              </dd>
            </div>
            <div>
              <dt>Hisob</dt>
              <dd>{entry.payment.method === 'cash' ? 'Naqd' : 'Karta'}</dd>
            </div>
            {entry.payment.balance_before != null && (
              <>
                <div>
                  <dt>Oldingi kassa qoldig‘i</dt>
                  <dd>
                    <Amount value={entry.payment.balance_before} />
                  </dd>
                </div>
                <div>
                  <dt>Keyingi kassa qoldig‘i</dt>
                  <dd>
                    <Amount value={entry.payment.balance_after} />
                  </dd>
                </div>
                <div>
                  <dt>Hisobdagi qoldiqdan ortiq topshirilgan</dt>
                  <dd>
                    <Amount value={entry.payment.unrecorded_amount} />
                  </dd>
                </div>
              </>
            )}
            {entry.kind === 'other_payment_cancelled' && (
              <div>
                <dt>Asl topshirish izohi</dt>
                <dd className="change-history-reason">{entry.payment.note}</dd>
              </div>
            )}
          </dl>
        </section>
      ) : entry.kind === 'price_change' ? (
        <section className="change-price-detail">
          <h3>{entry.price?.name || 'Mahsulot'}</h3>
          <p>SKU: {entry.price?.sku || '—'}</p>
          <div className="change-price-comparison">
            <div>
              <span>Oldingi narx · 1 kg</span>
              <strong>
                <Amount value={entry.price?.before} />
              </strong>
            </div>
            <ArrowRight aria-hidden="true" size={22} />
            <div>
              <span>Yangi narx · 1 kg</span>
              <strong>
                <Amount value={entry.price?.after} />
              </strong>
            </div>
          </div>
          <p>
            Bu yozuv narx o‘zgartirilgan vaqtdagi holatni ko‘rsatadi. Keyingi o‘zgarishlar alohida
            saqlanadi.
          </p>
          {entry.price?.labels_source === 'current_product' && (
            <p className="notice">
              Bu eski yozuvda mahsulot nomi va SKU saqlanmagan. Nom va SKU joriy katalogdan
              ko‘rsatilgan; oldingi va yangi narxlar tarixdagi asl qiymatlardir.
            </p>
          )}
        </section>
      ) : sale ? (
        <>
          <div className="change-cancelled-sale-heading">
            <h3>Asl savdo #{sale.id}</h3>
            <Badge tone="gray">O‘chirilgan</Badge>
          </div>
          <p className="modal-description">
            {eventDate(sale.created_at)} · {sale.cashier || '—'} · {sale.customer || 'Oddiy savdo'}
          </p>
          <p className="notice">
            Quyida o‘chirish paytida saqlangan savdo nusxasi ko‘rsatilgan. Bu summa joriy savdo
            hisobiga kirmaydi.
          </p>
          {sale.items?.length ? (
            <Table
              headers={['Mahsulot / SKU', 'Kg', 'Narx / kg', 'Chegirma', 'Mini chegirma', 'Jami']}
            >
              {sale.items.map((item, index) => (
                <tr key={item.id || index}>
                  <td>
                    <strong>{item.name || 'Mahsulot'}</strong>
                    <small>{item.sku || '—'}</small>
                  </td>
                  <td>{kgFmt(item.kg)}</td>
                  <td>
                    <Amount value={item.price} />
                  </td>
                  <td>{fmt(item.discount)}%</td>
                  <td>
                    <Amount value={item.mini_discount} />
                  </td>
                  <td>
                    <strong>
                      <Amount value={item.total} />
                    </strong>
                  </td>
                </tr>
              ))}
            </Table>
          ) : (
            <p className="change-history-snapshot-empty">
              Saqlangan nusxada mahsulot qatorlari topilmadi.
            </p>
          )}
          <dl className="details change-sale-totals">
            {[
              ['Asl savdo summasi', sale.total],
              ['Savdoda olingan naqd', sale.cash],
              ['Savdoda olingan karta', sale.card],
              ['Ehson', sale.donation],
              ['Mini chegirma', sale.mini_discount],
              ['Dastlabki qarz', sale.debt],
              ['Qarzga to‘langan naqd', sale.debt_cash],
              ['Qarzga to‘langan karta', sale.debt_card],
            ].map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>
                  <Amount value={value} />
                </dd>
              </div>
            ))}
          </dl>
        </>
      ) : (
        <p className="error" role="alert">
          Savdoning saqlangan nusxasi topilmadi.
        </p>
      )}
    </Modal>
  );
}

export function ChangeHistory({ branch, start, end, revision, initialChange, onChangeOpened }) {
  const [kind, setKind] = useState('');
  const scope = `${branch || 'all'}:${start}:${end}:${kind}:${revision}`;
  const [page, setPage] = useState({ scope, offset: 0 });
  const offset = page.scope === scope ? page.offset : 0;
  const [response, setResponse] = useState(null);
  const [retry, setRetry] = useState(0);
  const [selection, setSelection] = useState(null);
  const detailId = selection?.scope === scope ? selection.id : null;
  const [detailState, setDetailState] = useState(null);
  const [detailRetry, setDetailRetry] = useState(0);
  const opened = useRef(onChangeOpened);
  opened.current = onChangeOpened;
  const requestedInitial = useRef(null);
  const acknowledged = useRef(new Set());
  const validDates = !start || !end || start <= end;

  useEffect(() => {
    const markRead = (event) => {
      const ids = event.detail?.ids;
      if (!Array.isArray(ids) || !ids.length) return;
      for (const id of ids) acknowledged.current.add(String(id));
      setResponse((previous) =>
        previous?.data
          ? {
              ...previous,
              data: {
                ...previous.data,
                items: previous.data.items.map((item) =>
                  acknowledged.current.has(String(item.id)) ? { ...item, unread: false } : item,
                ),
              },
            }
          : previous,
      );
    };
    window.addEventListener('crm-change-read', markRead);
    return () => window.removeEventListener('crm-change-read', markRead);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setResponse((previous) => previous?.scope === scope ? previous : null);
    if (!validDates) return () => controller.abort();
    api(
      '/changes' + query({ branch_id: branch || null, start, end, kind, offset, limit: PAGE_SIZE }),
      {
        signal: controller.signal,
      },
    )
      .then((data) => {
        if (current)
          setResponse({
            scope,
            offset,
            data: {
              ...data,
              items: data.items.map((item) =>
                acknowledged.current.has(String(item.id)) ? { ...item, unread: false } : item,
              ),
            },
          });
      })
      .catch((error) => {
        if (current && error.name !== 'AbortError')
          setResponse({ scope, offset, error: error.message });
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [branch, start, end, kind, offset, scope, retry, validDates]);

  useEffect(() => {
    const id = initialChange?.id ?? initialChange?.cursor;
    const request = initialChange?.token ?? id;
    if (id && requestedInitial.current !== request) {
      requestedInitial.current = request;
      setSelection({ id, scope });
    }
  }, [initialChange?.id, initialChange?.cursor, initialChange?.token, scope]);

  useEffect(() => {
    if (!detailId) {
      setDetailState(null);
      return;
    }
    const controller = new AbortController();
    let current = true;
    setDetailState({ id: detailId, scope, loading: true });
    api(`/changes/${encodeURIComponent(detailId)}`, { signal: controller.signal })
      .then((entry) => {
        if (!current) return;
        setDetailState({ id: detailId, scope, entry });
        opened.current?.(entry.id);
      })
      .catch((error) => {
        if (current && error.name !== 'AbortError')
          setDetailState({ id: detailId, scope, error: error.message });
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [detailId, scope, detailRetry]);

  const current = response?.scope === scope ? response : null;
  const detail = detailState?.scope === scope && detailState.id === detailId ? detailState : null;
  const closeDetail = () => setSelection(null);
  return (
    <div className="change-history">
      <p className="change-history-intro">
        Narx, ombor qoldig‘i, savdo va pul topshirish yozuvlari. Sana filtri amal qilingan vaqtga
        qo‘llanadi.
      </p>
      <div className="change-history-filters">
        <Field label="O‘zgarish turi">
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="">Barcha o‘zgarishlar</option>
            <option value="price_change">Narx o‘zgarishi</option>
            <option value="stock_adjustment">Ombor qoldig‘ini tuzatish</option>
            <option value="sale_cancelled">O‘chirilgan savdolar</option>
            <option value="other_payment">Boshqa pul topshirish</option>
            <option value="other_payment_cancelled">Bekor qilingan pul topshiriqlari</option>
          </select>
        </Field>
      </div>
      {!validDates ? (
        <p className="error" role="alert">
          Boshlanish sanasi tugash sanasidan katta bo‘lmasin.
        </p>
      ) : !current ? (
        <Loading />
      ) : current.error ? (
        <div className="change-history-error" role="alert">
          <p>{current.error}</p>
          <button
            type="button"
            className="secondary"
            onClick={() => setRetry((value) => value + 1)}
          >
            <RefreshCw size={16} /> Qayta urinish
          </button>
        </div>
      ) : !current.data.items.length ? (
        <Empty
          title="Bu davrda o‘zgarish yo‘q"
          text="Narx, ombor qoldig‘i, savdo va pul topshirish yozuvlari shu yerda ko‘rinadi."
        />
      ) : (
        <Table
          headers={[
            'Mahsulot / savdo / topshiriq',
            'Narx / kg / summa',
            'Xodim / filial',
            'Sana va vaqt',
            'Amal',
          ]}
        >
          {current.data.items.map((entry) => (
            <React.Fragment key={entry.id}>
              <tr className="change-entry-row">
                <td>
                  <strong className="change-product-name">
                    {entry.price || entry.stock
                      ? (entry.price || entry.stock).name || 'Mahsulot'
                      : entry.payment
                        ? entry.payment.recipient
                        : `Savdo #${entry.sale?.id || '—'}`}
                  </strong>
                  <small>
                    {entry.stock
                      ? `№ ${entry.stock.sku || '—'} · Qoldiq tuzatildi`
                      : entry.kind === 'price_change'
                        ? `№ ${entry.price?.sku || '—'} · Narx o‘zgartirildi`
                        : changeTitle(entry)}
                  </small>
                  {entry.unread && <Badge>Yangi</Badge>}
                </td>
                <td>
                  <ChangeSummary entry={entry} />
                </td>
                <td>
                  <strong>{entry.actor || '—'}</strong>
                  <small>{entry.branch_name || '—'}</small>
                </td>
                <td>
                  <DateTime value={entry.created_at} />
                </td>
                <td>
                  <button
                    type="button"
                    className="text-btn"
                    onClick={() => setSelection({ id: entry.id, scope })}
                    aria-label={`${changeTitle(entry)}: #${entry.id} tafsiloti`}
                  >
                    Ko‘rish <ChevronRight size={15} />
                  </button>
                </td>
              </tr>
              <tr className="table-note-row">
                <td colSpan={5}>
                  <strong>Sabab:</strong> {entry.reason || 'Sabab yozilmagan'}
                </td>
              </tr>
            </React.Fragment>
          ))}
        </Table>
      )}
      {current?.data && (
        <Pager offset={offset} setOffset={(nextOffset) => setPage({ scope, offset: nextOffset })}
          count={current.data.items.length} pageSize={PAGE_SIZE} total={current.data.total}
          pageToken={current.data} showTotal />
      )}
      {detail?.entry ? (
        <ChangeDetail entry={detail.entry} onClose={closeDetail} />
      ) : (
        detail && (
          <Modal title="O‘zgarish tafsiloti" onClose={closeDetail}>
            {detail.loading ? (
              <Loading />
            ) : (
              <div className="change-history-error" role="alert">
                <p>{detail.error}</p>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => setDetailRetry((value) => value + 1)}
                >
                  <RefreshCw size={16} /> Qayta urinish
                </button>{' '}
                <button type="button" className="secondary" onClick={closeDetail}>
                  Yopish
                </button>
              </div>
            )}
          </Modal>
        )
      )}
    </div>
  );
}
