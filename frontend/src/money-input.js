// Tahrir paytida pul matnini aniq decimal sifatida saqlaydi; Number yaxlitlash ishlatilmaydi.
const GROUP_SPACE = /[\s\u00a0\u202f]/g;

export function parseMoneyText(text) {
  let raw = String(text ?? '')
    .replace(GROUP_SPACE, '')
    .replace(',', '.');
  if (!/^\d*(?:\.\d{0,2})?$/.test(raw)) return null;
  if (raw.startsWith('.')) raw = '0' + raw;
  return raw.replace(/^0+(?=\d)/, '');
}

export function formatMoneyText(value) {
  const raw = parseMoneyText(value);
  if (raw === null || raw === '') return raw ?? '';
  const [whole, fraction] = raw.split('.');
  return (
    whole.replace(/\B(?=(\d{3})+(?!\d))/g, ' ') + (fraction === undefined ? '' : '.' + fraction)
  );
}

export function moneyCaret(text, position) {
  const compact = String(text).replace(GROUP_SPACE, '').replace(',', '.');
  const before = String(text).slice(0, position).replace(GROUP_SPACE, '').length;
  const removed = compact.match(/^0+(?=\d)/)?.[0].length || 0;
  return Math.max(0, before - removed) + (compact.startsWith('.') && before > 0 ? 1 : 0);
}

export function displayCaret(formatted, rawPosition) {
  if (rawPosition <= 0) return 0;
  let seen = 0;
  for (let i = 0; i < formatted.length; i++) {
    if (formatted[i] !== ' ') seen++;
    if (seen >= rawPosition) return i + 1;
  }
  return formatted.length;
}

export function moneyEdit(text, selectionStart, selectionEnd = selectionStart) {
  const raw = parseMoneyText(text);
  if (raw === null) return null;
  const formatted = formatMoneyText(raw);
  return {
    raw,
    formatted,
    start: displayCaret(formatted, moneyCaret(text, selectionStart)),
    end: displayCaret(formatted, moneyCaret(text, selectionEnd)),
  };
}

// Ajratuvchi bo'shliqni o'chirish tugmasi pul raqamini o'chirsin, bo'shliqni qayta qo'ymasin.
export function deleteMoneyGroup(text, position, direction) {
  const index = direction === 'backward' ? position - 1 : position;
  if (text[index] !== ' ') return null;
  const digit = direction === 'backward' ? index - 1 : index + 1;
  if (!/\d/.test(text[digit] ?? '')) return null;
  const updated = text.slice(0, digit) + text.slice(digit + 1);
  const cursor = direction === 'backward' ? digit : position;
  return moneyEdit(updated, cursor);
}

export function moneyFormValue(raw) {
  return parseMoneyText(raw)?.replace(/\.$/, '') ?? '';
}

export function zeroAsEmpty(value) {
  const raw = parseMoneyText(value);
  return raw !== null && /^0*(?:\.0*)?$/.test(raw) ? '' : (raw ?? '');
}

function cents(raw) {
  const [whole, fraction = ''] = raw.split('.');
  return BigInt(whole || '0') * 100n + BigInt(fraction.padEnd(2, '0') || '0');
}

export function moneyValidation(raw, { required = false, min, max, step = '0.01' } = {}) {
  const parsed = parseMoneyText(raw);
  if (parsed === null) return 'Pul miqdorini kiriting. Ko‘pi bilan 2 ta kasr raqami bo‘lsin.';
  if (parsed === '') return required ? 'Pul miqdorini kiriting.' : '';
  const value = cents(parsed);
  if (min !== undefined && value < cents(parseMoneyText(min)))
    return `Eng kam miqdor: ${formatMoneyText(min)} so‘m.`;
  if (max !== undefined && value > cents(parseMoneyText(max)))
    return `Eng ko‘p miqdor: ${formatMoneyText(max)} so‘m.`;
  if (step !== 'any') {
    const increment = cents(parseMoneyText(step));
    const base = min === undefined ? 0n : cents(parseMoneyText(min));
    if (increment > 0n && (value - base) % increment !== 0n)
      return `Miqdorni ${formatMoneyText(step)} so‘m aniqlikda kiriting.`;
  }
  return '';
}
