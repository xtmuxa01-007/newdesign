import test from 'node:test';
import assert from 'node:assert/strict';
import {
  bindTelegramBack,
  bindTelegramReport,
  homeForRole,
  initializeTelegram,
  isTelegramEntry,
  isTelegramWebFrame,
  loadTelegramSdk,
  telegramBackDestination,
} from '../src/telegram.js';

function environment(search = '?telegram=1') {
  const properties = new Map();
  const classes = new Set();
  const calls = [];
  const handlers = new Map();
  const viewportAttributes = new Map([['content', 'width=device-width, initial-scale=1.0']]);
  const viewport = {
    getAttribute: (name) => viewportAttributes.get(name) ?? null,
    setAttribute: (name, value) => viewportAttributes.set(name, value),
    removeAttribute: (name) => viewportAttributes.delete(name),
  };
  const app = {
    viewportStableHeight: 720,
    safeAreaInset: { top: 24, bottom: 20 },
    contentSafeAreaInset: { top: 48, bottom: 0 },
    ready: () => calls.push('ready'),
    expand: () => calls.push('expand'),
    isVersionAtLeast: () => true,
    requestFullscreen: () => calls.push('fullscreen'),
    setHeaderColor: (color) => calls.push(['header', color]),
    setBackgroundColor: (color) => calls.push(['background', color]),
    setBottomBarColor: (color) => calls.push(['bottom', color]),
    onEvent: (name, handler) => handlers.set(name, handler),
    offEvent: (name, handler) => {
      if (handlers.get(name) === handler) handlers.delete(name);
    },
    BackButton: {
      show: () => calls.push('back-show'),
      hide: () => calls.push('back-hide'),
      onClick: (handler) => handlers.set('back', handler),
      offClick: (handler) => {
        if (handlers.get('back') === handler) handlers.delete('back');
      },
    },
  };
  const doc = {
    querySelector: () => viewport,
    documentElement: {
      classList: { add: (name) => classes.add(name), remove: (name) => classes.delete(name) },
      style: {
        setProperty: (name, value) => properties.set(name, value),
        removeProperty: (name) => properties.delete(name),
      },
    },
    head: {
      appendChild: () => {
        throw new Error('SDK should not be loaded');
      },
    },
    createElement: () => ({}),
  };
  const win = {
    location: { search },
    Telegram: { WebApp: app },
    setTimeout,
    clearTimeout,
    getComputedStyle: () => ({
      getPropertyValue: (name) => ({ '--topbar': '#234b40', '--page': '#efe6ce' })[name] || '',
    }),
  };
  return { app, win, doc, calls, handlers, properties, classes, viewport };
}

test('ordinary web and desktop URLs never initialize or load the Telegram SDK', async () => {
  for (const search of ['', '?telegram=0', '?page=telegram', '?telegram=true']) {
    const env = environment(search);
    let requests = 0;
    env.app.initData = 'signed-data-web-must-not-send';
    env.win.fetch = () => { requests++; throw new Error('Unexpected network'); };
    assert.equal(isTelegramEntry(search), false);
    assert.equal(await loadTelegramSdk(env.win, env.doc), null);
    assert.equal(await initializeTelegram(env.win, env.doc), null);
    assert.equal(env.classes.size, 0);
    assert.equal(env.calls.length, 0);
    assert.equal(env.viewport.getAttribute('content'), 'width=device-width, initial-scale=1.0');
    assert.equal(requests, 0);
  }
  assert.equal(isTelegramEntry('?telegram=1&section=crm'), true);
});

test('Telegram Web iframe detection does not alter native or ordinary web login cookies', () => {
  const sameWindow = {};
  assert.equal(
    isTelegramWebFrame({ location: { search: '?telegram=1' }, self: sameWindow, top: sameWindow }),
    false,
  );
  assert.equal(isTelegramWebFrame({ location: { search: '' }, self: {}, top: {} }), false);
  assert.equal(
    isTelegramWebFrame({ location: { search: '?telegram=1' }, self: {}, top: {} }),
    true,
  );
  assert.equal(
    isTelegramWebFrame({
      location: { search: '?telegram=1' },
      get self() {
        throw new Error('unavailable');
      },
    }),
    false,
  );
});

