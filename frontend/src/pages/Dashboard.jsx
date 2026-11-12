// Boshliq uchun filiallar va moliyaviy holat ko‘rinishi.
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
  WalletCards,
} from 'lucide-react';
import { api, post, query } from '../api';
import { requestId } from '../id';
import { BranchCarousel } from '../BranchCarousel';
import { isTelegramEntry } from '../telegram';
import { uzDate } from '../dates';
import { fmt, kgFmt, lineCents, decimal } from '../money';
import {
  Amount,
  Badge,
  Empty,
  Field,
  FormFooter,
  Loading,
  Modal,
  Pager,
  ProductImage,
  dateFmt,
} from '../components';

import {
  useData,
  DataState,
  PageActions,
  BranchField,
  Table,
  SaleRows,
  PaymentModal,
  PaymentTable,
} from './shared';
import './dashboard-revenue.css';
import '../emerald-dashboard.css';
import { CardSurface, DashboardMetric } from '../DashboardSurface';

export function Dashboard({ branch, branches, notify, setPage, user }) {
  const [today, setToday] = useState(() => uzDate(new Date(), false, true));
  const [data, reload, error] = useData(
    () => api('/dashboard' + query({ branch_id: branch })),
    [branch],
    notify,
  );
  useEffect(() => {
    // Sahifa ochiq qolsa ham sana Toshkentdagi yangi kunga o'tadi.
    const refresh = () => {
      setToday(uzDate(new Date(), false, true));
      reload();
    };
    const timer = setInterval(refresh, 30000);
    window.addEventListener('focus', refresh);
    return () => {
      clearInterval(timer);
      window.removeEventListener('focus', refresh);
    };
  }, [reload]);
  if (!data) return <DataState error={error} reload={reload} />;
  return (
    <div className="dashboard-overview">
      {isTelegramEntry() && user?.role === 'boss' && (
        <section className="panel dashboard-revenue" aria-labelledby="branch-revenue-title">
          <div className="dashboard-revenue-heading">
            <div>
              <h2 id="branch-revenue-title">Qaysi filial qancha pul tushirdi?</h2>
            </div>
            <span className="dashboard-revenue-date">{today} · Toshkent vaqti</span>
          </div>
          {data.branches.length ? (
            <div className="dashboard-revenue-grid">
              {data.branches.map((item) => (
                <article className="dashboard-revenue-card" key={item.id}>
                  <div className="dashboard-revenue-card-heading">
                    <h3>{item.name}</h3>
                    {item.archived && <Badge tone="gray">Arxiv</Badge>}
                  </div>
                  <span className="dashboard-revenue-label">Bugungi tushum</span>
                  <strong className="dashboard-revenue-amount">
                    <Amount value={item.today_inflow} />
                  </strong>
                  <div className="dashboard-revenue-month">
                    <span>Shu oy</span>
                    <strong>
                      <Amount value={item.month_inflow} />
                    </strong>
                  </div>
                </article>
              ))}
            </div>
          ) : (
            <Empty
              title="Filiallar topilmadi"
              text="Filiallar yaratilgach tushumlar shu yerda ko‘rinadi."
            />
          )}
          <div className="dashboard-revenue-footer">
            <small>
              Tushum kassa qoldig‘i yoki sof foyda emas. Xarajatlar alohida hisoblanadi.
            </small>
            <button type="button" className="text-btn" onClick={() => setPage('analytics')}>
              Tahlilni ochish <ChevronRight size={16} />
            </button>
          </div>
        </section>
      )}
      {isTelegramEntry() && (
        <PageActions>
          <button className="secondary" onClick={reload}>
            <RefreshCw size={16} />
            Yangilash
          </button>
          <button className="primary" onClick={() => setPage('pos')}>
            <Plus size={18} />
            Yangi savdo
          </button>
        </PageActions>
      )}
      {error && (
        <p className="error">
          Yangilash amalga oshmadi. Oxirgi yuklangan ma’lumotlar ko‘rsatilmoqda.
        </p>
      )}
      <div className="stats-grid">
        <DashboardMetric label="Bugungi savdo" value={data.today} icon={ShoppingBag} note={today} />
        <DashboardMetric
          label="Shu oydagi savdo"
          value={data.month}
          icon={Banknote}
          note="Oyning boshidan bugungacha"
        />
        <DashboardMetric
          variant="stat-card--cash"
          label="Kassadagi pullar"
          value={Number(data.cash) + Number(data.card)}
          icon={CreditCard}
          note={`Naqd: ${fmt(data.cash)} so‘m · Karta: ${fmt(data.card)} so‘m`}
        />
        <DashboardMetric
          variant="stat-card--stock"
          label="Ombordagi mahsulotlar"
          value={data.inventory_kg}
          icon={Warehouse}
          note={`${data.active_products} ta mahsulot qoldig‘i · arxiv bilan`}
          weight
        />
      </div>
      <div className="dashboard-middle">
        <section className="panel">
          <div className="panel-head">
            <div>
              <h2>Filiallar holati</h2>
              <p>Ombor va kassalar bo‘yicha joriy hisob</p>
            </div>
            <Badge>{data.branches.length} ta filial</Badge>
          </div>
          <BranchCarousel>
            {data.branches.map((b) => (
              <div className="branch-card emerald-card" key={b.id}>
                <CardSurface />
                <div className="branch-card-title">
                  <span className="tile-icon">
                    <Warehouse size={20} />
                  </span>
                  <h3>{b.name}</h3>
                  <Badge tone={b.archived ? 'gray' : 'green'}>
                    {b.archived ? 'Arxiv' : 'Faol'}
                  </Badge>
                </div>
                <dl>
                  {b.device_linked && (
                    <div>
                      <dt>Oxirgi kelgan ma’lumot</dt>
                      <dd>
                        {b.last_received_at ? dateFmt(b.last_received_at) : 'Hali yuborilmagan'}
                      </dd>
                    </div>
                  )}
                  <div>
                    <dt>Kassadagi jami pul</dt>
                    <dd>
                      <Amount value={Number(b.cash) + Number(b.card)} />
                    </dd>
                  </div>
                  <div>
                    <dt>Mijozlardan olinadigan qarz</dt>
                    <dd>
                      <Amount value={b.customer_debt || 0} />
                    </dd>
                  </div>
                  <div>
                    <dt>Bugungi savdo</dt>
                    <dd>
                      <Amount value={b.today} />
                    </dd>
                  </div>
                  <div>
                    <dt>Ombor qoldig‘i</dt>
                    <dd>{kgFmt(b.kg)} kg</dd>
                  </div>
                  <div>
                    <dt>Ombor qiymati</dt>
                    <dd>
                      <Amount value={b.inventory} />
                    </dd>
                  </div>
                  <div>
                    <dt>Naqd pul</dt>
                    <dd>
                      <Amount value={b.cash} />
                    </dd>
                  </div>
                  <div>
                    <dt>Kartadagi pul</dt>
                    <dd>
                      <Amount value={b.card} />
                    </dd>
                  </div>
                </dl>
              </div>
            ))}
          </BranchCarousel>
        </section>
        <section className="account-summary emerald-card">
          <CardSurface />
          <span className="account-summary-symbol" aria-hidden="true">
            <WalletCards size={22} />
          </span>
          <span className="eyebrow">HISOBLAR</span>
          <h2>Mablag‘lar taqsimoti</h2>
          <div>
            <span>
              <Truck size={18} />
              Ta’minotchilar haqi
            </span>
            <strong>
              <Amount value={data.supplier_debt} />
            </strong>
            <small>Sotilgan mahsulotlar uchun to‘lanmagan haq</small>
          </div>
          <div>
            <span>
              <HeartHandshake size={18} />
              Ehson qoldig‘i
            </span>
            <strong>
              <Amount value={data.donation_balance} />
            </strong>
            <small>Alohida hisobdagi ortiqcha to‘lovlar</small>
          </div>
          <button className="text-btn" onClick={() => setPage('suppliers')}>
            Hisoblarni ko‘rish
            <ArrowUpRight size={16} />
          </button>
        </section>
      </div>
      <section className="panel recent-sales-panel">
        <div className="panel-head">
          <div>
            <h2>So‘nggi savdolar</h2>
            <p>Filiallardagi eng so‘nggi yakunlangan savdolar</p>
          </div>
          <button className="text-btn" onClick={() => setPage('reports')}>
            Barchasini ko‘rish
            <ChevronRight size={17} />
          </button>
        </div>
        {data.recent_sales.length ? (
          <Table headers={['Savdo', 'Sana va vaqt', 'Filial', 'Kassir', 'Jami olingan', 'To‘lov']}>
            <SaleRows
              sales={data.recent_sales}
              branches={branches}
              onDetail={() => setPage('reports')}
            />
          </Table>
        ) : (
          <Empty
            title="Bugungi ishni boshlang"
            text="Yakunlangan savdolar shu yerda paydo bo‘ladi."
          />
        )}
      </section>
    </div>
  );
}
