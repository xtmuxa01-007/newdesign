import test from 'node:test';
import assert from 'node:assert/strict';
import { miniAppTabs } from '../src/miniapp-navigation.js';

test('boss and admin get the four primary Mini App sections', () => {
  for (const role of ['boss', 'admin']) {
    assert.deepEqual(
      miniAppTabs(role).map((tab) => tab.id),
      ['dashboard', 'pos', 'suppliers', 'settings'],
    );
  }
});

test('cashier tabs retain its existing permissions and unknown roles get no sections', () => {
  assert.deepEqual(
    miniAppTabs('cashier').map((tab) => tab.id),
    ['pos', 'debts', 'settings'],
  );
  for (const role of [undefined, null, '', 'unknown']) assert.deepEqual(miniAppTabs(role), []);
});
