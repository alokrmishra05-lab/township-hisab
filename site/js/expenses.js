// सूर्य कुंज | साइट खर्च — Supabase Auth + RLS + निजी Storage + server-side फ़ाइल जाँच
// नियम database में लागू हैं; यह UI केवल उन्हें आसान बनाता है।
import { inspectFile, expectedMime, extOf } from './filecheck.js';

const $ = id => document.getElementById(id);
const cfg = window.SITE_EXPENSE_CONFIG || {};
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = n => '₹' + Number(n || 0).toLocaleString('en-IN', { maximumFractionDigits: 2 });
const refNo = n => 'SE-' + String(n).padStart(6, '0');
const STATUS = { pending: 'जाँच बाकी', approved: 'स्वीकृत', rejected: 'अस्वीकृत' };
const PAYER = { partner: 'साझेदार', site_cash: 'साइट कैश', project_fund: 'परियोजना फंड' };
const ROLE = { admin: 'व्यवस्थापक', partner: 'साझेदार', assistant: 'साइट असिस्टेंट' };
const EV = { pending: 'जाँच जारी', verified: 'जाँचा गया ✓', rejected: 'अमान्य फ़ाइल' };
const BUCKET = 'site-expense-evidence';
const PAGE = 50;

let db, user, member, busy = false, editing = null, filter = 'all', page = 0, names = new Map();

// ---------- संदेश व संवाद
function show(text, type = '') {
  const m = $('message'); m.hidden = false; m.className = 'notice ' + type; m.textContent = text;
  if (type === 'error') m.scrollIntoView({ behavior: 'smooth', block: 'center' });
}
const errText = e => {
  const msg = String(e?.message || e || 'अज्ञात त्रुटि');
  if (e?.code === '23505' || /site_expenses_bill_unique|duplicate key/i.test(msg))
    return 'यही बिल/वाउचर नंबर पहले से किसी सक्रिय खर्च में दर्ज है। दोहरी एंट्री नहीं हो सकती।';
  if (/VERSION_CHANGED/.test(msg)) return 'आपके देखने के बाद यह खर्च बदला गया। सूची रिफ्रेश कर दी है — दोबारा जाँचें।';
  if (/failed to fetch|network/i.test(msg)) return 'इंटरनेट/सेवा से संपर्क नहीं हुआ। दोबारा कोशिश करें।';
  return msg.replace(/^.*?ERROR:\s*/, '');
};
function setBusy(v) {
  busy = v;
  ['loginBtn', 'submitBtn', 'refreshBtn', 'moreBtn'].forEach(id => { if ($(id)) $(id).disabled = v; });
}
// prompt/confirm की जगह मोबाइल-अनुकूल संवाद; लौटाता है Promise<boolean>
function dialog({ title, html, ok = 'ठीक है', danger = false, onOk }) {
  return new Promise(resolve => {
    $('modalTitle').textContent = title; $('modalBody').innerHTML = html;
    const okBtn = $('modalOk'); okBtn.textContent = ok; okBtn.className = danger ? 'danger' : '';
    const close = val => { $('modal').hidden = true; okBtn.onclick = $('modalCancel').onclick = null; resolve(val); };
    okBtn.onclick = async () => {
      if (onOk) { const r = await onOk(); if (r === false) return; }
      close(true);
    };
    $('modalCancel').onclick = () => close(false);
    $('modal').hidden = false; okBtn.focus();
  });
}
document.addEventListener('keydown', e => { if (e.key === 'Escape' && !$('modal').hidden) $('modalCancel').click(); });

// ---------- सेटअप
const validConfig = /^https:\/\/[a-z0-9-]+\.supabase\.co\/?$/i.test(cfg.url || '')
  && typeof cfg.anonKey === 'string' && cfg.anonKey.length > 40 && !/PASTE|YOUR/i.test(cfg.anonKey);
if (!validConfig || !window.supabase?.createClient) {
  $('setup').hidden = false;
  if (validConfig) $('setup').textContent = 'ऑनलाइन सेवा लोड नहीं हुई। नेटवर्क जाँचकर पेज फिर खोलें।';
} else {
  db = window.supabase.createClient(cfg.url, cfg.anonKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  });
  init();
}

