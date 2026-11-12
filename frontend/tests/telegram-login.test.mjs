import test from 'node:test';
import assert from 'node:assert/strict';
import { api, post } from '../src/api.js';

test('only explicit Telegram Web iframe login requests ask for embedded session delivery', async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ ok: true }) };
  };
  try {
    const sameWindow = {};
    globalThis.window = { location: { search: '?telegram=1' }, self: {}, top: {} };
    await post('/auth/login', { username: 'fixture', password: 'fixture' });
    assert.equal(new Headers(requests.at(-1).options.headers).get('X-CRM-Client'), 'telegram-web');
    assert.equal(requests.at(-1).options.credentials, 'same-origin');
    await api('/auth/me');
    assert.equal(new Headers(requests.at(-1).options.headers).get('X-CRM-Client'), null);
    await post('/auth/logout', {});
    assert.equal(new Headers(requests.at(-1).options.headers).get('X-CRM-Client'), null);
    globalThis.window = { location: { search: '?telegram=1' }, self: sameWindow, top: sameWindow };
    await post('/auth/login', {});
    assert.equal(new Headers(requests.at(-1).options.headers).get('X-CRM-Client'), null);
    globalThis.window = { location: { search: '' }, self: {}, top: {} };
    await post('/auth/login', {});
    assert.equal(new Headers(requests.at(-1).options.headers).get('X-CRM-Client'), null);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    globalThis.fetch = previousFetch;
  }
});
