-- ============================================================================
-- सूर्य कुंज आवासीय योजना | निजी खर्च रजिस्टर (v1)
-- अलग Surya Kunj Supabase project के SQL Editor में, खाली project पर एक बार चलाएँ।
-- (UPPCS Diary या किसी दूसरे project में कभी नहीं।)
--
-- यह रजिस्टर अलग है: मूल एन्क्रिप्टेड हिसाब (15 एंट्री, ₹5,26,81,755), साझेदारों
-- का निवेश, बकाया और सेटलमेंट इससे नहीं बदलते।
--
-- पहुँच (सब database और निजी storage में लागू; बटन छिपाने पर निर्भर नहीं):
--   Admin (केवल एक, SQL Editor से तय) : सब कुछ; सदस्यों को मंज़ूर/अस्वीकार/हटाए; अधिकार दे/ले
--   Read    : खर्च सूची, फ़िल्टर, महीने व श्रेणी के कुल, बदलाव का इतिहास
--   Write   : नया खर्च और उसकी रसीद जोड़ना (पुराना बदलना नहीं)
--   सुधार   : खर्च सुधारना/कारण देकर रद्द करना; सभी खर्च और उनकी रसीदें देखना
--   हर सक्रिय सदस्य: अपनी अपलोड की हुई रसीद देख सकता है
--   Pending / अस्वीकृत / हटाया गया: कुछ नहीं
-- अधिकार हर कार्रवाई पर database से दोबारा पढ़े जाते हैं — लॉगिन रहते भी बदलाव तुरंत लागू।
-- ============================================================================

create extension if not exists pgcrypto;

-- ============================================================ सदस्य
create table if not exists public.sk_members (
  user_id       uuid primary key references auth.users(id) on delete restrict,
  display_name  text not null check (char_length(btrim(display_name)) between 2 and 100),
  status        text not null default 'pending'
                  check (status in ('pending','active','rejected','removed')),
  is_admin      boolean not null default false,
  can_read      boolean not null default false,
  can_write     boolean not null default false,
  can_correct   boolean not null default false,
  requested_at  timestamptz not null default now(),
  decided_at    timestamptz,
  decided_by    uuid references auth.users(id),
  decision_note text check (decision_note is null or char_length(decision_note) <= 300),
  updated_at    timestamptz not null default now(),
  -- सक्रिय नहीं तो कोई अधिकार नहीं; Admin हमेशा सक्रिय और सभी अधिकारों सहित
  constraint sk_members_rights_need_active
    check (status = 'active' or not (can_read or can_write or can_correct)),
  constraint sk_members_admin_active
    check (not is_admin or (status = 'active' and can_read and can_write and can_correct))
);
-- पूरे रजिस्टर में केवल एक Admin
create unique index if not exists sk_members_one_admin on public.sk_members ((true)) where is_admin;

alter table public.sk_members enable row level security;
revoke all on public.sk_members from public, anon, authenticated;
grant select on public.sk_members to authenticated;
-- सीधा insert/update/delete किसी user को नहीं — केवल नीचे के RPC से।

-- ---------- अधिकार-जाँच helpers (हर कॉल पर ताज़ा पढ़ते हैं)
create or replace function public.sk_is_active()
returns boolean language sql stable security definer set search_path = ''
as $$
  select coalesce((select m.status = 'active' from public.sk_members m
                   where m.user_id = (select auth.uid())), false)
$$;

create or replace function public.sk_is_admin()
returns boolean language sql stable security definer set search_path = ''
as $$
  select coalesce((select m.is_admin and m.status = 'active' from public.sk_members m
                   where m.user_id = (select auth.uid())), false)
$$;

create or replace function public.sk_has(p_right text)
returns boolean language sql stable security definer set search_path = ''
as $$
  select coalesce((
    select m.status = 'active' and (m.is_admin or case p_right
      when 'read' then m.can_read when 'write' then m.can_write
      when 'correct' then m.can_correct else false end)
    from public.sk_members m where m.user_id = (select auth.uid())
  ), false)
$$;

create or replace function public.sk_today()
returns date language sql stable set search_path = ''
as $$ select (now() at time zone 'Asia/Kolkata')::date $$;

revoke all on function public.sk_is_active(), public.sk_is_admin(), public.sk_has(text), public.sk_today()
  from public, anon;
grant execute on function public.sk_is_active(), public.sk_is_admin(), public.sk_has(text), public.sk_today()
  to authenticated;

drop policy if exists "sk member sees own row" on public.sk_members;
create policy "sk member sees own row" on public.sk_members
  for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists "sk admin sees all members" on public.sk_members;
