-- ============================================================================
-- सूर्य कुंज आवासीय योजना | साइट खर्च मॉड्यूल (v2)
-- Supabase SQL Editor में एक बार, नए (खाली) project पर चलाएँ।
--
-- यह अलग मॉड्यूल है: मूल एन्क्रिप्टेड हिसाब (15 एंट्री, ₹5,26,81,755) और
-- साझेदारों की पूँजी / निपटान पर इसका कोई असर नहीं।
--
-- पहुँच नियम (सब database में लागू, UI पर निर्भर नहीं):
--   admin     : सब खर्च व प्रमाण देखे; दूसरों के खर्च approve/reject करे; अपना नहीं।
--   partner   : सब खर्च व प्रमाण देखे; खर्च जोड़े; अपना pending सुधारे;
--               can_review = true होने पर ही दूसरों के खर्च approve/reject करे।
--   assistant : केवल अपने खर्च व प्रमाण देखे; जोड़े; अपना pending सुधारे;
--               कोई approve/reject नहीं।
--
-- SECURITY: GitHub Pages पर service_role key या database password कभी न रखें।
-- ============================================================================

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------- सदस्य
create table if not exists public.site_expense_members (
  user_id      uuid primary key references auth.users(id) on delete restrict,
  display_name text not null check (char_length(btrim(display_name)) between 2 and 100),
  role         text not null check (role in ('admin','partner','assistant')),
  can_review   boolean not null default false,
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  -- review अधिकार केवल admin (हमेशा) या नामित partner को
  constraint site_expense_members_review_role
    check (not can_review or role in ('admin','partner'))
);
alter table public.site_expense_members enable row level security;
revoke all on public.site_expense_members from public, anon, authenticated;
grant select on public.site_expense_members to authenticated;

-- RLS recursion से बचने हेतु SECURITY DEFINER helper; केवल सक्रिय सदस्य।
create or replace function public.site_expense_role()
returns text language sql stable security definer set search_path = ''
as $$
  select m.role from public.site_expense_members m
  where m.user_id = (select auth.uid()) and m.active
$$;

create or replace function public.site_expense_is_reviewer()
returns boolean language sql stable security definer set search_path = ''
as $$
  select coalesce((
    select m.role = 'admin' or (m.role = 'partner' and m.can_review)
    from public.site_expense_members m
    where m.user_id = (select auth.uid()) and m.active
  ), false)
$$;

-- भारतीय समय के अनुसार आज की तारीख (भविष्य की तारीख रोकने हेतु)
create or replace function public.site_expense_today()
returns date language sql stable set search_path = ''
as $$ select (now() at time zone 'Asia/Kolkata')::date $$;

revoke all on function public.site_expense_role() from public, anon;
revoke all on function public.site_expense_is_reviewer() from public, anon;
revoke all on function public.site_expense_today() from public, anon;
grant execute on function public.site_expense_role() to authenticated;
grant execute on function public.site_expense_is_reviewer() to authenticated;
grant execute on function public.site_expense_today() to authenticated;

drop policy if exists "member sees own profile" on public.site_expense_members;
create policy "member sees own profile" on public.site_expense_members
  for select to authenticated using (user_id = (select auth.uid()));
drop policy if exists "admin and partners see members" on public.site_expense_members;
create policy "admin and partners see members" on public.site_expense_members
  for select to authenticated
  using ((select public.site_expense_role()) in ('admin','partner'));

