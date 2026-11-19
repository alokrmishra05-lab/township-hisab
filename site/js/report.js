// सूर्य कुंज | PDF रिपोर्ट — ब्राउज़र में ही बनती है (कोई डेटा बाहर नहीं जाता)।
// पन्ने HTML में बनते हैं, html2canvas से चित्र बनकर jsPDF में A4 पन्नों पर जाते हैं —
// इससे हिंदी (देवनागरी) अक्षर ठीक वैसे दिखते हैं जैसे स्क्रीन पर।
import { toPaise, rupee } from './money.js';

const LIBS = [
  ['vendor/html2canvas-1.4.1.min.js', 'sha384-ZZ1pncU3bQe8y31yfZdMFdSpttDoPmOZg2wguVK9almUodir1PghgT0eY7Mrty8H', () => window.html2canvas],
  ['vendor/jspdf-2.5.2.umd.min.js', 'sha384-en/ztfPSRkGfME4KIm05joYXynqzUgbsG5nMrj/xEFAHXkeZfO3yMK8QQ+mP7p1/', () => window.jspdf?.jsPDF],
];
const PARTNERS = ['आलोक रंजन मिश्र', 'अमरनाथ पाण्डेय', 'गगन आचारी'];
const ROWS_PER_PAGE = 26;

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const P = v => { const t = String(v ?? '0').trim(), neg = t.startsWith('-'); const p = toPaise(neg ? t.slice(1) : t) ?? 0n; return neg ? -p : p; };
const R = p => (p < 0n ? '−' + rupee(-p) : rupee(p));
const cut = (s, n) => { const a = [...String(s ?? '')]; return a.length > n ? a.slice(0, n - 1).join('') + '…' : a.join(''); };
const dmy = d => d ? d.split('-').reverse().join('-') : '';

function loadScript(src, integrity) {
  return new Promise((ok, bad) => {
    const s = document.createElement('script');
    s.src = src; s.integrity = integrity; s.crossOrigin = 'anonymous';
    s.onload = ok; s.onerror = () => bad(Error('रिपोर्ट की फ़ाइल लोड नहीं हुई: ' + src));
    document.head.appendChild(s);
  });
}
async function libs() {
  for (const [src, sri, ready] of LIBS) if (!ready()) await loadScript(src, sri);
  return { html2canvas: window.html2canvas, jsPDF: window.jspdf.jsPDF };
}

export const isNativeApp = () => !!window.Capacitor?.isNativePlatform?.();

// अवधि का सार: श्रेणी-वार और भुगतानकर्ता-वार (केवल सक्रिय एंट्री)
export function periodSummary(rows) {
  const act = rows.filter(r => r.status === 'active');
  const add = (m, k, v) => m.set(k, (m.get(k) ?? 0n) + v);
  const byCat = new Map(), byPayer = new Map(); let total = 0n;
  for (const r of act) { const a = P(r.amount); total += a; add(byCat, r.category, a); add(byPayer, r.payer, a); }
  const sortDesc = m => [...m].sort((a, b) => (b[1] > a[1] ? 1 : b[1] < a[1] ? -1 : 0));
  return { total, count: act.length, cancelled: rows.length - act.length, byCat: sortDesc(byCat), byPayer: sortDesc(byPayer) };
}

const CSS = `
.rp{position:fixed;left:-20000px;top:0;z-index:-1}
.pg{width:794px;height:1123px;background:#fff;color:#1c1f1a;padding:44px 46px 40px;box-sizing:border-box;position:relative;
  font-family:"Noto Sans Devanagari",system-ui,sans-serif;font-size:12.5px;line-height:1.45}
.pg h1{font-size:22px;margin:0;color:#14532d}.pg h2{font-size:15px;margin:18px 0 8px;color:#14532d;border-bottom:2px solid #14532d;padding-bottom:3px}
.pg .meta{color:#555;margin:4px 0 0}.pg table{width:100%;border-collapse:collapse;margin-top:4px}
.pg th,.pg td{border:1px solid #d6d9d2;padding:5px 6px;text-align:left;vertical-align:top;white-space:nowrap;overflow:hidden}
.pg th{background:#eef3ee;font-weight:600}.pg td.n,.pg th.n{text-align:right}
.pg .tot td{font-weight:700;background:#f6f8f5}.pg .pos{color:#1b7a3a}.pg .neg{color:#b42318}.pg .x{color:#888;text-decoration:line-through}
.pg .ft{position:absolute;left:46px;right:46px;bottom:20px;display:flex;justify-content:space-between;color:#777;font-size:11px;border-top:1px solid #ddd;padding-top:6px}
.pg .note{color:#555;font-size:11.5px;margin-top:8px}`;