create policy "sk admin sees all members" on public.sk_members
  for select to authenticated using ((select public.sk_is_admin()));

-- ---------- सदस्य-परिवर्तन का अपरिवर्तनीय रिकॉर्ड
create table if not exists public.sk_member_audit (
  id         bigint generated always as identity primary key,
  member_id  uuid not null,
  action     text not null,
  actor      uuid,
  at         timestamptz not null default now(),
  note       text,
  old_data   jsonb,
  new_data   jsonb
);
create index if not exists sk_member_audit_member_idx on public.sk_member_audit(member_id, at);
alter table public.sk_member_audit enable row level security;
revoke all on public.sk_member_audit from public, anon, authenticated, service_role;
grant select on public.sk_member_audit to authenticated;
drop policy if exists "sk admin reads member audit" on public.sk_member_audit;
create policy "sk admin reads member audit" on public.sk_member_audit
  for select to authenticated using ((select public.sk_is_admin()));

create or replace function public.sk_block_change()
returns trigger language plpgsql set search_path = ''
as $$ begin raise exception 'यह रिकॉर्ड अपरिवर्तनीय है (%)', tg_table_name; end; $$;

drop trigger if exists sk_member_audit_block on public.sk_member_audit;
create trigger sk_member_audit_block before update or delete on public.sk_member_audit
  for each row execute function public.sk_block_change();
drop trigger if exists sk_member_audit_block_trunc on public.sk_member_audit;
create trigger sk_member_audit_block_trunc before truncate on public.sk_member_audit
  for each statement execute function public.sk_block_change();

-- सदस्य-पंक्ति की रक्षा: हटाना वर्जित; बदलाव केवल RPC से; Admin पहचान केवल bootstrap से
create or replace function public.sk_members_guard()
returns trigger language plpgsql set search_path = ''
as $$
declare
  v_boot boolean := coalesce(current_setting('sk.bootstrap', true), '') = 'on';
  v_rpc  boolean := coalesce(current_setting('sk.rpc', true), '') = 'on';
begin
  if tg_op = 'DELETE' then
    raise exception 'सदस्य-पंक्ति हटाई नहीं जा सकती; स्थिति "removed" करें';
  end if;
  if not (v_rpc or v_boot) then
    raise exception 'सदस्य केवल रजिस्टर के RPC से बदले जा सकते हैं';
  end if;
  if tg_op = 'INSERT' then
    if new.is_admin and not v_boot then raise exception 'Admin केवल SQL Editor bootstrap से'; end if;
  else
    if (new.is_admin is distinct from old.is_admin or old.is_admin) and not v_boot then
      raise exception 'Admin की पंक्ति या पहचान RPC से नहीं बदल सकती';
    end if;
    if new.user_id <> old.user_id then raise exception 'user_id नहीं बदल सकता'; end if;
  end if;
  new.updated_at := now();
  return new;
end;
$$;
drop trigger if exists sk_members_guard on public.sk_members;
create trigger sk_members_guard before insert or update or delete on public.sk_members
  for each row execute function public.sk_members_guard();

create or replace function public.sk_members_audit_write()
returns trigger language plpgsql security definer set search_path = ''
as $$
begin
  insert into public.sk_member_audit(member_id, action, actor, note, old_data, new_data)
  values (new.user_id,
          coalesce(nullif(current_setting('sk.action', true), ''), lower(tg_op)),
          auth.uid(), nullif(current_setting('sk.note', true), ''),
          case when tg_op = 'UPDATE' then to_jsonb(old) end, to_jsonb(new));
  return null;
end;
$$;
revoke all on function public.sk_members_audit_write() from public, anon, authenticated;
drop trigger if exists sk_members_audit on public.sk_members;
create trigger sk_members_audit after insert or update on public.sk_members
  for each row execute function public.sk_members_audit_write();

-- ---------- Admin bootstrap: केवल SQL Editor (postgres) से, एक बार
create or replace function public.sk_bootstrap_admin(p_user uuid, p_name text)
returns void language plpgsql security definer set search_path = ''
as $$
begin
  if exists (select 1 from public.sk_members where is_admin) then
    raise exception 'Admin पहले से तय है';
  end if;
  perform set_config('sk.bootstrap', 'on', true);
  perform set_config('sk.action', 'admin_bootstrap', true);
  insert into public.sk_members(user_id, display_name, status, is_admin, can_read, can_write,
                                can_correct, decided_at)
  values (p_user, p_name, 'active', true, true, true, true, now())
  on conflict (user_id) do update set display_name = excluded.display_name, status = 'active',
    is_admin = true, can_read = true, can_write = true, can_correct = true, decided_at = now();
  perform set_config('sk.bootstrap', 'off', true);
