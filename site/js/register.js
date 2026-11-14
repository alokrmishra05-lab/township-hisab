// सूर्य कुंज | निजी खर्च रजिस्टर — Supabase Auth + RLS + RPC + निजी storage
// सारे अधिकार database में लागू हैं; यह UI केवल उन्हें आसान बनाता है।
import { inspectFile, expectedMime, extOf } from './filecheck.js';
import { ref, toPaise, paiseToText, rupee, toCsv, expensesCsv, csvActiveTotalPaise } from './money.js';

const $ = id => document.getElementById(id);
const cfg = window.SK_REGISTER_CONFIG || {};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
export const CATEGORIES = ['भूमि / रजिस्ट्री', 'मिट्टी भराई', 'मजदूरी', 'निर्माण सामग्री', 'बिजली / पानी',
  'मशीन / वाहन', 'कार्यालय / यात्रा', 'लेआउट / स्वीकृति शुल्क', 'सड़क / प्लॉटिंग विकास',
  'कानूनी / दस्तावेज़', 'साइट रखरखाव', 'अन्य'];
const METHODS = ['नकद', 'UPI', 'बैंक ट्रांसफर', 'चेक', 'अन्य'];
const BUCKET = 'sk-receipts';

let db, user, me, busy = false, rows = [], receiptsByExp = new Map(), tab = null;

function show(text, type = '') {
  const m = $('message'); m.hidden = false; m.className = 'notice ' + type; m.textContent = text;
  if (type === 'error') m.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
const errText = e => {
  const msg = String(e?.message || e || 'अज्ञात त्रुटि');
  if (/VERSION_CHANGED/.test(msg)) return 'आपके देखने के बाद यह खर्च बदला गया। सूची रिफ्रेश कर दी है — दोबारा देखें।';
  if (/failed to fetch|network/i.test(msg)) return 'इंटरनेट/सेवा से संपर्क नहीं हुआ। दोबारा कोशिश करें।';
  if (/invalid login/i.test(msg)) return 'ईमेल या पासवर्ड गलत है।';
  return msg.replace(/^.*?ERROR:\s*/, '');
};
function setBusy(v) { busy = v; document.querySelectorAll('button').forEach(b => { if (!b.closest('#modal')) b.disabled = v; }); }
function dialog({ title, html, ok = 'ठीक है', danger = false, onOk }) {
  return new Promise(resolve => {
    $('modalTitle').textContent = title; $('modalBody').innerHTML = html;
    const okBtn = $('modalOk'); okBtn.textContent = ok; okBtn.className = danger ? 'danger' : ''; okBtn.disabled = false;
    const close = v => { $('modal').hidden = true; okBtn.onclick = $('modalCancel').onclick = null; resolve(v); };
    okBtn.onclick = async () => { okBtn.disabled = true; const r = onOk ? await onOk() : true; okBtn.disabled = false; if (r !== false) close(true); };
    $('modalCancel').onclick = () => close(false);
    $('modal').hidden = false; okBtn.focus();
  });
}
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('modal').hidden) $('modalCancel').click(); });
const todayIST = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const when = t => t ? new Date(t).toLocaleString('hi-IN', { timeZone: 'Asia/Kolkata', dateStyle: 'medium', timeStyle: 'short' }) : '';

// ---------- प्रारंभ
const validConfig = /^https:\/\/[a-z0-9-]+\.supabase\.co\/?$/i.test(cfg.url || '')
  && typeof cfg.anonKey === 'string' && cfg.anonKey.length > 40 && !/PASTE|YOUR/i.test(cfg.anonKey + cfg.url);
if (!validConfig || !window.supabase?.createClient) {
  $('setup').hidden = false;
  if (validConfig) $('setup').textContent = 'ऑनलाइन सेवा लोड नहीं हुई। नेटवर्क जाँचकर पेज फिर खोलें।';
} else {
  db = window.supabase.createClient(cfg.url, cfg.anonKey, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false } });
  init();
}

function fillSelect(el, items, first) {
  el.innerHTML = (first ? `<option value="">${esc(first)}</option>` : '') + items.map(i => `<option>${esc(i)}</option>`).join('');
}

