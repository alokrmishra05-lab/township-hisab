"""निजी खर्च रजिस्टर — SQL/RLS परीक्षण (स्थानीय PostgreSQL पर mock Supabase; असली Supabase नहीं)।
चलाएँ: sudo -u postgres python3 test_expense_register.py <db>
सभी नाम/राशियाँ कृत्रिम हैं।
"""
import sys, uuid, json
from decimal import Decimal
import psycopg2

conn = psycopg2.connect(dbname=sys.argv[1] if len(sys.argv) > 1 else "t")
conn.autocommit = True
cur = conn.cursor()
U = {k: f"00000000-0000-0000-0000-0000000001{n:02d}" for n, k in enumerate(
    ["admin", "reader", "writer", "corrector", "rw", "pending", "rejected", "removed", "outsider", "intruder"])}
res = []

def as_(who, role="authenticated"):
    cur.execute("reset role")
    cur.execute("select set_config('request.jwt.claim.sub', %s, false)", (U.get(who, "") if who else "",))
    cur.execute(f"set role {role}")

def run(group, name, fn, expect=None):
    try:
        out = fn()
        res.append((group, "FAIL" if expect else "PASS", name, f"त्रुटि अपेक्षित थी: {expect}" if expect else ""))
        return out
    except psycopg2.Error as e:
        msg = (e.pgerror or str(e)).strip().splitlines()[0]
        ok = expect and expect.lower() in msg.lower()
        res.append((group, "PASS" if ok else "FAIL", name, msg if not ok else ""))
    finally:
        cur.execute("reset role")

def check(group, name, cond, info=""):
    res.append((group, "PASS" if cond else "FAIL", name, "" if cond else info))

def q(who, sql, args=(), role="authenticated"):
    as_(who, role)
    try:
        cur.execute(sql, args)
        return cur.fetchall() if cur.description else cur.rowcount
    finally:
        cur.execute("reset role")

def val(who, sql, args=()):
    r = q(who, sql, args)
    return r[0][0] if isinstance(r, list) and r else r

def add(who, date="2026-11-10", item="मिट्टी 10 हाइवा", cat="मिट्टी भराई", amt="30000.50", payer="साइट कैश", method="नकद"):
    r = q(who, "select * from public.sk_add_expense(%s,%s,%s,%s,%s,%s)", (date, item, cat, amt, payer, method))
    return r[0]  # (id, ref_no, version)

def total(who, **kw):
    rows = q(who, "select kind,key,entries,total from public.sk_summary(%s,%s,%s,%s)",
             (kw.get("f"), kw.get("t"), kw.get("c"), kw.get("p")))
    return {(k, key): (n, Decimal(t)) for k, key, n, t in rows}

def reserve(who, exp, ext="pdf"):
    return val(who, "select public.sk_reserve_receipt_slot(%s,%s)", (exp, ext))

def upload(who, exp, ext="pdf", mime="application/pdf", size=2048, path=None):
    """path न दें: पहले server-आरक्षण (जैसा UI करता है)। path दें: बिना आरक्षण सीधा storage प्रयास।"""
    path = path or reserve(who, exp, ext)
    q(who, "insert into storage.objects(bucket_id,name,owner_id,metadata) values ('sk-receipts',%s,%s,%s)",
      (path, U[who], json.dumps({"mimetype": mime, "size": size})))
    return path

# ---------- तैयारी: users, bootstrap admin (SQL Editor की तरह postgres से)
for u in U.values():
    cur.execute("insert into auth.users values (%s) on conflict do nothing", (u,))
G = "0 तैयारी"
run(G, "SQL Editor से पहला Admin तय", lambda: cur.execute("select public.sk_bootstrap_admin(%s,'आलोक (परीक्षण)')", (U["admin"],)))
run(G, "दूसरा Admin bootstrap नहीं हो सकता",
    lambda: cur.execute("select public.sk_bootstrap_admin(%s,'दूसरा')", (U["reader"],)), "पहले से तय")
run(G, "logged-in user bootstrap नहीं चला सकता",
    lambda: q("intruder", "select public.sk_bootstrap_admin(%s,'मैं')", (U["intruder"],)), "permission denied")

for who in ["reader", "writer", "corrector", "rw", "pending", "rejected", "removed", "intruder"]:
    run(G, f"{who}: लॉगिन करके जुड़ने का अनुरोध", lambda w=who: q(w, "select public.sk_request_membership(%s)", (f"{w} परीक्षण",)))
check(G, "अनुरोध के बाद स्थिति Pending, कोई अधिकार नहीं",
      val("reader", "select status||can_read||can_write||can_correct from public.sk_members where user_id=%s", (U["reader"],)) == "pendingfalsefalsefalse")

def decide(user, ok, r=False, w=False, c=False, note=None, by="admin"):
    return q(by, "select public.sk_admin_decide(%s,%s,%s,%s,%s,%s)", (U[user], ok, r, w, c, note))
run(G, "Admin: reader को केवल Read", lambda: decide("reader", True, r=True))
run(G, "Admin: writer को केवल Write", lambda: decide("writer", True, w=True))
run(G, "Admin: corrector को केवल सुधार", lambda: decide("corrector", True, c=True))
run(G, "Admin: rw को Read+Write", lambda: decide("rw", True, r=True, w=True))
run(G, "Admin: removed (पहले मंज़ूर Read+Write)", lambda: decide("removed", True, r=True, w=True))
run(G, "Admin: rejected का अनुरोध अस्वीकार", lambda: decide("rejected", False, note="पहचान स्पष्ट नहीं"))
run(G, "मंज़ूरी बिना किसी अधिकार के नहीं", lambda: decide("intruder", True), "कम से कम एक अधिकार")

