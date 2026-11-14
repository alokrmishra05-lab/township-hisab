"""साइट खर्च SQL के स्थानीय परीक्षण (mock Supabase पर, असली Supabase नहीं)।
चलाएँ: sudo -u postgres python3 test_site_expenses.py <dbname>
"""
import sys, uuid, json
import psycopg2

DB = sys.argv[1] if len(sys.argv) > 1 else "t"
conn = psycopg2.connect(dbname=DB)
conn.autocommit = True
cur = conn.cursor()

ADMIN, P_REV, P_NOREV, ASST, ASST2, OUT = (f"00000000-0000-0000-0000-0000000000{n:02d}" for n in range(1, 7))
results = []

def as_(user, role="authenticated"):
    cur.execute("reset role")
    cur.execute("select set_config('request.jwt.claim.sub', %s, false)", (user or "",))
    cur.execute(f"set role {role}")

def run(name, fn, expect_error=None):
    """expect_error=None → सफल होना चाहिए; string → उस अंश वाली त्रुटि अपेक्षित।"""
    try:
        out = fn()
        if expect_error:
            results.append(("FAIL", name, f"त्रुटि अपेक्षित थी ('{expect_error}'), पर सफल हुआ: {out}"))
        else:
            results.append(("PASS", name, str(out) if out is not None else ""))
        return out
    except psycopg2.Error as e:
        msg = (e.pgerror or str(e)).strip().splitlines()[0]
        if expect_error and expect_error.lower() in msg.lower():
            results.append(("PASS", name, "अपेक्षित रोक: " + msg))
        else:
            results.append(("FAIL", name, msg))
    finally:
        cur.execute("reset role")

def check(name, cond, detail=""):
    results.append(("PASS" if cond else "FAIL", name, detail))

def one(sql, args=()):
    cur.execute(sql, args)
    return cur.fetchone()[0] if cur.description else cur.rowcount

def new_expense(user, **kw):
    f = dict(incurred_on="2026-11-10", category="मिट्टी भराई", description="10 हाइवा मिट्टी",
             amount=30000, payer_type="site_cash", paid_by_partner=None,
             payment_method="नकद", bill_no=None, note=None)
    f.update(kw)
    as_(user)
    try:
        cur.execute("""insert into public.site_expenses(incurred_on,category,description,amount,
            payer_type,paid_by_partner,payment_method,bill_no,note)
            values (%(incurred_on)s,%(category)s,%(description)s,%(amount)s,%(payer_type)s,
            %(paid_by_partner)s,%(payment_method)s,%(bill_no)s,%(note)s) returning id""", f)
        return cur.fetchone()[0]
    finally:
        cur.execute("reset role")

def upload(user, expense_id, ext="pdf", mime="application/pdf", size=2048, path=None):
    """storage में फ़ाइल अपलोड (RLS सहित) — जैसा Supabase Storage API करता है।"""
    path = path or f"{user}/{expense_id}/{uuid.uuid4()}.{ext}"
    as_(user)
    try:
        cur.execute("""insert into storage.objects(bucket_id,name,owner_id,metadata)
            values ('site-expense-evidence',%s,%s,%s)""",
            (path, user, json.dumps({"mimetype": mime, "size": size})))
    finally:
        cur.execute("reset role")
    return path

def attach(user, expense_id, path, fname="bill.pdf"):
    as_(user)
    try:
        return one("select public.site_expense_attach_evidence(%s,%s,%s)", (expense_id, path, fname))
    finally:
        cur.execute("reset role")

def verify(evidence_id, status="verified", sha=None):
    """Edge Function की तरह service_role से जाँच-परिणाम लिखना।"""
    cur.execute("reset role")
    cur.execute("select set_config('request.jwt.claim.sub','',false)")
    cur.execute("set role service_role")
    try:
        cur.execute("""update public.site_expense_evidence set verification_status=%s,
            sha256=%s, verified_at=now() where id=%s""", (status, sha or uuid.uuid4().hex * 2, evidence_id))
        return cur.rowcount
    finally:
        cur.execute("reset role")