function init() {
  fillSelect($('fCategory'), CATEGORIES, 'चुनें…'); fillSelect($('fMethod'), METHODS, 'चुनें…');
  fillSelect($('qCategory'), CATEGORIES, 'सभी');
  $('fDate').max = todayIST(); $('fDate').min = '2024-01-01'; $('fDate').value = todayIST();
  let signup = false;
  $('toggleAuth').onclick = () => {
    signup = !signup;
    $('authTitle').textContent = signup ? 'नया अकाउंट बनाएँ' : 'सदस्य लॉगिन';
    $('authBtn').textContent = signup ? 'अकाउंट बनाएँ' : 'लॉगिन';
    $('toggleAuth').textContent = signup ? 'पहले से अकाउंट है — लॉगिन करूँ' : 'नया हूँ — अकाउंट बनाऊँ';
    $('password').autocomplete = signup ? 'new-password' : 'current-password';
  };
  $('authForm').onsubmit = async e => {
    e.preventDefault(); if (busy) return; setBusy(true);
    try {
      const creds = { email: $('email').value.trim(), password: $('password').value };
      if (signup) {
        if (creds.password.length < 10) throw Error('पासवर्ड कम से कम 10 अक्षर का रखें।');
        const { data, error } = await db.auth.signUp(creds); if (error) throw error;
        if (!data.session) { show('अकाउंट बना। ईमेल में आए link से पुष्टि करें, फिर लॉगिन करके जुड़ने का अनुरोध भेजें।', 'success'); return; }
      } else {
        const { error } = await db.auth.signInWithPassword(creds); if (error) throw error;
      }
      $('password').value = ''; $('message').hidden = true; await refresh();
    } catch (err) { show(errText(err), 'error'); } finally { setBusy(false); }
  };
  $('signOut').onclick = async () => { await db.auth.signOut(); location.reload(); };
  $('joinForm').onsubmit = async e => {
    e.preventDefault(); if (busy) return; setBusy(true);
    try {
      const { error } = await db.rpc('sk_request_membership', { p_name: $('joinName').value.trim() });
      if (error) throw error; show('अनुरोध भेज दिया गया। Admin की मंज़ूरी के बाद रजिस्टर खुलेगा।', 'success'); await refresh();
    } catch (err) { show(errText(err), 'error'); } finally { setBusy(false); }
  };
  $('addForm').onsubmit = addExpense;
  $('applyFilter').onclick = () => loadRegister();
  $('clearFilter').onclick = () => { ['qFrom', 'qTo', 'qPayer'].forEach(i => $(i).value = ''); $('qCategory').value = ''; loadRegister(); };
  $('csvExpenses').onclick = exportExpenses; $('csvAudit').onclick = exportAudit; $('csvMembers').onclick = exportMembers;
  $('listReceipts').onclick = listAllReceipts;
  refresh().catch(e => show('सेवा से संपर्क नहीं हुआ: ' + errText(e), 'error'));
}

