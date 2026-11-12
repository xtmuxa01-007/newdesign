import test from 'node:test';
import assert from 'node:assert/strict';
import { canShareFile, deliverExport, exportSize } from '../src/downloads.js';

function environment(search, handled = false) {
  const events = [];
  const downloads = [];
  const revoked = [];
  const timers = [];
  let objectUrls = 0;
  const win = {
    location: { search },
    CustomEvent: class {
      constructor(type, options) {
        Object.assign(this, options, { type });
      }
    },
    dispatchEvent: (event) => {
      events.push(event);
      return !handled;
    },
    URL: {
      createObjectURL: () => `blob:local-${++objectUrls}`,
      revokeObjectURL: (url) => revoked.push(url),
    },
    setTimeout: (callback, duration) => {
      timers.push({ callback, duration });
    },
  };
  const doc = {
    body: { appendChild() {} },
    createElement: () => ({
      click() {
        downloads.push({ href: this.href, filename: this.download });
      },
      remove() {},
    }),
  };
  return { win, doc, events, downloads, revoked, timers };
}

test('ordinary authenticated exports remain local Blob downloads with the captured filename', () => {
  const env = environment('');
  const blob = new Blob(['private report']);
  assert.equal(deliverExport(blob, 'filial-1.xlsx', env.win, env.doc), 'downloaded');
  assert.equal(env.events.length, 0);
  assert.deepEqual(env.downloads, [{ href: 'blob:local-1', filename: 'filial-1.xlsx' }]);
  assert.equal(env.timers[0].duration, 60000);
  env.timers[0].callback();
  assert.deepEqual(env.revoked, ['blob:local-1']);
});

test('Telegram export is prepared for a separate user gesture without publishing data or auto-sharing', () => {
  const env = environment('?telegram=1', true);
  const blob = new Blob(['private report']);
  assert.equal(deliverExport(blob, 'sales.json', env.win, env.doc), 'prepared');
  assert.equal(env.downloads.length, 0);
  assert.equal(env.events[0].type, 'crm-export-ready');
  assert.equal(env.events[0].detail.blob, blob);
  assert.equal(env.events[0].detail.filename, 'sales.json');
  assert.equal(env.events[0].cancelable, true);
  const noSheet = environment('?telegram=1');
  assert.equal(deliverExport(blob, 'sales.json', noSheet.win, noSheet.doc), 'downloaded');
});

test('file sharing is offered only when the platform can share the actual file', () => {
  const file = new Blob(['file']);
  assert.equal(canShareFile(file, {}), false);
  assert.equal(canShareFile(file, { share() {}, canShare: () => false }), false);
  assert.equal(
    canShareFile(file, {
      share() {},
      canShare() {
        throw new Error('unsupported');
      },
    }),
    false,
  );
  let candidate;
  assert.equal(
    canShareFile(file, {
      share() {},
      canShare(value) {
        candidate = value;
        return true;
      },
    }),
    true,
  );
  assert.equal(candidate.files[0], file);
  assert.equal(exportSize(1250000), '1.25 MB');
  assert.equal(exportSize(0), '1 KB');
});