function todayIST() {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(new Date());
  return p; // YYYY-MM-DD
}

function init() {
  $('date').max = todayIST(); $('date').min = '2020-01-01'; $('date').value = todayIST();
  $('payerType').addEventListener('change', () => {
    const p = $('payerType').value === 'partner';
    $('partnerWrap').hidden = !p; $('partner').required = p; if (!p) $('partner').value = '';
  });
  $('loginForm').addEventListener('submit', login);
  $('signOut').addEventListener('click', async () => { await db.auth.signOut(); location.reload(); });
  $('expenseForm').addEventListener('submit', submitExpense);
  $('cancelEdit').addEventListener('click', resetForm);
  $('refreshBtn').addEventListener('click', () => { if (!busy) loadAll(); });
  $('moreBtn').addEventListener('click', () => { if (!busy) { page++; loadExpenses(true); } });
  refreshSession().catch(e => show('सेवा से संपर्क नहीं हो पाया: ' + errText(e), 'error'));
}

async function login(e) {
  e.preventDefault(); if (busy) return; setBusy(true);
  try {
    const { error } = await db.auth.signInWithPassword({ email: $('email').value.trim(), password: $('password').value });
    if (error) throw error;
    $('password').value = ''; $('message').hidden = true;
    await refreshSession();
  } catch (err) { show('लॉगिन नहीं हुआ: ' + errText(err), 'error'); }
  finally { setBusy(false); }
}

const isReviewer = () => member && (member.role === 'admin' || (member.role === 'partner' && member.can_review));

async function refreshSession() {
  const { data: { user: u } } = await db.auth.getUser();
  user = u || null; member = null;
  if (user) {
    const { data, error } = await db.from('site_expense_members')
      .select('role,display_name,active,can_review').eq('user_id', user.id).maybeSingle();
    if (error) show('सदस्यता नहीं पढ़ सके: ' + errText(error), 'error');
    if (data?.active) member = data;
  }
  $('signOut').hidden = !user; $('loginBox').hidden = !!user; $('workspace').hidden = !member;
  if (user && !member) show('अकाउंट लॉगिन है, पर साइट खर्च की अनुमति नहीं। व्यवस्थापक से सदस्यता जुड़वाएँ।', 'error');
  if (!member) return;
  $('identity').textContent = member.display_name + ' · ' + ROLE[member.role] +
    (isReviewer() ? ' · समीक्षा अधिकार' : '') + (member.role === 'assistant' ? ' · केवल अपनी एंट्री दिखेंगी' : '');
  const f = [['all', 'सभी'], ['pending', 'जाँच बाकी'], ['approved', 'स्वीकृत'], ['rejected', 'अस्वीकृत']];
  if (isReviewer()) f.splice(1, 0, ['review', 'मेरी समीक्षा हेतु']);
  $('filters').innerHTML = f.map(([k, t]) => `<button type="button" class="chip${k === filter ? ' secondary' : ''}" data-f="${k}">${t}</button>`).join('');
  $('filters').querySelectorAll('button').forEach(b => b.onclick = () => { filter = b.dataset.f; refreshSession(); });
  if (member.role !== 'assistant') {
    const { data } = await db.from('site_expense_members').select('user_id,display_name');
    names = new Map((data || []).map(m => [m.user_id, m.display_name]));
  }
  await loadAll();
}

async function loadAll() { page = 0; await Promise.all([loadTotals(), loadExpenses(false)]); }