// हर बड़े कदम पर सदस्यता/अधिकार database से ताज़ा पढ़ें (Admin के बदलाव तुरंत लागू)
async function refresh() {
  const { data: { user: u } } = await db.auth.getUser();
  user = u || null; me = null;
  $('signOut').hidden = !user; $('loginBox').hidden = !!user;
  if (!user) { $('joinBox').hidden = true; $('workspace').hidden = true; return; }
  const { data, error } = await db.from('sk_members')
    .select('display_name,status,is_admin,can_read,can_write,can_correct,decision_note').eq('user_id', user.id).maybeSingle();
  if (error) { show('सदस्यता नहीं पढ़ सके: ' + errText(error), 'error'); return; }
  me = data;
  const active = me?.status === 'active';
  $('joinBox').hidden = active; $('workspace').hidden = !active;
  if (!active) {
    const st = me?.status;
    $('joinState').textContent = !me ? 'आप अभी सदस्य नहीं हैं। अपना नाम भेजकर अनुरोध करें।'
      : st === 'pending' ? `अनुरोध Pending है ("${me.display_name}")। Admin की मंज़ूरी का इंतज़ार करें। नाम बदलना हो तो दोबारा भेजें।`
      : st === 'rejected' ? 'आपका पिछला अनुरोध अस्वीकृत हुआ।' + (me.decision_note ? ` कारण: ${me.decision_note}` : '') + ' चाहें तो नया अनुरोध भेजें।'
      : 'आपकी पहुँच हटा दी गई है। ज़रूरत हो तो Admin से बात करके नया अनुरोध भेजें।';
    if (me?.display_name) $('joinName').value = me.display_name;
    return;
  }
  const r = { read: me.is_admin || me.can_read, write: me.is_admin || me.can_write, correct: me.is_admin || me.can_correct };
  $('identity').textContent = `${me.display_name} · ${me.is_admin ? 'Admin' : 'सदस्य'} · अधिकार: ` +
    [r.read && 'Read', r.write && 'Write', r.correct && 'सुधार'].filter(Boolean).join(', ');
  const tabs = [r.write && ['add', 'खर्च जोड़ें'], (r.read || r.correct) && ['register', 'रजिस्टर'],
    me.is_admin && ['members', 'सदस्य'], me.is_admin && ['export', 'CSV / समापन']].filter(Boolean);
  if (!tabs.some(t => t[0] === tab)) tab = tabs[0]?.[0] || null;
  $('tabs').innerHTML = tabs.map(([k, t]) => `<button type="button" data-t="${k}" class="${k === tab ? 'on' : ''}">${t}</button>`).join('');
  $('tabs').querySelectorAll('button').forEach(b => b.onclick = () => { tab = b.dataset.t; refresh(); });
  ['add', 'register', 'members', 'export'].forEach(v => $('v-' + v).hidden = v !== tab);
  if (!tabs.length) show('आपके पास अभी कोई अधिकार नहीं है। Admin से संपर्क करें।', 'error');
  $('summaryCard').hidden = !r.read;
  if (tab === 'register') await loadRegister();
  if (tab === 'members') await loadMembers();
}

// ---------- खर्च जोड़ना
async function prepareFiles(list) {
  const files = Array.from(list || []);
  if (files.length > 5) throw Error('एक बार में अधिकतम 5 रसीदें।');
  const out = [];
  for (const f of files) {
    const mime = expectedMime(f.name, f.type);
    if (!mime) throw Error(`"${f.name}": केवल JPG, PNG, WEBP, PDF, DOCX।`);
    const r = inspectFile(new Uint8Array(await f.arrayBuffer()), f.name);
    if (!r.ok) throw Error(`"${f.name}": ${r.reason}`);
    out.push({ file: f, mime: r.mime, ext: extOf(f.name) === 'jpeg' ? 'jpg' : extOf(f.name) });
  }
  return out;
}

async function uploadReceipts(expenseId, files) {
  let ok = 0;
  for (const { file, mime, ext } of files) {
    const path = `${user.id}/${expenseId}/${crypto.randomUUID()}.${ext}`;
    const { error: upErr } = await db.storage.from(BUCKET).upload(path, file, { upsert: false, contentType: mime, cacheControl: '0' });
    if (upErr) throw Error(`"${file.name}" अपलोड नहीं हुई: ${errText(upErr)}`);
    const { data: rid, error: aErr } = await db.rpc('sk_attach_receipt', { p_expense_id: expenseId, p_storage_path: path, p_original_filename: file.name.slice(0, 255) });
    if (aErr) throw Error(`"${file.name}" खर्च से नहीं जुड़ी: ${errText(aErr)}`);
    ok++;
    db.functions.invoke('verify-receipt', { body: { receipt_id: rid } }).catch(() => {}); // जाँच server पर; विफलता से एंट्री नहीं रुकती
  }
  return ok;
}

