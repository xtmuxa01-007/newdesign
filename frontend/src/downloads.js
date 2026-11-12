import { isTelegramEntry } from './telegram.js';

export const EXPORT_READY_EVENT = 'crm-export-ready';

export function downloadBlob(blob, filename, win = window, doc = document) {
  const url = win.URL.createObjectURL(blob);
  const link = doc.createElement('a');
  link.href = url;
  link.download = filename;
  doc.body.appendChild(link);
  link.click();
  link.remove();
  // iPhone webviews may start processing a large file after the click finishes.
  win.setTimeout(() => win.URL.revokeObjectURL(url), 60000);
}

export function deliverExport(blob, filename, win = window, doc = document) {
  if (isTelegramEntry(win.location.search)) {
    const event = new win.CustomEvent(EXPORT_READY_EVENT, {
      detail: { blob, filename },
      cancelable: true,
    });
    if (!win.dispatchEvent(event)) return 'prepared';
  }
  downloadBlob(blob, filename, win, doc);
  return 'downloaded';
}

export function canShareFile(file, navigator = globalThis.navigator) {
  if (typeof navigator?.share !== 'function' || typeof navigator?.canShare !== 'function')
    return false;
  try {
    return navigator.canShare({ files: [file] }) === true;
  } catch {
    return false;
  }
}

export function exportSize(bytes) {
  return bytes >= 1000000
    ? `${(bytes / 1000000).toFixed(2)} MB`
    : `${Math.max(1, Math.ceil(bytes / 1000))} KB`;
}