// ---------- पूरे database से योग (RPC; RLS के अनुसार)
async function loadTotals() {
  const { data, error } = await db.rpc('site_expense_totals');
  if (error) { $('totals').textContent = 'योग नहीं मिला: ' + errText(error); return; }
  const sum = st => (data || []).filter(r => r.status === st).reduce((s, r) => s + Number(r.total), 0);
  const cnt = st => (data || []).filter(r => r.status === st).reduce((s, r) => s + Number(r.entries), 0);
  $('totals').innerHTML = ['approved', 'pending', 'rejected'].map(st =>
    `<div><span>${STATUS[st]} (${cnt(st)})</span><b>${money(sum(st))}</b></div>`).join('');
  const byPayer = Object.keys(PAYER).map(p => {
    const v = (data || []).filter(r => r.status === 'approved' && r.payer_type === p).reduce((s, r) => s + Number(r.total), 0);
    return `${PAYER[p]}: ${money(v)}`;
  }).join(' · ');
  $('totalsNote').textContent = 'स्वीकृत में — ' + byPayer +
    '। यह मॉड्यूल अलग है: मूल हिसाब और साझेदारों की पूँजी पर अपने-आप असर नहीं।' +
    (member.role === 'assistant' ? ' (केवल आपकी एंट्री का योग)' : '');
}

// ---------- सूची
async function loadExpenses(append) {
  let q = db.from('site_expenses')
    .select('id,ref_no,incurred_on,category,description,amount,payer_type,paid_by_partner,payment_method,bill_no,note,status,version,submitted_by,review_note,reviewed_by,reviewed_at,created_at')
    .order('created_at', { ascending: false }).range(page * PAGE, page * PAGE + PAGE);
  if (filter === 'review') q = q.eq('status', 'pending').neq('submitted_by', user.id);
  else if (filter !== 'all') q = q.eq('status', filter);
  const { data, error } = await q;
  if (error) { show('रिकॉर्ड नहीं मिला: ' + errText(error), 'error'); return; }
  const rows = (data || []).slice(0, PAGE);
  $('moreBtn').hidden = (data || []).length <= PAGE;
  const ids = rows.map(r => r.id);
  const { data: proofs, error: pErr } = ids.length
    ? await db.from('site_expense_evidence')
        .select('id,expense_id,storage_path,original_filename,verification_status,verification_note,size_bytes').in('expense_id', ids)
    : { data: [] };
  if (pErr) { show('प्रमाण सूची नहीं खुली: ' + errText(pErr), 'error'); return; }
  const byExp = new Map();
  (proofs || []).forEach(p => { if (!byExp.has(p.expense_id)) byExp.set(p.expense_id, []); byExp.get(p.expense_id).push(p); });

  const html = rows.map(r => renderItem(r, byExp.get(r.id) || [])).join('');
  if (!append) $('entries').innerHTML = html || 'कोई एंट्री नहीं।';
  else $('entries').insertAdjacentHTML('beforeend', html);
  bindItemButtons(rows, byExp);
  // अपने pending खर्चों में अधूरे अपलोड खोजें (storage में है, पर जुड़ा नहीं)
  for (const r of rows.filter(r => r.status === 'pending' && r.submitted_by === user.id)) findOrphans(r, byExp.get(r.id) || []);
}