async function addExpense(e) {
  e.preventDefault(); if (busy) return;
  try {
    const d = $('fDate').value, paise = toPaise($('fAmount').value);
    if (!d || d > todayIST()) throw Error('सही तारीख भरें (भविष्य की नहीं)।');
    if (paise === null || paise <= 0n || paise > 10000000000n) throw Error('राशि सही भरें: जैसे 2450 या 2450.50 (अधिकतम ₹10 करोड़, दो दशमलव तक)।');
    const item = $('fItem').value.trim(), payer = $('fPayer').value.trim();
    if (!$('fCategory').value || !$('fMethod').value || item.length < 2 || payer.length < 2) throw Error('सभी * वाले खाने भरें।');
    const files = await prepareFiles($('fReceipt').files);
    setBusy(true);
    const { data, error } = await db.rpc('sk_add_expense', { p_date: d, p_item: item, p_category: $('fCategory').value,
      p_amount: paiseToText(paise), p_payer: payer, p_method: $('fMethod').value });
    if (error) throw error;
    const added = Array.isArray(data) ? data[0] : data;
    let msg = `${ref(added.ref_no)} सहेजा गया: ${rupee(paise)}।`;
    if (files.length) {
      try { msg += ` ${await uploadReceipts(added.id, files)} रसीद जुड़ी।`; }
      catch (err) { show(`${msg}\nपर रसीद पूरी नहीं जुड़ी — ${err.message}\nखर्च सुरक्षित है; सुधार-अधिकार वाले सदस्य/Admin बाद में रसीद जोड़ सकते हैं।`, 'error'); return; }
    }
    $('addForm').reset(); $('fDate').value = todayIST();
    $('addedList').insertAdjacentHTML('afterbegin', `<div>✓ ${esc(msg)}</div>`);
    show(msg, 'success');
  } catch (err) { show(errText(err), 'error'); } finally { setBusy(false); }
}

// ---------- रजिस्टर: फ़िल्टर, कुल, सूची
const filters = () => ({ from: $('qFrom').value || null, to: $('qTo').value || null,
  cat: $('qCategory').value || null, payer: $('qPayer').value.trim() || null });

async function loadRegister() {
  const f = filters();
  let qy = db.from('sk_expenses').select('id,ref_no,expense_date,item,category,amount,payer,payment_method,status,version,created_by,created_by_name,created_at,updated_by_name,updated_at,cancel_reason,cancelled_at')
    .order('expense_date', { ascending: false }).order('ref_no', { ascending: false }).limit(2000);
  if (f.from) qy = qy.gte('expense_date', f.from); if (f.to) qy = qy.lte('expense_date', f.to);
  if (f.cat) qy = qy.eq('category', f.cat); if (f.payer) qy = qy.eq('payer', f.payer);
  const [{ data, error }, { data: rc }] = await Promise.all([qy, db.from('sk_receipts').select('id,expense_id,storage_path,original_filename,verification_status,verification_note')]);
  if (error) { show('रजिस्टर नहीं खुला: ' + errText(error), 'error'); return; }
  rows = data || [];
  receiptsByExp = new Map(); (rc || []).forEach(r => { if (!receiptsByExp.has(r.expense_id)) receiptsByExp.set(r.expense_id, []); receiptsByExp.get(r.expense_id).push(r); });
  if (me.is_admin || me.can_read) await loadSummary(f);
  const canCorrect = me.is_admin || me.can_correct;
  $('listTitle').textContent = `खर्च (${rows.length})`;
  $('entries').innerHTML = rows.map(r => {
    const rec = (receiptsByExp.get(r.id) || []).map(p => `<button type="button" class="secondary rcBtn" data-path="${esc(p.storage_path)}" style="margin:6px 6px 0 0">📎 ${esc(p.original_filename)}</button>` +
      `<span class="badge ${p.verification_status === 'verified' ? '' : p.verification_status === 'rejected' ? 'b-no' : 'b-warn'}">${p.verification_status === 'verified' ? 'जाँची ✓' : p.verification_status === 'rejected' ? 'अमान्य' : 'जाँच बाकी'}</span>`).join(' ');
    return `<div class="item ${r.status}" id="it-${esc(r.id)}">
      <div class="row"><b>${esc(r.item)}</b><span class="amount">${rupee(r.amount)}</span></div>
      ${r.status === 'cancelled' ? `<span class="badge b-no">रद्द</span> <small>कारण: ${esc(r.cancel_reason)}</small>` : ''}
      <span class="ref">${ref(r.ref_no)} · ${esc(r.expense_date)} · ${esc(r.category)} · ${esc(r.payer)} · ${esc(r.payment_method)}</span>
      <small>दर्ज: ${esc(r.created_by_name)}, ${when(r.created_at)}${r.updated_by_name && r.updated_at !== r.created_at ? ` · अंतिम बदलाव: ${esc(r.updated_by_name)}, ${when(r.updated_at)}` : ''}</small>
      <div>${rec}</div>
      <div class="row" style="margin-top:8px">
        ${canCorrect && r.status === 'active' ? `<button type="button" class="secondary fixBtn" data-id="${esc(r.id)}">सुधारें</button>
          <button type="button" class="secondary cancelBtn" data-id="${esc(r.id)}">रद्द करें</button>` : ''}
        <button type="button" class="secondary histBtn" data-id="${esc(r.id)}" style="flex:0 0 auto">इतिहास</button>
      </div><div class="audit" id="au-${esc(r.id)}" hidden></div></div>`;
  }).join('') || 'इस फ़िल्टर में कोई खर्च नहीं।';
  const find = id => rows.find(x => x.id === id);
  document.querySelectorAll('.rcBtn').forEach(b => b.onclick = () => openReceipt(b));
  document.querySelectorAll('.fixBtn').forEach(b => b.onclick = () => correctDialog(find(b.dataset.id)));
  document.querySelectorAll('.cancelBtn').forEach(b => b.onclick = () => cancelDialog(find(b.dataset.id)));
  document.querySelectorAll('.histBtn').forEach(b => b.onclick = () => toggleHistory(b.dataset.id));
}