end;
$$;
revoke all on function public.sk_bootstrap_admin(uuid, text) from public, anon, authenticated, service_role;

-- ---------- सदस्य: जुड़ने का अनुरोध
create or replace function public.sk_request_membership(p_name text)
returns text language plpgsql security definer set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_st  text;
begin
  if v_uid is null then raise exception 'पहले लॉगिन करें'; end if;
  if char_length(btrim(coalesce(p_name, ''))) not between 2 and 100 then
    raise exception 'नाम 2 से 100 अक्षर का हो';
  end if;
  select status into v_st from public.sk_members where user_id = v_uid for update;
  perform set_config('sk.rpc', 'on', true);
  perform set_config('sk.action', 'requested', true);
  if v_st is null then
    insert into public.sk_members(user_id, display_name) values (v_uid, btrim(p_name));
  elsif v_st = 'active' then
    raise exception 'आप पहले से सक्रिय सदस्य हैं';
  else
    -- pending: नाम सुधार; अस्वीकृत/हटाया गया: नया अनुरोध — कोई अधिकार नहीं
    update public.sk_members set display_name = btrim(p_name), status = 'pending',
      can_read = false, can_write = false, can_correct = false, requested_at = now(),
      decided_at = null, decided_by = null, decision_note = null
    where user_id = v_uid;
  end if;
  perform set_config('sk.rpc', 'off', true);
  return 'pending';
end;
$$;
revoke all on function public.sk_request_membership(text) from public, anon;
grant execute on function public.sk_request_membership(text) to authenticated;

-- ---------- Admin: मंज़ूरी / अस्वीकृति / अधिकार / हटाना
create or replace function public.sk_admin_decide(
  p_user uuid, p_approve boolean, p_read boolean, p_write boolean, p_correct boolean,
  p_note text default null
) returns void language plpgsql security definer set search_path = ''
as $$
declare r public.sk_members%rowtype;
begin
  if not public.sk_is_admin() then raise exception 'केवल Admin'; end if;
  select * into r from public.sk_members where user_id = p_user for update;
  if not found or r.status <> 'pending' then raise exception 'यह अनुरोध pending नहीं है'; end if;
  if r.is_admin then raise exception 'Admin पर लागू नहीं'; end if;
  if p_approve and not (coalesce(p_read,false) or coalesce(p_write,false) or coalesce(p_correct,false)) then
    raise exception 'मंज़ूरी में कम से कम एक अधिकार चुनें';
  end if;
  perform set_config('sk.rpc', 'on', true);
  perform set_config('sk.action', case when p_approve then 'approved' else 'rejected' end, true);
  perform set_config('sk.note', coalesce(p_note, ''), true);
  update public.sk_members set
    status = case when p_approve then 'active' else 'rejected' end,
    can_read = p_approve and coalesce(p_read, false),
    can_write = p_approve and coalesce(p_write, false),
    can_correct = p_approve and coalesce(p_correct, false),
    decided_at = now(), decided_by = auth.uid(), decision_note = nullif(btrim(coalesce(p_note,'')), '')
  where user_id = p_user;
  perform set_config('sk.rpc', 'off', true);
end;
$$;

create or replace function public.sk_admin_set_rights(
  p_user uuid, p_read boolean, p_write boolean, p_correct boolean, p_note text default null
) returns void language plpgsql security definer set search_path = ''
as $$
declare r public.sk_members%rowtype;
begin
  if not public.sk_is_admin() then raise exception 'केवल Admin'; end if;
  select * into r from public.sk_members where user_id = p_user for update;
  if not found or r.status <> 'active' then raise exception 'केवल सक्रिय सदस्य के अधिकार बदलते हैं'; end if;
  if r.is_admin then raise exception 'Admin के अधिकार नहीं बदलते'; end if;
  perform set_config('sk.rpc', 'on', true);
  perform set_config('sk.action', 'rights_changed', true);
  perform set_config('sk.note', coalesce(p_note, ''), true);
  update public.sk_members set can_read = coalesce(p_read,false), can_write = coalesce(p_write,false),
    can_correct = coalesce(p_correct,false), decided_by = auth.uid()
  where user_id = p_user;
  perform set_config('sk.rpc', 'off', true);
end;
$$;

