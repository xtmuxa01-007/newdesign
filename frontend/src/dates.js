// Ba’zi brauzerlarda uz-UZ oy nomlari M09 kabi chiqadi; nomlar aniq beriladi.
const months = [
  'yanvar',
  'fevral',
  'mart',
  'aprel',
  'may',
  'iyun',
  'iyul',
  'avgust',
  'sentabr',
  'oktabr',
  'noyabr',
  'dekabr',
];
export function uzDate(value = new Date(), withTime = true, includeYear = false) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Asia/Tashkent',
      day: 'numeric',
      month: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(new Date(value))
      .map((part) => [part.type, part.value]),
  );
  const label = `${Number(parts.day)}-${months[Number(parts.month) - 1]}`;
  const date = withTime || includeYear ? `${label} ${parts.year}` : label;
  return withTime ? `${date}, ${parts.hour}:${parts.minute}` : date;
}