# removed से पहले उसकी एक एंट्री व रसीद, फिर हटाना
e_rem = add("removed", item="हटाए गए सदस्य की एंट्री", amt="111.11")
p_rem = upload("removed", e_rem[0])
q("removed", "select public.sk_attach_receipt(%s,%s,'r.pdf')", (e_rem[0], p_rem))
run(G, "Admin: सदस्य को हटाना", lambda: q("admin", "select public.sk_admin_remove(%s,'काम समाप्त')", (U["removed"],)))

# ---------- स्वीकृति जाँच 1: Pending/अस्वीकृत/हटाए गए — सीधे अनुरोध से भी कुछ नहीं
G = "जाँच 1"
e1 = add("rw", item="सीमेंट 50 बोरी", cat="निर्माण सामग्री", amt="21500.75", payer="गगन आचारी", method="UPI")
p1 = upload("rw", e1[0])
r1 = q("rw", "select public.sk_attach_receipt(%s,%s,'bill.pdf')", (e1[0], p1))[0][0]
for who in ["pending", "rejected", "removed", "outsider"]:
    check(G, f"{who}: खर्च तालिका सीधे पढ़ने पर 0 पंक्ति", val(who, "select count(*) from public.sk_expenses") == 0)
    check(G, f"{who}: रसीद तालिका 0 पंक्ति", val(who, "select count(*) from public.sk_receipts") == 0)
    check(G, f"{who}: storage की निजी रसीद नहीं दिखती", val(who, "select count(*) from storage.objects") == 0)
    check(G, f"{who}: बदलाव-रिकॉर्ड 0 पंक्ति", val(who, "select count(*) from public.sk_expense_audit") == 0)
    run(G, f"{who}: कुल (summary) RPC रुका", lambda w=who: q(w, "select * from public.sk_summary()"), "Read अधिकार नहीं")
    run(G, f"{who}: खर्च जोड़ना रुका", lambda w=who: add(w), "Write")
    run(G, f"{who}: सुधार RPC रुका", lambda w=who: q(w, "select public.sk_correct_expense(%s,%s,'2026-11-10','x','अन्य',1,'xy','नकद','कोई कारण')", (e1[0], e1[2])), "सुधार")
    run(G, f"{who}: जगह-आरक्षण रुका", lambda w=who: reserve(w, e1[0]), "अधिकार नहीं")
    run(G, f"{who}: बिना आरक्षण सीधा storage upload रुका", lambda w=who: upload(w, e1[0], path=f"{U[w]}/{e1[0]}/{uuid.uuid4()}.pdf"), "row-level security")
    run(G, f"{who}: किसी दूसरे की फ़ाइल को अपने नाम attach नहीं", lambda w=who: q(w, "select public.sk_attach_receipt(%s,%s,'x.pdf')", (e1[0], p1)), "अधिकार नहीं")
check(G, "हटाए गए सदस्य को अपनी पुरानी रसीद भी नहीं दिखती", val("removed", "select count(*) from storage.objects") == 0)
for role in ["anon"]:
    run(G, "anon: खर्च तालिका", lambda: q(None, "select count(*) from public.sk_expenses", role="anon"), "permission denied")
    run(G, "anon: storage/RPC", lambda: q(None, "select * from public.sk_summary()", role="anon"), "permission denied")

# ---------- स्वीकृति जाँच 2: खुद को मंज़ूर/अधिकार नहीं; वापस लेने पर अगली कार्रवाई रुके
G = "जाँच 2"
run(G, "pending सदस्य खुद को मंज़ूर नहीं कर सकता", lambda: decide("intruder", True, r=True, by="intruder"), "केवल Admin")
run(G, "सक्रिय सदस्य अपने अधिकार नहीं बढ़ा सकता", lambda: q("reader", "select public.sk_admin_set_rights(%s,true,true,true,null)", (U["reader"],)), "केवल Admin")
run(G, "सदस्य-तालिका में सीधा update मना", lambda: q("intruder", "update public.sk_members set status='active',can_read=true where user_id=%s", (U["intruder"],)), "permission denied")
run(G, "सीधा insert (खुद को Admin) मना", lambda: q("outsider", "insert into public.sk_members(user_id,display_name,status,is_admin) values (%s,'x','active',true)", (U["outsider"],)), "permission denied")
run(G, "अनुरोध दोहराकर अधिकार नहीं मिलते", lambda: q("intruder", "select public.sk_request_membership('फिर से')"))
check(G, "…स्थिति अब भी pending", val("intruder", "select status from public.sk_members where user_id=%s", (U["intruder"],)) == "pending")
run(G, "Admin अपनी Admin पहचान/अधिकार RPC से नहीं बदल सकता", lambda: q("admin", "select public.sk_admin_set_rights(%s,false,false,false,null)", (U["admin"],)), "Admin")
run(G, "Admin को हटाया नहीं जा सकता", lambda: q("admin", "select public.sk_admin_remove(%s,null)", (U["admin"],)), "Admin")
run(G, "superuser से भी is_admin बदलना trigger से रुका", lambda: cur.execute("update public.sk_members set is_admin=true where user_id=%s", (U["reader"],)), "RPC")
run(G, "दूसरा Admin unique index से असंभव (bootstrap से भी)", lambda: cur.execute("select public.sk_bootstrap_admin(%s,'x')", (U["rw"],)), "पहले से तय")
# writer लॉगिन रहते हुए (वही session/JWT) — Admin Write वापस लेता है
e_w = run(G, "writer (Write) खर्च जोड़ता है", lambda: add("writer", item="मजदूरी 4 लोग", cat="मजदूरी", amt="2400.00", payer="साइट कैश"))
run(G, "Admin: writer का Write वापस", lambda: q("admin", "select public.sk_admin_set_rights(%s,false,false,false,'अस्थायी रोक')", (U["writer"],)))
run(G, "उसी लॉगिन से अगली कार्रवाई (खर्च जोड़ना) तुरंत रुकी", lambda: add("writer"), "Write")
run(G, "…और अपनी अपलोड की रसीद अब भी दिखती है? (सक्रिय सदस्य: हाँ)", lambda: val("writer", "select count(*) from storage.objects"))
run(G, "Admin: writer को Write वापस दिया", lambda: q("admin", "select public.sk_admin_set_rights(%s,false,true,false,null)", (U["writer"],)))
run(G, "reader: Read वापस लेने पर सूची तुरंत बंद", lambda: q("admin", "select public.sk_admin_set_rights(%s,false,false,false,null)", (U["reader"],)))
check(G, "…reader को अब 0 खर्च", val("reader", "select count(*) from public.sk_expenses") == 0)
q("admin", "select public.sk_admin_set_rights(%s,true,false,false,null)", (U["reader"],))
check(G, "मंज़ूरी/अस्वीकृति/अधिकार/हटाने का रिकॉर्ड बना",
      {r[0] for r in q("admin", "select distinct action from public.sk_member_audit")} >=
      {"admin_bootstrap", "requested", "approved", "rejected", "rights_changed", "removed"})