create or replace function public.sk_admin_remove(p_user uuid, p_note text default null)
returns void language plpgsql security definer set search_path = ''
as $$
declare r public.sk_members%rowtype;
begin
  if not public.sk_is_admin() then raise exception 'केवल Admin'; end if;
  select * into r from public.sk_members where user_id = p_user for update;
  if not found or r.status not in ('active','pending') then raise exception 'सदस्य सक्रिय/pending नहीं'; end if;
  if r.is_admin then raise exception 'Admin को हटाया नहीं जा सकता'; end if;
  perform set_config('sk.rpc', 'on', true);
  perform set_config('sk.action', 'removed', true);
  perform set_config('sk.note', coalesce(p_note, ''), true);
  update public.sk_members set status = 'removed', can_read = false, can_write = false,
    can_correct = false, decided_at = now(), decided_by = auth.uid(),
    decision_note = nullif(btrim(coalesce(p_note,'')), '')
  where user_id = p_user;
  perform set_config('sk.rpc', 'off', true);
end;
$$;
revoke all on function public.sk_admin_decide(uuid,boolean,boolean,boolean,boolean,text),
                       public.sk_admin_set_rights(uuid,boolean,boolean,boolean,text),
                       public.sk_admin_remove(uuid,text) from public, anon;
grant execute on function public.sk_admin_decide(uuid,boolean,boolean,boolean,boolean,text),
                          public.sk_admin_set_rights(uuid,boolean,boolean,boolean,text),
                          public.sk_admin_remove(uuid,text) to authenticated;

-- ============================================================ खर्च
create table if not exists public.sk_expenses (
  id              uuid primary key default gen_random_uuid(),
  ref_no          bigint generated always as identity unique,      -- SK-000001
  expense_date    date not null check (expense_date >= date '2024-01-01'),
  item            text not null check (char_length(btrim(item)) between 2 and 200),
  category        text not null check (category in (
                    'भूमि / रजिस्ट्री','मिट्टी भराई','मजदूरी','निर्माण सामग्री','बिजली / पानी',
                    'मशीन / वाहन','कार्यालय / यात्रा','लेआउट / स्वीकृति शुल्क',
                    'सड़क / प्लॉटिंग विकास','कानूनी / दस्तावेज़','साइट रखरखाव','अन्य')),
  -- रुपये-पैसे तक सटीक (numeric, float नहीं)
  amount          numeric(14,2) not null check (amount > 0 and amount <= 100000000),
  payer           text not null check (char_length(btrim(payer)) between 2 and 100),
  payment_method  text not null check (payment_method in ('नकद','UPI','बैंक ट्रांसफर','चेक','अन्य')),
  status          text not null default 'active' check (status in ('active','cancelled')),
  version         integer not null default 1,
  created_by      uuid not null references auth.users(id),
  created_by_name text not null,
  created_at      timestamptz not null default now(),
  updated_by      uuid references auth.users(id),
  updated_by_name text,
  updated_at      timestamptz not null default now(),
  cancel_reason   text,
  cancelled_by    uuid references auth.users(id),
  cancelled_at    timestamptz,
  constraint sk_expenses_cancel_fields check (
    (status = 'cancelled') = (cancel_reason is not null and cancelled_by is not null and cancelled_at is not null))
);
create index if not exists sk_expenses_date_idx on public.sk_expenses(expense_date desc);
create index if not exists sk_expenses_cat_idx on public.sk_expenses(category);
create index if not exists sk_expenses_payer_idx on public.sk_expenses(payer);

alter table public.sk_expenses enable row level security;
revoke all on public.sk_expenses from public, anon, authenticated;
grant select on public.sk_expenses to authenticated;
-- जोड़ना/सुधार/रद्द केवल RPC से (कोई insert/update/delete grant नहीं)

drop policy if exists "sk read or correct sees expenses" on public.sk_expenses;
create policy "sk read or correct sees expenses" on public.sk_expenses
  for select to authenticated
  using ((select public.sk_has('read')) or (select public.sk_has('correct')));

create or replace function public.sk_expenses_guard()
returns trigger language plpgsql set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then raise exception 'खर्च हटाया नहीं जा सकता; कारण देकर रद्द करें'; end if;
  if coalesce(current_setting('sk.rpc', true), '') <> 'on' then
    raise exception 'खर्च केवल रजिस्टर के RPC से बदले जा सकते हैं';
  end if;
  if new.expense_date > public.sk_today() then raise exception 'भविष्य की तारीख नहीं हो सकती'; end if;
  if tg_op = 'UPDATE' then
    if old.status = 'cancelled' then raise exception 'रद्द खर्च बदला नहीं जा सकता'; end if;
    if (new.id, new.ref_no, new.created_by, new.created_by_name, new.created_at)
       is distinct from (old.id, old.ref_no, old.created_by, old.created_by_name, old.created_at) then
      raise exception 'एंट्री करने वाले/समय के कॉलम नहीं बदलते';
    end if;
    new.version := old.version + 1;
    new.updated_at := now();
  end if;
  return new;
