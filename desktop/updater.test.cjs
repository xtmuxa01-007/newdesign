const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { createUpdater, FEED } = require('./updater.cjs');

function fixture(backupFails = false) {
  const api = new EventEmitter();
  const calls = [];
  api.setFeedURL = (value) => { api.feed = value; };
  api.quitAndInstall = (...args) => calls.push(['install', ...args]);
  api.checkForUpdates = async () => {
    calls.push(['check']);
    api.emit('checking-for-update');
    api.emit('update-available', { version: '0.4.8' });
    return { downloadPromise: Promise.resolve() };
  };
  const control = createUpdater({ autoUpdater: api, version: '0.4.7', enabled: true,
    beforeInstall: async () => { calls.push(['backup']); if (backupFails) throw new Error('backup failed'); } });
  return { api, control, calls };
}
test('Downloads from fixed HTTPS feed without installing during normal app exit', async () => {
  const { api, control, calls } = fixture();
  assert.equal(api.feed.url, FEED);
  assert.equal(api.autoInstallOnAppQuit, false);
  assert.equal(api.allowDowngrade, false);
  await control.check();
  await control.check();
  assert.equal(calls.length, 1);
  api.emit('download-progress', { percent: 46.2 });
  assert.equal(control.status().percent, 46);
  await assert.rejects(control.install());
  api.emit('update-downloaded', { version: '0.4.8' });
  await control.install();
  assert.deepEqual(calls, [['check'], ['backup'], ['install', true, true]]);
});
test('Failed backup keeps downloaded update retryable and prevents installer', async () => {
  const { api, control, calls } = fixture(true);
  api.emit('update-downloaded', { version: '0.4.8' });
  await assert.rejects(control.install(), /backup failed/);
  assert.equal(control.status().phase, 'ready');
  assert.deepEqual(calls, [['backup']]);
});
test('Network/checksum failure is recoverable and never installs a package', async () => {
  const { api, control, calls } = fixture();
  await control.check();
  api.emit('error', new Error('checksum mismatch'));
  assert.equal(control.status().phase, 'error');
  await assert.rejects(control.install());
  await control.check();
  assert.equal(calls.length, 2);
});
