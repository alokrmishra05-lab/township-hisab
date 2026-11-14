// ब्राउज़र UI परीक्षण हेतु नकली Supabase client (नेटवर्क नहीं)। असली नियम SQL परीक्षणों में जाँचे गए हैं;
// यहाँ वही नियम सरल रूप में हैं ताकि UI का व्यवहार जाँचा जा सके। सारा डेटा कृत्रिम।
(() => {
  const ID = { admin: 'u-admin', reader: 'u-reader', writer: 'u-writer', corrector: 'u-corr', pending: 'u-pend', none: 'u-none' };
  const me = ID[window.__WHO || 'admin'];
  const calls = (window.__calls = []);
  const now = () => new Date().toISOString();
  const S = window.__STATE || (window.__STATE = {
    sk_members: [
      { user_id: 'u-admin', display_name: 'आलोक (परीक्षण)', status: 'active', is_admin: true, can_read: true, can_write: true, can_correct: true, requested_at: '2026-11-01T00:00:00Z' },
      { user_id: 'u-reader', display_name: 'पाठक (परीक्षण)', status: 'active', is_admin: false, can_read: true, can_write: false, can_correct: false, requested_at: '2026-11-02T00:00:00Z' },
      { user_id: 'u-writer', display_name: 'लेखक (परीक्षण)', status: 'active', is_admin: false, can_read: false, can_write: true, can_correct: false, requested_at: '2026-11-03T00:00:00Z' },
      { user_id: 'u-corr', display_name: 'सुधारक (परीक्षण)', status: 'active', is_admin: false, can_read: false, can_write: false, can_correct: true, requested_at: '2026-11-04T00:00:00Z' },
      { user_id: 'u-rd', display_name: 'पाठक-दो (परीक्षण)', status: 'active', is_admin: false, can_read: true, can_write: false, can_correct: false, requested_at: '2026-11-05T00:00:00Z' },
      { user_id: 'u-pend', display_name: 'नया सदस्य (परीक्षण)', status: 'pending', is_admin: false, can_read: false, can_write: false, can_correct: false, requested_at: '2026-11-14T00:00:00Z' },
    ],
    sk_expenses: [
      { id: 'e1', ref_no: 1, expense_date: '2026-11-10', item: 'सीमेंट 50 बोरी', category: 'निर्माण सामग्री', amount: 21500.75, payer: 'गगन आचारी', payment_method: 'UPI', status: 'active', version: 2, created_by: 'u-writer', created_by_name: 'लेखक (परीक्षण)', created_at: '2026-11-10T05:00:00Z', updated_at: '2026-11-10T05:00:00Z' },
      { id: 'e2', ref_no: 2, expense_date: '2026-10-05', item: 'बिजली बिल', category: 'बिजली / पानी', amount: 1234.56, payer: 'अमरनाथ पाण्डेय', payment_method: 'बैंक ट्रांसफर', status: 'active', version: 1, created_by: 'u-admin', created_by_name: 'आलोक (परीक्षण)', created_at: '2026-10-05T05:00:00Z', updated_at: '2026-10-05T05:00:00Z' },
      { id: 'e3', ref_no: 3, expense_date: '2026-10-20', item: 'मजदूरी', category: 'मजदूरी', amount: 2400, payer: 'साइट कैश', payment_method: 'नकद', status: 'cancelled', cancel_reason: 'दोहरी एंट्री', version: 3, created_by: 'u-writer', created_by_name: 'लेखक (परीक्षण)', created_at: '2026-10-20T05:00:00Z', updated_at: '2026-10-21T05:00:00Z' },
    ],
    sk_receipts: [{ id: 'r1', expense_id: 'e1', storage_path: 'u-writer/e1/a.pdf', original_filename: 'bill.pdf', verification_status: 'verified', uploaded_by: 'u-writer', created_at: '2026-11-10T05:00:00Z' }],
    sk_expense_audit: [], sk_member_audit: [], seq: 3,
  });
  const meRow = () => S.sk_members.find(m => m.user_id === me);
  const active = () => meRow()?.status === 'active';
  const has = r => active() && (meRow().is_admin || meRow()['can_' + r]);
  const admin = () => active() && meRow().is_admin;
  const P = v => Math.round(Number(v) * 100);
  const txt = p => `${Math.trunc(p / 100)}.${String(p % 100).padStart(2, '0')}`;
  const err = m => ({ data: null, error: { message: m } });
  const visible = t => {
    if (t === 'sk_members') return admin() ? S.sk_members : S.sk_members.filter(m => m.user_id === me);
    if (t === 'sk_expenses' || t === 'sk_expense_audit') return has('read') ? S[t] : [];
    if (t === 'sk_receipts') return S.sk_receipts.filter(r => admin() || (has('read') && has('correct')) || (active() && r.uploaded_by === me));
    if (t === 'sk_member_audit') return admin() ? S.sk_member_audit : [];
    return [];
  };
  function from(t) {
    let rows = [...visible(t)];
    const api = {
      select() { return api; }, order() { return api; }, limit() { return api; },
      eq(k, v) { rows = rows.filter(r => r[k] === v); return api; },
      gte(k, v) { rows = rows.filter(r => r[k] >= v); return api; },
      lte(k, v) { rows = rows.filter(r => r[k] <= v); return api; },
      maybeSingle() { return Promise.resolve({ data: rows[0] || null, error: null }); },
      then(res) { return Promise.resolve({ data: rows.map(r => ({ ...r })), error: null }).then(res); },
    };
    return api;
  }
  const logM = (u, action, note) => S.sk_member_audit.push({ id: S.sk_member_audit.length + 1, member_id: u, action, at: now(), note, new_data: { ...S.sk_members.find(m => m.user_id === u) } });
  const logE = (e, action, reason, o, n) => S.sk_expense_audit.push({ id: S.sk_expense_audit.length + 1, expense_id: e, action, actor_name: meRow()?.display_name, at: now(), reason, old_data: o, new_data: n });
  const rpc = {
    sk_request_membership: ({ p_name }) => { let m = meRow(); if (!m) { m = { user_id: me, status: 'pending', is_admin: false, can_read: false, can_write: false, can_correct: false, requested_at: now() }; S.sk_members.push(m); }
      if (m.status === 'active') return err('आप पहले से सक्रिय सदस्य हैं'); Object.assign(m, { display_name: p_name, status: 'pending' }); logM(me, 'requested'); return { data: 'pending', error: null }; },
    sk_admin_decide: ({ p_user, p_approve, p_read, p_write, p_correct, p_note }) => { if (!admin()) return err('केवल Admin');
      const m = S.sk_members.find(x => x.user_id === p_user); if (!m || m.status !== 'pending') return err('यह अनुरोध pending नहीं है');
      Object.assign(m, { status: p_approve ? 'active' : 'rejected', can_read: p_approve && p_read, can_write: p_approve && p_write, can_correct: p_approve && p_correct, decision_note: p_note, decided_at: now() });
      logM(p_user, p_approve ? 'approved' : 'rejected', p_note); return { data: null, error: null }; },
    sk_admin_set_rights: ({ p_user, p_read, p_write, p_correct }) => { if (!admin()) return err('केवल Admin');
      const m = S.sk_members.find(x => x.user_id === p_user); Object.assign(m, { can_read: p_read, can_write: p_write, can_correct: p_correct }); logM(p_user, 'rights_changed'); return { data: null, error: null }; },
    sk_admin_remove: ({ p_user, p_note }) => { if (!admin()) return err('केवल Admin');
      const m = S.sk_members.find(x => x.user_id === p_user); Object.assign(m, { status: 'removed', can_read: false, can_write: false, can_correct: false, decided_at: now(), decision_note: p_note }); logM(p_user, 'removed', p_note); return { data: null, error: null }; },
    sk_add_expense: a => { if (!has('write')) return err('खर्च जोड़ने का (Write) अधिकार नहीं');
      const e = { id: 'n' + (++S.seq), ref_no: S.seq, expense_date: a.p_date, item: a.p_item, category: a.p_category, amount: Number(a.p_amount), payer: a.p_payer, payment_method: a.p_method, status: 'active', version: 1, created_by: me, created_by_name: meRow().display_name, created_at: now(), updated_at: now() };
      S.sk_expenses.unshift(e); logE(e.id, 'created', null, null, { ...e }); return { data: [{ id: e.id, ref_no: e.ref_no, version: 1 }], error: null }; },
    sk_correct_expense: a => { if (!has('correct')) return err('सुधार का अधिकार नहीं'); if ((a.p_reason || '').length < 5) return err('सुधार का कारण अनिवार्य');
      const e = S.sk_expenses.find(x => x.id === a.p_id); if (e.version !== a.p_expected_version) return err('VERSION_CHANGED: बदला गया');
      const o = { ...e }; Object.assign(e, { expense_date: a.p_date, item: a.p_item, category: a.p_category, amount: Number(a.p_amount), payer: a.p_payer, payment_method: a.p_method, version: e.version + 1, updated_by_name: meRow().display_name, updated_at: now() });
      logE(e.id, 'corrected', a.p_reason, o, { ...e }); return { data: e.version, error: null }; },
    sk_cancel_expense: a => { if (!has('correct')) return err('रद्द करने का (सुधार) अधिकार नहीं'); if ((a.p_reason || '').length < 5) return err('कारण अनिवार्य');
      const e = S.sk_expenses.find(x => x.id === a.p_id); if (e.version !== a.p_expected_version) return err('VERSION_CHANGED');
      const o = { ...e }; Object.assign(e, { status: 'cancelled', cancel_reason: a.p_reason, version: e.version + 1, updated_at: now() }); logE(e.id, 'cancelled', a.p_reason, o, { ...e }); return { data: null, error: null }; },
    sk_summary: a => { if (!has('read')) return err('Read अधिकार नहीं');
      const f = S.sk_expenses.filter(e => (!a.p_from || e.expense_date >= a.p_from) && (!a.p_to || e.expense_date <= a.p_to) && (!a.p_category || e.category === a.p_category) && (!a.p_payer || e.payer === a.p_payer));
      const act = f.filter(e => e.status === 'active'), can = f.filter(e => e.status === 'cancelled');
      const sum = l => txt(l.reduce((s, e) => s + P(e.amount), 0));
      const grp = (l, k) => Object.entries(l.reduce((m, e) => ((m[k(e)] = m[k(e)] || []).push(e), m), {}));
      return { data: [{ kind: 'total', key: 'सक्रिय', entries: act.length, total: sum(act) }, { kind: 'cancelled', key: 'रद्द', entries: can.length, total: sum(can) },
        ...grp(act, e => e.expense_date.slice(0, 7)).map(([k, l]) => ({ kind: 'month', key: k, entries: l.length, total: sum(l) })),
        ...grp(act, e => e.category).map(([k, l]) => ({ kind: 'category', key: k, entries: l.length, total: sum(l) }))], error: null }; },
    sk_open_for_correction: a => { if (!has('correct')) return err('सुधार का अधिकार नहीं');
      const e = S.sk_expenses.find(x => x.ref_no === a.p_ref_no); if (!e) return err('इस क्रमांक का खर्च नहीं मिला');
      (S.opens = S.opens || []).push({ user: me, expense: e.id });
      return { data: { expense: { ...e }, receipts: S.sk_receipts.filter(r => r.expense_id === e.id), history: S.sk_expense_audit.filter(h => h.expense_id === e.id) }, error: null }; },
    sk_reserve_receipt_slot: a => {
      S.slots = S.slots || [];
      const used = S.sk_receipts.filter(r => r.expense_id === a.p_expense_id).length + S.slots.filter(s => s.expense_id === a.p_expense_id && s.status === 'reserved').length;
      if (used >= 5) return err('RECEIPT_LIMIT: एक खर्च में अधिकतम 5 रसीदें (जुड़ी + चल रहे अपलोड)');
      const path = `${me}/${a.p_expense_id}/${crypto.randomUUID()}.${a.p_ext}`;
      S.slots.push({ storage_path: path, expense_id: a.p_expense_id, status: 'reserved', uploaded: false }); return { data: path, error: null }; },
    sk_release_receipt_slot: a => { const s = (S.slots || []).find(x => x.storage_path === a.p_storage_path && x.status === 'reserved');
      if (!s) return err('खुला आरक्षण नहीं मिला'); if (s.uploaded) return err('फ़ाइल चढ़ चुकी है'); s.status = 'released'; return { data: null, error: null }; },
    sk_my_open_slots: () => ({ data: (S.slots || []).filter(s => s.status === 'reserved').map(s => ({ ...s, ref_no: (S.sk_expenses.find(e => e.id === s.expense_id) || {}).ref_no })), error: null }),
    sk_request_password_reset: a => { (S.resets = S.resets || []);
      if (!/^[a-z0-9][a-z0-9._+@-]{2,119}$/.test(String(a.p_login || '').trim().toLowerCase())) return err('यूज़र आईडी सही लिखें');
      S.resets.push({ id: S.resets.length + 1, login: a.p_login.trim().toLowerCase(), note: a.p_note, status: 'open', requested_at: now() }); return { data: null, error: null }; },
    sk_admin_reset_requests: () => { if (!admin()) return err('केवल Admin');
      return { data: (S.resets || []).filter(r => r.status === 'open').map(r => ({ ...r, member_user: r.login === 'writer' ? 'u-writer' : null, member_name: r.login === 'writer' ? 'लेखक (परीक्षण)' : null, member_status: r.login === 'writer' ? 'active' : null, member_is_admin: false })), error: null }; },
    sk_admin_close_reset: a => { if (!admin()) return err('केवल Admin'); const r = (S.resets || []).find(x => x.id === a.p_id && x.status === 'open'); if (!r) return err('यह अनुरोध खुला नहीं है'); r.status = a.p_status; return { data: null, error: null }; },
    sk_attach_receipt: a => { const sl = (S.slots || []).find(x => x.storage_path === a.p_storage_path && x.status === 'reserved');
      if (!sl) return err('इस फ़ाइल का वैध आरक्षण नहीं'); if (window.__FAIL_ATTACH) return err('नेटवर्क टूटा (परीक्षण)'); sl.status = 'attached';
      const r = { id: 'r' + (S.sk_receipts.length + 1), expense_id: a.p_expense_id, storage_path: a.p_storage_path, original_filename: a.p_original_filename, verification_status: 'pending', uploaded_by: me, created_at: now() };
      S.sk_receipts.push(r); logE(a.p_expense_id, 'receipt_attached'); return { data: r.id, error: null }; },
  };
  window.supabase = { createClient: () => ({
    auth: { getUser: async () => ({ data: { user: window.__WHO === 'loggedout' ? null : { id: me } } }),
      signInWithPassword: async c => { calls.push(['signin', c.email]); return { error: null }; }, signUp: async () => ({ data: { session: null }, error: null }), signOut: async () => ({ error: null }) },
    from,
    rpc: async (n, a = {}) => { calls.push(['rpc', n, a]); return rpc[n] ? rpc[n](a) : err('unknown rpc'); },
    storage: { from: () => ({
      upload: async (path, file, o) => { calls.push(['upload', path, o.contentType]);
        const sl = (S.slots || []).find(x => x.storage_path === path && x.status === 'reserved');
        if (window.__FAIL_UPLOAD || !sl) return { error: { message: window.__FAIL_UPLOAD ? 'नेटवर्क टूटा (परीक्षण)' : 'new row violates row-level security policy' } };
        sl.uploaded = true; return { error: null }; },
      remove: async paths => { calls.push(['remove', paths]); paths.forEach(p => { const sl = (S.slots || []).find(x => x.storage_path === p && x.status === 'reserved'); if (sl) sl.uploaded = false; }); return { error: null }; },
      createSignedUrl: async () => ({ data: { signedUrl: 'about:blank' }, error: null }),
    }) },
    functions: { invoke: async (n, o) => { calls.push(['invoke', n, o.body]);
      if (n === 'sk-admin-users' && o.body.action === 'set_password' && o.body.request_id) { const r = (S.resets || []).find(x => x.id === o.body.request_id); if (r) r.status = 'done'; }
      return { data: n === 'sk-admin-users' ? { ok: true } : { status: 'verified' }, error: null }; } },
  }) };
})();