async function loadSummary(f) {
  const { data, error } = await db.rpc('sk_summary', { p_from: f.from, p_to: f.to, p_category: f.cat, p_payer: f.payer });
  if (error) { $('totals').textContent = errText(error); return null; }
  const pick = k => (data || []).filter(x => x.kind === k);
  const t = pick('total')[0] || { entries: 0, total: '0' }, c = pick('cancelled')[0] || { entries: 0, total: '0' };
  $('totals').innerHTML = `<div><span>सक्रिय कुल (${t.entries})</span><b id="activeTotal">${rupee(t.total)}</b></div>
    <div><span>रद्द (${c.entries}) — कुल से बाहर</span><b>${rupee(c.total)}</b></div>`;
  const tbl = list => `<tr><th></th><th class="n">एंट्री</th><th class="n">राशि</th></tr>` +
    list.map(x => `<tr><td>${esc(x.key)}</td><td class="n">${x.entries}</td><td class="n">${rupee(x.total)}</td></tr>`).join('');
  $('byMonth').innerHTML = tbl(pick('month')); $('byCategory').innerHTML = tbl(pick('category'));
  return t;
}

async function openReceipt(b) {
  b.disabled = true;
  try {
    const { data, error } = await db.storage.from(BUCKET).createSignedUrl(b.dataset.path, 60);
    if (error) throw error; window.open(data.signedUrl, '_blank', 'noopener,noreferrer');
  } catch (e) { show('रसीद नहीं खुली: ' + errText(e), 'error'); } finally { b.disabled = false; }
}

async function toggleHistory(id) {
  const box = $('au-' + id);
  if (!box.hidden) { box.hidden = true; return; }
  const { data, error } = await db.from('sk_expense_audit').select('action,actor_name,at,reason,old_data,new_data').eq('expense_id', id).order('at');
  const A = { created: 'दर्ज', corrected: 'सुधारा', cancelled: 'रद्द', receipt_attached: 'रसीद जुड़ी', receipt_verified: 'रसीद जाँची ✓', receipt_rejected: 'रसीद अमान्य' };
  const F = { expense_date: 'तारीख', item: 'मद', category: 'श्रेणी', amount: 'राशि', payer: 'भुगतानकर्ता', payment_method: 'तरीका' };
  box.innerHTML = error ? esc(errText(error)) : (data || []).map(a => {
    const diff = a.action === 'corrected' && a.old_data && a.new_data ? Object.keys(F).filter(k => String(a.old_data[k]) !== String(a.new_data[k]))
      .map(k => `${F[k]}: ${esc(k === 'amount' ? rupee(a.old_data[k]) : a.old_data[k])} → ${esc(k === 'amount' ? rupee(a.new_data[k]) : a.new_data[k])}`).join('; ') : '';
    return `${when(a.at)} — <b>${A[a.action] || esc(a.action)}</b> (${esc(a.actor_name || '')})${a.reason ? ' · कारण: ' + esc(a.reason) : ''}${diff ? '<br>' + diff : ''}`;
  }).join('<br>') || 'कोई रिकॉर्ड नहीं';
  box.hidden = false;
}