check(G, "सदस्य-रिकॉर्ड केवल Admin देखता है", val("rw", "select count(*) from public.sk_member_audit") == 0)
run(G, "सदस्य-रिकॉर्ड बदला नहीं जा सकता", lambda: cur.execute("delete from public.sk_member_audit"), "अपरिवर्तनीय")

# ---------- स्वीकृति जाँच 3: Read बनाम Write बनाम सुधार
G = "जाँच 3"
run(G, "Read वाला खर्च नहीं जोड़ सकता", lambda: add("reader"), "Write")
run(G, "Read वाला सीधे insert भी नहीं", lambda: q("reader", "insert into public.sk_expenses(expense_date,item,category,amount,payer,payment_method,created_by,created_by_name) values ('2026-11-01','x','अन्य',1,'xx','नकद',%s,'x')", (U["reader"],)), "permission denied")
run(G, "Read वाला सुधार नहीं कर सकता", lambda: q("reader", "select public.sk_correct_expense(%s,%s,'2026-11-10','x1','अन्य',1,'xy','नकद','गलती सुधार')", (e1[0], e1[2])), "सुधार")
run(G, "Read वाला रद्द नहीं कर सकता", lambda: q("reader", "select public.sk_cancel_expense(%s,%s,'गलत एंट्री')", (e1[0], e1[2])), "सुधार")
check(G, "Read वाले को सूची दिखती है", val("reader", "select count(*) from public.sk_expenses") >= 2)
check(G, "Read वाले को दूसरों की रसीद नहीं दिखती (केवल Admin/सुधार/स्वयं)", val("reader", "select count(*) from storage.objects") == 0)
run(G, "Write वाला खर्च जोड़ सकता है", lambda: add("writer", item="JCB 3 घंटे", cat="मशीन / वाहन", amt="3600.00"))
run(G, "Write वाला पुराना खर्च सुधार नहीं सकता", lambda: q("writer", "select public.sk_correct_expense(%s,%s,'2026-11-10','x1','अन्य',1,'xy','नकद','गलती सुधार')", (e1[0], e1[2])), "सुधार")
run(G, "Write वाला अपना खर्च भी सुधार नहीं सकता", lambda: q("writer", "select public.sk_correct_expense(%s,%s,'2026-11-10','x1','अन्य',1,'xy','नकद','अपनी गलती')", (e_w[0], e_w[2])), "सुधार")
run(G, "Write वाला रद्द नहीं कर सकता", lambda: q("writer", "select public.sk_cancel_expense(%s,%s,'गलत एंट्री')", (e_w[0], e_w[2])), "सुधार")
check(G, "Write-only को खर्च सूची नहीं (Read नहीं)", val("writer", "select count(*) from public.sk_expenses") == 0)
p_w = run(G, "Write वाला अपने खर्च में रसीद upload", lambda: upload("writer", e_w[0], ext="jpg", mime="image/jpeg"))
run(G, "…और attach", lambda: q("writer", "select public.sk_attach_receipt(%s,%s,'IMG.jpg')", (e_w[0], p_w)))
check(G, "Write वाला अपनी रसीद देख सकता है", val("writer", "select count(*) from storage.objects") == 1)
run(G, "Write वाला दूसरे के खर्च में जगह आरक्षित नहीं कर सकता", lambda: upload("writer", e1[0]), "अधिकार नहीं")
run(G, "…और सीधा storage upload भी नहीं", lambda: upload("writer", e1[0], path=f"{U['writer']}/{e1[0]}/{uuid.uuid4()}.pdf"), "row-level security")
check(G, "Admin भी storage से जुड़ी रसीद delete नहीं कर सकता (0 पंक्ति)", q("admin", "delete from storage.objects") == 0)
check(G, "Admin भी रसीद overwrite नहीं कर सकता (0 पंक्ति)", q("admin", "update storage.objects set metadata='{}'::jsonb") == 0)
run(G, "सुधार वाला नया खर्च नहीं जोड़ सकता (Write नहीं)", lambda: add("corrector"), "Write")
run(G, "सुधार वाला summary नहीं देखता (Read नहीं)", lambda: q("corrector", "select * from public.sk_summary()"), "Read")

