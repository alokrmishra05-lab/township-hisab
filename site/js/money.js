// सूर्य कुंज | पैसे और CSV के शुद्ध (DOM-रहित) helpers — ब्राउज़र और node परीक्षण दोनों में।
// राशि कभी float में नहीं जोड़ी जाती: पूर्णांक पैसे (BigInt)।
export const ref = n => 'SK-' + String(n).padStart(6, '0');

export function toPaise(v) {
  const s = String(v ?? '').trim();
  const m = /^(\d{1,9})(?:\.(\d{1,2}))?$/.exec(s);
  if (!m) return null;
  return BigInt(m[1]) * 100n + BigInt((m[2] || '').padEnd(2, '0'));
}
export function paiseToText(p) { // 2145075n → "21450.75"
  const n = BigInt(p); return `${n / 100n}.${String(n % 100n).padStart(2, '0')}`;
}
export function rupee(v) {
  const p = typeof v === 'bigint' ? v : toPaise(Number.isFinite(v) ? Number(v).toFixed(2) : v);
  if (p === null) return '₹—';
  const whole = (p / 100n).toString().replace(/(\d)(?=(\d\d)+\d$)/g, '$1,');
  return `₹${whole}.${String(p % 100n).padStart(2, '0')}`;
}
// CSV: Excel में हिंदी हेतु BOM; formula-injection से बचाव
export function csvCell(v) {
  let s = String(v ?? '');
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
export const toCsv = rows => '\uFEFF' + rows.map(r => r.map(csvCell).join(',')).join('\r\n') + '\r\n';


export function expensesCsv(list) {
  const head = ['क्रमांक', 'तारीख', 'मद', 'श्रेणी', 'राशि (₹)', 'भुगतानकर्ता', 'भुगतान का तरीका', 'स्थिति', 'दर्ज करने वाला', 'दर्ज समय',
    'अंतिम बदलाव', 'अंतिम बदलाव समय', 'रद्द का कारण', 'संस्करण', 'id'];
  return toCsv([head, ...list.map(r => [ref(r.ref_no), r.expense_date, r.item, r.category, paiseToText(toPaise(Number(r.amount).toFixed(2))),
    r.payer, r.payment_method, r.status === 'active' ? 'सक्रिय' : 'रद्द', r.created_by_name, r.created_at, r.updated_by_name || '',
    r.updated_at, r.cancel_reason || '', r.version, r.id])]);
}
export function csvActiveTotalPaise(csvText) { // CSV को वापस पढ़कर सक्रिय राशि जोड़ना (मिलान हेतु)
  const lines = csvText.replace(/^\uFEFF/, '').trim().split(/\r\n/).slice(1);
  let sum = 0n;
  for (const line of lines) {
    const cells = []; let cur = '', q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (q) { if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; } else if (ch === '"') q = false; else cur += ch; }
      else if (ch === '"') q = true; else if (ch === ',') { cells.push(cur); cur = ''; } else cur += ch;
    }
    cells.push(cur);
    if (cells[7] === 'सक्रिय') sum += toPaise(cells[4]);
  }
  return sum;
}