function header(o) {
  return `<h1>सूर्य कुंज आवासीय योजना — हिसाब रिपोर्ट</h1>
    <div class="meta">अवधि: <b>${o.from ? dmy(o.from) : 'शुरू से'}</b> से <b>${o.to ? dmy(o.to) : 'आज तक'}</b>
    · बनाई: ${esc(o.when)} · ${esc(o.by)}</div>`;
}

function summaryPage(o, summary, ps) {
  const parts = summary.filter(x => x.kind === 'partner')
    .sort((a, b) => (PARTNERS.indexOf(a.name) + 1 || 99) - (PARTNERS.indexOf(b.name) + 1 || 99));
  const all = summary.find(x => x.kind === 'all'), other = summary.find(x => x.kind === 'other');
  const diff = v => { const p = P(v); return p > 0n ? `<span class="pos">+${rupee(p)} (लेना)</span>` : p < 0n ? `<span class="neg">−${rupee(-p)} (देना)</span>` : 'बराबर'; };
  return `${header(o)}
  <h2>1. कुल हिसाब — साझेदार-वार (शुरू से अब तक)</h2>
  <table><tr><th>साझेदार</th><th class="n">निवेश</th><th class="n">खर्च</th><th class="n">कुल योगदान</th><th class="n">तय हिस्सा</th><th class="n">अंतर</th></tr>
  ${parts.map(x => `<tr><td>${esc(x.name)}</td><td class="n">${R(P(x.invest))}</td><td class="n">${R(P(x.spend))}</td>
    <td class="n"><b>${R(P(x.total))}</b></td><td class="n">${R(P(x.due))}</td><td class="n">${diff(x.diff)}</td></tr>`).join('')}
  <tr class="tot"><td>कुल</td><td class="n">${R(P(all?.invest))}</td><td class="n">${R(P(all?.spend))}</td><td class="n">${R(P(all?.total))}</td><td></td><td></td></tr></table>
  ${P(other?.total) > 0n ? `<div class="note">अन्य भुगतानकर्ता (जैसे साइट कैश): ${R(P(other.total))} — साझेदारों के हिस्से में नहीं जुड़ा।</div>` : ''}
  <div class="note">"भूमि खरीद" = निवेश, बाकी = खर्च। अंतर = कुल योगदान − तय हिस्सा (+ लेना, − देना)। केवल सक्रिय (रद्द नहीं) एंट्री।</div>

  <h2>2. इस अवधि का सार</h2>
  <table><tr><th>कुल एंट्री (सक्रिय)</th><td class="n">${ps.count}</td><th>कुल राशि</th><td class="n"><b>${R(ps.total)}</b></td></tr>
  ${ps.cancelled ? `<tr><th>रद्द एंट्री</th><td class="n">${ps.cancelled}</td><td colspan="2"><small>राशि कुल में नहीं जुड़ी</small></td></tr>` : ''}</table>
  <h2>3. श्रेणी-वार (इस अवधि में)</h2>
  <table><tr><th>श्रेणी</th><th class="n">राशि</th></tr>
  ${ps.byCat.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${R(v)}</td></tr>`).join('') || '<tr><td colspan="2">कोई एंट्री नहीं</td></tr>'}</table>
  <h2>4. भुगतानकर्ता-वार (इस अवधि में)</h2>
  <table><tr><th>भुगतानकर्ता</th><th class="n">राशि</th></tr>
  ${ps.byPayer.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="n">${R(v)}</td></tr>`).join('') || '<tr><td colspan="2">कोई एंट्री नहीं</td></tr>'}</table>`;
}