# ---------- सुधार-पहुँच का दायरा (समीक्षा के बाद)
G = "सुधार-पहुँच"
check(G, "केवल-सुधार: सीधे खर्च-सूची 0 पंक्ति (सूची के लिए Read ज़रूरी)", val("corrector", "select count(*) from public.sk_expenses") == 0)
check(G, "केवल-सुधार: सीधे रसीद-तालिका 0 पंक्ति", val("corrector", "select count(*) from public.sk_receipts") == 0)
check(G, "केवल-सुधार: सीधे इतिहास 0 पंक्ति", val("corrector", "select count(*) from public.sk_expense_audit") == 0)
check(G, "केवल-सुधार: storage सूची में कोई रसीद नहीं (खोलने से पहले)", val("corrector", "select count(*) from storage.objects") == 0)
e1_ref = val("admin", "select ref_no from public.sk_expenses where id=%s", (e1[0],))
op = run(G, "केवल-सुधार: क्रमांक से एक खर्च खोलता है", lambda: val("corrector", "select public.sk_open_for_correction(%s)", (e1_ref,)))
check(G, "…उसमें खर्च, उसकी रसीद और इतिहास मिलते हैं", bool(op) and op["expense"]["id"] == e1[0] and len(op["receipts"]) == 1 and len(op["history"]) >= 2, str(op)[:120] if op else "")
check(G, "…अब केवल उसी खर्च की रसीद storage में दिखती है (1)", val("corrector", "select count(*) from storage.objects") == 1)
check(G, "…वह रसीद उसी खर्च की है", val("corrector", "select name from storage.objects") == p1)
check(G, "खोलना Admin के रिकॉर्ड में दर्ज", val("admin", "select count(*) from public.sk_correction_opens where user_id=%s", (U["corrector"],)) == 1)
check(G, "सदस्य खोलने का रिकॉर्ड नहीं देख/बदल सकता", val("corrector", "select count(*) from public.sk_correction_opens") == 0)
run(G, "खोलने का रिकॉर्ड बदला नहीं जा सकता", lambda: cur.execute("update public.sk_correction_opens set expires_at=now()+interval '1 year'"), "अपरिवर्तनीय")
cur.execute("alter table public.sk_correction_opens disable trigger sk_correction_opens_block")
cur.execute("update public.sk_correction_opens set expires_at = now() - interval '1 second'")   # परीक्षण हेतु समय बीतना
cur.execute("alter table public.sk_correction_opens enable trigger sk_correction_opens_block")
check(G, "10 मिनट बाद (समय बीतने पर) रसीद फिर बंद", val("corrector", "select count(*) from storage.objects") == 0)
run(G, "Read/सुधार दोनों नहीं: क्रमांक से खोलना रुका", lambda: val("reader", "select public.sk_open_for_correction(%s)", (e1_ref,)), "सुधार")
run(G, "Write-only: क्रमांक से खोलना रुका", lambda: val("writer", "select public.sk_open_for_correction(%s)", (e1_ref,)), "सुधार")
run(G, "अनजान क्रमांक", lambda: val("corrector", "select public.sk_open_for_correction(999999)"), "नहीं मिला")
q("admin", "select public.sk_admin_set_rights(%s,true,false,true,null)", (U["corrector"],))
check(G, "Read+सुधार: सूची और सभी जुड़ी रसीदें", val("corrector", "select count(*) from public.sk_expenses") >= 3 and val("corrector", "select count(*) from public.sk_receipts") >= 3)
q("admin", "select public.sk_admin_set_rights(%s,false,false,true,null)", (U["corrector"],))
val("corrector", "select public.sk_open_for_correction(%s)", (e1_ref,))
q("admin", "select public.sk_admin_set_rights(%s,false,false,false,'सुधार वापस')", (U["corrector"],))
check(G, "सुधार वापस लेते ही (10 मिनट के भीतर भी) रसीद storage से बंद", val("corrector", "select count(*) from storage.objects") == 0)
run(G, "…और उसी लॉगिन से खोलना/सुधार रुका", lambda: val("corrector", "select public.sk_open_for_correction(%s)", (e1_ref,)), "सुधार")
q("admin", "select public.sk_admin_set_rights(%s,false,false,true,null)", (U["corrector"],))

