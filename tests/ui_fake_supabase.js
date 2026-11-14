// UI परीक्षण हेतु नकली Supabase client (कोई नेटवर्क नहीं)। केवल ब्राउज़र टेस्ट में।
(() => {
  const ROLE = window.__ROLE || 'admin';
  const ME = '00000000-0000-0000-0000-0000000000aa', OTHER = '00000000-0000-0000-0000-0000000000bb';
  const calls = (window.__calls = []);
  const db = {
    site_expense_members: [
      { user_id: ME, role: ROLE, display_name: ROLE === 'assistant' ? 'असिस्टेंट' : 'आलोक रंजन मिश्र', active: true, can_review: ROLE !== 'assistant' },
      { user_id: OTHER, role: 'assistant', display_name: 'साइट असिस्टेंट', active: true, can_review: false },
    ],
    site_expenses: [
      { id: 'e-1', ref_no: 1, incurred_on: '2026-11-13', category: 'मिट्टी भराई', description: '38 हाइवा × ₹3,000 (नकली डेटा)', amount: 114000,
        payer_type: 'site_cash', paid_by_partner: null, payment_method: 'नकद', bill_no: 'T-1', note: null, status: 'pending', version: 3,
        submitted_by: OTHER, created_at: '2026-11-14T05:00:00Z' },
      { id: 'e-2', ref_no: 2, incurred_on: '2026-11-12', category: 'मजदूरी', description: 'मजदूरी (नकली डेटा)', amount: 5000,
        payer_type: 'partner', paid_by_partner: 'गगन आचारी', payment_method: 'UPI', bill_no: null, note: null, status: 'approved', version: 4,
        submitted_by: OTHER, review_note: null, created_at: '2026-11-13T05:00:00Z' },
      { id: 'e-3', ref_no: 3, incurred_on: '2026-11-11', category: 'कार्यालय / यात्रा', description: 'मेरा अपना खर्च (नकली)', amount: 700,
        payer_type: 'partner', paid_by_partner: 'आलोक रंजन मिश्र', payment_method: 'UPI', bill_no: null, note: null, status: 'pending', version: 2,
        submitted_by: ME, created_at: '2026-11-12T05:00:00Z' },
    ],
    site_expense_evidence: [
      { id: 'v-1', expense_id: 'e-1', storage_path: `${OTHER}/e-1/a.pdf`, original_filename: 'bill.pdf', verification_status: 'verified', size_bytes: 10 },
      { id: 'v-2', expense_id: 'e-2', storage_path: `${OTHER}/e-2/b.jpg`, original_filename: 'photo.jpg', verification_status: 'verified', size_bytes: 10 },
      { id: 'v-3', expense_id: 'e-3', storage_path: `${ME}/e-3/c.pdf`, original_filename: 'my.pdf', verification_status: 'pending', size_bytes: 10 },
    ],
    site_expense_audit: [{ action: 'created', actor_role: 'assistant', at: '2026-11-14T05:00:00Z', new_data: { amount: 114000 } }],
  };
  const visible = t => ROLE === 'assistant' && t === 'site_expenses' ? db[t].filter(r => r.submitted_by === ME) : db[t];
  function q(table) {
    let rows = [...(visible(table) || [])], op = 'select', payload = null;
    const api = {
      select() { return api; }, order() { return api; }, range() { return api; },
      eq(k, v) { rows = rows.filter(r => r[k] === v); return api; },
      neq(k, v) { rows = rows.filter(r => r[k] !== v); return api; },
      in(k, v) { rows = rows.filter(r => v.includes(r[k])); return api; },
      insert(p) { op = 'insert'; payload = p; calls.push(['insert', table, p]); return api; },
      update(p) { op = 'update'; payload = p; calls.push(['update', table, p]); return api; },
      maybeSingle() { return Promise.resolve({ data: rows[0] || null, error: null }); },
      single() {
        if (op === 'insert') { const r = { ...payload, id: 'new-1', ref_no: 9, status: 'pending', version: 1, submitted_by: ME, created_at: new Date().toISOString() }; db[table].unshift(r); return Promise.resolve({ data: r, error: null }); }
        return Promise.resolve({ data: rows[0] || null, error: null });
      },
      then(res) { return Promise.resolve({ data: rows, error: null }).then(res); },
    };
    return api;
  }
  window.supabase = { createClient: () => ({
    auth: {
      getUser: async () => ({ data: { user: { id: ME } } }),
      signInWithPassword: async () => ({ error: null }), signOut: async () => ({ error: null }),
    },
    from: q,
    rpc: async (name, args) => {
      calls.push(['rpc', name, args]);
      if (name === 'site_expense_totals') return { data: [
        { status: 'approved', payer_type: 'partner', entries: 1, total: 5000 },
        { status: 'pending', payer_type: 'site_cash', entries: 1, total: 114000 },
        { status: 'pending', payer_type: 'partner', entries: 1, total: 700 }], error: null };
      if (name === 'site_expense_duplicates') return { data: args.p_expense_id === 'e-1' ? [{ ref_no: 7, status: 'approved', reason: 'same_date_amount_category' }] : [], error: null };
      if (name === 'site_expense_attach_evidence') return { data: 'v-new', error: null };
      if (name === 'site_expense_review') return { data: null, error: null };
      return { data: null, error: null };
    },
    storage: { from: () => ({
      upload: async (path, file, opts) => { calls.push(['upload', path, opts.contentType, file.name]); return { error: null }; },
      list: async () => ({ data: [{ name: 'c.pdf' }, { name: 'orphan.pdf' }], error: null }),
      createSignedUrl: async () => ({ data: { signedUrl: 'about:blank' }, error: null }),
    }) },
    functions: { invoke: async (n, o) => { calls.push(['invoke', n, o.body]); return { data: { status: 'verified' }, error: null }; } },
  }) };
})();
