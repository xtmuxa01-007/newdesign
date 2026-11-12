import { decimal, safeCents, scaled } from './money.js';

export function debtPayments(debt) {
  return Array.isArray(debt.payments) ? debt.payments : debt.payment ? [debt.payment] : [];
}

export function paymentCancelled(payment) {
  return !!(payment.cancelled || payment.operation?.cancelled);
}

export function debtAmounts(debt) {
  const original = safeCents(debt.amount);
  const paid =
    debt.paid_amount !== undefined
      ? safeCents(debt.paid_amount)
      : debtPayments(debt)
          .filter((payment) => !paymentCancelled(payment))
          .reduce((sum, payment) => sum + safeCents(payment.cash) + safeCents(payment.card), 0n);
  const remaining =
    debt.remaining_amount !== undefined ? safeCents(debt.remaining_amount) : original - paid;
  return { original: decimal(original), paid: decimal(paid), remaining: decimal(remaining) };
}

export function tashkentToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: 'Asia/Tashkent',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const value = (name) => parts.find((part) => part.type === name).value;
  return `${value('year')}-${value('month')}-${value('day')}`;
}

export function paymentValidation({
  cash,
  card,
  remaining,
  nextDueDate = '',
  today = tashkentToday(),
}) {
  let total;
  try {
    total = scaled(cash || '0', 2) + scaled(card || '0', 2);
  } catch {
    return 'Naqd va karta summalarini to‘g‘ri kiriting.';
  }
  const balance = safeCents(remaining);
  if (total <= 0n) return 'Qabul qilingan pul summasini kiriting.';
  if (total > balance) return 'To‘lov qolgan qarzdan oshmasligi kerak.';
  if (nextDueDate && total === balance) return 'Qarz to‘liq yopilganda yangi muddat kerak emas.';
  if (nextDueDate && nextDueDate < today) return 'Yangi muddat bugungi sanadan oldin bo‘lmasin.';
  return '';
}
