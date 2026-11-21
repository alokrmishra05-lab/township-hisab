-- सूर्य कुंज | खर्च रजिस्टर — "कुल हिसाब" (निवेश + खर्च, साझेदार-वार हिस्सा)  — expense-register.sql के बाद
-- केवल Surya Kunj project में। दोबारा चलाना सुरक्षित (idempotent)।
--
-- * हर एंट्री (निवेश या खर्च) रजिस्टर में ही दर्ज होती है; "भूमि खरीद" श्रेणी = निवेश, बाकी = खर्च।
-- * जिस एंट्री का भुगतानकर्ता कोई साझेदार है, वह उस साझेदार का योगदान है।
--   कुल = साझेदारों का कुल योगदान; हर साझेदार का तय हिस्सा = कुल × हिस्सा;
--   अंतर = योगदान − तय हिस्सा  (+ = बाकी से लेना, − = देना)। पुराने हिसाब पेज का यही नियम।
-- * जिसका भुगतानकर्ता साझेदार नहीं (जैसे "साइट कैश"), वह अलग "अन्य भुगतानकर्ता" पंक्ति में दिखता है।

-- ---------- नई श्रेणियाँ (पुराने हिसाब की: भूमि खरीद, दलाली / कमीशन, आर्किटेक्ट)
do $$
declare c text;
begin
  for c in select conname from pg_constraint
            where conrelid = 'public.sk_expenses'::regclass and contype = 'c'
              and pg_get_constraintdef(oid) like '%category%'
  loop
    execute format('alter table public.sk_expenses drop constraint %I', c);
  end loop;
end $$;
alter table public.sk_expenses add constraint sk_expenses_category_check check (category in (
  'भूमि खरीद','भूमि / रजिस्ट्री','दलाली / कमीशन','आर्किटेक्ट','मिट्टी भराई','मजदूरी','निर्माण सामग्री',
  'बिजली / पानी','मशीन / वाहन','कार्यालय / यात्रा','लेआउट / स्वीकृति शुल्क','सड़क / प्लॉटिंग विकास',
  'कानूनी / दस्तावेज़','साइट रखरखाव','अन्य'));

-- ---------- साझेदार और हिस्सा (Admin SQL से बदलता है)। हिस्सा = parts / सभी parts का योग
-- (बराबर हिस्से = हर साझेदार 1 part; इससे 1/3 जैसा हिस्सा पैसे तक सटीक बँटता है)
create table if not exists public.sk_partners (
  name  text primary key check (char_length(btrim(name)) between 2 and 100),
  parts integer not null default 1 check (parts between 1 and 1000),
  sort  integer not null default 0
);
alter table public.sk_partners enable row level security;
revoke all on public.sk_partners from public, anon, authenticated;
insert into public.sk_partners(name, parts, sort) values
  ('आलोक रंजन मिश्र', 1, 1), ('अमरनाथ पाण्डेय', 1, 2), ('गगन आचारी', 1, 3)
on conflict (name) do nothing;

-- ---------- कुल हिसाब (Read अधिकार)
create or replace function public.sk_partner_summary()
returns table (kind text, name text, share numeric, invest text, spend text, total text, due text, diff text, entries bigint)
language plpgsql stable security definer set search_path = ''
as $$
declare v_total numeric(16,2); v_parts integer;
begin
  if not public.sk_has('read') then raise exception 'Read अधिकार नहीं'; end if;
  select coalesce(sum(p.parts), 0) into v_parts from public.sk_partners p;
  select coalesce(sum(e.amount), 0) into v_total
    from public.sk_expenses e join public.sk_partners p on p.name = e.payer where e.status = 'active';
  return query
    select 'partner'::text, p.name, round(p.parts::numeric / nullif(v_parts, 0), 6),
           coalesce(sum(e.amount) filter (where e.category = 'भूमि खरीद'), 0)::numeric(16,2)::text,
           coalesce(sum(e.amount) filter (where e.category <> 'भूमि खरीद'), 0)::numeric(16,2)::text,
           coalesce(sum(e.amount), 0)::numeric(16,2)::text,
           round(v_total * p.parts / nullif(v_parts, 0), 2)::numeric(16,2)::text,
           (coalesce(sum(e.amount), 0) - round(v_total * p.parts / nullif(v_parts, 0), 2))::numeric(16,2)::text,
           count(e.id)
      from public.sk_partners p
      left join public.sk_expenses e on e.payer = p.name and e.status = 'active'
     group by p.name, p.parts, p.sort
    union all
    select 'all', 'कुल (साझेदार)', null::numeric,
           coalesce(sum(e.amount) filter (where e.category = 'भूमि खरीद'), 0)::numeric(16,2)::text,
           coalesce(sum(e.amount) filter (where e.category <> 'भूमि खरीद'), 0)::numeric(16,2)::text,
           v_total::text, null, null, count(*)
      from public.sk_expenses e join public.sk_partners p on p.name = e.payer where e.status = 'active'
    union all
    select 'other', 'अन्य भुगतानकर्ता', null::numeric,
           coalesce(sum(e.amount) filter (where e.category = 'भूमि खरीद'), 0)::numeric(16,2)::text,
           coalesce(sum(e.amount) filter (where e.category <> 'भूमि खरीद'), 0)::numeric(16,2)::text,
           coalesce(sum(e.amount), 0)::numeric(16,2)::text, null, null, count(*)
      from public.sk_expenses e
     where e.status = 'active' and not exists (select 1 from public.sk_partners p where p.name = e.payer);
end;
$$;
revoke all on function public.sk_partner_summary() from public, anon;
grant execute on function public.sk_partner_summary() to authenticated;