end;
$$;
drop trigger if exists sk_expenses_guard on public.sk_expenses;
create trigger sk_expenses_guard before insert or update or delete on public.sk_expenses
  for each row execute function public.sk_expenses_guard();

-- ---------- खर्च का अपरिवर्तनीय बदलाव-रिकॉर्ड
create table if not exists public.sk_expense_audit (
  id          bigint generated always as identity primary key,
  expense_id  uuid not null,
  receipt_id  uuid,
  action      text not null,      -- created / corrected / cancelled / receipt_attached / receipt_verified / receipt_rejected
  actor       uuid,
  actor_name  text,
  at          timestamptz not null default now(),
  reason      text,
  old_data    jsonb,
  new_data    jsonb
);
create index if not exists sk_expense_audit_exp_idx on public.sk_expense_audit(expense_id, at);
alter table public.sk_expense_audit enable row level security;
revoke all on public.sk_expense_audit from public, anon, authenticated, service_role;
grant select on public.sk_expense_audit to authenticated;
drop policy if exists "sk readers see expense history" on public.sk_expense_audit;
create policy "sk readers see expense history" on public.sk_expense_audit
  for select to authenticated
  using ((select public.sk_has('read')) or (select public.sk_has('correct')));
drop trigger if exists sk_expense_audit_block on public.sk_expense_audit;
create trigger sk_expense_audit_block before update or delete on public.sk_expense_audit
  for each row execute function public.sk_block_change();
drop trigger if exists sk_expense_audit_block_trunc on public.sk_expense_audit;
create trigger sk_expense_audit_block_trunc before truncate on public.sk_expense_audit
  for each statement execute function public.sk_block_change();

create or replace function public.sk_member_name(p_uid uuid)
returns text language sql stable security definer set search_path = ''
as $$ select display_name from public.sk_members where user_id = p_uid $$;
revoke all on function public.sk_member_name(uuid) from public, anon, authenticated;

create or replace function public.sk_log(p_expense uuid, p_receipt uuid, p_action text,
  p_reason text, p_old jsonb, p_new jsonb)
returns void language sql security definer set search_path = ''
as $$
  insert into public.sk_expense_audit(expense_id, receipt_id, action, actor, actor_name, reason, old_data, new_data)
  values (p_expense, p_receipt, p_action, auth.uid(), public.sk_member_name(auth.uid()), p_reason, p_old, p_new)
$$;
revoke all on function public.sk_log(uuid,uuid,text,text,jsonb,jsonb) from public, anon, authenticated;

-- ---------- RPC: नया खर्च (Write)
create or replace function public.sk_add_expense(
  p_date date, p_item text, p_category text, p_amount numeric, p_payer text, p_method text
) returns table (id uuid, ref_no bigint, version integer)
language plpgsql security definer set search_path = ''
as $$
declare e public.sk_expenses%rowtype;
begin
  if not public.sk_has('write') then raise exception 'खर्च जोड़ने का (Write) अधिकार नहीं'; end if;
  if p_amount is null or p_amount <> round(p_amount, 2) then
    raise exception 'राशि अधिकतम दो दशमलव (पैसे) तक';
  end if;
  perform set_config('sk.rpc', 'on', true);
  insert into public.sk_expenses(expense_date, item, category, amount, payer, payment_method,
                                 created_by, created_by_name)
  values (p_date, btrim(p_item), p_category, p_amount, btrim(p_payer), p_method,
          auth.uid(), public.sk_member_name(auth.uid()))
  returning * into e;
  perform set_config('sk.rpc', 'off', true);
  perform public.sk_log(e.id, null, 'created', null, null, to_jsonb(e));
  return query select e.id, e.ref_no, e.version;
end;
$$;