function renderItem(r, ev) {
  const badge = r.status === 'approved' ? 'b-ok' : r.status === 'rejected' ? 'b-no' : '';
  const payer = r.payer_type === 'partner' ? `साझेदार: ${esc(r.paid_by_partner)}` : PAYER[r.payer_type];
  const who = names.get(r.submitted_by) || (r.submitted_by === user.id ? 'आप' : '');
  const files = ev.map(p => {
    const b = p.verification_status === 'verified' ? 'b-ok' : p.verification_status === 'rejected' ? 'b-no' : '';
    return `<div class="row" style="align-items:center;margin-top:6px">
      <button type="button" class="secondary proofBtn" data-path="${esc(p.storage_path)}" style="flex:2">📎 ${esc(p.original_filename)}</button>
      <span class="badge ${b}" style="flex:0 0 auto" title="${esc(p.verification_note || '')}">${EV[p.verification_status]}</span>
      ${p.verification_status === 'pending' && r.status === 'pending' ? `<button type="button" class="secondary verifyBtn" data-ev="${esc(p.id)}" style="flex:0 0 auto">जाँच चलाएँ</button>` : ''}
    </div>${p.verification_note ? `<small>${esc(p.verification_note)}</small>` : ''}`;
  }).join('') || '<small>प्रमाण संलग्न नहीं है</small>';
  const mine = r.submitted_by === user.id;
  const canEdit = r.status === 'pending' && mine;
  const canReview = r.status === 'pending' && !mine && isReviewer();
  return `<div class="item" id="it-${esc(r.id)}">
    <div class="row" style="align-items:baseline"><span style="font-weight:600">${esc(r.category)}</span>
      <span class="amount" style="text-align:right">${money(r.amount)}</span></div>
    <span class="badge ${badge}">${STATUS[r.status]}</span>
    <span class="ref">${refNo(r.ref_no)} · ${esc(r.incurred_on)} · ${payer} · ${esc(r.payment_method)}${who ? ' · दर्ज: ' + esc(who) : ''}</span>
    <p style="margin:8px 0">${esc(r.description)}</p>
    ${r.bill_no ? `<small>बिल: ${esc(r.bill_no)}</small>` : ''}${r.note ? `<small>टिप्पणी: ${esc(r.note)}</small>` : ''}
    ${r.review_note ? `<small>समीक्षा: ${esc(r.review_note)}</small>` : ''}
    <div>${files}</div><div class="orphans" data-id="${esc(r.id)}"></div>
    <div class="row" style="margin-top:10px">
      ${canEdit ? `<button type="button" class="secondary editBtn" data-id="${esc(r.id)}">एंट्री सुधारें / फ़ाइल जोड़ें</button>` : ''}
      ${canReview ? `<button type="button" class="approveBtn" data-id="${esc(r.id)}">स्वीकृत करें</button>
                     <button type="button" class="secondary rejectBtn" data-id="${esc(r.id)}">अस्वीकृत करें</button>` : ''}
      ${r.status === 'pending' && mine && isReviewer() ? '<small>अपना खर्च दूसरा reviewer स्वीकृत करेगा।</small>' : ''}
      <button type="button" class="secondary historyBtn" data-id="${esc(r.id)}" style="flex:0 0 auto">इतिहास</button>
    </div><div class="audit" id="au-${esc(r.id)}" hidden></div>
  </div>`;
}

function bindItemButtons(rows, byExp) {
  const find = id => rows.find(r => r.id === id);
  document.querySelectorAll('.proofBtn:not([data-b])').forEach(b => { b.dataset.b = 1; b.onclick = () => openProof(b); });
  document.querySelectorAll('.verifyBtn:not([data-b])').forEach(b => { b.dataset.b = 1; b.onclick = () => runVerify(b.dataset.ev, b); });
  document.querySelectorAll('.editBtn:not([data-b])').forEach(b => { b.dataset.b = 1; b.onclick = () => startEdit(find(b.dataset.id), byExp.get(b.dataset.id) || []); });
  document.querySelectorAll('.approveBtn:not([data-b])').forEach(b => { b.dataset.b = 1; b.onclick = () => reviewDialog(find(b.dataset.id), byExp.get(b.dataset.id) || [], true); });
  document.querySelectorAll('.rejectBtn:not([data-b])').forEach(b => { b.dataset.b = 1; b.onclick = () => reviewDialog(find(b.dataset.id), byExp.get(b.dataset.id) || [], false); });
  document.querySelectorAll('.historyBtn:not([data-b])').forEach(b => { b.dataset.b = 1; b.onclick = () => toggleHistory(b.dataset.id); });
}

async function openProof(b) {
  b.disabled = true;
  try {
    const { data, error } = await db.storage.from(BUCKET).createSignedUrl(b.dataset.path, 60);
    if (error) throw error;
    window.open(data.signedUrl, '_blank', 'noopener,noreferrer');
  } catch (e) { show('प्रमाण नहीं खुला: ' + errText(e), 'error'); }
  finally { b.disabled = false; }
}

