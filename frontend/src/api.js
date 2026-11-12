import { isTelegramWebFrame } from './telegram.js';

async function responseFor(path, options = {}) {
  const headers = new Headers(
    options.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
  );
  new Headers(options.headers).forEach((value, name) => headers.set(name, value));
  if (window.tinDesktop) headers.set('X-CRM-Client', 'desktop');
  else if (path === '/auth/login' && isTelegramWebFrame())
    headers.set('X-CRM-Client', 'telegram-web');
  const response = await fetch('/api' + path, {
    credentials: 'same-origin',
    ...options,
    headers,
  }).catch((cause) => {
    if (cause.name === 'AbortError') throw cause;
    // Status qo'yilmaydi: javobi noma'lum savdo recovery'da saqlanadi.
    throw new Error(
      'Serverga aloqa yo‘q. Internetni tekshiring. Javobi kelmagan amalni «Natijani tekshirish» orqali davom ettiring.',
    );
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const error = new Error(
      typeof data.detail === 'string'
        ? data.detail
        : Array.isArray(data.detail)
          ? 'Maydonlarni tekshiring: ' +
            data.detail.map((x) => x.loc.slice(1).join('.') + ' — ' + x.msg).join('; ')
          : 'So‘rov bajarilmadi. Qayta urinib ko‘ring.',
    );
    error.status = response.status;
    if (typeof data.code === 'string') error.code = data.code;
    if ([503, 423].includes(response.status) && error.code === 'desktop_paused')
      window.dispatchEvent(new CustomEvent('desktop-paused', { detail: error.message }));
    if (response.status === 401 && path !== '/auth/login' && path !== '/auth/me')
      window.dispatchEvent(new Event('session-ended'));
    throw error;
  }
  return response;
}
export async function api(path, options = {}) {
  return (await responseFor(path, options)).json();
}
export async function apiBlob(path, options = {}) {
  return (await responseFor(path, options)).blob();
}
export const post = (path, data, method = 'POST') =>
  api(path, { method, body: JSON.stringify(data) });
export const query = (data) =>
  '?' +
  new URLSearchParams(Object.entries(data).filter(([, v]) => v !== '' && v != null)).toString();