function entriesPage(o, chunk, first) {
  return `${first ? '<h2 style="margin-top:0">5. एंट्री-वार सूची</h2>' : '<h2 style="margin-top:0">5. एंट्री-वार सूची (जारी)</h2>'}
  <table><tr><th>क्र.</th><th>तारीख</th><th>विवरण</th><th>श्रेणी</th><th>भुगतानकर्ता</th><th>तरीका</th><th class="n">राशि</th></tr>
  ${chunk.map(r => { const x = r.status === 'active' ? '' : ' class="x"';
    return `<tr><td${x}>SK-${r.ref_no}</td><td${x}>${dmy(r.expense_date)}</td><td${x}>${esc(cut(r.item, 30))}${r.status === 'active' ? '' : ' (रद्द)'}</td>
      <td${x}>${esc(cut(r.category, 16))}</td><td${x}>${esc(cut(r.payer, 15))}</td><td${x}>${esc(cut(r.payment_method, 13))}</td><td class="n"${x}>${R(P(r.amount))}</td></tr>`; }).join('')}</table>`;
}

// रिपोर्ट के पन्नों का HTML (परीक्षण में भी इस्तेमाल)
export function buildPages(o, summary, rows) {
  const ps = periodSummary(rows);
  const pages = [summaryPage(o, summary, ps)];
  if (o.details) for (let i = 0; i < rows.length; i += ROWS_PER_PAGE) pages.push(entriesPage(o, rows.slice(i, i + ROWS_PER_PAGE), i === 0));
  return pages.map((h, i) => `<div class="pg">${h}<div class="ft"><span>सूर्य कुंज आवासीय योजना · निजी — केवल साझेदारों के लिए</span><span>पृष्ठ ${i + 1} / ${pages.length}</span></div></div>`);
}

export async function makeReport(db, o, onStep = () => {}) {
  onStep('डेटा लाया जा रहा है…');
  const { data: summary, error: sErr } = await db.rpc('sk_partner_summary'); if (sErr) throw sErr;
  let q = db.from('sk_expenses').select('ref_no,expense_date,item,category,amount,payer,payment_method,status')
    .order('expense_date').order('ref_no').limit(10000);
  if (o.from) q = q.gte('expense_date', o.from);
  if (o.to) q = q.lte('expense_date', o.to);
  if (!o.cancelled) q = q.eq('status', 'active');
  const { data: rows, error: rErr } = await q; if (rErr) throw rErr;

  onStep('PDF के पन्ने बन रहे हैं…');
  const { html2canvas, jsPDF } = await libs();
  if (document.fonts?.ready) await document.fonts.ready;
  const box = document.createElement('div'); box.className = 'rp';
  box.innerHTML = `<style>${CSS}</style>` + buildPages(o, summary, rows).join('');
  document.body.appendChild(box);
  try {
    const pdf = new jsPDF({ unit: 'mm', format: 'a4', compress: true });
    const pgs = [...box.querySelectorAll('.pg')];
    for (let i = 0; i < pgs.length; i++) {
      onStep(`पृष्ठ ${i + 1} / ${pgs.length}…`);
      const c = await html2canvas(pgs[i], { scale: 2, backgroundColor: '#ffffff', logging: false, useCORS: false });
      if (i) pdf.addPage();
      pdf.addImage(c.toDataURL('image/jpeg', 0.88), 'JPEG', 0, 0, 210, 297);
    }
    pdf.setProperties({ title: 'सूर्य कुंज हिसाब रिपोर्ट', creator: 'सूर्य कुंज हिसाब-किताब' });
    const name = `surya-kunj-report-${o.from || 'shuru'}-to-${o.to || 'aaj'}.pdf`;
    pdf.save(name);
    return { pages: pgs.length, rows: rows.length, name };
  } finally { box.remove(); }
}
