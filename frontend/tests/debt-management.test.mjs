import test from 'node:test';
import assert from 'node:assert/strict';
import {
  debtAmounts,
  debtPayments,
  paymentValidation,
  tashkentToday,
} from '../src/debt-management.js';

test('legacy settlements and installment cancellation keep exact outstanding balances', () => {
  assert.deepEqual(debtAmounts({ amount: '100.01', payment: { cash: '50.00', card: '50.01' } }), {
    original: '100.01',
    paid: '100.01',
    remaining: '0.00',
  });
  const debt = {
    amount: '1000000000000000.05',
    payments: [
      { cash: '1000000000000000', card: '0.01' },
      { cash: '0.02', card: '0', operation: { cancelled: true } },
    ],
  };
  assert.equal(debtAmounts(debt).remaining, '0.04');
  assert.equal(debtPayments(debt).length, 2);
  assert.equal(debtPayments({ amount: '10' }).length, 0);
  assert.equal(
    debtAmounts({ amount: '50', paid_amount: '20', remaining_amount: '30' }).paid,
    '20.00',
  );
});

test('early and partial payments permit real receipts, rejecting zero and overpayment', () => {
  const base = { remaining: '100.03', today: '2026-10-13' };
  assert.equal(
    paymentValidation({ ...base, cash: '50', card: '.03' }),
    'Naqd va karta summalarini to‘g‘ri kiriting.',
  );
  assert.equal(
    paymentValidation({ ...base, cash: '50', card: '0.03', nextDueDate: '2026-10-13' }),
    '',
  );
  assert.equal(paymentValidation({ ...base, cash: '100.03', card: '' }), '');
  assert.notEqual(paymentValidation({ ...base, cash: '100.04', card: '' }), '');
  assert.notEqual(paymentValidation({ ...base, cash: '', card: '' }), '');
  assert.notEqual(paymentValidation({ ...base, cash: '-1', card: '50' }), '');
  assert.notEqual(
    paymentValidation({ ...base, cash: '1', card: '', nextDueDate: '2026-10-12' }),
    '',
  );
  assert.notEqual(
    paymentValidation({ ...base, cash: '100.03', card: '', nextDueDate: '2026-10-14' }),
    '',
  );
});

test('debt deadlines use Tashkent day even around midnight UTC', () => {
  assert.equal(tashkentToday(new Date('2026-10-12T18:59:59Z')), '2026-10-12');
  assert.equal(tashkentToday(new Date('2026-10-12T19:00:00Z')), '2026-10-13');
});