-- ---------- RPC: सुधार (सुधार अधिकार, कारण अनिवार्य, version-pinned)
create or replace function public.sk_correct_expense(
  p_id uuid, p_expected_version integer, p_date date, p_item text, p_category text,
  p_amount numeric, p_payer text, p_method text, p_reason text
) returns integer language plpgsql security definer set search_path = ''
as $$
declare o public.sk_expenses%rowtype; n public.sk_expenses%rowtype;
begin
  if not public.sk_has('correct') then raise exception 'सुधार का अधिकार नहीं'; end if;
  if char_length(btrim(coalesce(p_reason, ''))) < 5 then raise exception 'सुधार का कारण (कम से कम 5 अक्षर) अनिवार्य'; end if;
  if p_amount is null or p_amount <> round(p_amount, 2) then raise exception 'राशि अधिकतम दो दशमलव तक'; end if;
  select * into o from public.sk_expenses where id = p_id for update;
  if not found then raise exception 'खर्च नहीं मिला'; end if;
  if o.status <> 'active' then raise exception 'रद्द खर्च सुधारा नहीं जा सकता'; end if;
  if o.version <> p_expected_version then
    raise exception 'VERSION_CHANGED: आपके देखने के बाद यह खर्च बदला गया — रिफ्रेश करें';
  end if;
  if (o.expense_date, o.item, o.category, o.amount, o.payer, o.payment_method)
     is not distinct from (p_date, btrim(p_item), p_category, p_amount, btrim(p_payer), p_method) then
    raise exception 'कोई बदलाव नहीं किया गया';
  end if;
  perform set_config('sk.rpc', 'on', true);
  update public.sk_expenses set expense_date = p_date, item = btrim(p_item), category = p_category,
    amount = p_amount, payer = btrim(p_payer), payment_method = p_method,
    updated_by = auth.uid(), updated_by_name = public.sk_member_name(auth.uid())
  where id = p_id returning * into n;
  perform set_config('sk.rpc', 'off', true);
  perform public.sk_log(p_id, null, 'corrected', btrim(p_reason), to_jsonb(o), to_jsonb(n));
  return n.version;
end;
$$;

-- ---------- RPC: रद्द (सुधार अधिकार, कारण अनिवार्य)
create or replace function public.sk_cancel_expense(p_id uuid, p_expected_version integer, p_reason text)
returns void language plpgsql security definer set search_path = ''
as $$
declare o public.sk_expenses%rowtype; n public.sk_expenses%rowtype;
begin
  if not public.sk_has('correct') then raise exception 'रद्द करने का (सुधार) अधिकार नहीं'; end if;
  if char_length(btrim(coalesce(p_reason, ''))) < 5 then raise exception 'रद्द करने का कारण (कम से कम 5 अक्षर) अनिवार्य'; end if;
  select * into o from public.sk_expenses where id = p_id for update;
  if not found then raise exception 'खर्च नहीं मिला'; end if;
  if o.status <> 'active' then raise exception 'खर्च पहले से रद्द है'; end if;
  if o.version <> p_expected_version then
    raise exception 'VERSION_CHANGED: आपके देखने के बाद यह खर्च बदला गया — रिफ्रेश करें';
  end if;
  perform set_config('sk.rpc', 'on', true);
  update public.sk_expenses set status = 'cancelled', cancel_reason = btrim(p_reason),
    cancelled_by = auth.uid(), cancelled_at = now(),
    updated_by = auth.uid(), updated_by_name = public.sk_member_name(auth.uid())
  where id = p_id returning * into n;
  perform set_config('sk.rpc', 'off', true);
  perform public.sk_log(p_id, null, 'cancelled', btrim(p_reason), to_jsonb(o), to_jsonb(n));
end;
$$;

-- ---------- RPC: फ़िल्टर सहित कुल (Read) — केवल सक्रिय खर्च; राशि text में (सटीक)
create or replace function public.sk_summary(
  p_from date default null, p_to date default null, p_category text default null, p_payer text default null
) returns table (kind text, key text, entries bigint, total text)
language plpgsql stable security definer set search_path = ''
as $$
begin
  if not public.sk_has('read') then raise exception 'Read अधिकार नहीं'; end if;
  return query
  with f as (
    select * from public.sk_expenses e
    where (p_from is null or e.expense_date >= p_from) and (p_to is null or e.expense_date <= p_to)
      and (p_category is null or e.category = p_category) and (p_payer is null or e.payer = p_payer)
  )
  select 'total'::text, 'सक्रिय'::text, count(*), coalesce(sum(amount),0)::numeric(16,2)::text
    from f where status = 'active'
  union all
  select 'cancelled', 'रद्द', count(*), coalesce(sum(amount),0)::numeric(16,2)::text
    from f where status = 'cancelled'
  union all
  (select 'month', to_char(expense_date, 'YYYY-MM'), count(*), sum(amount)::numeric(16,2)::text
     from f where status = 'active' group by 2 order by 2 desc)
  union all
  (select 'category', category, count(*), sum(amount)::numeric(16,2)::text
     from f where status = 'active' group by 2 order by sum(amount) desc);
end;
$$;
revoke all on function public.sk_add_expense(date,text,text,numeric,text,text),
  public.sk_correct_expense(uuid,integer,date,text,text,numeric,text,text,text),
  public.sk_cancel_expense(uuid,integer,text),
  public.sk_summary(date,date,text,text) from public, anon;
grant execute on function public.sk_add_expense(date,text,text,numeric,text,text),
  public.sk_correct_expense(uuid,integer,date,text,text,numeric,text,text,text),
  public.sk_cancel_expense(uuid,integer,text),
  public.sk_summary(date,date,text,text) to authenticated;