# ---------- स्वीकृति जाँच 4: सुधार/रद्द → रिकॉर्ड, कुल, CSV मिलान
G = "जाँच 4"
before = total("admin")[("total", "सक्रिय")]
run(G, "सुधार बिना कारण नहीं", lambda: q("corrector", "select public.sk_correct_expense(%s,%s,'2026-11-10','सीमेंट 50 बोरी','निर्माण सामग्री',21000.75,'गगन आचारी','UPI','')", (e1[0], e1[2] + 1)), "कारण")
v_now = val("admin", "select version from public.sk_expenses where id=%s", (e1[0],))
check(G, "रसीद जुड़ने से version बढ़ा", v_now == e1[2] + 1, str(v_now))
run(G, "पुराने version पर सुधार रुका (VERSION_CHANGED)", lambda: q("corrector", "select public.sk_correct_expense(%s,%s,'2026-11-10','सीमेंट','निर्माण सामग्री',21000.75,'गगन आचारी','UPI','दर गलत थी')", (e1[0], e1[2])), "VERSION_CHANGED")
run(G, "बिना बदलाव का सुधार रुका", lambda: q("corrector", "select public.sk_correct_expense(%s,%s,'2026-11-10','सीमेंट 50 बोरी','निर्माण सामग्री',21500.75,'गगन आचारी','UPI','कुछ नहीं')", (e1[0], v_now)), "कोई बदलाव नहीं")
run(G, "तीन दशमलव वाली राशि रुकी", lambda: q("corrector", "select public.sk_correct_expense(%s,%s,'2026-11-10','सीमेंट 50 बोरी','निर्माण सामग्री',21000.755,'गगन आचारी','UPI','दर गलत थी')", (e1[0], v_now)), "दो दशमलव")
run(G, "भविष्य की तारीख वाला सुधार रुका", lambda: q("corrector", "select public.sk_correct_expense(%s,%s,'2099-01-01','सीमेंट 50 बोरी','निर्माण सामग्री',21000.75,'गगन आचारी','UPI','दर गलत थी')", (e1[0], v_now)), "भविष्य")
run(G, "सुधार: ₹21,500.75 → ₹21,000.25, कारण सहित", lambda: q("corrector", "select public.sk_correct_expense(%s,%s,'2026-11-10','सीमेंट 50 बोरी','निर्माण सामग्री',21000.25,'गगन आचारी','UPI','दुकानदार ने छूट दी')", (e1[0], v_now)))
aud = q("admin", "select action, reason, old_data->>'amount', new_data->>'amount', actor_name from public.sk_expense_audit where expense_id=%s and action='corrected'", (e1[0],))
check(G, "बदलाव-रिकॉर्ड: पुरानी+नई राशि, कारण, करने वाला", aud and aud[0][1] == "दुकानदार ने छूट दी" and Decimal(aud[0][2]) == Decimal("21500.75")
      and Decimal(aud[0][3]) == Decimal("21000.25") and aud[0][4] == "corrector परीक्षण", str(aud))
after = total("admin")[("total", "सक्रिय")]
check(G, "सुधार के बाद कुल ठीक ₹500.50 घटा (21,500.75→21,000.25)", before[1] - after[1] == Decimal("500.50"), f"{before}→{after}")
v2 = val("admin", "select version from public.sk_expenses where id=%s", (e_w[0],))
run(G, "रद्द बिना कारण नहीं", lambda: q("corrector", "select public.sk_cancel_expense(%s,%s,'  ')", (e_w[0], v2)), "कारण")
run(G, "रद्द: मजदूरी ₹2,400 (कारण सहित)", lambda: q("corrector", "select public.sk_cancel_expense(%s,%s,'दोहरी एंट्री थी')", (e_w[0], v2)))
t3 = total("admin")
check(G, "रद्द खर्च सक्रिय कुल से बाहर (₹2,400.00 घटा)", after[1] - t3[("total", "सक्रिय")][1] == Decimal("2400.00"))
check(G, "रद्द खर्च रिकॉर्ड में दिखता है", val("reader", "select count(*) from public.sk_expenses where status='cancelled'") >= 1)
check(G, "रद्द का अलग योग दिखता है", t3[("cancelled", "रद्द")][1] >= Decimal("2400.00"))
run(G, "रद्द खर्च दोबारा सुधरता/रद्द नहीं होता", lambda: q("corrector", "select public.sk_cancel_expense(%s,%s,'फिर से रद्द')", (e_w[0], v2 + 1)), "पहले से रद्द")
run(G, "खर्च हटाया नहीं जा सकता (superuser भी)", lambda: cur.execute("delete from public.sk_expenses"), "हटाया नहीं")
run(G, "बदलाव-रिकॉर्ड बदला नहीं जा सकता", lambda: cur.execute("update public.sk_expense_audit set reason='x'"), "अपरिवर्तनीय")
run(G, "खर्च तालिका में सीधा update (superuser) भी रुका", lambda: cur.execute("update public.sk_expenses set amount=1"), "RPC")
# फ़िल्टर व समूह
add("rw", date="2026-10-05", item="बिजली बिल", cat="बिजली / पानी", amt="1234.56", payer="अमरनाथ पाण्डेय", method="बैंक ट्रांसफर")
add("rw", date="2026-10-20", item="रजिस्ट्री फ़ीस", cat="कानूनी / दस्तावेज़", amt="0.01", payer="आलोक रंजन मिश्र", method="UPI")
s = total("reader")
months = {k[1]: v for k, v in s.items() if k[0] == "month"}
cats = {k[1]: v for k, v in s.items() if k[0] == "category"}
check(G, "महीने के कुल का योग = सक्रिय कुल", sum(v[1] for v in months.values()) == s[("total", "सक्रिय")][1], str(months))
check(G, "श्रेणी के कुल का योग = सक्रिय कुल", sum(v[1] for v in cats.values()) == s[("total", "सक्रिय")][1])
check(G, "अक्टूबर 2026 = ₹1,234.57 (पैसे तक सटीक)", months.get("2026-10", (0, 0))[1] == Decimal("1234.57"), str(months.get("2026-10")))
sf = total("reader", f="2026-10-01", t="2026-10-31", p="अमरनाथ पाण्डेय")
check(G, "फ़िल्टर (तारीख+भुगतानकर्ता) सही", sf[("total", "सक्रिय")] == (1, Decimal("1234.56")), str(sf[("total", "सक्रिय")]))
sc = total("reader", c="निर्माण सामग्री")
check(G, "फ़िल्टर (श्रेणी) सही", sc[("total", "सक्रिय")] == (1, Decimal("21000.25")))
# CSV मिलान: Admin की पूरी सूची से सक्रिय योग (CSV में जो जाएगा) = summary
rows = q("admin", "select amount::text, status from public.sk_expenses")
csv_active = sum(Decimal(a) for a, st in rows if st == "active")
check(G, "CSV (सक्रिय पंक्तियाँ) का योग = स्क्रीन का सक्रिय कुल", csv_active == total("admin")[("total", "सक्रिय")][1], f"{csv_active}")
check(G, "एंट्री करने वाला और समय अपने-आप", val("admin", "select count(*) from public.sk_expenses where created_by_name is null or created_at is null") == 0)

