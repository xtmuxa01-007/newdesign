import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { MoreHorizontal } from 'lucide-react';

export function DebtActionsMenu({ label, items, scope }) {
  const [position, setPosition] = useState(null);
  const trigger = useRef(null);
  const menu = useRef(null);
  const focusLast = useRef(false);
  const menuId = useId();

  const close = (restoreFocus = false) => {
    setPosition(null);
    if (restoreFocus) trigger.current?.focus();
  };

  useEffect(() => setPosition(null), [scope]);
  useLayoutEffect(() => {
    if (!position) return;
    const controls = menu.current?.querySelectorAll('[role="menuitem"]');
    controls?.[focusLast.current ? controls.length - 1 : 0]?.focus();
    const dismiss = (event) => {
      if (!trigger.current?.contains(event.target) && !menu.current?.contains(event.target))
        setPosition(null);
    };
    const onScroll = (event) => {
      if (!menu.current?.contains(event.target)) setPosition(null);
    };
    const onResize = () => setPosition(null);
    document.addEventListener('pointerdown', dismiss);
    document.addEventListener('focusin', dismiss);
    document.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', onResize);
    return () => {
      document.removeEventListener('pointerdown', dismiss);
      document.removeEventListener('focusin', dismiss);
      document.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', onResize);
    };
  }, [position]);

  function toggle(last = false) {
    if (position) return close();
    focusLast.current = last;
    const rect = trigger.current.getBoundingClientRect();
    const width = Math.min(272, window.innerWidth - 24);
    const height = items.length * 44 + 12;
    const below = window.innerHeight - rect.bottom - 12;
    const above = rect.top - 12;
    const flip = below < height && above > below;
    setPosition({
      left: Math.max(12, Math.min(rect.right - width, window.innerWidth - width - 12)),
      top: flip ? undefined : rect.bottom + 6,
      bottom: flip ? window.innerHeight - rect.top + 6 : undefined,
      width,
      maxHeight: Math.max(80, flip ? above : below),
    });
  }

  function navigate(event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close(true);
      return;
    }
    if (event.key === 'Tab') {
      close(true);
      return;
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const controls = [...menu.current.querySelectorAll('[role="menuitem"]')];
    const current = controls.indexOf(document.activeElement);
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? controls.length - 1
          : (current + (event.key === 'ArrowDown' ? 1 : -1) + controls.length) % controls.length;
    controls[next]?.focus();
  }

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="secondary debt-more-trigger"
        aria-label={label}
        title="Boshqa amallar"
        aria-haspopup="menu"
        aria-expanded={!!position}
        aria-controls={position ? menuId : undefined}
        onClick={() => toggle()}
        onKeyDown={(event) => {
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault();
            if (!position) toggle(event.key === 'ArrowUp');
          }
        }}
      >
        <MoreHorizontal size={19} />
      </button>
      {position &&
        createPortal(
          <div
            ref={menu}
            id={menuId}
            className="debt-action-menu"
            role="menu"
            aria-label={label}
            style={position}
            onKeyDown={navigate}
          >
            {items.map(({ label: title, icon: Icon, danger, action }) => (
              <button
                key={title}
                type="button"
                role="menuitem"
                tabIndex={-1}
                className={danger ? 'debt-menu-danger' : undefined}
                onClick={() => {
                  close(true);
                  action();
                }}
              >
                <Icon size={17} />
                <span>{title}</span>
              </button>
            ))}
          </div>,
          document.body,
        )}
    </>
  );
}
