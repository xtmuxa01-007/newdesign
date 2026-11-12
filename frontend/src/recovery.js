// Kirim va to‘lovni yuborishdan oldin saqlaymiz. Noma’lum javobda yangi ID yaratmaymiz.
import { post } from './api.js';

const key = (userId) => `marva-operation:${userId}`;
const changed = () => window.dispatchEvent(new Event('crm-operation-changed'));

export function readPending(userId) {
  const raw = localStorage.getItem(key(userId));
  return raw ? JSON.parse(raw) : null;
}

async function sendStored(userId, operation) {
  try {
    const result = await post(operation.path, operation.payload);
    localStorage.removeItem(key(userId));
    changed();
    if (
      /^\/stocks\/\d+\/(?:price|adjustments)$|^\/operations\/(?:sale|other_payment|stock_adjustment)\/\d+\/cancel$|^\/other-payments$/.test(
        operation.path,
      )
    )
      window.dispatchEvent(new Event('crm-changes-changed'));
    return result;
  } catch (error) {
    // Pause is not an answer to the original operation, even from an older 4xx policy.
    // Keep its request ID until the server can confirm that same operation.
    if (error.status && error.status < 500 && error.code !== 'desktop_paused')
      localStorage.removeItem(key(userId));
    changed();
    throw error;
  }
}

export async function recoverablePost(userId, path, payload, label) {
  if (readPending(userId)) {
    changed();
    throw new Error('Avval yuborilgan amalning natijasini tekshiring.');
  }
  const operation = { path, payload, label };
  // Xotiraga yozilmasa so‘rov umuman yuborilmaydi.
  localStorage.setItem(key(userId), JSON.stringify(operation));
  return sendStored(userId, operation);
}

export function retryPending(userId) {
  const operation = readPending(userId);
  if (!operation) throw new Error('Tekshiriladigan amal topilmadi.');
  return sendStored(userId, operation);
}
