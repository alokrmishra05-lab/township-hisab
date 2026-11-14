-- सूर्य कुंज | साइट खर्च: Supabase SQL Editor में एक बार चलाएँ
-- यह नया मॉड्यूल है; मौजूदा एन्क्रिप्टेड मूल हिसाब/15 एंट्री नहीं बदलता।
-- SECURITY: GitHub Pages पर service_role key या database password कभी न रखें।

create table if not exists public.site_expense_members (
  user_id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null check (char_length(trim(display_name)) between 2 and 100),
  role text not null check (role in ('admin','partner','assistant')),
  active boolean not null default true,
  created_at timestamptz not null default now()
);
alter table public.site_expense_members enable row level security;
revoke all on public.site_expense_members from anon, authenticated;
grant select on public.site_expense_members to authenticated;
drop policy if exists "member sees own profile" on public.site_expense_members;
create policy "member sees own profile" on public.site_expense_members
  for select to authenticated using (user_id = (select auth.uid()));

-- RLS में members टेबल का recursion न हो: केवल सक्रिय सदस्य की भूमिका लौटाता है।
create or replace function public.site_expense_role()
returns text language sql stable security definer set search_path = ''
as $$
  select m.role from public.site_expense_members m
  where m.user_id = (select auth.uid()) and m.active = true
  limit 1
$$;
revoke all on function public.site_expense_role() from public, anon;
grant execute on function public.site_expense_role() to authenticated;

