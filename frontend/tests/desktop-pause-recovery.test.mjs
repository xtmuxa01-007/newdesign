import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readPending, recoverablePost, retryPending } from '../src/recovery.js';

const original = {
  window: globalThis.window,
  fetch: globalThis.fetch,
  localStorage: globalThis.localStorage,
};
afterEach(() => {
  for (const [name, value] of Object.entries(original)) {
    if (value === undefined) delete globalThis[name];
    else globalThis[name] = value;
  }
});

function environment() {
  const storage = new Map();
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  };
  const win = new EventTarget();
  win.location = { search: '' };
  win.self = win;
  win.top = win;
  win.tinDesktop = { mode: 'online' };
  globalThis.window = win;
  return storage;
}

for (const pause of [
  { status: 503, code: 'desktop_paused' },
  { status: 423, code: 'desktop_paused' },
  { status: 503 },
]) {
  test(`unknown sale-edit commit survives pause ${pause.status}/${pause.code || 'status-only cached-client contract'} and retries its original ID once`, async () => {
    const storage = environment();
    const user = 123,
      key = 'marva-operation:123';
    const payload = {
      request_id: '00000000-0000-4000-8000-000000000123',
      version: 2,
      reason: 'Customer correction',
      customer: 'Fixture',
      cash: '100',
      card: '0',
      items: [{ item_id: 7, product_id: 1, kg: '1', price: '100', discount: '0' }],
    };
    const commits = new Map();
    const requests = [];
    let phase = 'lost-original',
      mutations = 0;
    globalThis.fetch = async (path, options) => {
      const body = JSON.parse(options.body);
      requests.push(body);
      assert.equal(path, '/api/sales/77/edit');
      assert.deepEqual(
        JSON.parse(storage.get(key)).payload,
        payload,
        'Persist before any POST reaches the server',
      );
      if (phase === 'paused')
        return new Response(JSON.stringify({ ...pause, detail: 'EXE paused' }), {
          status: pause.status,
          headers: { 'Content-Type': 'application/json' },
        });
      if (!commits.has(body.request_id)) {
        mutations++;
        commits.set(body.request_id, { id: 77, edit_version: 3 });
      }
      if (phase === 'lost-original') throw new Error('Committed response was lost');
      return new Response(JSON.stringify(commits.get(body.request_id)), {
        headers: { 'Content-Type': 'application/json' },
      });
    };
    await assert.rejects(recoverablePost(user, '/sales/77/edit', payload, 'Savdo #77 tahriri'));
    const originalBytes = storage.get(key);
    assert.equal(mutations, 1);
    assert.equal(requests.length, 1, 'No automatic retry');
    phase = 'paused';
    await assert.rejects(retryPending(user), (error) => error.status === pause.status);
    assert.equal(
      storage.get(key),
      originalBytes,
      'A pause must not discard unknown original outcome',
    );
    assert.deepEqual(
      readPending(user).payload,
      payload,
      'Reload recovery reads the same body and request ID',
    );
    assert.equal(mutations, 1);
    assert.equal(requests.length, 2);
    phase = 'resumed';
    assert.deepEqual(await retryPending(user), { id: 77, edit_version: 3 });
    assert.equal(readPending(user), null);
    assert.equal(mutations, 1, 'The original committed mutation is not repeated');
    assert.deepEqual(requests, [payload, payload, payload]);
  });
}

test('a normal definitive business rejection still releases its pending request', async () => {
  environment();
  globalThis.fetch = async () =>
    new Response(JSON.stringify({ detail: 'Stale stock' }), {
      status: 409,
      headers: { 'Content-Type': 'application/json' },
    });
  await assert.rejects(
    recoverablePost(123, '/stocks/1/adjustments', { request_id: 'fixture' }, 'Fixture'),
    (error) => error.status === 409,
  );
  assert.equal(readPending(123), null);
});
