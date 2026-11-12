import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Archive, Boxes, Check, ChevronDown, PackageCheck, PackageX } from 'lucide-react';
import './inventory-status-filter.css';

const options = [
  { value: 'all', label: 'Mahsulotlar · arxivsiz', hint: 'Faol va tugagan mahsulotlar', Icon: Boxes },
  { value: 'active', label: 'Faol mahsulotlar', hint: 'Sotuvdagi mahsulotlar', Icon: PackageCheck },
  { value: 'inactive', label: 'Tugagan mahsulotlar', hint: 'Qoldig‘i tugagan mahsulotlar', Icon: PackageX },
  { value: 'archived', label: 'Arxivlangan mahsulotlar', hint: 'Arxivga olingan mahsulotlar', Icon: Archive },
];

export function InventoryStatusFilter({ value, onChange }) {
  const [position, setPosition] = useState(null);
  const trigger = useRef(null);
  const menu = useRef(null);
  const optionRefs = useRef([]);
  const id = useId();
  const selected = Math.max(0, options.findIndex((item) => item.value === value));
  function close(restoreFocus = false) {
    setPosition(null);
    if (restoreFocus) trigger.current?.focus();
  }
  function open() {
    const rect = trigger.current.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 310), window.innerWidth - 24);
    const below = window.innerHeight - rect.bottom - 16;
    const above = rect.top - 16;
    const placeAbove = below < 280 && above > below;
    setPosition({
      position: 'fixed', width,
      left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)),
      ...(placeAbove ? { bottom: window.innerHeight - rect.top + 8 } : { top: rect.bottom + 8 }),
      maxHeight: Math.max(80, placeAbove ? above : below),
    });
  }
  useLayoutEffect(() => {
    if (position) optionRefs.current[selected]?.focus();
  }, [position, selected]);
  useEffect(() => {
    if (!position) return;
    const dismiss = (event) => {
      if (!trigger.current?.contains(event.target) && !menu.current?.contains(event.target)) close();
    };
    const scroll = (event) => {
      if (!menu.current?.contains(event.target)) close();
    };
    const resize = () => close();
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('focusin', dismiss);
    document.addEventListener('scroll', scroll, true);
    window.addEventListener('resize', resize);
    return () => {
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('focusin', dismiss);
      document.removeEventListener('scroll', scroll, true);
      window.removeEventListener('resize', resize);
    };
  }, [position]);
  function navigate(event, index) {
    const keys = { ArrowDown: (index + 1) % options.length, ArrowUp: (index + options.length - 1) % options.length,
      Home: 0, End: options.length - 1 };
    if (event.key in keys) {
      event.preventDefault();
      optionRefs.current[keys[event.key]]?.focus();
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === 'Tab') {
      // Return to the trigger so the browser continues through the page in order.
      close(true);
    }
  }
  return <>
    <button type="button" ref={trigger} className="secondary inventory-status-trigger"
      aria-label={`Mahsulot holati: ${options[selected].label}`} aria-haspopup="listbox"
      aria-expanded={!!position} aria-controls={position ? id : undefined}
      onClick={() => position ? close() : open()}
      onKeyDown={(event) => {
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
          event.preventDefault();
          open();
        }
      }}>
      <span>{options[selected].label}</span><ChevronDown size={18} aria-hidden="true" />
    </button>
    {position && createPortal(
      <div id={id} ref={menu} role="listbox" aria-label="Mahsulot holati"
        className="inventory-status-menu" style={position}>
        {options.map(({ value: optionValue, label, hint, Icon }, index) =>
          <button type="button" role="option" key={optionValue}
            aria-selected={value === optionValue} tabIndex={value === optionValue ? 0 : -1}
            ref={(node) => { optionRefs.current[index] = node; }}
            onKeyDown={(event) => navigate(event, index)}
            onClick={() => { onChange(optionValue); close(true); }}>
            <span className="inventory-status-icon"><Icon size={20} /></span>
            <span className="inventory-status-copy"><strong>{label}</strong><small>{hint}</small></span>
            {value === optionValue && <Check size={18} className="inventory-status-check" aria-hidden="true" />}
          </button>)}
      </div>, document.body)}
  </>;
}