create table if not exists public.site_expenses (
  id uuid primary key default gen_random_uuid(),
  incurred_on date not null,
  category text not null check (char_length(trim(category)) between 2 and 80),
  description text not null check (char_length(trim(description)) between 3 and 1000),
  amount numeric(14,2) not null check (amount > 0 and amount <= 100000000),
  paid_by text not null check (char_length(trim(paid_by)) between 2 and 100),
  payment_method text not null check (payment_method in ('नकद','UPI','बैंक','अन्य')),
  bill_no text check (bill_no is null or char_length(bill_no) <= 120),
  note text check (note is null or char_length(note) <= 1000),
  submitted_by uuid not null default auth.uid() references auth.users(id),
  status text not null default 'pending'
    check (status in ('pending','approved','rejected')),
  reviewed_by uuid references auth.users(id),
  reviewed_at timestamptz,
  review_note text check (review_note is null or char_length(review_note) <= 500),
  updated_by uuid references auth.users(id),
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index if not exists site_expenses_status_date_idx
  on public.site_expenses(status, incurred_on desc);
alter table public.site_expenses enable row level security;
revoke all on public.site_expenses from anon, authenticated;
grant select on public.site_expenses to authenticated;
grant insert (incurred_on,category,description,amount,paid_by,payment_method,bill_no,note)
  on public.site_expenses to authenticated;
grant update (incurred_on,category,description,amount,paid_by,payment_method,bill_no,note)
  on public.site_expenses to authenticated;

drop policy if exists "member reads site expenses" on public.site_expenses;
create policy "member reads site expenses" on public.site_expenses
  for select to authenticated using ((select public.site_expense_role()) is not null);
drop policy if exists "member adds pending expense" on public.site_expenses;
create policy "member adds pending expense" on public.site_expenses
  for insert to authenticated
  with check (
    (select public.site_expense_role()) in ('admin','partner','assistant')
    and submitted_by = (select auth.uid()) and status = 'pending'
    and reviewed_by is null and reviewed_at is null
  );
drop policy if exists "submitter edits own pending" on public.site_expenses;
create policy "submitter edits own pending" on public.site_expenses
  for update to authenticated
  using (submitted_by = (select auth.uid()) and status = 'pending'
    and (select public.site_expense_role()) is not null)
  with check (submitted_by = (select auth.uid()) and status = 'pending'
    and (select public.site_expense_role()) is not null);

create or replace function public.site_expense_touch()
returns trigger language plpgsql security definer set search_path = ''
as $$
begin
  new.updated_at := now();
  new.updated_by := auth.uid();
  return new;
end;
$$;
drop trigger if exists site_expenses_touch on public.site_expenses;
create trigger site_expenses_touch before update on public.site_expenses
for each row execute function public.site_expense_touch();

create table if not exists public.site_expense_evidence (
  id uuid primary key default gen_random_uuid(),
  expense_id uuid not null references public.site_expenses(id) on delete restrict,
  storage_path text not null unique,
  original_filename text not null check (char_length(original_filename) between 1 and 255),
  mime_type text not null,
  size_bytes integer not null check (size_bytes > 0 and size_bytes <= 10485760),
  uploaded_by uuid not null default auth.uid() references auth.users(id),
  created_at timestamptz not null default now()
);
create index if not exists site_expense_evidence_expense_idx
  on public.site_expense_evidence(expense_id);
alter table public.site_expense_evidence enable row level security;
revoke all on public.site_expense_evidence from anon, authenticated;
grant select on public.site_expense_evidence to authenticated;
grant insert (expense_id,storage_path,original_filename,mime_type,size_bytes)
  on public.site_expense_evidence to authenticated;

drop policy if exists "member reads evidence metadata" on public.site_expense_evidence;
create policy "member reads evidence metadata" on public.site_expense_evidence
  for select to authenticated using ((select public.site_expense_role()) is not null);
drop policy if exists "submitter adds proof to pending" on public.site_expense_evidence;
create policy "submitter adds proof to pending" on public.site_expense_evidence
  for insert to authenticated
  with check (
    (select public.site_expense_role()) is not null
    and uploaded_by = (select auth.uid())
    and storage_path like (select auth.uid())::text || '/' || expense_id::text || '/%'
    and exists (
      select 1 from public.site_expenses e
      where e.id = expense_id and e.status = 'pending'
        and e.submitted_by = (select auth.uid())
    )
  );

-- निजी bucket: JPEG/PNG/WEBP/PDF/DOC/DOCX, अधिकतम 10 MB प्रति फ़ाइल।
insert into storage.buckets
  (id,name,public,file_size_limit,allowed_mime_types)
values
  ('site-expense-evidence','site-expense-evidence',false,10485760,
   array['image/jpeg','image/png','image/webp','application/pdf',
         'application/msword','application/vnd.openxmlformats-officedocument.wordprocessingml.document'])
on conflict (id) do update
set public = false, file_size_limit = excluded.file_size_limit,
    allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "member views linked site proof" on storage.objects;
create policy "member views linked site proof" on storage.objects
  for select to authenticated using (
    bucket_id = 'site-expense-evidence'
    and (select public.site_expense_role()) is not null
    and exists (
      select 1 from public.site_expense_evidence ev
      where ev.storage_path = name
    )
  );

drop policy if exists "submitter uploads to own pending expense" on storage.objects;
create policy "submitter uploads to own pending expense" on storage.objects
  for insert to authenticated with check (
    bucket_id = 'site-expense-evidence'
    and (select public.site_expense_role()) is not null
    and (storage.foldername(name))[1] = (select auth.uid())::text
    and exists (
      select 1 from public.site_expenses e
      where e.id::text = (storage.foldername(name))[2]
      and e.status = 'pending' and e.submitted_by = (select auth.uid())
    )
  );
-- जानबूझकर update/delete policy नहीं: मंज़ूर दस्तावेज़ बदले/हटाए न जा सकें।

-- Approve/reject केवल admin, UI बटन से या RPC के माध्यम से; सदस्यों को सीधे
-- status,reviewed_by,reviewed_at,review_note बदलने का column permission नहीं।
create or replace function public.review_site_expense(
  p_expense_id uuid, p_approve boolean, p_note text default null
)
returns void language plpgsql security definer set search_path = ''
as $$
begin
  if (select public.site_expense_role()) is distinct from 'admin' then
    raise exception 'Only an active site-expense admin can review';
  end if;
  if p_note is not null and char_length(p_note) > 500 then
    raise exception 'Review note too long';
  end if;
  if p_approve and not exists (
    select 1 from public.site_expense_evidence ev
    where ev.expense_id = p_expense_id
  ) then
    raise exception 'Approval requires at least one uploaded evidence file';
  end if;
  update public.site_expenses
  set status = case when p_approve then 'approved' else 'rejected' end,
      reviewed_by = auth.uid(), reviewed_at = now(), review_note = p_note
  where id = p_expense_id and status = 'pending';
  if not found then
    raise exception 'Expense missing or already reviewed';
  end if;
end;
$$;
revoke all on function public.review_site_expense(uuid,boolean,text) from public, anon;
grant execute on function public.review_site_expense(uuid,boolean,text) to authenticated;

-- IMPORTANT SETUP (SQL Editor; examples only, do not run without real user IDs):
-- 1. Supabase Authentication > Users में email/password accounts बनाएँ।
-- 2. नीचे के example में UUID बदलकर admin को अधिकार दें:
-- insert into public.site_expense_members(user_id,display_name,role)
-- values ('ACTUAL_ADMIN_AUTH_UUID','आलोक रंजन मिश्र','admin');
-- 3. साइट कर्मचारी के लिए role='assistant', साझेदार के लिए role='partner'।
-- 4. Email signups सार्वजनिक रूप से बंद रखें; Users केवल admin invite करे।
