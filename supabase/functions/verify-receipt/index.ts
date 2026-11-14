// सूर्य कुंज | Edge Function: verify-receipt (निजी खर्च रजिस्टर)
// अपलोड हुई रसीद-फ़ाइल की असली सामग्री server पर जाँचता है (magic bytes, PDF में
// script, DOCX में macro, आकार), sha256 निकालता है, और परिणाम evidence पंक्ति में
// लिखता है (sk_receipts)। केवल यही (service_role से) verification_status बदल सकता है।
//
// Deploy (केवल Surya Kunj project में): supabase functions deploy verify-receipt
// Secrets (Supabase स्वयं देता है): SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY
// वैकल्पिक: ALLOWED_ORIGIN (डिफ़ॉल्ट GitHub Pages)
import { createClient } from 'npm:@supabase/supabase-js@2.119.0';
import { inspectFile } from '../_shared/filecheck.js';

const ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? 'https://alokrmishra05-lab.github.io';
const cors = {
  'Access-Control-Allow-Origin': ORIGIN,
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Vary': 'Origin',
};
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, 'Content-Type': 'application/json' } });

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') return reply(405, { error: 'POST only' });

  const auth = req.headers.get('Authorization') ?? '';
  if (!auth.startsWith('Bearer ')) return reply(401, { error: 'लॉगिन आवश्यक' });

  let evidenceId = '';
  try { evidenceId = String((await req.json())?.receipt_id ?? ''); } catch { /* नीचे जाँच */ }
  if (!/^[0-9a-f-]{36}$/i.test(evidenceId)) return reply(400, { error: 'receipt_id मान्य नहीं' });

  const url = Deno.env.get('SUPABASE_URL')!;
  // 1) caller की अपनी पहचान से: क्या यह रसीद उसे RLS के तहत दिखती है? (Admin/सुधार/स्वयं अपलोड)
  const asUser = createClient(url, Deno.env.get('SUPABASE_ANON_KEY')!, {
    global: { headers: { Authorization: auth } }, auth: { persistSession: false },
  });
  const { data: visible, error: visErr } = await asUser
    .from('sk_receipts').select('id').eq('id', evidenceId).maybeSingle();
  if (visErr || !visible) return reply(403, { error: 'इस रसीद तक पहुँच नहीं' });

  // 2) service_role से फ़ाइल पढ़कर जाँच
  const admin = createClient(url, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, {
    auth: { persistSession: false },
  });
  const { data: ev, error: evErr } = await admin.from('sk_receipts')
    .select('id, storage_path, mime_type, size_bytes, verification_status')
    .eq('id', evidenceId).single();
  if (evErr || !ev) return reply(404, { error: 'रसीद नहीं मिली' });
  if (ev.verification_status !== 'pending') {
    return reply(200, { status: ev.verification_status, already: true });
  }

  const { data: blob, error: dlErr } = await admin.storage
    .from('sk-receipts').download(ev.storage_path);
  if (dlErr || !blob) return reply(502, { error: 'फ़ाइल पढ़ी नहीं जा सकी, बाद में पुनः प्रयास करें' });
  const bytes = new Uint8Array(await blob.arrayBuffer());

  let verdict = inspectFile(bytes, ev.storage_path);
  if (verdict.ok && verdict.mime !== ev.mime_type) {
    verdict = { ok: false, mime: verdict.mime, reason: 'फ़ाइल अस्वीकार: सामग्री और दर्ज प्रकार मेल नहीं खाते' };
  }
  if (verdict.ok && bytes.length !== Number(ev.size_bytes)) {
    verdict = { ok: false, mime: verdict.mime, reason: 'फ़ाइल अस्वीकार: आकार दर्ज रिकॉर्ड से अलग' };
  }
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  const sha256 = [...new Uint8Array(digest)].map((x) => x.toString(16).padStart(2, '0')).join('');

  const status = verdict.ok ? 'verified' : 'rejected';
  const { error: upErr } = await admin.from('sk_receipts')
    .update({
      verification_status: status,
      verification_note: verdict.ok ? null : String(verdict.reason).slice(0, 300),
      sha256,
      verified_at: new Date().toISOString(),
    })
    .eq('id', evidenceId).eq('verification_status', 'pending');
  if (upErr) return reply(500, { error: 'परिणाम दर्ज नहीं हुआ' });

  return reply(200, { status, reason: verdict.ok ? null : verdict.reason });
});
