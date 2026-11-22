// WhatsApp पर भेजने के लिए सादा संदेश (कोई server/API नहीं — wa.me लिंक WhatsApp खोलता है, भेजना उपयोगकर्ता स्वयं चुनता है)
import { rupee, ref } from './money.js';

const R = v => rupee(v).replace(/\.00$/, '');
const dmy = d => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(d || '')); return m ? `${m[3]}-${m[2]}-${m[1]}` : String(d || ''); };
const clean = s => String(s ?? '').replace(/[*_~`]/g, '').replace(/\s+/g, ' ').trim();

export const waUrl = text => 'https://wa.me/?text=' + encodeURIComponent(text);

// h = { asOf:'YYYY-MM-DD', total, invest, spend (bigint paise), partners:[{name, diff:bigint}], other:{total:bigint, entries} , link }
export function hisabText(h) {
  const line = p => p.diff > 0n ? `${clean(p.name)}: +${R(p.diff)} (लेना है)`
    : p.diff < 0n ? `${clean(p.name)}: −${R(-p.diff)} (देना है)` : `${clean(p.name)}: बराबर`;
  return [
    '*सूर्य कुंज आवासीय योजना — कुल हिसाब*',
    `${dmy(h.asOf)} तक`,
    '',
    `कुल (साझेदारों से): ${R(h.total)}`,
    `निवेश (भूमि खरीद): ${R(h.invest)}`,
    `बाकी खर्च: ${R(h.spend)}`,
    '',
    '*साझेदार-वार अंतर*',
    ...h.partners.map(line),
    ...(h.other && h.other.total > 0n ? ['', `अन्य भुगतानकर्ता: ${R(h.other.total)} (${h.other.entries} एंट्री)`] : []),
    '',
    `पूरा हिसाब: ${h.link}`,
  ].join('\n');
}

// e = sk_expenses की पंक्ति; receipts = रसीदों की संख्या
export function entryText(e, receipts = 0, link = '') {
  const no = ref(e.ref_no);
  return [
    `*${e.status === 'cancelled' ? 'रद्द खर्च' : 'खर्च'} · ${no}*`,
    `${dmy(e.expense_date)} · ${clean(e.item)}`,
    `${R(e.amount)} · ${clean(e.payer)} · ${clean(e.payment_method)}`,
    `श्रेणी: ${clean(e.category)}`,
    ...(receipts ? [`रसीद: ${receipts}`] : []),
    ...(e.created_by_name ? [`दर्ज: ${clean(e.created_by_name)}`] : []),
    ...(link ? ['', link] : []),
  ].join('\n');
}

export function openWhatsApp(text) {
  const a = document.createElement('a');
  a.href = waUrl(text); a.target = '_blank'; a.rel = 'noopener noreferrer';
  document.body.appendChild(a); a.click(); a.remove();
}
