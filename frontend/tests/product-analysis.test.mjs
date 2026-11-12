import test from 'node:test';
import assert from 'node:assert/strict';
import { productChartBuckets, stockAdjustmentPreview } from '../src/product-analysis.js';

test('revision preview uses exact grams for increases, decreases and zero stock', () => {
  assert.deepEqual(stockAdjustmentPreview('88.011', '86,761'), {
    kg: '86.761',
    difference: '-1.250',
    changed: true,
  });
  assert.deepEqual(stockAdjustmentPreview('88.011', '89.012'), {
    kg: '89.012',
    difference: '1.001',
    changed: true,
  });
  assert.deepEqual(stockAdjustmentPreview('0.001', '0'), {
    kg: '0.000',
    difference: '-0.001',
    changed: true,
  });
  assert.deepEqual(stockAdjustmentPreview('88.011', '088.011'), {
    kg: '88.011',
    difference: '0.000',
    changed: false,
  });
});

test('revision preview rejects invalid precision, negative and oversized quantities', () => {
  for (const value of ['', '-1', '1.0001', '1e3', 'no', '100000000000']) {
    assert.equal(stockAdjustmentPreview('88.011', value), null, value);
  }
  assert.deepEqual(stockAdjustmentPreview('99999999999.998', '99999999999.999'), {
    kg: '99999999999.999',
    difference: '0.001',
    changed: true,
  });
});

test('long product charts preserve every decimal amount and kilogram without dropping days', () => {
  const rows = [
    { date: '2026-10-01', total: '1000000000000000.01', kg: '0.001', sales_count: 1 },
    { date: '2026-10-02', total: '0.02', kg: '0.002', sales_count: 2 },
    { date: '2026-10-03', total: '0.03', kg: '0.003', sales_count: 3 },
    { date: '2026-10-31', total: '0.04', kg: '0.004', sales_count: 4 },
  ];
  assert.deepEqual(productChartBuckets(rows, 2), [
    {
      start: '2026-10-01',
      end: '2026-10-02',
      total: '1000000000000000.03',
      kg: '0.003',
      sales_count: 3,
    },
    { start: '2026-10-03', end: '2026-10-31', total: '0.07', kg: '0.007', sales_count: 7 },
  ]);
  assert.deepEqual(productChartBuckets([]), []);
});

test('zero days stay on the product chart and short periods keep daily labels', () => {
  assert.deepEqual(
    productChartBuckets([
      { date: '2026-10-20', total: '0', kg: '0', sales_count: 0 },
      { date: '2026-10-21', total: '10.25', kg: '1.125', sales_count: 1 },
    ]),
    [
      { start: '2026-10-20', end: '2026-10-20', total: '0.00', kg: '0.000', sales_count: 0 },
      { start: '2026-10-21', end: '2026-10-21', total: '10.25', kg: '1.125', sales_count: 1 },
    ],
  );
});