# ---------- रसीद की बाकी जाँचें
G = "रसीद"
run(G, "आरक्षण के बिना attach नहीं", lambda: q("rw", "select public.sk_attach_receipt(%s,%s,'x.pdf')", (e1[0], f"{U['rw']}/{e1[0]}/{uuid.uuid4()}.pdf")), "वैध आरक्षण नहीं")
pr = reserve("rw", e1[0])
run(G, "आरक्षण है पर फ़ाइल नहीं चढ़ी तो attach नहीं", lambda: q("rw", "select public.sk_attach_receipt(%s,%s,'x.pdf')", (e1[0], pr)), "storage में")
q("rw", "select public.sk_release_receipt_slot(%s)", (pr,))
pb = upload("rw", e1[0], mime="image/png")
run(G, "extension/MIME बेमेल तो attach नहीं", lambda: q("rw", "select public.sk_attach_receipt(%s,%s,'x.pdf')", (e1[0], pb)), "मेल नहीं")
run(G, ".doc के लिए जगह-आरक्षण नहीं", lambda: upload("rw", e1[0], ext="doc", mime="application/msword"), "केवल JPG")
run(G, ".doc सीधा storage upload भी नहीं", lambda: upload("rw", e1[0], path=f"{U['rw']}/{e1[0]}/{uuid.uuid4()}.doc"), "row-level security")
run(G, "रसीद पंक्ति सीधे नहीं डाल सकते", lambda: q("rw", "insert into public.sk_receipts(expense_id,storage_path,original_filename,mime_type,size_bytes,uploaded_by) values (%s,'a/b/c.pdf','c.pdf','application/pdf',1,%s)", (e1[0], U["rw"])), "permission denied")
run(G, "user रसीद को verified नहीं कर सकता", lambda: q("admin", "update public.sk_receipts set verification_status='verified'"), "permission denied")
cur.execute("select set_config('request.jwt.claim.sub','',false)"); cur.execute("set role service_role")
cur.execute("update public.sk_receipts set verification_status='verified', sha256=%s, verified_at=now() where id=%s", ("a" * 64, r1))
cur.execute("reset role")
check(G, "server जाँच का परिणाम बदलाव-रिकॉर्ड में", val("admin", "select count(*) from public.sk_expense_audit where action='receipt_verified'") == 1)
run(G, "रद्द खर्च में नई रसीद-जगह नहीं", lambda: upload("corrector", e_w[0]), "अधिकार नहीं")

# ---------- प्रति खर्च अधिकतम 5 रसीदें — server-आरक्षण (जुड़ी + लंबित ≤ 5)
G = "5 रसीद सीमा"
import threading, time
DBN = sys.argv[1] if len(sys.argv) > 1 else "t"
def storage_count(exp):
    cur.execute("select count(*) from storage.objects where bucket_id='sk-receipts' and name like %s", (f"%/{exp}/%",)); return cur.fetchone()[0]
def receipts_count(exp):
    cur.execute("select count(*) from public.sk_receipts where expense_id=%s", (exp,)); return cur.fetchone()[0]
def used(exp):
    cur.execute("select public.sk_slots_used(%s)", (exp,)); return cur.fetchone()[0]
def full_upload_thread(who, exp, out, barrier):
    """एक असली client की तरह: आरक्षण → upload → attach, अलग connection से, साथ-साथ।"""
    cc = psycopg2.connect(dbname=DBN); cc.autocommit = True; kk = cc.cursor()
    kk.execute("select set_config('request.jwt.claim.sub', %s, false)", (U[who],)); kk.execute("set role authenticated")
    barrier.wait()
    try:
        kk.execute("select public.sk_reserve_receipt_slot(%s,'pdf')", (exp,)); path = kk.fetchone()[0]
        time.sleep(0.2)
        kk.execute("insert into storage.objects(bucket_id,name,owner_id,metadata) values ('sk-receipts',%s,%s,%s)",
                   (path, U[who], json.dumps({"mimetype": "application/pdf", "size": 77})))
        kk.execute("select public.sk_attach_receipt(%s,%s,'saath.pdf')", (exp, path)); out.append("स्वीकार")
    except psycopg2.Error as ex:
        out.append("RECEIPT_LIMIT" if "RECEIPT_LIMIT" in (ex.pgerror or "") else "अन्य: " + (ex.pgerror or "")[:70])
    cc.close()

e5 = add("rw", item="पाँच रसीद परीक्षण", amt="10.00")
for i in range(4):
    q("rw", "select public.sk_attach_receipt(%s,%s,%s)", (e5[0], upload("rw", e5[0]), f"r{i}.pdf"))