def version(eid):
    return one("select version from public.site_expenses where id=%s", (eid,))

def review(user, eid, ver, approve=True, note=None, dup=False):
    as_(user)
    try:
        cur.execute("select public.site_expense_review(%s,%s,%s,%s,%s)", (eid, ver, approve, note, dup))
        return one("select status from public.site_expenses where id=%s", (eid,))
    finally:
        cur.execute("reset role")

# ---------- सदस्य
for u in (ADMIN, P_REV, P_NOREV, ASST, ASST2, OUT):
    cur.execute("insert into auth.users values (%s) on conflict do nothing", (u,))
cur.execute("""insert into public.site_expense_members(user_id,display_name,role,can_review) values
 (%s,'आलोक रंजन मिश्र','admin',true),(%s,'अमरनाथ पाण्डेय','partner',true),
 (%s,'गगन आचारी','partner',false),(%s,'असिस्टेंट एक','assistant',false),
 (%s,'असिस्टेंट दो','assistant',false) on conflict do nothing""", (ADMIN, P_REV, P_NOREV, ASST, ASST2))

run("assistant को review अधिकार नहीं दिया जा सकता (constraint)",
    lambda: one("update public.site_expense_members set can_review=true where user_id=%s", (ASST,)),
    "site_expense_members_review_role")

# ---------- 1. अनाम पहुँच
def anon_select():
    as_(None, "anon"); return one("select count(*) from public.site_expenses")
run("anon खर्च नहीं पढ़ सकता", anon_select, "permission denied")
def anon_rpc():
    as_(None, "anon"); return one("select public.site_expense_totals()")
run("anon totals RPC नहीं चला सकता", anon_rpc, "permission denied")
def anon_audit():
    as_(None, "anon"); return one("select count(*) from public.site_expense_audit")
run("anon audit नहीं पढ़ सकता", anon_audit, "permission denied")

# ---------- 2. खर्च जोड़ना
e1 = run("assistant खर्च जोड़ सकता है", lambda: new_expense(ASST))
def asst_status():
    as_(ASST); return one("""insert into public.site_expenses(incurred_on,category,description,amount,
        payer_type,payment_method,status) values ('2026-11-10','अन्य','abc',1,'site_cash','नकद','approved')""")
run("insert में status=approved भेजना मना", asst_status, "permission denied")
run("भविष्य की तारीख रुकती है", lambda: new_expense(ASST, incurred_on="2099-01-01"), "भविष्य")
run("2020 से पहले की तारीख रुकती है", lambda: new_expense(ASST, incurred_on="2019-12-31"), "check constraint")
run("payer_type=partner पर साझेदार का नाम ज़रूरी",
    lambda: new_expense(ASST, payer_type="partner"), "site_expenses_partner_payer")
run("साइट कैश के साथ साझेदार का नाम मना",
    lambda: new_expense(ASST, payer_type="site_cash", paid_by_partner="गगन आचारी"), "site_expenses_partner_payer")
run("अनजान भुगतानकर्ता नाम रुकता है",
    lambda: new_expense(ASST, payer_type="partner", paid_by_partner="कोई बाहरी"), "check constraint")
run("सूची से बाहर की श्रेणी रुकती है", lambda: new_expense(ASST, category="कुछ भी"), "check constraint")
run("बाहरी (non-member) खर्च नहीं जोड़ सकता", lambda: new_expense(OUT), "row-level security")
e_partner = run("partner अपनी जेब से दिया खर्च जोड़ सकता है",
    lambda: new_expense(P_NOREV, payer_type="partner", paid_by_partner="गगन आचारी",
                        category="मजदूरी", amount=5000, description="मजदूरी भुगतान"))

# ---------- 3. पढ़ने के अधिकार
def count_as(user, sql):
    as_(user); return one(sql)
check("assistant केवल अपने खर्च देखता है",
      run("—", lambda: count_as(ASST, "select count(*) from public.site_expenses")) == 1)
check("दूसरा assistant पहले के खर्च नहीं देखता",
      run("—", lambda: count_as(ASST2, "select count(*) from public.site_expenses")) == 0)
