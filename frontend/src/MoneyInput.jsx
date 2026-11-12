import React, { useLayoutEffect, useRef, useState } from 'react';
import {
  parseMoneyText,
  formatMoneyText,
  moneyEdit,
  deleteMoneyGroup,
  moneyFormValue,
  moneyValidation,
} from './money-input';

// Ko'rinadigan maydon 10 000.50; state va FormData uchun 10000.50.
export function MoneyInput({
  value,
  defaultValue = '',
  onChange,
  name,
  min = '0',
  max,
  step = '0.01',
  required = false,
  disabled = false,
  placeholder = '0',
  onKeyDown,
  onBlur,
  ...props
}) {
  const [localValue, setLocalValue] = useState(() => parseMoneyText(defaultValue) ?? '');
  const raw = value === undefined ? localValue : String(value ?? '');
  const input = useRef(null);
  const selection = useRef(null);
  useLayoutEffect(() => {
    const element = input.current;
    element.setCustomValidity(moneyValidation(raw, { min, max, step, required }));
    if (selection.current && document.activeElement === element) {
      element.setSelectionRange(selection.current.start, selection.current.end);
      selection.current = null;
    }
  });
  function apply(edit, element) {
    if (!edit) {
      element.value = formatMoneyText(raw);
      return;
    }
    selection.current = edit;
    // Qayta formatlash state o'zgarmasa ham kursorni va vergulni to'g'ri saqlaydi.
    element.value = edit.formatted;
    element.setSelectionRange(edit.start, edit.end);
    if (value === undefined) setLocalValue(edit.raw);
    onChange?.(edit.raw);
  }
  return (
    <>
      <input
        {...props}
        ref={input}
        type="text"
        inputMode="decimal"
        value={formatMoneyText(raw)}
        placeholder={placeholder}
        required={required}
        disabled={disabled}
        onChange={(event) =>
          apply(
            moneyEdit(event.target.value, event.target.selectionStart, event.target.selectionEnd),
            event.target,
          )
        }
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return;
          const element = event.currentTarget;
          if (element.selectionStart !== element.selectionEnd) return;
          if (event.key !== 'Backspace' && event.key !== 'Delete') return;
          const edit = deleteMoneyGroup(
            element.value,
            element.selectionStart,
            event.key === 'Backspace' ? 'backward' : 'forward',
          );
          if (edit) {
            event.preventDefault();
            apply(edit, element);
          }
        }}
        onBlur={(event) => {
          if (raw.endsWith('.')) apply(moneyEdit(raw.slice(0, -1), raw.length), event.target);
          onBlur?.(event);
        }}
      />
      {name && <input type="hidden" name={name} value={moneyFormValue(raw)} disabled={disabled} />}
    </>
  );
}