-- ---------------------------------------------------------------- खर्च
create table if not exists public.site_expenses (
  id              uuid primary key default gen_random_uuid(),
  -- स्थिर, मानव-पठनीय क्रमांक (SE-000001); भविष्य के मिलान हेतु
  ref_no          bigint generated always as identity unique,
  incurred_on     date not null check (incurred_on >= date '2020-01-01'),
  category        text not null check (category in (
                    'मिट्टी भराई','मजदूरी','निर्माण सामग्री','बिजली / पानी',
                    'मशीन / वाहन','कार्यालय / यात्रा','लेआउट / स्वीकृति शुल्क',
                    'सड़क / प्लॉटिंग विकास','साइट रखरखाव','अन्य')),
  description     text not null check (char_length(btrim(description)) between 3 and 1000),
  amount          numeric(14,2) not null check (amount > 0 and amount <= 100000000),
  -- पैसा कहाँ से गया: साझेदार की जेब / साइट कैश / परियोजना फंड
  payer_type      text not null check (payer_type in ('partner','site_cash','project_fund')),
  paid_by_partner text check (paid_by_partner in
                    ('आलोक रंजन मिश्र','अमरनाथ पाण्डेय','गगन आचारी')),
  payment_method  text not null check (payment_method in ('नकद','UPI','बैंक','चेक','अन्य')),
  bill_no         text check (bill_no is null or char_length(btrim(bill_no)) between 1 and 120),
  note            text check (note is null or char_length(note) <= 1000),
  submitted_by    uuid not null default auth.uid() references auth.users(id),
  status          text not null default 'pending'
                    check (status in ('pending','approved','rejected')),
  -- हर बदलाव पर +1; review के समय देखा गया version भेजना ज़रूरी (optimistic lock)
  version         integer not null default 1,
  reviewed_by     uuid references auth.users(id),
  reviewed_at     timestamptz,
  review_note     text check (review_note is null or char_length(review_note) <= 500),
  updated_by      uuid references auth.users(id),
  updated_at      timestamptz not null default now(),
  created_at      timestamptz not null default now(),
  constraint site_expenses_partner_payer
    check ((payer_type = 'partner') = (paid_by_partner is not null))
);
create index if not exists site_expenses_status_date_idx
  on public.site_expenses(status, incurred_on desc);
create index if not exists site_expenses_dup_idx
  on public.site_expenses(incurred_on, amount, category);
create index if not exists site_expenses_submitter_idx
  on public.site_expenses(submitted_by);
-- एक ही बिल/वाउचर नंबर दो सक्रिय (pending/approved) खर्चों में नहीं हो सकता।
-- तुलना में बड़े/छोटे अक्षर, खाली जगह, '-', '/' आदि अनदेखे: 'INV-101' = 'inv 101'।
create unique index if not exists site_expenses_bill_unique
  on public.site_expenses (regexp_replace(lower(bill_no), '[^[:alnum:]]', '', 'g'))
  where bill_no is not null and status <> 'rejected';

alter table public.site_expenses enable row level security;
revoke all on public.site_expenses from public, anon, authenticated;
grant select on public.site_expenses to authenticated;
grant insert (incurred_on,category,description,amount,payer_type,paid_by_partner,
              payment_method,bill_no,note)
  on public.site_expenses to authenticated;
grant update (incurred_on,category,description,amount,payer_type,paid_by_partner,
              payment_method,bill_no,note)
  on public.site_expenses to authenticated;

drop policy if exists "read site expenses by role" on public.site_expenses;
create policy "read site expenses by role" on public.site_expenses
  for select to authenticated using (
    (select public.site_expense_role()) in ('admin','partner')
    or ((select public.site_expense_role()) = 'assistant'
        and submitted_by = (select auth.uid()))
  );
drop policy if exists "member adds own pending expense" on public.site_expenses;
create policy "member adds own pending expense" on public.site_expenses
  for insert to authenticated with check (
    (select public.site_expense_role()) is not null
    and submitted_by = (select auth.uid()) and status = 'pending'
  );
drop policy if exists "submitter edits own pending" on public.site_expenses;
create policy "submitter edits own pending" on public.site_expenses
  for update to authenticated
  using (submitted_by = (select auth.uid()) and status = 'pending'
         and (select public.site_expense_role()) is not null)
  with check (submitted_by = (select auth.uid()) and status = 'pending'
         and (select public.site_expense_role()) is not null);

-- नियम-रक्षक trigger: service_role/SQL Editor पर भी लागू।
create or replace function public.site_expenses_guard()
returns trigger language plpgsql set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'साइट खर्च हटाया नहीं जा सकता (audit हेतु सुरक्षित)';
  end if;

  if new.incurred_on > public.site_expense_today() then
    raise exception 'खर्च की तारीख भविष्य की नहीं हो सकती';
  end if;

  if tg_op = 'INSERT' then
    new.status := 'pending';
    new.version := 1;
    new.reviewed_by := null; new.reviewed_at := null; new.review_note := null;
    if auth.uid() is not null then new.submitted_by := auth.uid(); end if;
    new.updated_by := new.submitted_by;
    new.updated_at := now(); new.created_at := now();
    return new;
  end if;

  -- UPDATE
  if old.status <> 'pending' then
    raise exception 'स्वीकृत/अस्वीकृत खर्च बदला नहीं जा सकता (SE-%)', old.ref_no;
  end if;
  if new.id <> old.id or new.ref_no <> old.ref_no
     or new.submitted_by <> old.submitted_by or new.created_at <> old.created_at then
    raise exception 'पहचान वाले कॉलम बदले नहीं जा सकते';
  end if;
  if (new.status, new.reviewed_by, new.reviewed_at, new.review_note)
     is distinct from (old.status, old.reviewed_by, old.reviewed_at, old.review_note)
     and coalesce(current_setting('site_expense.reviewing', true), '') <> 'on' then
    raise exception 'स्थिति केवल review RPC से बदल सकती है';
  end if;
  new.version := old.version + 1;
  new.updated_at := now();
  new.updated_by := coalesce(auth.uid(), old.updated_by);
  return new;