check("partner सब खर्च देखता है",
      run("—", lambda: count_as(P_NOREV, "select count(*) from public.site_expenses")) == 2)
check("admin सब खर्च देखता है",
      run("—", lambda: count_as(ADMIN, "select count(*) from public.site_expenses")) == 2)
check("बाहरी व्यक्ति 0 खर्च देखता है",
      run("—", lambda: count_as(OUT, "select count(*) from public.site_expenses")) == 0)
check("assistant सदस्य-सूची में केवल खुद को देखता है",
      run("—", lambda: count_as(ASST, "select count(*) from public.site_expense_members")) == 1)

# ---------- 4. बदलाव के अधिकार
def upd(user, eid, sql_set):
    as_(user); return one(f"update public.site_expenses set {sql_set} where id=%s", (eid,))
check("partner दूसरे का pending नहीं बदल सकता (0 पंक्ति)", run("—", lambda: upd(P_REV, e1, "amount=1")) == 0)
check("assistant2 दूसरे का pending नहीं बदल सकता", run("—", lambda: upd(ASST2, e1, "amount=1")) == 0)
run("submitter सीधे status नहीं बदल सकता", lambda: upd(ASST, e1, "status='approved'"), "permission denied")
run("submitter version नहीं बदल सकता", lambda: upd(ASST, e1, "version=99"), "permission denied")
v0 = version(e1)
run("submitter अपना pending सुधार सकता है", lambda: upd(ASST, e1, "description='12 हाइवा मिट्टी'"))
check("हर सुधार पर version बढ़ता है", version(e1) == v0 + 1, f"{v0}→{version(e1)}")
def delete_as(user, eid):
    as_(user); return one("delete from public.site_expenses where id=%s", (eid,))
run("कोई user खर्च नहीं हटा सकता", lambda: delete_as(ADMIN, e1), "permission denied")
run("superuser/service से भी हटाना trigger से रुकता है",
    lambda: one("delete from public.site_expenses where id=%s", (e1,)), "हटाया नहीं")

# ---------- 5. प्रमाण (evidence)
def asst_direct_evidence():
    as_(ASST); return one("""insert into public.site_expense_evidence(expense_id,storage_path,
        original_filename,mime_type,size_bytes,uploaded_by) values (%s,%s,'x.pdf','application/pdf',10,%s)""",
        (e1, f"{ASST}/{e1}/{uuid.uuid4()}.pdf", ASST))
run("सीधे evidence पंक्ति (नकली metadata) डालना मना", asst_direct_evidence, "permission denied")
run("storage में बिना फ़ाइल के attach रुकता है",
    lambda: attach(ASST, e1, f"{ASST}/{e1}/{uuid.uuid4()}.pdf"), "storage में यह फ़ाइल नहीं")
run("दूसरे के फ़ोल्डर में अपलोड मना (storage RLS)",
    lambda: upload(ASST, e1, path=f"{ASST2}/{e1}/{uuid.uuid4()}.pdf"), "row-level security")
run("अनुमत सूची से बाहर extension (.exe) मना",
    lambda: upload(ASST, e1, ext="exe", mime="application/pdf"), "row-level security")
run("पुराना .doc मना", lambda: upload(ASST, e1, ext="doc", mime="application/msword"), "row-level security")
p_bad_mime = run("upload: .pdf नाम पर image MIME (storage में चढ़ा)", lambda: upload(ASST, e1, mime="image/png"))
run("extension और MIME मेल न खाएँ तो attach रुकता है", lambda: attach(ASST, e1, p_bad_mime), "मेल नहीं")
p_big = run("upload: 11 MB metadata", lambda: upload(ASST, e1, size=11 * 1024 * 1024))
run("10 MB से बड़ी फ़ाइल attach नहीं होती", lambda: attach(ASST, e1, p_big), "10 MB")
p1 = run("असली PDF अपलोड", lambda: upload(ASST, e1))
v_before = version(e1)
ev1 = run("असली फ़ाइल attach होती है (size/MIME storage से)", lambda: attach(ASST, e1, p1, "बिल.pdf"))
check("attach दोबारा चलाने पर वही पंक्ति (retry सुरक्षित)", attach(ASST, e1, p1) == ev1)
check("नया प्रमाण जुड़ने पर version बढ़ता है", version(e1) == v_before + 1)
run("दूसरा व्यक्ति आपकी फ़ाइल अपने खर्च से नहीं जोड़ सकता",
    lambda: attach(ASST2, e1, p1), "केवल अपने pending")
