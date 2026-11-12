// CRM login and server permissions stay authoritative in Telegram too.
const SDK_URL = 'https://telegram.org/js/telegram-web-app.js';
const SIDES = ['top', 'right', 'bottom', 'left'];
const CSS_PROPERTIES = [
  '--tin-telegram-height',
  ...SIDES.map((side) => `--tin-telegram-safe-${side}`),
];

export function isTelegramEntry(search = globalThis.location?.search || '') {
  return new URLSearchParams(search).get('telegram') === '1';
}

export function isTelegramWebFrame(win = window) {
  if (!isTelegramEntry(win.location.search)) return false;
  try {
    return win.self !== win.top;
  } catch {
    return false;
  }
}

export function homeForRole(role) {
  return role === 'cashier' ? 'pos' : 'dashboard';
}

export function telegramBackDestination({ menuOpen, page, role }) {
  if (menuOpen) return 'menu';
  const home = homeForRole(role);
  return page === home ? null : home;
}

export function loadTelegramSdk(win, doc) {
  if (!isTelegramEntry(win.location.search)) return Promise.resolve(null);
  if (win.Telegram?.WebApp) return Promise.resolve(win.Telegram.WebApp);
  return new Promise((resolve) => {
    const script = doc.createElement('script');
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      win.clearTimeout(timer);
      script.onload = null;
      script.onerror = null;
      resolve(win.Telegram?.WebApp || null);
    };
    const timer = win.setTimeout(finish, 6000);
    script.src = SDK_URL;
    script.async = true;
    script.referrerPolicy = 'no-referrer';
    script.onload = finish;
    script.onerror = finish;
    doc.head.appendChild(script);
  });
}

function optionalCall(target, method, ...args) {
  try {
    target?.[method]?.(...args);
  } catch {
    // Older Telegram clients still use the same CRM in the ordinary web layout.
  }
}

function inset(value) {
  return Number.isFinite(value) ? Math.max(0, Math.min(300, value)) : 0;
}

export function bindTelegramReport(controller, win = window) {
  const app = controller?.app;
  // Only signed Mini App data goes to this same-origin verification endpoint.
  // initDataUnsafe is never a trusted recipient identity.
  if (!isTelegramEntry(win.location?.search || '') || typeof win.fetch !== 'function' ||
      typeof app?.initData !== 'string' || !app.initData.trim()) return () => {};
  const initData = app.initData;
  let disposed = false;
  let bound = false;
  let active = null;
  const attempt = () => {
    if (disposed || bound || active) return;
    const request = { abort: null, timer: null };
    active = request;
    const send = async () => {
      try {
        if (typeof win.AbortController === 'function') {
          request.abort = new win.AbortController();
          request.timer = win.setTimeout(() => request.abort.abort(), 8000);
        }
        const response = await win.fetch('/api/telegram/daily-report/bind-mini-app', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ init_data: initData }),
          ...(request.abort ? { signal: request.abort.signal } : {}),
        });
        if (!disposed && response?.ok) {
          const result = await response.json();
          if (result?.ok === true && result.bound === true) bound = true;
        }
      } catch {
        // Report enrollment must never interrupt CRM login or normal usage.
      } finally {
        if (request.timer != null) win.clearTimeout(request.timer);
        if (active === request) active = null;
      }
    };
    void send().catch(() => {});
  };
  optionalCall(app, 'onEvent', 'activated', attempt);
  attempt();
  return () => {
    disposed = true;
    optionalCall(app, 'offEvent', 'activated', attempt);
    if (active?.timer != null) win.clearTimeout(active.timer);
    active?.abort?.abort();
  };
}

export async function initializeTelegram(win = window, doc = document) {
  if (!isTelegramEntry(win.location.search)) return null;
  const viewport = doc.querySelector?.('meta[name="viewport"]');
  const viewportContent = viewport?.getAttribute('content');
  viewport?.setAttribute('content', 'width=device-width, initial-scale=1.0, viewport-fit=cover');
  doc.documentElement.classList.add('telegram-mini-app');
  const app = await loadTelegramSdk(win, doc);
  const updateLayout = () => {
    const height = app?.viewportStableHeight;
    if (Number.isFinite(height) && height > 0)
      doc.documentElement.style.setProperty('--tin-telegram-height', `${height}px`);
    for (const side of SIDES) {
      const value = Math.max(
        inset(app?.safeAreaInset?.[side]),
        inset(app?.contentSafeAreaInset?.[side]),
      );
      doc.documentElement.style.setProperty(`--tin-telegram-safe-${side}`, `${value}px`);
    }
  };
  const updateColors = () => {
    const style = win.getComputedStyle(doc.documentElement);
    const header = style.getPropertyValue('--topbar').trim();
    const background = style.getPropertyValue('--page').trim();
    if (/^#[\da-f]{6}$/i.test(header)) optionalCall(app, 'setHeaderColor', header);
    if (/^#[\da-f]{6}$/i.test(background)) {
      optionalCall(app, 'setBackgroundColor', background);
      optionalCall(app, 'setBottomBarColor', background);
    }
  };
  const viewportChanged = (event) => {
    if (event?.isStateStable !== false) updateLayout();
  };
  updateLayout();
  updateColors();
  optionalCall(app, 'onEvent', 'viewportChanged', viewportChanged);
  optionalCall(app, 'onEvent', 'safeAreaChanged', updateLayout);
  optionalCall(app, 'onEvent', 'contentSafeAreaChanged', updateLayout);
  optionalCall(app, 'onEvent', 'fullscreenChanged', updateLayout);
  optionalCall(app, 'onEvent', 'themeChanged', updateColors);
  optionalCall(app, 'expand');
  optionalCall(app, 'ready');
  // Fullscreen also removes Telegram Desktop's native username footer.
  if (!app?.isFullscreen && (!app?.isVersionAtLeast || app.isVersionAtLeast('8.0')))
    optionalCall(app, 'requestFullscreen');
  const unbindReport = bindTelegramReport({ app }, win);
  return {
    app,
    updateColors,
    dispose() {
      unbindReport();
      optionalCall(app, 'offEvent', 'viewportChanged', viewportChanged);
      optionalCall(app, 'offEvent', 'safeAreaChanged', updateLayout);
      optionalCall(app, 'offEvent', 'contentSafeAreaChanged', updateLayout);
      optionalCall(app, 'offEvent', 'fullscreenChanged', updateLayout);
      optionalCall(app, 'offEvent', 'themeChanged', updateColors);
      optionalCall(app?.BackButton, 'hide');
      if (viewportContent == null) viewport?.removeAttribute('content');
      else viewport?.setAttribute('content', viewportContent);
      doc.documentElement.classList.remove('telegram-mini-app');
      for (const property of CSS_PROPERTIES) doc.documentElement.style.removeProperty(property);
    },
  };
}

export function bindTelegramBack(controller, destination, onBack) {
  const back = controller?.app?.BackButton;
  if (!back) return () => {};
  if (destination) {
    optionalCall(back, 'onClick', onBack);
    optionalCall(back, 'show');
  } else optionalCall(back, 'hide');
  return () => optionalCall(back, 'offClick', onBack);
}