test('Telegram entry expands, becomes ready and follows stable viewport and safe areas', async () => {
  const env = environment();
  const controller = await initializeTelegram(env.win, env.doc);
  assert.equal(controller.app, env.app);
  assert.equal(env.classes.has('telegram-mini-app'), true);
  assert.equal(env.properties.get('--tin-telegram-height'), '720px');
  assert.equal(env.properties.get('--tin-telegram-safe-top'), '48px');
  assert.equal(env.properties.get('--tin-telegram-safe-bottom'), '20px');
  assert(env.calls.includes('ready'));
  assert(env.calls.includes('expand'));
  assert.equal(env.viewport.getAttribute('content'), 'width=device-width, initial-scale=1.0, viewport-fit=cover');
  env.app.viewportStableHeight = 650;
  env.handlers.get('viewportChanged')({ isStateStable: false });
  assert.equal(env.properties.get('--tin-telegram-height'), '720px');
  env.handlers.get('viewportChanged')({ isStateStable: true });
  assert.equal(env.properties.get('--tin-telegram-height'), '650px');
  env.app.contentSafeAreaInset = { top: -4, bottom: Infinity, left: 5000, right: NaN };
  env.handlers.get('contentSafeAreaChanged')();
  assert.equal(env.properties.get('--tin-telegram-safe-left'), '300px');
  assert.equal(env.properties.get('--tin-telegram-safe-right'), '0px');
  controller.dispose();
  assert.equal(env.classes.size, 0);
  assert.equal(env.properties.size, 0);
  assert.equal(env.handlers.size, 0);
  assert.equal(env.viewport.getAttribute('content'), 'width=device-width, initial-scale=1.0');
});

test('fullscreen reclaims Telegram chrome, updates safe areas and tolerates unsupported clients', async () => {
  const env = environment();
  const controller = await initializeTelegram(env.win, env.doc);
  assert.equal(env.calls.filter((call) => call === 'fullscreen').length, 1);
  env.app.viewportStableHeight = 900;
  env.app.contentSafeAreaInset = { top: 64, bottom: 0 };
  env.handlers.get('fullscreenChanged')();
  assert.equal(env.properties.get('--tin-telegram-height'), '900px');
  assert.equal(env.properties.get('--tin-telegram-safe-top'), '64px');
  assert.equal(env.calls.filter((call) => call === 'fullscreen').length, 1);
  controller.dispose();
  assert.equal(env.handlers.size, 0);
  for (const state of ['already-fullscreen', 'old-client', 'unsupported']) {
    const client = environment();
    if (state === 'already-fullscreen') client.app.isFullscreen = true;
    if (state === 'old-client') client.app.isVersionAtLeast = () => false;
    if (state === 'unsupported') client.app.requestFullscreen = () => { throw new Error('UNSUPPORTED'); };
    const fallback = await initializeTelegram(client.win, client.doc);
    assert(client.calls.includes('ready'));
    assert.equal(client.calls.includes('fullscreen'), false);
    fallback.dispose();
  }
});

test('CRM roles keep their own home and Telegram back closes a menu before changing page', () => {
  assert.equal(homeForRole('cashier'), 'pos');
  for (const role of ['boss', 'admin']) assert.equal(homeForRole(role), 'dashboard');
  assert.equal(
    telegramBackDestination({ menuOpen: true, page: 'settings', role: 'cashier' }),
    'menu',
  );
  assert.equal(
    telegramBackDestination({ menuOpen: false, page: 'settings', role: 'cashier' }),
    'pos',
  );
  assert.equal(
    telegramBackDestination({ menuOpen: false, page: 'reports', role: 'admin' }),
    'dashboard',
  );
  assert.equal(telegramBackDestination({ menuOpen: false, page: 'dashboard', role: 'boss' }), null);
  assert.equal(telegramBackDestination({ menuOpen: false, page: 'pos', role: 'cashier' }), null);
  const env = environment();
  let pressed = 0;
  const dispose = bindTelegramBack({ app: env.app }, 'pos', () => pressed++);
  env.handlers.get('back')();
  assert.equal(pressed, 1);
  dispose();
  assert.equal(env.handlers.has('back'), false);
  bindTelegramBack({ app: env.app }, null, () => {});
  assert(env.calls.includes('back-hide'));
});

test('SDK failure falls back to the same login and unsupported old-client methods are harmless', async () => {
  const env = environment();
  delete env.win.Telegram;
  let loaded;
  env.doc.head.appendChild = (script) => {
    loaded = script;
    queueMicrotask(() => script.onerror());
  };
  const controller = await initializeTelegram(env.win, env.doc);
  assert.equal(controller.app, null);
  assert.equal(loaded.src, 'https://telegram.org/js/telegram-web-app.js');
  assert.equal(loaded.referrerPolicy, 'no-referrer');
  assert.equal(env.classes.has('telegram-mini-app'), true);
  controller.dispose();
  const older = environment();
  older.app.setHeaderColor = () => {
    throw new Error('unsupported');
  };
  older.app.setBackgroundColor = undefined;
  older.app.setBottomBarColor = undefined;
  older.app.onEvent = undefined;
  older.app.offEvent = undefined;
  older.app.BackButton = undefined;
  const oldController = await initializeTelegram(older.win, older.doc);
  assert(older.calls.includes('ready'));
  oldController.dispose();
});

const settleRequests = () => new Promise((resolve) => setImmediate(resolve));