check("assistant2 को assistant1 का प्रमाण नहीं दिखता",
      run("—", lambda: count_as(ASST2, "select count(*) from public.site_expense_evidence")) == 0)
check("partner को प्रमाण दिखता है",
      run("—", lambda: count_as(P_NOREV, "select count(*) from public.site_expense_evidence")) == 1)
check("assistant2 को assistant1 की storage फ़ाइल नहीं दिखती",
      run("—", lambda: count_as(ASST2, "select count(*) from storage.objects")) == 0)
check("partner को केवल जुड़ी (linked) फ़ाइल दिखती है",
      run("—", lambda: count_as(P_NOREV, "select count(*) from storage.objects")) == 1)
def asst_update_ev():
    as_(ASST); return one("update public.site_expense_evidence set verification_status='verified' where id=%s", (ev1,))
run("submitter अपने प्रमाण को verified नहीं कर सकता", asst_update_ev, "permission denied")
def storage_delete(user):
    as_(user); return one("delete from storage.objects where bucket_id='site-expense-evidence'")
check("storage फ़ाइल कोई नहीं हटा सकता (0 पंक्ति)", run("—", lambda: storage_delete(ASST)) == 0)
def storage_overwrite(user):
    as_(user); return one("update storage.objects set metadata='{}'::jsonb where bucket_id='site-expense-evidence'")
check("storage फ़ाइल overwrite नहीं (0 पंक्ति)", run("—", lambda: storage_overwrite(ASST)) == 0)

# ---------- 6. समीक्षा अधिकार
ver = version(e1)
run("assistant review नहीं कर सकता", lambda: review(ASST, e1, ver), "केवल अधिकृत")
run("non-reviewer partner review नहीं कर सकता", lambda: review(P_NOREV, e1, ver), "केवल अधिकृत")
run("server-जाँच से पहले approve नहीं (pending evidence)", lambda: review(ADMIN, e1, ver), "verified")
verify(ev1, "verified", "a" * 64)
check("verified होने से version नहीं बदलता", version(e1) == ver)
run("गलत version पर approve रुकता है", lambda: review(ADMIN, e1, ver - 1), "VERSION_CHANGED")

# समवर्तीता: reviewer ने version देखा, फिर submitter ने राशि बदली
seen = version(e1)
upd(ASST, e1, "amount=500000")
run("देखने के बाद राशि बदली → approve रुका (₹30,000→₹5,00,000)",
    lambda: review(ADMIN, e1, seen), "VERSION_CHANGED")
upd(ASST, e1, "amount=30000")
st = run("ताज़ा version पर admin approve करता है", lambda: review(ADMIN, e1, version(e1)))
check("स्थिति approved", st == "approved")
check("approved के बाद submitter बदल नहीं सकता (0 पंक्ति)", run("—", lambda: upd(ASST, e1, "amount=1")) == 0)
run("approved को superuser से भी बदलना रुकता है",
    lambda: one("update public.site_expenses set amount=1 where id=%s", (e1,)), "बदला नहीं जा सकता")
run("approved खर्च में नई फ़ाइल नहीं जुड़ती", lambda: upload(ASST, e1), "row-level security")
run("दोबारा review नहीं", lambda: review(P_REV, e1, version(e1)), "पहले ही")

# ---------- 7. स्वयं-स्वीकृति व दूसरा reviewer
e_admin = new_expense(ADMIN, payer_type="partner", paid_by_partner="आलोक रंजन मिश्र",
                      category="कार्यालय / यात्रा", amount=7000, description="ऑफिस खर्च")