async function toggleHistory(id) {
  const box = $('au-' + id);
  if (!box.hidden) { box.hidden = true; return; }
  const { data, error } = await db.from('site_expense_audit').select('action,actor_role,at,new_data')
    .eq('expense_id', id).order('at', { ascending: true });
  const A = { created: 'बनाया', edited: 'सुधारा', approved: 'स्वीकृत', rejected: 'अस्वीकृत',
    evidence_attached: 'प्रमाण जुड़ा', evidence_verified: 'प्रमाण जाँचा ✓', evidence_rejected: 'प्रमाण अमान्य' };
  box.innerHTML = error ? esc(errText(error)) : (data || []).map(a =>
    `${new Date(a.at).toLocaleString('hi-IN', { timeZone: 'Asia/Kolkata' })} — ${A[a.action] || esc(a.action)}` +
    `${a.actor_role ? ' (' + (ROLE[a.actor_role] || esc(a.actor_role)) + ')' : a.action.startsWith('evidence_v') || a.action === 'evidence_rejected' ? ' (server जाँच)' : ''}` +
    `${a.action === 'edited' && a.new_data ? ' · राशि ' + money(a.new_data.amount) : ''}`).join('<br>');
  box.hidden = false;
}

// ---------- अधूरे अपलोड की recovery
async function findOrphans(r, ev) {
  const folder = `${user.id}/${r.id}`;
  const { data, error } = await db.storage.from(BUCKET).list(folder, { limit: 100 });
  if (error || !data) return;
  const linked = new Set(ev.map(p => p.storage_path));
  const orphans = data.filter(o => o.name && !linked.has(`${folder}/${o.name}`));
  const box = document.querySelector(`.orphans[data-id="${CSS.escape(r.id)}"]`);
  if (!box || !orphans.length) return;
  box.innerHTML = `<div class="notice" style="margin:8px 0">${orphans.length} फ़ाइल अपलोड हुई पर खर्च से जुड़ी नहीं (अधूरा अपलोड)।
    <button type="button" class="secondary" style="margin-top:8px;width:100%">अधूरी फ़ाइलें जोड़ें</button></div>`;
  box.querySelector('button').onclick = async () => {
    setBusy(true);
    try {
      for (const o of orphans) {
        const { data: evId, error: aErr } = await db.rpc('site_expense_attach_evidence',
          { p_expense_id: r.id, p_storage_path: `${folder}/${o.name}`, p_original_filename: o.name });
        if (aErr) throw aErr;
        await runVerify(evId);
      }
      show('अधूरी फ़ाइलें जुड़ गईं।', 'success'); await loadAll();
    } catch (e) { show('जोड़ नहीं सके: ' + errText(e), 'error'); }
    finally { setBusy(false); }
  };
}

async function runVerify(evidenceId, btn) {
  if (btn) btn.disabled = true;
  try {
    const { data, error } = await db.functions.invoke('verify-evidence', { body: { evidence_id: evidenceId } });
    if (error) throw error;
    if (btn) { show(data?.status === 'verified' ? 'फ़ाइल जाँची गई ✓' : 'फ़ाइल अमान्य: ' + (data?.reason || ''), data?.status === 'verified' ? 'success' : 'error'); await loadAll(); }
    return data?.status;
  } catch (e) {
    if (btn) show('server जाँच अभी नहीं हुई — बाद में "जाँच चलाएँ" दबाएँ। ' + errText(e), 'error');
    return 'pending';
  } finally { if (btn) btn.disabled = false; }
}

// ---------- फ़ॉर्म
function resetForm() {
  $('expenseForm').reset(); $('date').value = todayIST(); $('date').max = todayIST();
  $('partnerWrap').hidden = true; editing = null;
  $('formTitle').textContent = 'नया साइट खर्च जोड़ें';
  $('submitBtn').textContent = 'खर्च समीक्षा के लिए भेजें'; $('cancelEdit').hidden = true;
  $('proofLabel').textContent = 'बिल / फोटो / PDF / Word (DOCX) *';
}

