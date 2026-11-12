// Ta’minotchi haqi va amalda berilgan to‘lovlar tarixi.
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
import { SupplierExpenses } from './SupplierExpenses';
import { OtherPayments } from './OtherPayments';
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

export function Suppliers({ branch, branches, notify, user }) {
  const [offset, setOffset] = useState(0);
  const [supplierOffset, setSupplierOffset] = useState(0);
  useEffect(() => {
    setOffset(0);
    setSupplierOffset(0);
  }, [branch]);
  const [otherOpen, setOtherOpen] = useState(false);
  const [data, reload, error] = useData(
    async () => {
      const [suppliers, payments] = await Promise.all([
        api('/suppliers' + query({ branch_id: branch })),
        api('/payments' + query({ branch_id: branch, offset, suppliers_limit: 20 })),
      ]);
      return { suppliers, payments };
    },
    [branch, offset],
    notify,
    { keepPreviousData: true, dataScope: branch },
  );
  const [modal, setModal] = useState(null),
    [busy, setBusy] = useState(false),
    [search, setSearch] = useState('');
  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await post('/suppliers', Object.fromEntries(new FormData(e.currentTarget)));
      setModal(null);
      await reload();
      notify('Ta’minotchi qo‘shildi.');
    } catch (e) {
      notify(e.message, true);
    } finally {
      setBusy(false);
    }
  }
  if (!data) return <DataState error={error} reload={reload} />;
  const filteredSuppliers = data.suppliers.filter((s) => s.name.toLowerCase().includes(search.toLowerCase()));
  const supplierPageOffset = Math.min(supplierOffset, Math.max(0, Math.ceil(filteredSuppliers.length / 5) - 1) * 5);
  const supplierPage = filteredSuppliers.slice(supplierPageOffset, supplierPageOffset + 5);
  const totals = data.suppliers.reduce(
    (n, s) => ({
      debt: n.debt + Number(s.debt),
      paid: n.paid + Number(s.paid),
      earned: n.earned + Number(s.earned),
      expenses: n.expenses + Number(s.expenses || 0),
    }),
    { debt: 0, paid: 0, earned: 0, expenses: 0 },
  );
  return (
    <>
      <PageActions>
        <button className="secondary" onClick={() => setOtherOpen(true)}>
          <Banknote size={18} />
          Boshqa pullar
        </button>
        <button className="primary" onClick={() => setModal('new')}>
          <Plus size={18} />
          Ta’minotchi qo‘shish
        </button>
      </PageActions>
      <div className="metrics">
        <Metric
          label="Ta’minotchilarning qolgan haqi"
          value={totals.debt}
          icon={Truck}
          note="Hali egalariga berilmagan"
          accent
        />
        <Metric
          label="Ta’minotchilarga berilgan pul"
          value={totals.paid}
          icon={Banknote}
          note="Egalariga berilgan to‘lovlar"
        />
        <Metric
          label="Xarajatlar"
          value={totals.expenses}
          icon={Warehouse}
          note="Ta’minotchilar hisobidan filialga sarflangan"
        />
        <Metric
          label="Jami sotilgan mahsulot"
          value={totals.earned}
          icon={ShoppingBag}
          note="Chegirmadan keyin, ehsonsiz"
        />
      </div>
      <section className="panel">
        <div className="filter-row">
          <label className="search">
            <Search size={18} />
            <input
              aria-label="Ta’minotchini qidirish"
              placeholder="Ta’minotchini qidirish…"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setSupplierOffset(0); }}
            />
          </label>
        </div>
        {filteredSuppliers.length ? (
          <Table
            headers={[
              'Ta’minotchi',
              'Telefon',
              'Sotilgan summa',
              'Mini chegirma',
              'Filial xarajatlari',
              'Ta’minotchiga berilgan',
              'Qolgan haq',
              'Amal',
            ]}
          >
            {supplierPage.map((s) => (
                <tr key={s.id}>
                  <td>
                    <strong>{s.name}</strong>
                    <small>{s.note}</small>
                  </td>
                  <td>{s.phone || '—'}</td>
                  <td>
                    <Amount value={s.earned} />
                  </td>
                  <td>
                    <Amount value={s.mini_discount || 0} />
                  </td>
                  <td>
                    <Amount value={s.expenses || 0} />
                  </td>
                  <td>
                    <Amount value={s.paid} />
                  </td>
                  <td className="number">
                    <Amount value={s.debt} />
                  </td>
                  <td>
                    <button
                      className="secondary compact"
                      disabled={Number(s.debt) <= 0}
                      onClick={() => setModal(s)}
                    >
                      Pul berish
                      <ArrowUpRight size={15} />
                    </button>
                  </td>
                </tr>
              ))}
          </Table>
        ) : (
          <Empty
            title={search ? 'Ta’minotchi topilmadi' : 'Birinchi ta’minotchini qo‘shing'}
            text={search ? 'Qidiruv matnini o‘zgartirib ko‘ring.' : 'Mahsulotlar ta’minotchiga bog‘lanadi va sotuvdan uning haqi hisoblanadi.'}
          />
        )}
        <Pager offset={supplierPageOffset} setOffset={setSupplierOffset} count={supplierPage.length}
          pageSize={5} total={filteredSuppliers.length} />
      </section>
      <section className="panel section-gap">
        <div className="panel-head">
          <div>
            <h2>Ta’minotchilarga berilgan pullar tarixi</h2>
            <p>Kimga, qachon va qancha pul berilgan</p>
          </div>
        </div>
        <PaymentTable
          entries={data.payments.suppliers}
          branches={branches}
          suppliers={data.suppliers}
        />
        <Pager offset={offset} setOffset={setOffset} count={data.payments.suppliers.length}
          pageSize={20} total={data.payments.suppliers_count} pageToken={data.payments} />
      </section>
      <OtherPayments branch={branch} branches={branches} user={user} notify={notify}
        open={otherOpen} onOpen={() => setOtherOpen(true)} onClose={() => setOtherOpen(false)} />
      <SupplierExpenses branch={branch} branches={branches} notify={notify} />
      {modal === 'new' && (
        <Modal title="Yangi ta’minotchi" onClose={() => setModal(null)} busy={busy}>
          <form onSubmit={submit}>
            <Field label="Ta’minotchi nomi">
              <input name="name" required maxLength={120} />
            </Field>
            <Field label="Telefon">
              <input name="phone" type="tel" maxLength={60} placeholder="+998" />
            </Field>
            <Field label="Izoh">
              <textarea name="note" maxLength={500} />
            </Field>
            <FormFooter busy={busy} onClose={() => setModal(null)} />
          </form>
        </Modal>
      )}
      {modal && modal !== 'new' && (
        <PaymentModal
          user={user}
          supplier={modal}
          branch={branch}
          branches={branches}
          onClose={() => setModal(null)}
          notify={notify}
          reload={reload}
        />
      )}
    </>
  );
}
