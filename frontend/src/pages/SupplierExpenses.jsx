// Xarajatlar egasiga berilgan puldan alohida ko'rsatiladi va alohida sahifalanadi.
import React, { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api, query } from '../api';
import { Amount, Badge, Empty, Pager, dateFmt } from '../components';
import { useData, DataState, Table } from './shared';

export function SupplierExpenses({ branch, branches, notify }) {
  const [offset, setOffset] = useState(0);
  const [data, reload, error] = useData(
    () => api('/expenses' + query({ branch_id: branch, offset })),
    [branch, offset],
    notify,
    { keepPreviousData: true, dataScope: branch },
  );
  return (
    <section className="panel section-gap">
      <div className="panel-head">
        <div>
          <h2>Barcha qilingan xarajatlar</h2>
          <p>Ta’minotchilar hisobidan filial ehtiyojlari uchun ishlatilgan pul.</p>
          {data && (
            <p>
              {data.count} ta xarajat · <Amount value={data.amount} />
            </p>
          )}
        </div>
        <button className="secondary compact" onClick={reload}>
          <RefreshCw size={16} /> Yangilash
        </button>
      </div>
      {!data ? (
        <DataState error={error} reload={reload} />
      ) : (
        <>
          {error && <p className="error">Yangilash amalga oshmadi: {error}</p>}
          <Table
            headers={['Ta’minotchi', 'Filial / raqam', 'Xarajat summasi', 'Hisob', 'Xodim', 'Vaqt']}
          >
            {data.items.map((e) => (
              <React.Fragment key={e.id}>
                <tr>
                  <td>{e.supplier}</td>
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
          {!data.items.length && <Empty title="Hali xarajat kiritilmagan" />}
          <Pager offset={offset} setOffset={setOffset} count={data.items.length} pageToken={data} />
        </>
      )}
    </section>
  );
}