function startEdit(r, ev) {
  if (!r || r.status !== 'pending' || r.submitted_by !== user.id) return;
  editing = { id: r.id, hasProof: ev.length > 0 };
  $('date').value = r.incurred_on; $('amount').value = r.amount; $('category').value = r.category;
  $('payerType').value = r.payer_type; $('payerType').dispatchEvent(new Event('change'));
  $('partner').value = r.paid_by_partner || ''; $('method').value = r.payment_method;
  $('bill').value = r.bill_no || ''; $('description').value = r.description; $('note').value = r.note || '';
  $('proof').value = '';
  $('formTitle').textContent = `सुधार: ${refNo(r.ref_no)}`;
  $('proofLabel').textContent = ev.length ? 'और फ़ाइल जोड़ें (वैकल्पिक)' : 'बिल / फोटो / PDF / Word (DOCX) *';
  $('submitBtn').textContent = 'बदलाव सहेजें'; $('cancelEdit').hidden = false;
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function prepareFiles(list) {
  const files = Array.from(list);
  if (files.length > 5) throw Error('एक बार में अधिकतम 5 फ़ाइलें।');
  const out = [];
  for (const f of files) {
    const mime = expectedMime(f.name, f.type);
    if (!mime) throw Error(`"${f.name}": केवल JPG, PNG, WEBP, PDF, DOCX (पुराना .doc नहीं)।`);
    const bytes = new Uint8Array(await f.arrayBuffer());
    const r = inspectFile(bytes, f.name);
    if (!r.ok) throw Error(`"${f.name}": ${r.reason}`);
    out.push({ file: f, mime: r.mime, ext: extOf(f.name) === 'jpeg' ? 'jpg' : extOf(f.name) });
  }
  return out;
}

async function submitExpense(e) {
  e.preventDefault(); if (busy || !member) return;
  let expenseId = editing?.id || null, step = 'जाँच';
  try {
    const amt = Number($('amount').value);
    if (!Number.isFinite(amt) || amt <= 0 || amt > 100000000) throw Error('सही राशि भरें (₹0.01 से ₹10 करोड़)।');
    const d = $('date').value;
    if (!d) throw Error('तारीख भरें।');
    if (d > todayIST()) throw Error('भविष्य की तारीख नहीं हो सकती।');
    const payerType = $('payerType').value;
    if (!PAYER[payerType]) throw Error('पैसा कहाँ से गया, चुनें।');
    if (payerType === 'partner' && !$('partner').value) throw Error('साझेदार का नाम चुनें।');
    const fields = {
      incurred_on: d, category: $('category').value, description: $('description').value.trim(), amount: amt,
      payer_type: payerType, paid_by_partner: payerType === 'partner' ? $('partner').value : null,
      payment_method: $('method').value, bill_no: $('bill').value.trim() || null, note: $('note').value.trim() || null,
    };
    if (!fields.category || !fields.payment_method || fields.description.length < 3) throw Error('सभी * वाले विवरण भरें।');
    const files = await prepareFiles($('proof').files);
    if (!files.length && !(editing && editing.hasProof)) throw Error('कम से कम एक प्रमाण फ़ाइल लगाएँ।');

    setBusy(true); step = 'खर्च सहेजना';
    if (editing) {
      const { error } = await db.from('site_expenses').update(fields).eq('id', editing.id).select('id').single();
      if (error) throw error;
    } else {
      const { data, error } = await db.from('site_expenses').insert(fields).select('id').single();
      if (error) throw error;
      expenseId = data.id;
    }
    let ok = 0, verified = 0;
    for (const { file, mime, ext } of files) {
      step = `"${file.name}" अपलोड`;
      const path = `${user.id}/${expenseId}/${crypto.randomUUID()}.${ext}`;
      const { error: upErr } = await db.storage.from(BUCKET).upload(path, file, { upsert: false, contentType: mime, cacheControl: '0' });
      if (upErr) throw upErr;
      step = `"${file.name}" को खर्च से जोड़ना`;
      const { data: evId, error: aErr } = await db.rpc('site_expense_attach_evidence',
        { p_expense_id: expenseId, p_storage_path: path, p_original_filename: file.name.slice(0, 255) });
      if (aErr) throw aErr;
      ok++;
      if (await runVerify(evId) === 'verified') verified++;
    }
    resetForm();
    show(`खर्च सुरक्षित हुआ। ${ok} फ़ाइल जुड़ी, ${verified} server पर जाँची गई। स्वीकृति अभी बाकी है।` +
      (ok > verified ? '\nजिन फ़ाइलों की जाँच बाकी है, उनके आगे "जाँच चलाएँ" दबाएँ।' : ''), 'success');
    await loadAll();
  } catch (err) {
    const partial = expenseId && step !== 'खर्च सहेजना' && step !== 'जाँच';
    show((partial ? `खर्च Pending में दर्ज है, पर ${step} पूरा नहीं हुआ। सूची में उस एंट्री पर "अधूरी फ़ाइलें जोड़ें" या "एंट्री सुधारें" से दोबारा कोशिश करें।\n` : '') + errText(err), 'error');
    if (partial) await loadAll();
  } finally { setBusy(false); }
}

// ---------- समीक्षा (version-pinned)
async function reviewDialog(r, ev, approve) {
  if (!r || busy) return;
  const { data: dups } = approve ? await db.rpc('site_expense_duplicates', { p_expense_id: r.id }) : { data: [] };
  const evState = ev.map(p => `${esc(p.original_filename)} — ${EV[p.verification_status]}`).join('<br>') || 'कोई नहीं';
  const blocked = approve && (!ev.some(p => p.verification_status === 'verified') || ev.some(p => p.verification_status !== 'verified'));
  const dupHtml = (dups || []).length ? `<div class="notice error">संभावित दोहराव: ${(dups || []).map(d =>
      `${refNo(d.ref_no)} (${STATUS[d.status]}, ${d.reason === 'same_file' ? 'वही फ़ाइल' : 'वही तारीख+राशि+श्रेणी'})`).join(', ')}
      <label class="check"><input type="checkbox" id="dupOk"> मैंने जाँच लिया है, यह अलग खर्च है</label></div>` : '';
  const html = `<dl class="kv"><dt>क्रमांक</dt><dd>${refNo(r.ref_no)} (संस्करण ${r.version})</dd>
      <dt>राशि</dt><dd>${money(r.amount)}</dd><dt>तारीख</dt><dd>${esc(r.incurred_on)}</dd>
      <dt>श्रेणी</dt><dd>${esc(r.category)}</dd>
      <dt>भुगतान</dt><dd>${r.payer_type === 'partner' ? 'साझेदार: ' + esc(r.paid_by_partner) : PAYER[r.payer_type]} · ${esc(r.payment_method)}</dd>
      <dt>प्रमाण</dt><dd>${evState}</dd></dl>
    ${blocked ? '<div class="notice error">स्वीकृति के लिए सभी प्रमाण server पर "जाँचा गया ✓" होने चाहिए।</div>' : ''}
    ${dupHtml}
    ${approve ? '<small>यही संस्करण स्वीकृत होगा। बीच में कोई बदलाव हुआ तो स्वीकृति अपने-आप रुक जाएगी।</small>'
      : '<label for="rejNote">अस्वीकृति का कारण *</label><textarea id="rejNote" maxlength="500"></textarea>'}`;
  await dialog({
    title: approve ? 'खर्च स्वीकृत करें?' : 'खर्च अस्वीकृत करें?', html,
    ok: approve ? 'स्वीकृत करें' : 'अस्वीकृत करें', danger: !approve,
    onOk: async () => {
      const note = approve ? null : ($('rejNote').value || '').trim();
      if (!approve && note.length < 3) { $('rejNote').focus(); return false; }
      if ((dups || []).length && !$('dupOk')?.checked) { $('dupOk').focus(); return false; }
      setBusy(true);
      try {
        const { error } = await db.rpc('site_expense_review', {
          p_expense_id: r.id, p_expected_version: r.version, p_approve: approve,
          p_note: note, p_confirm_duplicate: !!$('dupOk')?.checked,
        });
        if (error) throw error;
        show(approve ? `${refNo(r.ref_no)} स्वीकृत।` : `${refNo(r.ref_no)} अस्वीकृत।`, 'success');
      } catch (e) { show('समीक्षा नहीं हुई: ' + errText(e), 'error'); }
      finally { setBusy(false); await loadAll(); }
    },
  });
}
