import { decimal, safeCents, scaled } from './money.js';

export function stockAdjustmentPreview(current, value) {
  try {
    const before = scaled(current, 3);
    const after = scaled(value, 3);
    if (after > 99999999999999n) return null;
    return {
      kg: decimal(after, 3),
      difference: decimal(after - before, 3),
      changed: after !== before,
    };
  } catch {
    return null;
  }
}

// Grafik davrning hamma kunlarini qamraydi; uzun davrda ustunlar guruhlanadi.
export function productChartBuckets(daily, limit = 28) {
  const size = Math.max(1, Math.ceil(daily.length / limit));
  const result = [];
  for (let offset = 0; offset < daily.length; offset += size) {
    const rows = daily.slice(offset, offset + size);
    result.push({
      start: rows[0].date,
      end: rows.at(-1).date,
      total: decimal(rows.reduce((sum, row) => sum + safeCents(row.total), 0n)),
      kg: decimal(
        rows.reduce((sum, row) => sum + scaled(row.kg || '0', 3), 0n),
        3,
      ),
      sales_count: rows.reduce((sum, row) => sum + row.sales_count, 0),
    });
  }
  return result;
}
