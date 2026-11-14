// सूर्य कुंज | Edge Function: sk-admin-users (केवल Admin)
// 1) create       — यूज़र आईडी + 6 अंकों का पासवर्ड से खाता बनाना (अस्थायी ईमेल, पुष्टि पहले से) और
//                   उसी समय चुने अधिकारों के साथ सक्रिय सदस्य बनाना।
// 2) set_password — किसी (गैर-Admin) सदस्य का नया 6 अंकों का पासवर्ड; चाहें तो रीसेट-अनुरोध बंद।
// caller का Admin होना database (sk_is_admin, RLS-सुरक्षित RPC) से जाँचा जाता है; service_role केवल
// Auth के admin API के लिए। Verify JWT चालू रखें।
// Secrets (Supabase स्वयं देता है): SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY; ALLOWED_ORIGIN
import { createClient } from 'npm:@supabase/supabase-js@2.119.0';

const ORIGIN = Deno.env.get('ALLOWED_ORIGIN') ?? 'https://alokrmishra05-lab.github.io';
const DOMAIN = 'suryakunj.example.com';
const cors = {
  'Access-Control-Allow-Origin': ORIGIN,
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  'Vary': 'Origin',
};
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { ...cors, 'Content-Type': 'application/json' } });

const LOGIN_RE = /^[a-z0-9][a-z0-9._-]{2,39}$/;   // यूज़र आईडी: 3–40, छोटे अक्षर/अंक/._-
const PIN_RE = /^\d{6}$/;
const UUID_RE = /^[0-9a-f-]{36}$/i;

Deno.serve(async (req) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors });
  if (req.method !== 'POST') return reply(405, { error: 'POST only' });
  const auth = req.headers.get('Authorization') ?? '';
  if (!auth.startsWith('Bearer ')) return reply(401, { error: 'लॉगिन आवश्यक' });

  let body: Record<string, unknown> = {};
  try { body = (await req.json()) ?? {}; } catch { /* नीचे जाँच */ }

  const url = Deno.env.get('SUPABASE_URL')!;
  const asUser = createClient(url, Deno.env.get('SUPABASE_ANON_KEY')!, {
    global: { headers: { Authorization: auth } }, auth: { persistSession: false },
  });
  const { data: isAdmin, error: aErr } = await asUser.rpc('sk_is_admin');
  if (aErr || isAdmin !== true) return reply(403, { error: 'केवल Admin' });
  const admin = createClient(url, Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!, { auth: { persistSession: false } });

  if (body.action === 'create') {
    const login = String(body.login ?? '').trim().toLowerCase();
    const name = String(body.name ?? '').trim();
    const pin = String(body.password ?? '');
    const r = body.read === true, w = body.write === true, c = body.correct === true;
    if (!LOGIN_RE.test(login)) return reply(400, { error: 'यूज़र आईडी 3–40 अक्षर: छोटे अंग्रेज़ी अक्षर, अंक, . _ -' });
    if (name.length < 2 || name.length > 100) return reply(400, { error: 'नाम 2 से 100 अक्षर का हो' });
    if (!PIN_RE.test(pin)) return reply(400, { error: 'पासवर्ड ठीक 6 अंकों का हो' });
    if (!(r || w || c)) return reply(400, { error: 'कम से कम एक अधिकार चुनें' });

    const { data: created, error: cErr } = await admin.auth.admin.createUser({
      email: `${login}@${DOMAIN}`, password: pin, email_confirm: true,
    });
    if (cErr || !created?.user) {
      const dup = /already|exists|registered/i.test(cErr?.message ?? '');
      return reply(dup ? 409 : 400, { error: dup ? 'यह यूज़र आईडी पहले से है' : 'खाता नहीं बना: ' + (cErr?.message ?? '') });
    }
    const uid = created.user.id;
    const { error: mErr } = await asUser.rpc('sk_admin_add_member', {
      p_user: uid, p_name: name, p_read: r, p_write: w, p_correct: c,
    });
    if (mErr) {
      await admin.auth.admin.deleteUser(uid);   // अधूरा खाता न रहे
      return reply(400, { error: 'सदस्य नहीं जुड़ा: ' + mErr.message });
    }
    return reply(200, { ok: true, login, user_id: uid });
  }

  if (body.action === 'set_password') {
    const uid = String(body.user_id ?? '');
    const pin = String(body.password ?? '');
    const requestId = body.request_id == null ? null : Number(body.request_id);
    if (!UUID_RE.test(uid)) return reply(400, { error: 'सदस्य मान्य नहीं' });
    if (!PIN_RE.test(pin)) return reply(400, { error: 'पासवर्ड ठीक 6 अंकों का हो' });
    if (requestId !== null && !Number.isSafeInteger(requestId)) return reply(400, { error: 'अनुरोध मान्य नहीं' });
    const { data: allowed, error: pErr } = await asUser.rpc('sk_admin_can_set_password', { p_user: uid });
    if (pErr || allowed !== true) return reply(403, { error: 'इस खाते का पासवर्ड यहाँ से नहीं बदल सकता' });
    const { error: uErr } = await admin.auth.admin.updateUserById(uid, { password: pin });
    if (uErr) return reply(400, { error: 'पासवर्ड नहीं बदला: ' + uErr.message });
    if (requestId !== null) {
      const { error: rErr } = await asUser.rpc('sk_admin_close_reset', { p_id: requestId, p_status: 'done' });
      if (rErr) return reply(200, { ok: true, warning: 'पासवर्ड बदला, पर अनुरोध बंद नहीं हुआ: ' + rErr.message });
    }
    return reply(200, { ok: true });
  }

  return reply(400, { error: 'action मान्य नहीं' });
});