function correctDialog(r) {
  if (!r) return;
  const sel = (items, v) => items.map(i => `<option${i === v ? ' selected' : ''}>${esc(i)}</option>`).join('');
  dialog({
    title: `सुधार: ${ref(r.ref_no)}`, ok: 'सुधार सहेजें',
    html: `<div class="grid"><div><label for="cDate">तारीख</label><input id="cDate" type="date" max="${todayIST()}" value="${esc(r.expense_date)}"></div>
      <div><label for="cAmount">राशि (₹)</label><input id="cAmount" inputmode="decimal" value="${esc(paiseToText(toPaise(Number(r.amount).toFixed(2))))}"></div>
      <div><label for="cCategory">श्रेणी</label><select id="cCategory">${sel(CATEGORIES, r.category)}</select></div>
      <div><label for="cMethod">तरीका</label><select id="cMethod">${sel(METHODS, r.payment_method)}</select></div></div>
      <label for="cItem">मद</label><input id="cItem" maxlength="200" value="${esc(r.item)}">
      <label for="cPayer">भुगतानकर्ता</label><input id="cPayer" maxlength="100" list="payers" value="${esc(r.payer)}">
      <label for="cReason">सुधार का कारण * (कम से कम 5 अक्षर)</label><textarea id="cReason" maxlength="500"></textarea>
      <small>पुरानी और नई जानकारी, आपका नाम और समय रिकॉर्ड में सुरक्षित रहेंगे। यही संस्करण (${r.version}) बदलेगा।</small>`,
    onOk: async () => {
      const p = toPaise($('cAmount').value), reason = $('cReason').value.trim();
      if (reason.length < 5) { $('cReason').focus(); return false; }
      if (p === null || p <= 0n) { $('cAmount').focus(); return false; }
      const { error } = await db.rpc('sk_correct_expense', { p_id: r.id, p_expected_version: r.version, p_date: $('cDate').value,
        p_item: $('cItem').value.trim(), p_category: $('cCategory').value, p_amount: paiseToText(p), p_payer: $('cPayer').value.trim(),
        p_method: $('cMethod').value, p_reason: reason });
      if (error) show('सुधार नहीं हुआ: ' + errText(error), 'error'); else show(`${ref(r.ref_no)} सुधारा गया।`, 'success');
      await refresh(); return true;
    },
  });
}

function cancelDialog(r) {
  if (!r) return;
  dialog({
    title: `रद्द करें: ${ref(r.ref_no)} (${rupee(r.amount)})`, ok: 'रद्द करें', danger: true,
    html: `<p>रद्द खर्च रिकॉर्ड में दिखता रहेगा, पर सक्रिय कुल से बाहर हो जाएगा। यह वापस नहीं होगा।</p>
      <label for="xReason">रद्द करने का कारण * (कम से कम 5 अक्षर)</label><textarea id="xReason" maxlength="500"></textarea>`,
    onOk: async () => {
      const reason = $('xReason').value.trim(); if (reason.length < 5) { $('xReason').focus(); return false; }
      const { error } = await db.rpc('sk_cancel_expense', { p_id: r.id, p_expected_version: r.version, p_reason: reason });
      if (error) show('रद्द नहीं हुआ: ' + errText(error), 'error'); else show(`${ref(r.ref_no)} रद्द किया गया।`, 'success');
      await refresh(); return true;
    },
  });
}