test('report binding sends signed initData once to the same origin and stops after binding', async () => {
  const env = environment();
  const signed = 'auth_date=123&user=%7B%22id%22%3A42%7D&hash=signed-fixture';
  env.app.initData = signed;
  env.app.initDataUnsafe = { user: { id: 999, username: 'untrusted' } };
  env.win.AbortController = AbortController;
  const requests = [];
  env.win.fetch = async (...args) => {
    requests.push(args);
    return { ok: true, json: async () => ({ ok: true, bound: true }) };
  };
  const controller = await initializeTelegram(env.win, env.doc);
  assert(env.calls.includes('ready'));
  await settleRequests();
  assert.equal(requests.length, 1);
  const [path, options] = requests[0];
  assert.equal(path, '/api/telegram/daily-report/bind-mini-app');
  assert.equal(options.method, 'POST');
  assert.equal(options.credentials, 'same-origin');
  assert.deepEqual(options.headers, { 'Content-Type': 'application/json' });
  assert.deepEqual(JSON.parse(options.body), { init_data: signed });
  assert(options.signal instanceof AbortSignal);
  env.handlers.get('activated')();
  env.handlers.get('activated')();
  await settleRequests();
  assert.equal(requests.length, 1);
  controller.dispose();
  assert.equal(env.handlers.size, 0);
});

test('report binding ignores absent SDK or signed data and does not use initDataUnsafe', async () => {
  for (const state of ['sdk-missing', 'no-data', 'empty-data', 'unsafe-only']) {
    const env = environment();
    let requests = 0;
    env.win.fetch = async () => { requests++; return { ok: true }; };
    if (state === 'sdk-missing') {
      delete env.win.Telegram;
      env.doc.head.appendChild = (script) => queueMicrotask(() => script.onerror());
    }
    if (state === 'empty-data') env.app.initData = '  ';
    if (state === 'unsafe-only') env.app.initDataUnsafe = { user: { id: 42 } };
    const controller = await initializeTelegram(env.win, env.doc);
    await settleRequests();
    assert.equal(requests, 0, state);
    assert.equal(env.handlers.has('activated'), false, state);
    controller.dispose();
  }
  const noFetch = environment();
  noFetch.app.initData = 'signed-fixture';
  const controller = await initializeTelegram(noFetch.win, noFetch.doc);
  assert.equal(noFetch.handlers.has('activated'), false);
  controller.dispose();
});

test('report enrollment retries only on activation, with one concurrent request', async () => {
  const env = environment();
  env.app.initData = 'unchanged-signed-fixture';
  const requests = [];
  let finish;
  env.win.fetch = (...args) => {
    requests.push(args);
    return new Promise((resolve) => { finish = resolve; });
  };
  const dispose = bindTelegramReport({ app: env.app }, env.win);
  assert.equal(requests.length, 1);
  env.handlers.get('activated')();
  env.handlers.get('activated')();
  assert.equal(requests.length, 1);
  finish({ ok: true, json: async () => ({ ok: true, bound: false }) });
  await settleRequests();
  assert.equal(requests.length, 1);
  env.handlers.get('activated')();
  assert.equal(requests.length, 2);
  assert.deepEqual(requests[0][1].body, requests[1][1].body);
  finish({ ok: true, json: async () => ({ ok: true, bound: true }) });
  await settleRequests();
  env.handlers.get('activated')();
  assert.equal(requests.length, 2);
  dispose();
});

test('network, HTTP and malformed JSON failures never interrupt ready or CRM layout', async () => {
  for (const state of ['reject', 'throw', 'http-error', 'invalid-json']) {
    const env = environment();
    env.app.initData = 'signed-fixture';
    env.win.fetch = () => {
      if (state === 'throw') throw new Error('network');
      if (state === 'reject') return Promise.reject(new Error('network'));
      return Promise.resolve({ ok: state !== 'http-error', json: async () => { throw new Error('invalid JSON'); } });
    };
    const controller = await initializeTelegram(env.win, env.doc);
    await settleRequests();
    assert(env.calls.includes('ready'), state);
    assert(env.classes.has('telegram-mini-app'), state);
    assert.equal(env.properties.get('--tin-telegram-height'), '720px', state);
    controller.dispose();
    assert.equal(env.handlers.size, 0, state);
  }
});

test('report request timeout is bounded at eight seconds and disposal aborts pending fetch', async () => {
  for (const action of ['timeout', 'dispose']) {
    const env = environment();
    env.app.initData = 'signed-fixture';
    env.win.AbortController = AbortController;
    const timers = new Map();
    env.win.setTimeout = (callback, delay) => { assert.equal(delay, 8000); timers.set(1, callback); return 1; };
    env.win.clearTimeout = (id) => timers.delete(id);
    let signal;
    let requests = 0;
    env.win.fetch = (path, options) => {
      requests++;
      signal = options.signal;
      return new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
      });
    };
    const controller = await initializeTelegram(env.win, env.doc);
    assert.equal(requests, 1);
    assert.equal(signal.aborted, false);
    const activate = env.handlers.get('activated');
    if (action === 'timeout') timers.get(1)();
    else controller.dispose();
    await settleRequests();
    assert.equal(signal.aborted, true);
    assert.equal(timers.size, 0);
    if (action === 'timeout') controller.dispose();
    activate();
    assert.equal(requests, 1);
    assert.equal(env.handlers.size, 0);
  }
});