p_a = upload(ADMIN, e_admin); ev_a = attach(ADMIN, e_admin, p_a); verify(ev_a, "verified", "b" * 64)
run("admin अपना खर्च खुद approve नहीं कर सकता", lambda: review(ADMIN, e_admin, version(e_admin)), "स्वयं")
run("admin अपना खर्च खुद reject भी नहीं कर सकता",
    lambda: review(ADMIN, e_admin, version(e_admin), False, "गलत"), "स्वयं")
check("नामित partner (दूसरा reviewer) admin का खर्च approve करता है",
      run("—", lambda: review(P_REV, e_admin, version(e_admin))) == "approved")
e_prev = new_expense(P_REV, payer_type="partner", paid_by_partner="अमरनाथ पाण्डेय",
                     category="मजदूरी", amount=1200, description="मजदूरी")
p_p = upload(P_REV, e_prev); ev_p = attach(P_REV, e_prev, p_p); verify(ev_p, "verified", "c" * 64)
run("reviewer partner अपना खर्च approve नहीं कर सकता", lambda: review(P_REV, e_prev, version(e_prev)), "स्वयं")
run("reject में कारण ज़रूरी", lambda: review(ADMIN, e_prev, version(e_prev), False, None), "कारण")

# ---------- 8. नकली/अमान्य फ़ाइल
e_forged = new_expense(ASST, amount=8000, description="नकली बिल परीक्षण", incurred_on="2026-11-09")
ev_ok = attach(ASST, e_forged, upload(ASST, e_forged)); verify(ev_ok, "verified", "f" * 64)
p_f = upload(ASST, e_forged); ev_f = attach(ASST, e_forged, p_f)
verify(ev_f, "rejected", "d" * 64)   # दूसरी फ़ाइल सामग्री-जाँच में नकली निकली
run("सामग्री-जाँच में अमान्य फ़ाइल वाले खर्च का approve रुकता है",
    lambda: review(ADMIN, e_forged, version(e_forged)), "अमान्य")
run("जाँचा प्रमाण दोबारा बदला नहीं जा सकता", lambda: verify(ev_f, "verified"), "बदला नहीं")
check("ऐसा खर्च reject किया जा सकता है",
      run("—", lambda: review(ADMIN, e_forged, version(e_forged), False, "फ़ाइल अमान्य")) == "rejected")

# ---------- 9. दोहराव
e_b1 = new_expense(ASST, bill_no="INV-101", amount=1500, description="सामग्री", category="निर्माण सामग्री")
run("उसी बिल नंबर का दूसरा खर्च रुकता है", lambda: new_expense(ASST, bill_no="inv 101", amount=1500,
    description="सामग्री दोबारा", category="निर्माण सामग्री"), "duplicate key")
run("दूसरे assistant से भी वही बिल नंबर रुकता है",
    lambda: new_expense(ASST2, bill_no="INV-101", amount=10, description="अलग"), "duplicate key")
e_d1 = new_expense(ASST, amount=4444, category="मजदूरी", description="मजदूरी 1", incurred_on="2026-11-08")
e_d2 = new_expense(ASST2, amount=4444, category="मजदूरी", description="मजदूरी 2", incurred_on="2026-11-08")
for e in (e_d1, e_d2):
    pth = upload(ASST if e == e_d1 else ASST2, e)
    verify(attach(ASST if e == e_d1 else ASST2, e, pth), "verified", uuid.uuid4().hex * 2)
check("दोहराव-जाँच संभावित दोहराव दिखाती है",
      run("—", lambda: count_as(ADMIN, f"select count(*) from public.site_expense_duplicates('{e_d2}')")) == 1)
run("संभावित दोहराव पर बिना पुष्टि approve रुकता है", lambda: review(ADMIN, e_d2, version(e_d2)), "POSSIBLE_DUPLICATE")
check("पुष्टि के साथ approve संभव (सचेत निर्णय, audit में दर्ज)",
      run("—", lambda: review(ADMIN, e_d2, version(e_d2), True, "दो अलग दिन के मज़दूर", True)) == "approved")