// ---------- Admin: सदस्य
async function loadMembers() {
  const { data, error } = await db.from('sk_members').select('user_id,display_name,status,is_admin,can_read,can_write,can_correct,requested_at,decided_at,decision_note').order('requested_at');
  if (error) { show(errText(error), 'error'); return; }
  const box = (m, pre) => `<span class="rights">${[['r', 'Read', m.can_read], ['w', 'Write', m.can_write], ['c', 'सुधार', m.can_correct]]
    .map(([k, t, v]) => `<label><input type="checkbox" id="${pre}${k}-${esc(m.user_id)}"${v ? ' checked' : ''}> ${t}</label>`).join('')}</span>`;
  const pend = data.filter(m => m.status === 'pending'), act = data.filter(m => m.status === 'active'), closed = data.filter(m => ['rejected', 'removed'].includes(m.status));
  $('pendingList').innerHTML = pend.map(m => `<div class="item"><b>${esc(m.display_name)}</b> <small>अनुरोध: ${when(m.requested_at)}</small>
      ${box({ ...m, can_read: true }, 'p')}<input id="pn-${esc(m.user_id)}" placeholder="टिप्पणी (वैकल्पिक)" maxlength="300">
      <div class="row" style="margin-top:8px"><button type="button" class="apBtn" data-u="${esc(m.user_id)}">मंज़ूर करें</button>
      <button type="button" class="secondary rjBtn" data-u="${esc(m.user_id)}">अस्वीकार करें</button></div></div>`).join('') || 'कोई pending अनुरोध नहीं।';
  $('activeList').innerHTML = act.map(m => `<div class="item"><b>${esc(m.display_name)}</b>${m.is_admin ? ' <span class="badge">Admin</span>' : ''}
      ${m.is_admin ? '<small>Admin के सभी अधिकार स्थायी हैं।</small>' : `${box(m, 'a')}
      <div class="row"><button type="button" class="secondary saveBtn" data-u="${esc(m.user_id)}">अधिकार सहेजें</button>
      <button type="button" class="danger rmBtn" data-u="${esc(m.user_id)}">पहुँच हटाएँ</button></div>`}</div>`).join('');
  $('closedList').innerHTML = closed.map(m => `<div>${esc(m.display_name)} — ${m.status === 'rejected' ? 'अस्वीकृत' : 'हटाया गया'} ${when(m.decided_at)}${m.decision_note ? ' · ' + esc(m.decision_note) : ''}</div>`).join('') || 'कोई नहीं।';
  const rights = (u, pre) => ['r', 'w', 'c'].map(k => $(`${pre}${k}-${u}`).checked);
  const call = async (fn, args, okMsg) => {
    setBusy(true);
    try { const { error } = await db.rpc(fn, args); if (error) throw error; show(okMsg, 'success'); }
    catch (e) { show(errText(e), 'error'); } finally { setBusy(false); await loadMembers(); }
  };
  document.querySelectorAll('.apBtn').forEach(b => b.onclick = () => {
    const [r, w, c] = rights(b.dataset.u, 'p');
    if (!(r || w || c)) { show('कम से कम एक अधिकार चुनें।', 'error'); return; }
    if (c && !r) show('ध्यान दें: सुधार के साथ Read न हो तो सदस्य कुल/फ़िल्टर नहीं देख पाएगा।', '');
    call('sk_admin_decide', { p_user: b.dataset.u, p_approve: true, p_read: r, p_write: w, p_correct: c, p_note: $('pn-' + b.dataset.u).value || null }, 'सदस्य मंज़ूर।');
  });
  document.querySelectorAll('.rjBtn').forEach(b => b.onclick = () =>
    call('sk_admin_decide', { p_user: b.dataset.u, p_approve: false, p_read: false, p_write: false, p_correct: false, p_note: $('pn-' + b.dataset.u).value || null }, 'अनुरोध अस्वीकृत।'));
  document.querySelectorAll('.saveBtn').forEach(b => b.onclick = () => {
    const [r, w, c] = rights(b.dataset.u, 'a');
    call('sk_admin_set_rights', { p_user: b.dataset.u, p_read: r, p_write: w, p_correct: c, p_note: null }, 'अधिकार बदले — सदस्य की अगली कार्रवाई से लागू।');
  });
  document.querySelectorAll('.rmBtn').forEach(b => b.onclick = () => dialog({
    title: 'पहुँच हटाएँ?', danger: true, ok: 'हटाएँ',
    html: '<p>सदस्य तुरंत खर्च और रसीदें नहीं देख पाएगा। उसकी पुरानी एंट्रियाँ रिकॉर्ड में रहेंगी।</p><label for="rmNote">कारण (वैकल्पिक)</label><input id="rmNote" maxlength="300">',
    onOk: async () => { await call('sk_admin_remove', { p_user: b.dataset.u, p_note: $('rmNote').value || null }, 'पहुँच हटा दी गई।'); return true; },
  }));
  const { data: au } = await db.from('sk_member_audit').select('member_id,action,at,note,new_data').order('at', { ascending: false }).limit(200);
  const names = new Map(data.map(m => [m.user_id, m.display_name]));
  const A = { admin_bootstrap: 'Admin तय', requested: 'अनुरोध', approved: 'मंज़ूर', rejected: 'अस्वीकृत', rights_changed: 'अधिकार बदले', removed: 'पहुँच हटाई' };
  $('memberAudit').innerHTML = (au || []).map(a => `${when(a.at)} — ${esc(names.get(a.member_id) || a.member_id)}: <b>${A[a.action] || esc(a.action)}</b>` +
    (a.new_data ? ` (R:${a.new_data.can_read ? '✓' : '✗'} W:${a.new_data.can_write ? '✓' : '✗'} सुधार:${a.new_data.can_correct ? '✓' : '✗'})` : '') + (a.note ? ' · ' + esc(a.note) : '')).join('<br>');
}

