// Admin o‘z filialini, boshliq tanlangan yoki barcha filiallarning xarajatini ko‘radi.
import React, { useEffect, useState } from 'react';
import { Plus, RefreshCw } from 'lucide-react';
import { api, query } from '../api';
import { Amount, Badge, Empty, Pager, dateFmt } from '../components';
import { useData, DataState, PageActions, Table } from './shared';
import { ExpenseModal } from '../ExpenseModal';

export function Expenses({ user, branch, branches, notify }) {
  const [modal, setModal] = useState(false),
    [offset, setOffset] = useState(0);
  const [branchOffset, setBranchOffset] = useState(0);
  useEffect(() => {
    setOffset(0);
    setBranchOffset(0);
  }, [branch]);
  const [data, reload, error] = useData(
    async () => {
      const [expenses, dashboard] = await Promise.all([
        api('/expenses' + query({ branch_id: branch, offset, limit: 20 })),
        api('/dashboard' + query({ branch_id: branch })),
      ]);
      return { expenses, dashboard };
    },
    [branch, offset],
    notify,
    { keepPreviousData: true, dataScope: branch },
  );
  if (!data) return <DataState error={error} reload={reload} />;
  const branchPageOffset = Math.min(branchOffset, Math.max(0, Math.ceil(data.dashboard.branches.length / 20) - 1) * 20);
  const branchPage = data.dashboard.branches.slice(branchPageOffset, branchPageOffset + 20);
  return (
    <>
      <PageActions>
        <button className="secondary" onClick={reload}>
          <RefreshCw size={16} />
          Yangilash
        </button>
        <button className="primary" onClick={() => setModal(true)}>
          <Plus size={18} />
          Xarajat kiritish
        </button>
      </PageActions>
      {error && <p className="error">Yangilash amalga oshmadi: {error}</p>}
      <section className="panel">
        <div className="panel-head">
          <h2>Filiallar hisoblari</h2>
        </div>
        <Table headers={['Filial', 'Naqd qoldiq', 'Karta qoldiq', 'Jami xarajat']}>
          {branchPage.map((b) => (
            <tr key={b.id}>
              <td>{b.name}</td>
              <td>
                <Amount value={b.cash} />
              </td>
              <td>
                <Amount value={b.card} />
              </td>
              <td>
                <Amount value={b.branch_expenses} />
              </td>
            </tr>
          ))}
        </Table>
        <Pager offset={branchPageOffset} setOffset={setBranchOffset} count={branchPage.length}
          pageSize={20} total={data.dashboard.branches.length} />
      </section>
      <section className="panel section-gap">
        <div className="panel-head">
          <div>
            <h2>Xarajatlar tarixi</h2>
            <p>
              {data.expenses.count} ta · <Amount value={data.expenses.amount} />
            </p>
          </div>
        </div>
        <Table headers={['Filial / raqam', 'Summa', 'Hisob', 'Ta’minotchi', 'Xodim', 'Vaqt']}>
          {data.expenses.items.map((e) => (
            <React.Fragment key={e.id}>
              <tr>
                <td>
                  {branches.find((b) => b.id === e.branch_id)?.name}
                  <small>#{e.id}</small>
                </td>
                <td>
                  <Amount value={e.amount} />
                </td>
                <td>
                  <Badge>{e.method === 'cash' ? 'Naqd' : 'Karta'}</Badge>
                </td>
                <td>{e.supplier}</td>

                <td>{e.actor}</td>
                <td>{dateFmt(e.created_at)}</td>
              </tr>
              <tr className="table-note-row">
                <td colSpan={6}>
                  <strong>Sabab:</strong> {e.reason || '—'}
                </td>
              </tr>
            </React.Fragment>
          ))}
        </Table>
        {!data.expenses.items.length && <Empty title="Hali xarajat kiritilmagan" />}
        <Pager offset={offset} setOffset={setOffset} count={data.expenses.items.length}
          pageSize={20} total={data.expenses.count} pageToken={data.expenses} />
      </section>
      {modal && (
        <ExpenseModal
          user={user}
          branch={branch}
          branches={branches}
          notify={notify}
          onClose={() => setModal(false)}
          onSaved={reload}
        />
      )}
    </>
  );
}