check(G, "शुरुआत: 4 रसीदें जुड़ी, storage में 4 फ़ाइलें", receipts_count(e5[0]) == 4 and storage_count(e5[0]) == 4)
# मुख्य केस: चार के बाद दो समवर्ती अपलोड (दो अलग सदस्य/सत्र)
outs = []; bar = threading.Barrier(2)
ts = [threading.Thread(target=full_upload_thread, args=(w, e5[0], outs, bar)) for w in ("rw", "admin")]
[t.start() for t in ts]; [t.join() for t in ts]
check(G, "दो समवर्ती अपलोड: केवल एक स्वीकार, दूसरा RECEIPT_LIMIT", sorted(outs) == ["RECEIPT_LIMIT", "स्वीकार"], str(outs))
check(G, "Storage में छठी फ़ाइल नहीं बनी (ठीक 5)", storage_count(e5[0]) == 5, str(storage_count(e5[0])))
check(G, "खर्च से जुड़ी रसीदें ठीक 5", receipts_count(e5[0]) == 5, str(receipts_count(e5[0])))
run(G, "अब नया आरक्षण भी RECEIPT_LIMIT", lambda: reserve("rw", e5[0]), "RECEIPT_LIMIT")
# सीधे storage पर, बिना आरक्षण, दो समवर्ती प्रयास
def direct(who, exp, out, barrier):
    cc = psycopg2.connect(dbname=DBN); cc.autocommit = True; kk = cc.cursor()
    kk.execute("select set_config('request.jwt.claim.sub', %s, false)", (U[who],)); kk.execute("set role authenticated")
    barrier.wait()
    try:
        kk.execute("insert into storage.objects(bucket_id,name,owner_id,metadata) values ('sk-receipts',%s,%s,%s)",
                   (f"{U[who]}/{exp}/{uuid.uuid4()}.pdf", U[who], json.dumps({"mimetype": "application/pdf", "size": 5}))); out.append("स्वीकार")
    except psycopg2.Error as ex:
        out.append("RLS" if "row-level security" in (ex.pgerror or "") else (ex.pgerror or "")[:60])
    cc.close()
outs = []; bar = threading.Barrier(2)
ts = [threading.Thread(target=direct, args=("rw", e5[0], outs, bar)) for _ in range(2)]
[t.start() for t in ts]; [t.join() for t in ts]
check(G, "बिना आरक्षण दो समवर्ती सीधे storage upload: दोनों अस्वीकार", outs == ["RLS", "RLS"], str(outs))
check(G, "…storage में फिर भी 5", storage_count(e5[0]) == 5)

# 4 जुड़ी + 1 लंबित आरक्षण = 5: एक साथ दो आरक्षण-अनुरोध
e6 = add("rw", item="आरक्षण परीक्षण", amt="20.00")
for i in range(4):
    q("rw", "select public.sk_attach_receipt(%s,%s,%s)", (e6[0], upload("rw", e6[0]), f"q{i}.pdf"))
res_out = []
def reserve_thread(who, out, barrier):
    cc = psycopg2.connect(dbname=DBN); cc.autocommit = True; kk = cc.cursor()
    kk.execute("select set_config('request.jwt.claim.sub', %s, false)", (U[who],)); kk.execute("set role authenticated"); barrier.wait()
    try: kk.execute("select public.sk_reserve_receipt_slot(%s,'png')", (e6[0],)); out.append(kk.fetchone()[0])
    except psycopg2.Error as ex: out.append("RECEIPT_LIMIT" if "RECEIPT_LIMIT" in (ex.pgerror or "") else (ex.pgerror or "")[:60])
    cc.close()
bar = threading.Barrier(3)
ts = [threading.Thread(target=reserve_thread, args=(w, res_out, bar)) for w in ("rw", "rw", "admin")]
[t.start() for t in ts]; [t.join() for t in ts]
got = [x for x in res_out if x != "RECEIPT_LIMIT"]
check(G, "तीन समवर्ती आरक्षण (4 जुड़ी पर): केवल एक जगह मिली", len(got) == 1 and res_out.count("RECEIPT_LIMIT") == 2, str(res_out))
check(G, "घिरी जगहें = 4 जुड़ी + 1 लंबित = 5", used(e6[0]) == 5)
slot = got[0]
same = []
def same_path(out, barrier):
    cc = psycopg2.connect(dbname=DBN); cc.autocommit = True; kk = cc.cursor()
    owner = U["rw"] if slot.startswith(U["rw"]) else U["admin"]
    kk.execute("select set_config('request.jwt.claim.sub', %s, false)", (owner,)); kk.execute("set role authenticated"); barrier.wait()
    try:
        kk.execute("insert into storage.objects(bucket_id,name,owner_id,metadata) values ('sk-receipts',%s,%s,%s)",
                   (slot, owner, json.dumps({"mimetype": "image/png", "size": 5}))); out.append("स्वीकार")
    except psycopg2.Error as ex: out.append("दोहरा" if "duplicate key" in (ex.pgerror or "") else (ex.pgerror or "")[:60])
    cc.close()
bar = threading.Barrier(2)
ts = [threading.Thread(target=same_path, args=(same, bar)) for _ in range(2)]
[t.start() for t in ts]; [t.join() for t in ts]
check(G, "एक ही आरक्षित path पर दो समवर्ती upload: एक ही फ़ाइल बनती है", sorted(same) == ["दोहरा", "स्वीकार"] and storage_count(e6[0]) == 5, str(same))
owner_of_slot = "rw" if slot.startswith(U["rw"]) else "admin"