-- ============================================================ रसीदें (वैकल्पिक, निजी)
create table if not exists public.sk_receipts (
  id                  uuid primary key default gen_random_uuid(),
  expense_id          uuid not null references public.sk_expenses(id) on delete restrict,
  storage_path        text not null unique,
  original_filename   text not null check (char_length(original_filename) between 1 and 255),
  mime_type           text not null check (mime_type in ('image/jpeg','image/png','image/webp',
                        'application/pdf',
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
  size_bytes          bigint not null check (size_bytes > 0 and size_bytes <= 10485760),
  verification_status text not null default 'pending'
                        check (verification_status in ('pending','verified','rejected')),
  verification_note   text check (verification_note is null or char_length(verification_note) <= 300),
  sha256              text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
  verified_at         timestamptz,
  uploaded_by         uuid not null references auth.users(id),
  created_at          timestamptz not null default now()
);
create index if not exists sk_receipts_expense_idx on public.sk_receipts(expense_id);
alter table public.sk_receipts enable row level security;
revoke all on public.sk_receipts from public, anon, authenticated;
grant select on public.sk_receipts to authenticated;
grant select on public.sk_receipts, public.sk_expenses to service_role;
grant update (verification_status, verification_note, sha256, verified_at) on public.sk_receipts to service_role;

drop policy if exists "sk receipts by role" on public.sk_receipts;
create policy "sk receipts by role" on public.sk_receipts
  for select to authenticated using (
    (select public.sk_is_admin())
    or (select public.sk_has('correct'))
    or (uploaded_by = (select auth.uid()) and (select public.sk_is_active()))
  );

create or replace function public.sk_receipts_guard()
returns trigger language plpgsql set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then raise exception 'रसीद हटाई नहीं जा सकती'; end if;
  if old.verification_status <> 'pending' then raise exception 'जाँची हुई रसीद बदली नहीं जा सकती'; end if;
  if (new.id, new.expense_id, new.storage_path, new.original_filename, new.mime_type, new.size_bytes,
      new.uploaded_by, new.created_at) is distinct from
     (old.id, old.expense_id, old.storage_path, old.original_filename, old.mime_type, old.size_bytes,
      old.uploaded_by, old.created_at) then
    raise exception 'रसीद का मूल विवरण नहीं बदलता';
  end if;
  return new;
end;
$$;
drop trigger if exists sk_receipts_guard on public.sk_receipts;
create trigger sk_receipts_guard before update or delete on public.sk_receipts
  for each row execute function public.sk_receipts_guard();

create or replace function public.sk_receipts_verify_log()
returns trigger language plpgsql security definer set search_path = ''
as $$
begin
  if new.verification_status <> old.verification_status then
    insert into public.sk_expense_audit(expense_id, receipt_id, action, actor, actor_name, reason, new_data)
    values (new.expense_id, new.id, 'receipt_' || new.verification_status, null, 'server जाँच',
            new.verification_note, jsonb_build_object('sha256', new.sha256, 'file', new.original_filename));
  end if;
  return null;
end;
$$;
revoke all on function public.sk_receipts_verify_log() from public, anon, authenticated;
drop trigger if exists sk_receipts_verify_log on public.sk_receipts;
create trigger sk_receipts_verify_log after update on public.sk_receipts
  for each row execute function public.sk_receipts_verify_log();

-- storage policies के लिए definer helpers (RLS के कारण Write-only सदस्य को खर्च-पंक्ति नहीं दिखती)
create or replace function public.sk_can_attach(p_expense uuid)
returns boolean language sql stable security definer set search_path = ''
as $$
  select exists (
    select 1 from public.sk_expenses e
    where e.id = p_expense and e.status = 'active'
      and ((e.created_by = (select auth.uid()) and public.sk_has('write')) or public.sk_has('correct'))
  )
$$;
create or replace function public.sk_receipt_visible(p_path text)
returns boolean language sql stable security definer set search_path = ''
as $$
  select exists (select 1 from public.sk_receipts r where r.storage_path = p_path)
     and (public.sk_is_admin() or public.sk_has('correct'))
$$;
revoke all on function public.sk_can_attach(uuid), public.sk_receipt_visible(text) from public, anon;
grant execute on function public.sk_can_attach(uuid), public.sk_receipt_visible(text) to authenticated;

-- ---------- RPC: रसीद जोड़ना (storage में असली फ़ाइल जाँचकर)
create or replace function public.sk_attach_receipt(p_expense_id uuid, p_storage_path text, p_original_filename text)
returns uuid language plpgsql security definer set search_path = ''
as $$
declare
  v_uid uuid := auth.uid(); v_meta jsonb; v_mime text; v_size bigint; v_ext text; v_id uuid;
  o public.sk_expenses%rowtype;
begin
  if not public.sk_can_attach(p_expense_id) then
    raise exception 'इस खर्च में रसीद जोड़ने का अधिकार नहीं (अपना खर्च + Write, या सुधार अधिकार)';
  end if;
  if p_storage_path !~ ('^' || v_uid::text || '/' || p_expense_id::text
                        || '/[0-9a-f-]{36}\.(jpg|jpeg|png|webp|pdf|docx)$') then
    raise exception 'फ़ाइल का path मान्य नहीं';
  end if;
  select id into v_id from public.sk_receipts where storage_path = p_storage_path;
  if v_id is not null then return v_id; end if;      -- retry सुरक्षित
  if (select count(*) from public.sk_receipts where expense_id = p_expense_id) >= 5 then
    raise exception 'एक खर्च में अधिकतम 5 रसीदें';
  end if;
  select ob.metadata into v_meta from storage.objects ob
   where ob.bucket_id = 'sk-receipts' and ob.name = p_storage_path
     and coalesce(ob.owner_id, ob.owner::text) = v_uid::text;
  if v_meta is null then raise exception 'storage में यह फ़ाइल नहीं मिली — पहले अपलोड पूरा करें'; end if;
  v_mime := lower(v_meta->>'mimetype'); v_size := (v_meta->>'size')::bigint;
  v_ext := lower(substring(p_storage_path from '\.([a-z]+)$'));
  if v_size is null or v_size <= 0 or v_size > 10485760 then raise exception 'फ़ाइल 1 byte से 10 MB तक'; end if;
  if not ((v_ext in ('jpg','jpeg') and v_mime = 'image/jpeg') or (v_ext = 'png' and v_mime = 'image/png')
       or (v_ext = 'webp' and v_mime = 'image/webp') or (v_ext = 'pdf' and v_mime = 'application/pdf')
       or (v_ext = 'docx' and v_mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')) then
    raise exception 'फ़ाइल का प्रकार और extension मेल नहीं खाते';
  end if;
  insert into public.sk_receipts(expense_id, storage_path, original_filename, mime_type, size_bytes, uploaded_by)
  values (p_expense_id, p_storage_path, left(coalesce(nullif(btrim(p_original_filename), ''), 'file'), 255),
          v_mime, v_size, v_uid)
  returning id into v_id;
  -- रसीद जुड़ना भी बदलाव है: version +1 ताकि चल रहा सुधार पुराने संस्करण पर न हो
  select * into o from public.sk_expenses where id = p_expense_id;
  perform set_config('sk.rpc', 'on', true);
  update public.sk_expenses set updated_by = v_uid, updated_by_name = public.sk_member_name(v_uid)
   where id = p_expense_id;
  perform set_config('sk.rpc', 'off', true);
  perform public.sk_log(p_expense_id, v_id, 'receipt_attached', null, null,
                        jsonb_build_object('file', p_original_filename, 'mime', v_mime, 'size', v_size));
  return v_id;
end;
$$;
revoke all on function public.sk_attach_receipt(uuid,text,text) from public, anon;
grant execute on function public.sk_attach_receipt(uuid,text,text) to authenticated;

-- ---------- निजी storage bucket और नियम
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('sk-receipts', 'sk-receipts', false, 10485760,
        array['image/jpeg','image/png','image/webp','application/pdf',
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "sk receipts read" on storage.objects;
create policy "sk receipts read" on storage.objects
  for select to authenticated using (
    bucket_id = 'sk-receipts' and (
      -- सक्रिय सदस्य: अपनी अपलोड की हुई फ़ाइलें
      ((storage.foldername(name))[1] = (select auth.uid())::text and (select public.sk_is_active()))
      -- Admin / सुधार अधिकार: रजिस्टर से जुड़ी सभी रसीदें
      or (select public.sk_receipt_visible(name))
    )
  );
drop policy if exists "sk receipts upload" on storage.objects;
create policy "sk receipts upload" on storage.objects
  for insert to authenticated with check (
    bucket_id = 'sk-receipts'
    and name ~ '^[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}\.(jpg|jpeg|png|webp|pdf|docx)$'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and (select public.sk_can_attach(((storage.foldername(name))[2])::uuid))
  );
-- storage update/delete policy जानबूझकर नहीं: रसीद overwrite/delete नहीं।

-- ============================================================================
-- पहला Admin (SQL Editor में, अपने Auth user का UUID डालकर, एक बार):
--   select public.sk_bootstrap_admin('YOUR-AUTH-USER-UUID', 'आलोक रंजन मिश्र');
-- ============================================================================