// ---------- Admin: CSV और समापन
function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 2000);
}
const stamp = () => todayIST();

async function exportExpenses() {
  setBusy(true);
  try {
    const { data, error } = await db.from('sk_expenses').select('*').order('ref_no').limit(10000);
    if (error) throw error;
    const csv = expensesCsv(data);
    const { data: s, error: sErr } = await db.rpc('sk_summary', {});
    if (sErr) throw sErr;
    const screen = toPaise((s.find(x => x.kind === 'total') || { total: '0' }).total), fromCsv = csvActiveTotalPaise(csv);
    const ok = screen === fromCsv;
    $('reconcile').hidden = false; $('reconcile').className = 'notice ' + (ok ? 'success' : 'error');
    $('reconcile').textContent = `${data.length} पंक्तियाँ। CSV का सक्रिय कुल ${rupee(fromCsv)} · database/स्क्रीन का सक्रिय कुल ${rupee(screen)} — ` +
      (ok ? 'मिलान सही ✓' : 'मेल नहीं खाता! CSV साझा न करें, Admin जाँच करें।');
    download(`surya-kunj-kharch-register-${stamp()}.csv`, csv);
  } catch (e) { show('CSV नहीं बना: ' + errText(e), 'error'); } finally { setBusy(false); }
}
async function exportAudit() {
  const { data, error } = await db.from('sk_expense_audit').select('*').order('id').limit(50000);
  if (error) { show(errText(error), 'error'); return; }
  download(`surya-kunj-badlav-record-${stamp()}.csv`, toCsv([['क्रम', 'खर्च id', 'रसीद id', 'कार्रवाई', 'करने वाला', 'समय', 'कारण', 'पुरानी जानकारी', 'नई जानकारी'],
    ...data.map(a => [a.id, a.expense_id, a.receipt_id || '', a.action, a.actor_name || '', a.at, a.reason || '', JSON.stringify(a.old_data || ''), JSON.stringify(a.new_data || '')])]));
}
async function exportMembers() {
  const { data, error } = await db.from('sk_member_audit').select('*').order('id').limit(50000);
  if (error) { show(errText(error), 'error'); return; }
  download(`surya-kunj-sadasya-record-${stamp()}.csv`, toCsv([['क्रम', 'सदस्य id', 'कार्रवाई', 'Admin/करने वाला id', 'समय', 'टिप्पणी', 'नई स्थिति'],
    ...data.map(a => [a.id, a.member_id, a.action, a.actor || '', a.at, a.note || '', JSON.stringify(a.new_data || '')])]));
}
async function listAllReceipts() {
  const { data, error } = await db.from('sk_receipts').select('expense_id,storage_path,original_filename,created_at').order('created_at');
  if (error) { show(errText(error), 'error'); return; }
  const refs = new Map(rows.map(r => [r.id, r.ref_no]));
  const out = [];
  for (const r of data) {
    const { data: s } = await db.storage.from(BUCKET).createSignedUrl(r.storage_path, 300, { download: r.original_filename });
    out.push(`<div>${refs.has(r.expense_id) ? ref(refs.get(r.expense_id)) + ' · ' : ''}${s ? `<a href="${esc(s.signedUrl)}" target="_blank" rel="noopener noreferrer">${esc(r.original_filename)}</a>` : esc(r.original_filename) + ' (link नहीं बना)'}</div>`);
  }
  $('receiptList').innerHTML = out.join('') || 'कोई रसीद नहीं।';
}