# असफल / बीच में छूटा अपलोड → जगह सुरक्षित वापसी
G = "जगह वापसी"
e7 = add("rw", item="वापसी परीक्षण", amt="30.00")
for i in range(4):
    q("rw", "select public.sk_attach_receipt(%s,%s,%s)", (e7[0], upload("rw", e7[0]), f"z{i}.pdf"))
s1 = reserve("rw", e7[0])
run(G, "5 घिरी होने पर दूसरा आरक्षण रुका", lambda: reserve("admin", e7[0]), "RECEIPT_LIMIT")
run(G, "upload विफल (फ़ाइल नहीं चढ़ी) → स्वयं जगह छोड़ना", lambda: q("rw", "select public.sk_release_receipt_slot(%s)", (s1,)))
check(G, "…जगह तुरंत वापस (4 घिरी)", used(e7[0]) == 4)
run(G, "छोड़े गए path पर बाद में upload नहीं", lambda: upload("rw", e7[0], path=s1), "row-level security")
s2 = reserve("rw", e7[0])
cur.execute("alter table public.sk_receipt_slots disable trigger sk_receipt_slots_guard")
cur.execute("update public.sk_receipt_slots set expires_at = now() - interval '1 second' where storage_path=%s", (s2,))  # 15 मिनट बीतना
cur.execute("alter table public.sk_receipt_slots enable trigger sk_receipt_slots_guard")
check(G, "बीच में छूटा (फ़ाइल नहीं चढ़ी), समय बीता → जगह अपने-आप वापस", used(e7[0]) == 4)
run(G, "समय बीते आरक्षण पर upload नहीं", lambda: upload("rw", e7[0], path=s2), "row-level security")
s3 = upload("rw", e7[0])                     # फ़ाइल चढ़ी पर attach से पहले सत्र टूटा
cur.execute("alter table public.sk_receipt_slots disable trigger sk_receipt_slots_guard")
cur.execute("update public.sk_receipt_slots set expires_at = now() - interval '1 second' where storage_path=%s", (s3,))
cur.execute("alter table public.sk_receipt_slots enable trigger sk_receipt_slots_guard")
check(G, "फ़ाइल चढ़ी पर जुड़ी नहीं (समय बीता) → जगह अब भी घिरी (storage 5 से ऊपर न जाए)", used(e7[0]) == 5 and storage_count(e7[0]) == 5)
run(G, "…ऐसे में नया आरक्षण रुका", lambda: reserve("admin", e7[0]), "RECEIPT_LIMIT")
opens = q("rw", "select storage_path, uploaded from public.sk_my_open_slots()")
check(G, "सदस्य को अपना अधूरा अपलोड recovery सूची में दिखता है", (s3, True) in opens, str(opens))
run(G, "फ़ाइल रहते जगह छोड़ना रुका", lambda: q("rw", "select public.sk_release_receipt_slot(%s)", (s3,)), "फ़ाइल चढ़ चुकी")
check(G, "दूसरा सदस्य यह अधूरी फ़ाइल नहीं हटा सकता (0)", q("writer", "delete from storage.objects where name=%s", (s3,)) == 0)
check(G, "स्वामी अपनी अधूरी फ़ाइल हटा सकता है (1)", q("rw", "delete from storage.objects where name=%s", (s3,)) == 1)
run(G, "…फिर जगह छोड़ी", lambda: q("rw", "select public.sk_release_receipt_slot(%s)", (s3,)))
check(G, "…जगह वापस (4) और storage 4", used(e7[0]) == 4 and storage_count(e7[0]) == 4)
s4 = upload("rw", e7[0])
cur.execute("alter table public.sk_receipt_slots disable trigger sk_receipt_slots_guard")
cur.execute("update public.sk_receipt_slots set expires_at = now() - interval '1 second' where storage_path=%s", (s4,))
cur.execute("alter table public.sk_receipt_slots enable trigger sk_receipt_slots_guard")
run(G, "अधूरा अपलोड बाद में जोड़ना (recovery) संभव", lambda: q("rw", "select public.sk_attach_receipt(%s,%s,'baad.pdf')", (e7[0], s4)))
check(G, "…अब 5 जुड़ी", receipts_count(e7[0]) == 5)
check(G, "जुड़ी रसीद स्वामी भी नहीं हटा सकता (0)", q("rw", "delete from storage.objects where name=%s", (s4,)) == 0)
run(G, "जुड़ी रसीद की जगह छोड़ना रुका", lambda: q("rw", "select public.sk_release_receipt_slot(%s)", (s4,)), "खुला आरक्षण नहीं")
run(G, "आरक्षण तालिका में सीधा बदलाव रुका", lambda: q("rw", "update public.sk_receipt_slots set status='released'"), "permission denied")
run(G, "आरक्षण-रिकॉर्ड हटाना रुका (superuser भी)", lambda: cur.execute("delete from public.sk_receipt_slots"), "हटाया नहीं")
check(G, "सदस्य केवल अपने आरक्षण देखता है", val("writer", "select count(*) from public.sk_receipt_slots where user_id<>%s", (U["writer"],)) == 0)

# ---------- रिपोर्ट
for g, s, n, i in res:
    print(f"{s:5} | {g:8} | {n}" + (f"  [{i[:140]}]" if i else ""))
p = sum(r[1] == "PASS" for r in res)
print(f"\nकुल {len(res)} : PASS {p} / FAIL {len(res) - p}")
sys.exit(0 if p == len(res) else 1)
