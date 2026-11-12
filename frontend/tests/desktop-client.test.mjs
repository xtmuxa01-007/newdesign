import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { api } from '../src/api.js';

const originalWindow = globalThis.window;
const originalFetch = globalThis.fetch;
afterEach(() => {
  if (originalWindow === undefined) delete globalThis.window;
  else globalThis.window = originalWindow;
  globalThis.fetch = originalFetch;
});

function environment({ desktop = false, telegram = false } = {}) {
  const win = new EventTarget();
  win.location = { search: telegram ? '?telegram=1' : '' };
  win.self = win;
  win.top = telegram ? {} : win;
  if (desktop) win.tinDesktop = { mode: 'online' };
  globalThis.window = win;
  const requests = [];
  globalThis.fetch = async (path, options) => {
    requests.push({ path, ...options });
    return new Response('{}', { headers: { 'Content-Type': 'application/json' } });
  };
  return { win, requests };
}

test('web and Telegram retain their own request headers and upload content type', async () => {
  const web = environment();
  await api('/auth/me');
  assert.equal(web.requests[0].headers.get('X-CRM-Client'), null);
  assert.equal(web.requests[0].credentials, 'same-origin');
  await api('/products/1/image', {
    method: 'POST',
    body: new FormData(),
    headers: { 'X-Test': 'kept' },
  });
  assert.equal(web.requests[1].headers.get('Content-Type'), null);
  assert.equal(web.requests[1].headers.get('X-Test'), 'kept');
  const telegram = environment({ telegram: true });
  await api('/auth/login', { method: 'POST', body: '{}' });
  assert.equal(telegram.requests[0].headers.get('X-CRM-Client'), 'telegram-web');
  await api('/auth/me');
  assert.equal(telegram.requests[1].headers.get('X-CRM-Client'), null);
});

test('the actual desktop bridge marks all API calls and cannot be hidden by Telegram headers', async () => {
  const desktop = environment({ desktop: true, telegram: true });
  await api('/auth/login', { headers: { 'x-crm-client': 'telegram-web' } });
  await api('/products?branch_id=1');
  await api('/desktop/status');
  for (const request of desktop.requests)
    assert.equal(request.headers.get('X-CRM-Client'), 'desktop');
});

test('503 and earlier 423 desktop pauses keep their reason and trigger the pause screen, not logout', async () => {
  const { win } = environment({ desktop: true });
  const messages = [];
  let logouts = 0;
  win.addEventListener('desktop-paused', (event) => messages.push(event.detail));
  win.addEventListener('session-ended', () => logouts++);
  for (const status of [503, 423]) {
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({
          code: 'desktop_paused',
          detail: 'EXE vaqtincha to‘xtatilgan.',
        }),
        { status, headers: { 'Content-Type': 'application/json' } },
      );
    await assert.rejects(api('/auth/me'), (error) => {
      assert.equal(error.status, status);
      assert.equal(error.code, 'desktop_paused');
      assert.equal(error.message, 'EXE vaqtincha to‘xtatilgan.');
      return true;
    });
  }
  assert.deepEqual(messages, ['EXE vaqtincha to‘xtatilgan.', 'EXE vaqtincha to‘xtatilgan.']);
  assert.equal(logouts, 0);
});
