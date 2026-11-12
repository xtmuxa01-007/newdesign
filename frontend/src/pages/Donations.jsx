// Savdodagi ortiqcha tushum va ehson to‘lovlari.
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
} from 'lucide-react';
import { api, post, query } from '../api';
import { requestId } from '../id';
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
  Metric,
  BranchField,
  Table,
  SaleRows,
  PaymentModal,
  PaymentTable,
} from './shared';

export function Donations({ branch, branches, notify, user }) {
  const [modal, setModal] = useState(false),
    [offset, setOffset] = useState(0);
  const [miniOffset, setMiniOffset] = useState(0);
  useEffect(() => {
    setOffset(0);
    setMiniOffset(0);
  }, [branch]);
  const [data, reload, error] = useData(
    async () => {
      const [dashboard, payments, minis] = await Promise.all([
        api('/dashboard' + query({ branch_id: branch })),
        api('/payments' + query({ branch_id: branch, offset, donations_limit: 20 })),
        api('/mini-discounts' + query({ branch_id: branch, offset: miniOffset, limit: 20 })),
      ]);
      return { ...dashboard, payments, minis };
    },
    [branch, offset, miniOffset],
    notify,
    { keepPreviousData: true, dataScope: branch },
  );
  if (!data) return <DataState error={error} reload={reload} />;
  return (
    <>
      <PageActions>
        <button className="secondary" onClick={reload}>
          <RefreshCw size={16} />
          Yangilash
        </button>
        <button
          className="primary"
          disabled={Number(data.donation_balance) <= 0}
          onClick={() => setModal(true)}
        >
          <HeartHandshake size={18} />
          Ehson puli berish
        </button>
      </PageActions>
      <div className="metrics">
        <Metric
          label="Ehson qoldig‘i"
          value={data.donation_balance}
          icon={HeartHandshake}
          note="Hozir berish mumkin bo‘lgan mablag‘"
          accent
        />
        <Metric
          label="Jami yig‘ilgan ehson"
          value={data.donation_received}
          icon={Plus}
          note="Savdolardagi ortiqcha tushumlar"
        />
        <Metric
          label="Jami berilgan ehson"
          value={data.donation_paid}
          icon={ArrowUpRight}
          note="Qabul qiluvchilarga berilgan"
        />
        <Metric
          label="Mini chegirmalar"
          value={data.minis.amount}
          icon={Percent}
          note={`${data.minis.count} ta savdo · har birida ko‘pi bilan 5 000 so‘m`}
        />
      </div>
      <div className="donation-explainer">
        <HeartHandshake size={28} />
        <div>
          <h3>Ezgu niyat, aniq hisob</h3>
          <p>
            13 800 so‘mlik savdo uchun 14 000 so‘m olinsa, 200 so‘m ehson hisobiga yoziladi.
            Ta’minotchining haqi 13 800 so‘m bo‘lib qoladi. Mini chegirmalar esa ta’minotchilarning
            haqidan ayriladi va ehson qoldig‘ini kamaytirmaydi.
          </p>
        </div>
      </div>
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Mini chegirmalar</h2>
            <p>Savdo raqami, chegirma summasi va uni bergan xodim</p>
          </div>
        </div>
        <Table
          headers={[
            'Savdo',
            'Filial',
            'Chegirmadan oldin',
            'Mini chegirma',
            'Ta’minotchidan ayrildi',
            'Naqd / karta',
            'Xodim',
            'Vaqt',
          ]}
        >
          {data.minis.items.map((m) => (
            <tr key={m.id}>
              <td>#{m.sale_id}</td>
              <td>{branches.find((b) => b.id === m.branch_id)?.name}</td>
              <td>
                <Amount value={m.original_total} />
              </td>
              <td>
                <Amount value={m.amount} />
              </td>
              <td>
                {m.shares.map((s) => (
                  <small key={s.id}>
                    {s.supplier}: {fmt(s.amount)} so‘m
                  </small>
                ))}
              </td>
              <td>
                {fmt(m.cash)} / {fmt(m.card)}
              </td>
              <td>{m.actor}</td>
              <td>{dateFmt(m.created_at)}</td>
            </tr>
          ))}
        </Table>
        {!data.minis.items.length && <Empty title="Mini chegirmalar hali yo‘q" />}
        <Pager offset={miniOffset} setOffset={setMiniOffset} count={data.minis.items.length}
          pageSize={20} total={data.minis.count} pageToken={data.minis} />
      </section>
      <section className="panel section-gap">
        <div className="panel-head">
          <div>
            <h2>Ehson to‘lovlari tarixi</h2>
            <p>Qabul qiluvchi, summa va mas’ul xodim</p>
          </div>
        </div>
        <PaymentTable entries={data.payments.donations} branches={branches} />
        <Pager offset={offset} setOffset={setOffset} count={data.payments.donations.length}
          pageSize={20} total={data.payments.donations_count} pageToken={data.payments} />
      </section>
      {modal && (
        <PaymentModal
          user={user}
          branch={branch}
          branches={branches}
          onClose={() => setModal(false)}
          reload={reload}
          notify={notify}
        />
      )}
    </>
  );
}
