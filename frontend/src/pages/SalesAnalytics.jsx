import React, { useEffect, useId, useRef, useState } from 'react';
import { Download, RefreshCw, Banknote, CreditCard, WalletCards, HandCoins, HeartHandshake, CircleDollarSign, ArrowDownLeft, Landmark, ChartColumnIncreasing, Warehouse, Info } from 'lucide-react';
import { api, apiBlob, query } from '../api';
import { deliverExport } from '../downloads';
import { Amount, Badge, Empty, Field } from '../components';
import { uzDate } from '../dates';
import { decimal, fmt, kgFmt, safeCents } from '../money';
import { DataState, PageActions, Table, useData } from './shared';
import './sales-analytics-design.css';

function todayInTashkent() {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Asia/Tashkent',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
      .formatToParts(new Date())
      .map((part) => [part.type, part.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}`;
}
function monthDates(month) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return null;
  const first = `${month}-01`;
  const date = new Date(first + 'T12:00:00Z');
  date.setUTCMonth(date.getUTCMonth() + 1, 0);
  return { start: first, end: date.toISOString().slice(0, 10) };
}
function validDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(value + 'T12:00:00Z');
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}
function dayLabel(date) {
  return uzDate(date + 'T07:00:00Z', false, true);
}
function monthLabel(month) {
  return dayLabel(month + '-01').replace(/^1-/, '');
}
function maxMoney(rows) {
  return rows.reduce((max, row) => {
    const amount = safeCents(row.goods_total);
    return amount > max ? amount : max;
  }, 0n);
}
function ratio(value, max) {
  return max > 0n ? Number((safeCents(value) * 10000n) / max) / 100 : 0;
}

function SalesChart({ rows, monthly, complete = true }) {
  const gradientId = `sales-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const [active, setActive] = useState(null);
  const max = maxMoney(rows);
  const title = monthly ? 'Oylik savdo' : 'Kunlik savdo';
  const width = 720,
    height = 190,
    left = 14,
    top = 14;
  const slot = width / Math.max(rows.length, 1);
  const labelEvery = Math.max(1, Math.ceil(rows.length / 6));
  const description = (row) =>
    `${monthly ? monthLabel(row.month) : dayLabel(row.date)}: ${fmt(row.goods_total)} so‘m · ${row.sales_count} ta savdo`;
  return (
    <section className="panel analytics-chart-panel">
      <div className="analytics-chart-head">
        <div className="analytics-chart-title"><span className="analytics-section-icon"><ChartColumnIncreasing size={21} /></span><h2>{title}</h2></div>
        <span>Mahsulot qiymati · so‘m</span>
      </div>
      {!max ? (
        <Empty title="Bu davrda savdo yo‘q" text="Boshqa sana yoki filialni tanlang." />
      ) : (
        <>
          <div className="analytics-chart-scale">
            <span>Eng yuqori: <strong>{fmt(decimal(max))} so‘m</strong></span>
            <span>0 so‘m</span>
          </div>
          <svg
            className="analytics-sales-chart"
            viewBox="0 0 750 250"
            role="group"
            aria-label={`${title} grafigi. Mahsulot qiymati bo‘yicha.`}
            style={{ '--analytics-bar-fill': `url(#${gradientId})`, '--analytics-bar-active': `url(#${gradientId}-gold)` }}
          >
            <title>{title}: mahsulot qiymati</title>
            <defs>
              <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#3e9970" /><stop offset="100%" stopColor="#07533f" />
              </linearGradient>
              <linearGradient id={`${gradientId}-gold`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#e1cf7a" /><stop offset="100%" stopColor="#a18c37" />
              </linearGradient>
            </defs>
            {[0, 0.5, 1].map((level) => (
              <line
                key={level}
                x1={left}
                x2={left + width}
                y1={top + height * level}
                y2={top + height * level}
                className="analytics-chart-grid"
              />
            ))}
            {rows.map((row, index) => {
              const value = ratio(row.goods_total, max) / 100;
              const barHeight = value > 0 ? Math.max(2, value * height) : 0;
              const x = left + slot * index + slot * 0.12;
              const label = monthly ? row.month : row.date.slice(5);
              const tip = description(row);
              return (
                <g
                  key={row.month || row.date}
                  role="img"
                  tabIndex={0}
                  aria-label={tip}
                  onMouseEnter={() => setActive(tip)}
                  onMouseLeave={() => setActive(null)}
                  onFocus={() => setActive(tip)}
                  onBlur={() => setActive(null)}
                >
                  <title>{tip}</title>
                  <rect
                    x={left + slot * index}
                    y={top}
                    width={slot}
                    height={height}
                    fill="transparent"
                  />
                  <rect
                    x={x}
                    y={top + height - barHeight}
                    width={Math.max(0.5, slot * 0.76)}
                    height={barHeight}
                    rx={Math.min(6, slot * 0.15)}
                    className="analytics-chart-bar"
                  />
                  {(index % labelEvery === 0 || index === rows.length - 1) && (
                    <text
                      x={left + slot * (index + 0.5)}
                      y={top + height + 24}
                      textAnchor="middle"
                      className="analytics-chart-label"
                    >
                      {label}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          <p className="analytics-chart-tooltip" role="status">
            {active ||
              'Ustun ustiga olib boring yoki Tab orqali tanlang: aniq summa va savdolar soni ko‘rinadi.'}
          </p>
        </>
      )}
      {!complete && (
        <p className="analytics-note">
          Uzoq davr uchun grafik amallar bo‘lgan sanalarni ko‘rsatadi.
        </p>
      )}
    </section>
  );
}

function BranchChart({ rows }) {
  const max = maxMoney(rows);
  const total = rows.reduce((sum, row) => sum + safeCents(row.goods_total), 0n);
  return (
    <section className="panel analytics-chart-panel">
      <div className="analytics-chart-head">
        <div className="analytics-chart-title"><span className="analytics-section-icon"><Warehouse size={21} /></span><h2>Filiallar savdosi</h2></div>
        <span>Mahsulot qiymati · so‘m</span>
      </div>
      {!rows.length ? (
        <Empty title="Filiallar yo‘q" />
      ) : (
        <>
        <div className="analytics-branch-total"><span>{rows.length} ta filial · jami savdo</span><strong><Amount value={decimal(total)} /></strong></div>
        <div
          className="analytics-branch-bars"
          role="list"
          aria-label="Filiallar savdosini taqqoslash"
        >
          {rows.map((row, index) => (
            <div className="analytics-branch-bar" role="listitem" key={row.id}>
              <div>
                <span>
                  <b className="analytics-branch-rank">{index + 1}</b>
                  {row.name}
                  {row.archived ? ' · Arxiv' : ''}
                </span>
                <strong>
                  <Amount value={row.goods_total} />
                </strong>
              </div>
              <div
                className="analytics-branch-track"
                role="img"
                aria-label={`${row.name}: ${fmt(row.goods_total)} so‘m, ${row.sales_count} ta savdo`}
                title={`${row.name}: ${fmt(row.goods_total)} so‘m, ${row.sales_count} ta savdo`}
              >
                <span style={{ width: `${ratio(row.goods_total, max)}%` }} />
              </div>
              <small>
                {row.sales_count} ta savdo · {kgFmt(row.kg)} kg
              </small>
            </div>
          ))}
        </div>
        </>
      )}
    </section>
  );
}

function FinancialRows({ summary }) {
  return (
    <dl className="analytics-finance">
      {[
        ['Savdoda olingan naqd', 'cash', Banknote, ''],
        ['Savdoda olingan karta', 'card', CreditCard, ''],
        ['Savdoda olingan jami', 'received_at_sale', WalletCards, ''],
        ['Davrda yig‘ilgan qarz to‘lovlari', 'debt_collected', ArrowDownLeft, ''],
        ['Davrning jami tushumi', 'period_inflow', Landmark, 'inflow'],
        ['Savdoda yozilgan ehson', 'donation', HeartHandshake, 'donation'],
        ['Savdoda yozilgan qarz', 'debt_created', HandCoins, 'debt'],
        ['Shu savdolardan hozir ochiq qarz', 'debt_outstanding', CircleDollarSign, 'debt'],
      ].map(([label, key, Icon, tone]) => (
        <div key={key} className={`analytics-finance-card ${tone}`}>
          <dt><span className="analytics-finance-icon"><Icon size={20} /></span><span>{label}</span></dt>
          <dd>
            <Amount value={summary[key]} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function SalesAnalytics({ branch, notify, user }) {
  const [initialToday] = useState(todayInTashkent);
  const [start, setStart] = useState(initialToday.slice(0, 7) + '-01');
  const [end, setEnd] = useState(initialToday);
  const [month, setMonth] = useState(initialToday.slice(0, 7));
  const [grain, setGrain] = useState('auto');
  const [exporting, setExporting] = useState(false);
  const canUse = user.role === 'boss' || user.role === 'admin';
  const branchId = user.role === 'boss' ? branch : String(user.branch_id);
  const valid = validDate(start) && validDate(end) && start <= end;
  const filters = { branch_id: branchId, start, end };
  const scope = JSON.stringify(filters);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const exportGeneration = useRef(0);
  useEffect(() => {
    exportGeneration.current++;
    setExporting(false);
    return () => {
      exportGeneration.current++;
    };
  }, [scope]);
  const [result, reload, error] = useData(
    async () => ({
      scope,
      value: valid && canUse ? await api('/sales/analytics' + query(filters)) : null,
    }),
    [scope, valid, canUse],
    notify,
  );
  const data = result?.scope === scope ? result.value : null;
  const days = valid
    ? (Date.parse(end + 'T12:00:00Z') - Date.parse(start + 'T12:00:00Z')) / 86400000 + 1
    : 0;
  const visibleGrain = grain === 'daily' && days > 366 ? 'auto' : grain;
  const monthly = visibleGrain === 'monthly' || (visibleGrain === 'auto' && days > 62);
  function pickMonth(value) {
    setMonth(value);
    const range = monthDates(value);
    if (range) {
      const today = todayInTashkent();
      setStart(range.start);
      setEnd(value === today.slice(0, 7) ? today : range.end);
    }
  }
  function previousMonth() {
    const date = new Date(todayInTashkent().slice(0, 7) + '-01T12:00:00Z');
    date.setUTCMonth(date.getUTCMonth() - 1);
    pickMonth(date.toISOString().slice(0, 7));
  }
  async function download() {
    if (!valid || exporting || !canUse) return;
    const generation = ++exportGeneration.current;
    const capturedScope = scope;
    const captured = { ...filters };
    setExporting(true);
    try {
      const blob = await apiBlob('/sales/analytics/export.xlsx' + query(captured));
      if (generation !== exportGeneration.current || capturedScope !== currentScope.current) return;
      const filename = `marwa-savdolar-analizi-${captured.branch_id ? `filial-${captured.branch_id}` : 'barcha-filiallar'}-${captured.start}-${captured.end}.xlsx`;
      const delivery = deliverExport(blob, filename);
      notify(
        delivery === 'prepared'
          ? 'Hisobot tayyor. Saqlash yoki ulashish usulini tanlang.'
          : 'Savdolar analizi Excel fayli yuklandi.',
      );
    } catch (cause) {
      if (generation === exportGeneration.current && capturedScope === currentScope.current)
        notify(cause.message, true);
    } finally {
      if (generation === exportGeneration.current && capturedScope === currentScope.current)
        setExporting(false);
    }
  }
  if (!canUse) return <Empty title="Bu bo‘lim boshliq va admin uchun" />;
  return (
    <div className="sales-analytics">
      <PageActions>
        <button className="secondary" onClick={reload} disabled={!valid}>
          <RefreshCw size={17} />
          Yangilash
        </button>
        <button className="primary" onClick={download} disabled={!valid || exporting}>
          <Download size={17} />
          {exporting ? 'Tayyorlanmoqda…' : 'Excel yuklash'}
        </button>
      </PageActions>
      <section className="panel analytics-filters">
        <Field label="Oyni tanlash">
          <input type="month" value={month} onChange={(event) => pickMonth(event.target.value)} />
        </Field>
        <Field label="Boshlanish sanasi">
          <input
            type="date"
            value={start}
            max={end || undefined}
            onChange={(event) => {
              setStart(event.target.value);
              setMonth('');
            }}
            required
          />
        </Field>
        <Field label="Tugash sanasi">
          <input
            type="date"
            value={end}
            min={start || undefined}
            onChange={(event) => {
              setEnd(event.target.value);
              setMonth('');
            }}
            required
          />
        </Field>
        <div className="analytics-presets">
          <button className="secondary" onClick={() => pickMonth(todayInTashkent().slice(0, 7))}>
            Shu oy
          </button>
          <button className="secondary" onClick={previousMonth}>
            O‘tgan oy
          </button>
        </div>
        {!valid && (
          <p className="error" role="alert">
            Boshlanish va tugash sanalarini to‘g‘ri tanlang. Boshlanish sanasi tugashdan keyin
            bo‘lmasin.
          </p>
        )}
      </section>
      {valid &&
        (!data ? (
          <DataState error={error} reload={reload} />
        ) : (
          <>
            {error && (
              <p className="error">
                Yangilash amalga oshmadi. Oxirgi yuklangan hisoblar ko‘rsatilmoqda.
              </p>
            )}
            <dl className="analytics-summary">
              {[
                ['Mahsulot savdosi', 'goods_total', 'money'],
                ['Davrning jami tushumi', 'period_inflow', 'money'],
                ['Savdolar soni', 'sales_count', 'count'],
                ['Sotilgan kilogramm', 'kg', 'kg'],
                ['O‘rtacha savdo', 'average_sale', 'money'],
                ['Davr xarajatlari', 'expenses', 'money'],
              ].map(([label, key, kind]) => (
                <div key={key}>
                  <dt>{label}</dt>
                  <dd>
                    {kind === 'money' ? (
                      <Amount value={data.summary[key]} />
                    ) : kind === 'kg' ? (
                      <>
                        {kgFmt(data.summary[key])}
                        <small> kg</small>
                      </>
                    ) : (
                      data.summary[key]
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            <section className="panel analytics-finance-panel">
              <div className="analytics-finance-heading"><span className="analytics-section-icon"><WalletCards size={23} /></span><div><h2>Pul, qarz va ehson</h2><p>Tanlangan davrdagi pul harakati va qarzlar</p></div></div>
              <FinancialRows summary={data.summary} />
              <p className="analytics-note analytics-finance-note"><Info size={18} /><span>
                Mahsulot savdosiga ehson kirmaydi. Jami tushum — savdoda olingan naqd/karta va shu
                davrda yopilgan qarz to‘lovlari. Ochiq qarz shu davr savdolarining hozirgi holatini
                ko‘rsatadi.</span>
              </p>
            </section>
            <div className="analytics-grain">
              <div className="analytics-visuals-title"><ChartColumnIncreasing size={23} /><div><h2>Savdo dinamikasi</h2><p>Davr va filiallar bo‘yicha taqqoslash</p></div></div>
              <Field label="Grafik davri">
                <select value={visibleGrain} onChange={(event) => setGrain(event.target.value)}>
                  <option value="auto">Avtomatik</option>
                  <option value="daily" disabled={days > 366}>
                    Kunlik
                  </option>
                  <option value="monthly">Oylik</option>
                </select>
              </Field>
            </div>
            <div className="analytics-charts">
              <SalesChart
                key={`${scope}:${monthly}`}
                rows={monthly ? data.monthly : data.daily}
                monthly={monthly}
                complete={
                  monthly
                    ? data.series?.monthly_complete !== false
                    : data.series?.daily_complete !== false
                }
              />
              <BranchChart rows={data.branches} />
            </div>
            <section className="panel section-gap">
              <div className="panel-head">
                <h2>Filiallar bo‘yicha hisob</h2>
              </div>
              {!data.branches.length ? (
                <Empty title="Filiallar yo‘q" />
              ) : (
                <Table
                  headers={[
                    'Filial',
                    'Savdolar',
                    'Mahsulot savdosi',
                    'Jami tushum',
                    'Kilogramm',
                    'Ehson',
                    'Ochiq qarz',
                    'Xarajat',
                  ]}
                >
                  {data.branches.map((row) => (
                    <tr key={row.id}>
                      <td>
                        {row.name}
                        {row.archived && <Badge tone="gray">Arxiv</Badge>}
                      </td>
                      <td>{row.sales_count}</td>
                      <td>
                        <Amount value={row.goods_total} />
                      </td>
                      <td>
                        <Amount value={row.period_inflow} />
                      </td>
                      <td>{kgFmt(row.kg)} kg</td>
                      <td>
                        <Amount value={row.donation} />
                      </td>
                      <td>
                        <Amount value={row.debt_outstanding} />
                      </td>
                      <td>
                        <Amount value={row.expenses} />
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </section>
            <section className="panel section-gap">
              <div className="panel-head">
                <h2>Oylik hisob</h2>
              </div>
              {!data.monthly.length ? (
                <Empty title="Bu davrda yozuv yo‘q" />
              ) : (
                <Table
                  headers={[
                    'Oy',
                    'Savdolar',
                    'Mahsulot savdosi',
                    'Naqd',
                    'Karta',
                    'Qarz to‘lovlari',
                    'Jami tushum',
                    'Ehson',
                    'Yozilgan qarz',
                    'Ochiq qarz',
                    'Xarajat',
                  ]}
                >
                  {data.monthly.map((row) => (
                    <tr key={row.month}>
                      <td>{monthLabel(row.month)}</td>
                      <td>{row.sales_count}</td>
                      <td>
                        <Amount value={row.goods_total} />
                      </td>
                      <td>
                        <Amount value={row.cash} />
                      </td>
                      <td>
                        <Amount value={row.card} />
                      </td>
                      <td>
                        <Amount value={row.debt_collected} />
                      </td>
                      <td>
                        <Amount value={row.period_inflow} />
                      </td>
                      <td>
                        <Amount value={row.donation} />
                      </td>
                      <td>
                        <Amount value={row.debt_created} />
                      </td>
                      <td>
                        <Amount value={row.debt_outstanding} />
                      </td>
                      <td>
                        <Amount value={row.expenses} />
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </section>
            <section className="panel section-gap">
              <div className="panel-head">
                <h2>Eng ko‘p sotilgan mahsulotlar</h2>
                <span>Mahsulot qiymati bo‘yicha · eng ko‘pi 20 ta</span>
              </div>
              {!data.products.length ? (
                <Empty title="Bu davrda sotilgan mahsulot yo‘q" />
              ) : (
                <Table headers={['Mahsulot', 'SKU', 'Sotilgan kilogramm', 'Mahsulot savdosi']}>
                  {data.products.slice(0, 20).map((row) => (
                    <tr key={row.product_id}>
                      <td>{row.name}</td>
                      <td>{row.sku}</td>
                      <td>{kgFmt(row.kg)} kg</td>
                      <td>
                        <Amount value={row.total} />
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
            </section>
          </>
        ))}
    </div>
  );
}