# एक जैसी फ़ाइल (sha256) दो खर्चों में
e_s1 = new_expense(ASST, amount=111, description="फ़ाइल 1", category="अन्य", incurred_on="2026-11-01")
e_s2 = new_expense(ASST, amount=222, description="फ़ाइल 2", category="अन्य", incurred_on="2026-11-02")
same = "e" * 64
for e in (e_s1, e_s2):
    verify(attach(ASST, e, upload(ASST, e)), "verified", same)
run("एक ही फ़ाइल दो खर्चों में → approve से पहले चेतावनी", lambda: review(ADMIN, e_s2, version(e_s2)), "POSSIBLE_DUPLICATE")

# ---------- 10. योग (पूरा database)
for i in range(250):
    new_expense(ASST2, amount=10, description=f"थोक परीक्षण {i}", category="साइट रखरखाव",
                incurred_on="2026-10-01")
def totals(user):
    as_(user)
    cur.execute("select status, sum(entries), sum(total) from public.site_expense_totals() group by status order by status")
    return {r[0]: (int(r[1]), float(r[2])) for r in cur.fetchall()}
t_admin = run("—", lambda: totals(ADMIN))
check("योग पूरे database से (250+ एंट्री, 200 की सीमा नहीं)",
      t_admin.get("pending", (0, 0))[0] >= 250, str(t_admin))
t_a2 = run("—", lambda: totals(ASST2))
check("assistant के योग में केवल उसके अपने खर्च",
      sum(v[0] for v in t_a2.values()) == one("select count(*) from public.site_expenses where submitted_by=%s", (ASST2,)),
      str(t_a2))
check("approved योग = ₹30,000 + ₹7,000 + ₹4,444 (pending/rejected बाहर)",
      abs(t_admin.get("approved", (0, 0))[1] - 41444) < 0.01, str(t_admin.get("approved")))

# ---------- 11. Audit trail
n_audit = one("select count(*) from public.site_expense_audit where expense_id=%s", (e1,))
check("audit में बनना, सुधार, प्रमाण, जाँच, स्वीकृति दर्ज", n_audit >= 6, f"{n_audit} पंक्तियाँ")
check("audit में approved कार्रवाई और reviewer दर्ज",
      one("select count(*) from public.site_expense_audit where expense_id=%s and action='approved' and actor=%s",
          (e1, ADMIN)) == 1)
run("audit बदला नहीं जा सकता (superuser भी)",
    lambda: one("update public.site_expense_audit set action='x'"), "अपरिवर्तनीय")
run("audit हटाया नहीं जा सकता", lambda: one("delete from public.site_expense_audit"), "अपरिवर्तनीय")
run("audit truncate नहीं", lambda: one("truncate public.site_expense_audit"), "अपरिवर्तनीय")
def audit_insert():
    as_(ADMIN); return one("insert into public.site_expense_audit(expense_id,action) values (%s,'fake')", (e1,))
run("user नकली audit पंक्ति नहीं डाल सकता", audit_insert, "permission denied")
check("assistant2 को assistant1 का audit नहीं दिखता",
      run("—", lambda: count_as(ASST2, f"select count(*) from public.site_expense_audit where expense_id='{e1}'")) == 0)

# ---------- 12. निष्क्रिय सदस्य
cur.execute("update public.site_expense_members set active=false where user_id=%s", (ASST,))
check("निष्क्रिय सदस्य की पहुँच तुरंत बंद",
      run("—", lambda: count_as(ASST, "select count(*) from public.site_expenses")) == 0)
run("निष्क्रिय सदस्य खर्च नहीं जोड़ सकता", lambda: new_expense(ASST), "row-level security")

# ---------- रिपोर्ट
results = [r for r in results if not (r[1] == "—" and r[0] == "PASS")]  # सहायक कदम केवल असफल होने पर दिखें
w = max(len(r[1]) for r in results)
for s, n, d in results:
    print(f"{s:5} | {n}" + (f"  [{d[:110]}]" if d else ""))
p = sum(1 for r in results if r[0] == "PASS"); f = len(results) - p
print(f"\nकुल {len(results)} : PASS {p} / FAIL {f}")
sys.exit(1 if f else 0)