end;
$$;
drop trigger if exists site_expenses_guard on public.site_expenses;
create trigger site_expenses_guard
  before insert or update or delete on public.site_expenses
  for each row execute function public.site_expenses_guard();
drop trigger if exists site_expenses_touch on public.site_expenses;
drop function if exists public.site_expense_touch();

-- ---------------------------------------------------------------- प्रमाण
create table if not exists public.site_expense_evidence (
  id                  uuid primary key default gen_random_uuid(),
  expense_id          uuid not null references public.site_expenses(id) on delete restrict,
  storage_path        text not null unique,
  original_filename   text not null check (char_length(original_filename) between 1 and 255),
  mime_type           text not null check (mime_type in (
                        'image/jpeg','image/png','image/webp','application/pdf',
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document')),
  size_bytes          bigint not null check (size_bytes > 0 and size_bytes <= 10485760),
  -- server-side सामग्री जाँच (Edge Function verify-evidence, service_role) का परिणाम
  verification_status text not null default 'pending'
                        check (verification_status in ('pending','verified','rejected')),
  verification_note   text check (verification_note is null or char_length(verification_note) <= 300),
  sha256              text check (sha256 is null or sha256 ~ '^[0-9a-f]{64}$'),
  verified_at         timestamptz,
  uploaded_by         uuid not null references auth.users(id),
  created_at          timestamptz not null default now()
);
create index if not exists site_expense_evidence_expense_idx
  on public.site_expense_evidence(expense_id);
create index if not exists site_expense_evidence_sha_idx
  on public.site_expense_evidence(sha256) where sha256 is not null;

alter table public.site_expense_evidence enable row level security;
revoke all on public.site_expense_evidence from public, anon, authenticated;
-- सीधा insert/update किसी user को नहीं: पंक्ति केवल attach RPC से बनती है,
-- जो storage में असली फ़ाइल की जाँच करता है।
grant select on public.site_expense_evidence to authenticated;

drop policy if exists "read evidence by role" on public.site_expense_evidence;
create policy "read evidence by role" on public.site_expense_evidence
  for select to authenticated using (
    (select public.site_expense_role()) in ('admin','partner')
    or ((select public.site_expense_role()) = 'assistant'
        and exists (select 1 from public.site_expenses e
                    where e.id = expense_id and e.submitted_by = (select auth.uid())))
  );

create or replace function public.site_expense_evidence_guard()
returns trigger language plpgsql set search_path = ''
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'प्रमाण हटाया नहीं जा सकता';
  end if;
  -- UPDATE: केवल pending → verified/rejected, और केवल जाँच वाले कॉलम
  if old.verification_status <> 'pending' then
    raise exception 'जाँचा हुआ प्रमाण बदला नहीं जा सकता';
  end if;
  if (new.id, new.expense_id, new.storage_path, new.original_filename, new.mime_type,
      new.size_bytes, new.uploaded_by, new.created_at)
     is distinct from
     (old.id, old.expense_id, old.storage_path, old.original_filename, old.mime_type,
      old.size_bytes, old.uploaded_by, old.created_at) then
    raise exception 'प्रमाण का मूल विवरण बदला नहीं जा सकता';
  end if;
  return new;
end;
$$;
drop trigger if exists site_expense_evidence_guard on public.site_expense_evidence;
create trigger site_expense_evidence_guard
  before update or delete on public.site_expense_evidence
  for each row execute function public.site_expense_evidence_guard();

-- Edge Function (service_role) केवल जाँच-परिणाम लिख सकती है
grant select on public.site_expenses, public.site_expense_evidence to service_role;
grant update (verification_status, verification_note, sha256, verified_at)
  on public.site_expense_evidence to service_role;

-- ---------------------------------------------------------------- Storage
-- निजी bucket: JPG/PNG/WEBP/PDF/DOCX, अधिकतम 10 MB। पुराना .doc हटाया गया।
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('site-expense-evidence', 'site-expense-evidence', false, 10485760,
        array['image/jpeg','image/png','image/webp','application/pdf',
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document'])
on conflict (id) do update
set public = false, file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "member views linked site proof" on storage.objects;
drop policy if exists "view site proof by role" on storage.objects;
create policy "view site proof by role" on storage.objects
  for select to authenticated using (
    bucket_id = 'site-expense-evidence'
    and (
      -- अपनी अपलोड की हुई फ़ाइलें (अधूरे अपलोड की recovery हेतु भी)
      ((select public.site_expense_role()) is not null
        and (storage.foldername(name))[1] = (select auth.uid())::text)
      -- admin/partner: केवल वे फ़ाइलें जो किसी खर्च से जुड़ चुकी हैं
      or ((select public.site_expense_role()) in ('admin','partner')
        and exists (select 1 from public.site_expense_evidence ev
                    where ev.storage_path = name))
    )
  );

drop policy if exists "submitter uploads to own pending expense" on storage.objects;
create policy "submitter uploads to own pending expense" on storage.objects
  for insert to authenticated with check (
    bucket_id = 'site-expense-evidence'
    and (select public.site_expense_role()) is not null
    and name ~ '^[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}\.(jpg|jpeg|png|webp|pdf|docx)$'
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and exists (
      select 1 from public.site_expenses e
      where e.id::text = (storage.foldername(name))[2]
        and e.status = 'pending' and e.submitted_by = (select auth.uid())
    )
  );
-- जानबूझकर storage update/delete policy नहीं: फ़ाइल overwrite/delete नहीं।

-- ---------------------------------------------------------------- Audit trail
create table if not exists public.site_expense_audit (
  id          bigint generated always as identity primary key,
  expense_id  uuid not null,
  evidence_id uuid,
  action      text not null,
  actor       uuid,
  actor_role  text,
  at          timestamptz not null default now(),
  old_data    jsonb,
  new_data    jsonb
);
create index if not exists site_expense_audit_expense_idx
  on public.site_expense_audit(expense_id, at);
alter table public.site_expense_audit enable row level security;
revoke all on public.site_expense_audit from public, anon, authenticated, service_role;
grant select on public.site_expense_audit to authenticated;
drop policy if exists "read audit of visible expenses" on public.site_expense_audit;
create policy "read audit of visible expenses" on public.site_expense_audit
  for select to authenticated using (
    exists (select 1 from public.site_expenses e where e.id = expense_id)
  );

create or replace function public.site_expense_audit_block()
returns trigger language plpgsql set search_path = ''
as $$ begin raise exception 'audit trail अपरिवर्तनीय है'; end; $$;
drop trigger if exists site_expense_audit_block on public.site_expense_audit;
create trigger site_expense_audit_block
  before update or delete on public.site_expense_audit
  for each row execute function public.site_expense_audit_block();
drop trigger if exists site_expense_audit_block_truncate on public.site_expense_audit;
create trigger site_expense_audit_block_truncate
  before truncate on public.site_expense_audit
  for each statement execute function public.site_expense_audit_block();

create or replace function public.site_expense_audit_write()
returns trigger language plpgsql security definer set search_path = ''
as $$
declare
  v_action text;
begin
  if tg_table_name = 'site_expenses' then
    v_action := case
      when tg_op = 'INSERT' then 'created'
      when new.status <> old.status then new.status
      else 'edited' end;
    insert into public.site_expense_audit(expense_id, action, actor, actor_role, old_data, new_data)
    values (new.id, v_action, auth.uid(), public.site_expense_role(),
            case when tg_op = 'UPDATE' then to_jsonb(old) end, to_jsonb(new));
  else
    v_action := case when tg_op = 'INSERT' then 'evidence_attached'
                     else 'evidence_' || new.verification_status end;
    insert into public.site_expense_audit(expense_id, evidence_id, action, actor, actor_role,
                                          old_data, new_data)
    values (new.expense_id, new.id, v_action, auth.uid(), public.site_expense_role(),
            case when tg_op = 'UPDATE' then to_jsonb(old) end, to_jsonb(new));
  end if;
  return null;
end;
$$;
revoke all on function public.site_expense_audit_write() from public, anon, authenticated;
drop trigger if exists site_expenses_audit on public.site_expenses;
create trigger site_expenses_audit after insert or update on public.site_expenses
  for each row execute function public.site_expense_audit_write();
drop trigger if exists site_expense_evidence_audit on public.site_expense_evidence;
create trigger site_expense_evidence_audit after insert or update on public.site_expense_evidence
  for each row execute function public.site_expense_audit_write();

-- ---------------------------------------------------------------- RPC: प्रमाण जोड़ना
-- फ़ाइल storage में अपलोड होने के बाद ही पंक्ति बनती है। आकार व MIME storage के
-- अपने रिकॉर्ड से लिए जाते हैं, client से नहीं। दोबारा चलाने पर वही पंक्ति लौटती है।
create or replace function public.site_expense_attach_evidence(
  p_expense_id uuid, p_storage_path text, p_original_filename text
) returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  v_uid  uuid := auth.uid();
  v_meta jsonb;
  v_mime text;
  v_size bigint;
  v_ext  text;
  v_id   uuid;
begin
  if public.site_expense_role() is null then
    raise exception 'सक्रिय सदस्य नहीं';
  end if;
  perform 1 from public.site_expenses e
   where e.id = p_expense_id and e.submitted_by = v_uid and e.status = 'pending'
   for update;
  if not found then
    raise exception 'केवल अपने pending खर्च में प्रमाण जोड़ सकते हैं';
  end if;
  if p_storage_path !~ ('^' || v_uid::text || '/' || p_expense_id::text
                        || '/[0-9a-f-]{36}\.(jpg|jpeg|png|webp|pdf|docx)$') then
    raise exception 'फ़ाइल का path मान्य नहीं';
  end if;

  select id into v_id from public.site_expense_evidence where storage_path = p_storage_path;
  if v_id is not null then return v_id; end if;   -- retry: पहले से जुड़ा

  select o.metadata into v_meta from storage.objects o
   where o.bucket_id = 'site-expense-evidence' and o.name = p_storage_path
     and coalesce(o.owner_id, o.owner::text) = v_uid::text;
  if v_meta is null then
    raise exception 'storage में यह फ़ाइल नहीं मिली — पहले अपलोड पूरा करें';
  end if;

  v_mime := lower(v_meta->>'mimetype');
  v_size := (v_meta->>'size')::bigint;
  v_ext  := lower(substring(p_storage_path from '\.([a-z]+)$'));
  if v_size is null or v_size <= 0 or v_size > 10485760 then
    raise exception 'फ़ाइल का आकार 1 byte से 10 MB तक होना चाहिए';
  end if;
  if not ((v_ext in ('jpg','jpeg') and v_mime = 'image/jpeg')
       or (v_ext = 'png'  and v_mime = 'image/png')
       or (v_ext = 'webp' and v_mime = 'image/webp')
       or (v_ext = 'pdf'  and v_mime = 'application/pdf')
       or (v_ext = 'docx' and v_mime =
           'application/vnd.openxmlformats-officedocument.wordprocessingml.document')) then
    raise exception 'फ़ाइल का प्रकार और extension मेल नहीं खाते';
  end if;

  insert into public.site_expense_evidence
    (expense_id, storage_path, original_filename, mime_type, size_bytes, uploaded_by)
  values (p_expense_id, p_storage_path,
          left(coalesce(nullif(btrim(p_original_filename), ''), 'file'), 255),
          v_mime, v_size, v_uid)
  returning id into v_id;

  -- नया प्रमाण = खर्च बदला; reviewer को दोबारा देखना होगा (version +1)
  update public.site_expenses set updated_at = now() where id = p_expense_id;
  return v_id;
end;
$$;
revoke all on function public.site_expense_attach_evidence(uuid,text,text) from public, anon;
grant execute on function public.site_expense_attach_evidence(uuid,text,text) to authenticated;

-- ---------------------------------------------------------------- संभावित दोहराव
-- उसी तारीख+राशि+श्रेणी वाले, या एक जैसी फ़ाइल (sha256) वाले दूसरे सक्रिय खर्च।
-- SECURITY INVOKER: हर व्यक्ति को केवल वही दिखता है जो RLS उसे दिखाता है।
create or replace function public.site_expense_duplicates(p_expense_id uuid)
returns table (ref_no bigint, status text, reason text)
language sql stable set search_path = ''
as $$
  select o.ref_no, o.status, 'same_date_amount_category'
  from public.site_expenses e
  join public.site_expenses o
    on o.id <> e.id and o.status <> 'rejected'
   and o.incurred_on = e.incurred_on and o.amount = e.amount and o.category = e.category
  where e.id = p_expense_id
  union
  select o.ref_no, o.status, 'same_file'
  from public.site_expense_evidence ev
  join public.site_expense_evidence ov
    on ov.sha256 = ev.sha256 and ov.expense_id <> ev.expense_id
  join public.site_expenses o on o.id = ov.expense_id and o.status <> 'rejected'
  where ev.expense_id = p_expense_id and ev.sha256 is not null
$$;
revoke all on function public.site_expense_duplicates(uuid) from public, anon;
grant execute on function public.site_expense_duplicates(uuid) to authenticated;

-- ---------------------------------------------------------------- RPC: समीक्षा
create or replace function public.site_expense_review(
  p_expense_id uuid, p_expected_version integer, p_approve boolean,
  p_note text default null, p_confirm_duplicate boolean default false
) returns void
language plpgsql security definer set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  e     public.site_expenses%rowtype;
  v_ok  integer; v_bad integer;
begin
  if not public.site_expense_is_reviewer() then
    raise exception 'केवल अधिकृत reviewer (admin या नामित partner) समीक्षा कर सकते हैं';
  end if;
  select * into e from public.site_expenses where id = p_expense_id for update;
  if not found or e.status <> 'pending' then
    raise exception 'खर्च नहीं मिला या पहले ही समीक्षा हो चुकी है';
  end if;
  if e.submitted_by = v_uid then
    raise exception 'अपना खर्च स्वयं स्वीकृत/अस्वीकृत नहीं कर सकते — दूसरे reviewer से कराएँ';
  end if;
  if p_expected_version is null or e.version <> p_expected_version then
    raise exception 'VERSION_CHANGED: आपके देखने के बाद यह खर्च बदला गया है — रिफ्रेश कर दोबारा जाँचें';
  end if;
  if p_note is not null and char_length(p_note) > 500 then
    raise exception 'समीक्षा टिप्पणी 500 अक्षर से अधिक';
  end if;

  if not p_approve then
    if p_note is null or char_length(btrim(p_note)) < 3 then
      raise exception 'अस्वीकृति का कारण लिखना ज़रूरी है';
    end if;
  else
    select count(*) filter (where verification_status = 'verified'),
           count(*) filter (where verification_status <> 'verified')
      into v_ok, v_bad
      from public.site_expense_evidence where expense_id = p_expense_id;
    if v_ok = 0 then
      raise exception 'स्वीकृति हेतु कम से कम एक server-जाँचा (verified) प्रमाण ज़रूरी';
    end if;
    if v_bad > 0 then
      raise exception 'कुछ प्रमाण अभी जाँच में हैं या अमान्य पाए गए — स्वीकृति रुकी';
    end if;
    if not coalesce(p_confirm_duplicate, false)
       and exists (select 1 from public.site_expense_duplicates(p_expense_id)) then
      raise exception 'POSSIBLE_DUPLICATE: इसी जैसा दूसरा खर्च मौजूद है — पुष्टि के साथ दोबारा भेजें';
    end if;
  end if;

  perform set_config('site_expense.reviewing', 'on', true);
  update public.site_expenses
     set status = case when p_approve then 'approved' else 'rejected' end,
         reviewed_by = v_uid, reviewed_at = now(), review_note = nullif(btrim(p_note), '')
   where id = p_expense_id;
  perform set_config('site_expense.reviewing', 'off', true);
end;
$$;
drop function if exists public.review_site_expense(uuid, boolean, text);
revoke all on function public.site_expense_review(uuid,integer,boolean,text,boolean) from public, anon;
grant execute on function public.site_expense_review(uuid,integer,boolean,text,boolean) to authenticated;

-- ---------------------------------------------------------------- पूरे database से योग
-- SECURITY INVOKER: assistant को केवल अपने खर्चों का योग, बाकी को सबका।
create or replace function public.site_expense_totals()
returns table (status text, payer_type text, entries bigint, total numeric)
language sql stable set search_path = ''
as $$
  select status, payer_type, count(*), coalesce(sum(amount), 0)
  from public.site_expenses group by status, payer_type
$$;
revoke all on function public.site_expense_totals() from public, anon;
grant execute on function public.site_expense_totals() to authenticated;

-- ============================================================================
-- SETUP (SQL Editor; असली UUID डालकर ही चलाएँ):
-- insert into public.site_expense_members(user_id,display_name,role,can_review) values
--   ('ADMIN_UUID','आलोक रंजन मिश्र','admin',true),
--   ('PARTNER1_UUID','अमरनाथ पाण्डेय','partner',true),   -- दूसरा reviewer
--   ('PARTNER2_UUID','गगन आचारी','partner',false),
--   ('ASSISTANT_UUID','साइट असिस्टेंट','assistant',false);
-- ============================================================================
