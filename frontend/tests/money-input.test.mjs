import test from 'node:test';
import assert from 'node:assert/strict';
import {
  parseMoneyText,
  formatMoneyText,
  moneyEdit,
  deleteMoneyGroup,
  moneyFormValue,
  moneyValidation,
  zeroAsEmpty,
} from '../src/money-input.js';

test('typing groups sums while keeping exact decimal state', () => {
  const displays = ['1', '10', '100', '1 000', '10 000', '100 000'];
  let raw = '';
  for (const display of displays) {
    const typed = formatMoneyText(raw) + (raw ? '0' : '1');
    const edit = moneyEdit(typed, typed.length);
    assert.equal(edit.formatted, display);
    assert.equal(edit.start, display.length);
    raw = edit.raw;
  }
  assert.equal(raw, '100000');
  assert.equal(
    formatMoneyText('123456789012345678901234567890.01'),
    '123 456 789 012 345 678 901 234 567 890.01',
  );
});

test('pasted sums accept thousand spaces and decimal comma without float conversion', () => {
  assert.equal(parseMoneyText('10 000,50'), '10000.50');
  assert.equal(parseMoneyText('10\u00a0000\u202f000.05'), '10000000.05');
  assert.equal(formatMoneyText('10000.05'), '10 000.05');
  assert.equal(parseMoneyText('.5'), '0.5');
  assert.equal(parseMoneyText('00010000.50'), '10000.50');
  for (const invalid of ['1e3', '-1', 'ten', '1.234', '10,00,00', '1.2.3', '+100'])
    assert.equal(parseMoneyText(invalid), null, invalid);
});

test('insertion into an existing sum preserves caret next to the edited digit', () => {
  // Insert 5 between 10 and 000; caret follows the inserted 5.
  const edit = moneyEdit('105 000', 3);
  assert.deepEqual(edit, { raw: '105000', formatted: '105 000', start: 3, end: 3 });
  const leadingDecimal = moneyEdit('.5', 1);
  assert.equal(leadingDecimal.formatted, '0.5');
  assert.equal(leadingDecimal.start, 2);
  const zeros = moneyEdit('00010 000', 9);
  assert.equal(zeros.formatted, '10 000');
  assert.equal(zeros.start, 6);
});

test('backspace and delete at grouping spaces remove the adjacent digit immediately', () => {
  assert.deepEqual(deleteMoneyGroup('10 000', 3, 'backward'), {
    raw: '1000',
    formatted: '1 000',
    start: 1,
    end: 1,
  });
  assert.deepEqual(deleteMoneyGroup('10 000', 2, 'forward'), {
    raw: '1000',
    formatted: '1 000',
    start: 3,
    end: 3,
  });
  assert.equal(deleteMoneyGroup('10 000', 4, 'backward'), null);
  assert.equal(deleteMoneyGroup('10 000', 0, 'backward'), null);
  const selectionReplacement = moneyEdit('1250.50', 3);
  assert.equal(selectionReplacement.formatted, '1 250.50');
  assert.equal(selectionReplacement.start, 4);
  const selection = moneyEdit('10 000.50', 1, 8);
  assert.equal(selection.start, 1);
  assert.equal(selection.end, 8);
});

test('FormData uses canonical decimal and zero defaults can remain placeholders', () => {
  assert.equal(moneyFormValue('10 000,50'), '10000.50');
  assert.equal(moneyFormValue('10000.'), '10000');
  assert.equal(moneyFormValue(''), '');
  for (const zero of [undefined, '', '0', '0.00', '00.00']) assert.equal(zeroAsEmpty(zero), '');
  assert.equal(zeroAsEmpty('10000.00'), '10000.00');
});

test('custom text input validation preserves required, decimal, min, max and step constraints', () => {
  assert.equal(moneyValidation(''), '');
  assert.notEqual(moneyValidation('', { required: true }), '');
  assert.notEqual(moneyValidation('0', { min: '0.01' }), '');
  assert.equal(moneyValidation('0.01', { min: '0.01' }), '');
  assert.equal(moneyValidation('15000.00', { min: '0.01', max: '15000' }), '');
  assert.notEqual(moneyValidation('15000.01', { min: '0.01', max: '15000' }), '');
  assert.notEqual(moneyValidation('10000.001'), '');
  assert.equal(moneyValidation('10000.15', { min: '0.05', step: '0.10' }), '');
  assert.notEqual(moneyValidation('10000.10', { min: '0.05', step: '0.10' }), '');
});
