// Pul hisobida binary float ishlatilmaydi. Backend ham xuddi shunday yaxlitlaydi.
export function scaled(value, digits) {
  const s = String(value ?? '')
    .trim()
    .replace(',', '.');
  if (!new RegExp(`^\\d+(\\.\\d{0,${digits}})?$`).test(s)) throw new Error('Son noto‘g‘ri');
  const [whole, fraction = ''] = s.split('.');
  return BigInt(whole) * 10n ** BigInt(digits) + BigInt(fraction.padEnd(digits, '0') || '0');
}
export function decimal(value, digits = 2) {
  const sign = value < 0n ? '-' : '';
  const s = (value < 0n ? -value : value).toString().padStart(digits + 1, '0');
  return sign + s.slice(0, -digits) + '.' + s.slice(-digits);
}
export function lineCents(kg, price, discount) {
  const numerator = scaled(kg, 3) * scaled(price, 2) * (10000n - scaled(discount || '0', 2));
  return (numerator + 5000000n) / 10000000n;
}
export function safeCents(value) {
  try {
    return scaled(value || '0', 2);
  } catch {
    return 0n;
  }
}
export const fmt = (value) =>
  new Intl.NumberFormat('uz-UZ', { maximumFractionDigits: 2 }).format(Number(value || 0));
export const kgFmt = (value) =>
  new Intl.NumberFormat('uz-UZ', { maximumFractionDigits: 3 }).format(Number(value || 0));
