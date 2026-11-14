-- सूर्य कुंज | खर्च रजिस्टर — खाते Admin बनाता है + पासवर्ड-रीसेट अनुरोध (expense-register.sql के बाद चलाएँ)
-- केवल Surya Kunj project में। दोबारा चलाना सुरक्षित (idempotent)।
--
-- * सदस्य "यूज़र आईडी" से लॉगिन करते हैं; भीतर यह <आईडी>@suryakunj.example.com नाम का अस्थायी
--   (बिना inbox) पता बनता है। खाता Admin बनाता है (Edge Function sk-admin-users) — ईमेल पुष्टि नहीं चाहिए।
-- * पासवर्ड भूलने पर लॉगिन पेज से "Admin से नया पासवर्ड माँगें": अनुरोध यहाँ दर्ज होता है,
--   Admin पैनल में दिखता है, Admin नया 6 अंकों का पासवर्ड रखता है।

-- ---------- यूज़र आईडी → अस्थायी ईमेल (UI और Edge Function में भी यही नियम)
create or replace function public.sk_login_email(p_login text)
returns text language sql immutable set search_path = ''
as $$
  select case when position('@' in lower(btrim(coalesce(p_login, '')))) > 0
              then lower(btrim(p_login))
              else lower(btrim(coalesce(p_login, ''))) || '@suryakunj.example.com' end
$$;
grant execute on function public.sk_login_email(text) to anon, authenticated;

-- ---------- Admin द्वारा बना सदस्य (सीधा सक्रिय, चुने अधिकारों सहित)
create or replace function public.sk_admin_add_member(
  p_user uuid, p_name text, p_read boolean, p_write boolean, p_correct boolean
) returns void language plpgsql security definer set search_path = ''
as $$
begin
  if not public.sk_is_admin() then raise exception 'केवल Admin'; end if;
  if char_length(btrim(coalesce(p_name, ''))) not between 2 and 100 then raise exception 'नाम 2 से 100 अक्षर का हो'; end if;
  if not (coalesce(p_read,false) or coalesce(p_write,false) or coalesce(p_correct,false)) then
    raise exception 'कम से कम एक अधिकार चुनें';
  end if;
  if exists (select 1 from public.sk_members where user_id = p_user) then raise exception 'यह खाता पहले से सदस्य है'; end if;
  perform set_config('sk.rpc', 'on', true);
  perform set_config('sk.action', 'added_by_admin', true);
  perform set_config('sk.note', '', true);
  insert into public.sk_members(user_id, display_name, status, can_read, can_write, can_correct, decided_at, decided_by)
  values (p_user, btrim(p_name), 'active', coalesce(p_read,false), coalesce(p_write,false), coalesce(p_correct,false),
          now(), auth.uid());
  perform set_config('sk.rpc', 'off', true);
end;
$$;
revoke all on function public.sk_admin_add_member(uuid,text,boolean,boolean,boolean) from public, anon;
grant execute on function public.sk_admin_add_member(uuid,text,boolean,boolean,boolean) to authenticated;

-- ---------- Admin: किस सदस्य का पासवर्ड बदला जा सकता है (Admin स्वयं नहीं — वह dashboard से)
create or replace function public.sk_admin_can_set_password(p_user uuid)
returns boolean language plpgsql stable security definer set search_path = ''
as $$
begin
  if not public.sk_is_admin() then raise exception 'केवल Admin'; end if;
  return exists (select 1 from public.sk_members where user_id = p_user and not is_admin);
end;
$$;
revoke all on function public.sk_admin_can_set_password(uuid) from public, anon;
grant execute on function public.sk_admin_can_set_password(uuid) to authenticated;

-- ---------- पासवर्ड-रीसेट अनुरोध
create table if not exists public.sk_reset_requests (
  id           bigint generated always as identity primary key,
  login        text not null check (char_length(login) between 3 and 120),
  note         text check (note is null or char_length(note) <= 200),
  requested_at timestamptz not null default now(),
  status       text not null default 'open' check (status in ('open','done','dismissed')),
  closed_at    timestamptz,
  closed_by    uuid references auth.users(id)
);
create index if not exists sk_reset_requests_open_idx on public.sk_reset_requests(login) where status = 'open';
alter table public.sk_reset_requests enable row level security;
revoke all on public.sk_reset_requests from public, anon, authenticated;
-- पढ़ना/बदलना केवल नीचे के RPC से

-- लॉगिन पेज से (बिना लॉगिन)। खाता है या नहीं, यह कभी नहीं बताता; एक आईडी का एक ही खुला अनुरोध;
-- पूरे रजिस्टर पर प्रति घंटा 20 अनुरोध की सीमा (दुरुपयोग रोकने हेतु)।
create or replace function public.sk_request_password_reset(p_login text, p_note text default null)
returns void language plpgsql security definer set search_path = ''
as $$
declare v text := lower(btrim(coalesce(p_login, '')));
begin
  if v !~ '^[a-z0-9][a-z0-9._+@-]{2,119}$' then raise exception 'यूज़र आईडी सही लिखें'; end if;
  if char_length(coalesce(p_note, '')) > 200 then raise exception 'संदेश 200 अक्षर तक'; end if;
  perform pg_advisory_xact_lock(hashtext('sk_reset_requests'));
  if (select count(*) from public.sk_reset_requests where requested_at > now() - interval '1 hour') >= 20 then
    raise exception 'अभी बहुत अनुरोध आए हैं — एक घंटे बाद फिर कोशिश करें या Admin से सीधे बात करें';
  end if;
  if exists (select 1 from public.sk_reset_requests where login = v and status = 'open') then return; end if;
  insert into public.sk_reset_requests(login, note) values (v, nullif(btrim(coalesce(p_note, '')), ''));
end;
$$;
revoke all on function public.sk_request_password_reset(text, text) from public;
grant execute on function public.sk_request_password_reset(text, text) to anon, authenticated;

-- Admin: खुले अनुरोध, मिलते सदस्य के साथ
create or replace function public.sk_admin_reset_requests()
returns table (id bigint, login text, note text, requested_at timestamptz,
               member_user uuid, member_name text, member_status text, member_is_admin boolean)
language plpgsql stable security definer set search_path = ''
as $$
begin
  if not public.sk_is_admin() then raise exception 'केवल Admin'; end if;
  return query
    select r.id, r.login, r.note, r.requested_at, m.user_id, m.display_name, m.status, m.is_admin
      from public.sk_reset_requests r
      left join auth.users u on lower(u.email) = public.sk_login_email(r.login)
      left join public.sk_members m on m.user_id = u.id
     where r.status = 'open'
     order by r.requested_at;
end;
$$;
revoke all on function public.sk_admin_reset_requests() from public, anon;
grant execute on function public.sk_admin_reset_requests() to authenticated;

create or replace function public.sk_admin_close_reset(p_id bigint, p_status text)
returns void language plpgsql security definer set search_path = ''
as $$
begin
  if not public.sk_is_admin() then raise exception 'केवल Admin'; end if;
  if p_status not in ('done','dismissed') then raise exception 'स्थिति done/dismissed हो'; end if;
  update public.sk_reset_requests set status = p_status, closed_at = now(), closed_by = auth.uid()
   where id = p_id and status = 'open';
  if not found then raise exception 'यह अनुरोध खुला नहीं है'; end if;
end;
$$;
revoke all on function public.sk_admin_close_reset(bigint, text) from public, anon;
grant execute on function public.sk_admin_close_reset(bigint, text) to authenticated;
