# सूर्य कुंज आवासीय योजना — निजी खर्च रजिस्टर

6–12 महीने, 5–7 सदस्य, 1–2 नियमित एंट्री करने वाले। Admin: आलोक रंजन मिश्र (केवल एक)।
यह रजिस्टर पुराने "साइट खर्च" मॉड्यूल (PR #1) की जगह लेता है। **मूल एन्क्रिप्टेड हिसाब
(15 एंट्री, ₹5,26,81,755), साझेदारों का निवेश, बकाया और सेटलमेंट इससे नहीं बदलते।**
योगदान/बकाया/आपसी सेटलमेंट बाद के चरण में।

## सदस्य और अधिकार (database + निजी storage में लागू)
| स्थिति / अधिकार | क्या कर सकता है |
|---|---|
| Pending / अस्वीकृत / हटाया गया | कुछ नहीं — न खर्च, न कुल, न रसीद (सीधे API अनुरोध से भी नहीं) |
| **Read** | खर्च सूची, फ़िल्टर (तारीख/श्रेणी/भुगतानकर्ता), महीने व श्रेणी के कुल, बदलाव का इतिहास (रसीदें नहीं) |
| **Write** | नया खर्च + वैकल्पिक रसीद। पुराना खर्च (अपना भी) सुधार/रद्द नहीं |
| **सुधार** | **सभी खर्चों पर लागू।** किसी भी खर्च को क्रमांक (SK-…) से खोलकर सुधारना या कारण देकर रद्द करना; उसकी रसीद देखना/जोड़ना। Read के बिना पूरी सूची, कुल, फ़िल्टर और सीधी तालिका-पहुँच नहीं; हर "खोलना" `sk_correction_opens` में दर्ज, और उस खर्च की रसीद 10 मिनट तक खुलती है |
| **Read + सुधार** | सूची के साथ सभी खर्च और सभी जुड़ी रसीदें |
| हर सक्रिय सदस्य | अपनी अपलोड की हुई रसीद देखना |
| Admin | सब कुछ; अनुरोध मंज़ूर/अस्वीकार, अधिकार देना/वापस लेना, पहुँच हटाना, CSV |

- नया व्यक्ति अकाउंट बनाकर "जुड़ने का अनुरोध" भेजता है → `Pending`। केवल Admin फ़ैसला करता है।
- तीनों अधिकार स्वतंत्र हैं; Write से सुधार नहीं मिलता। Admin स्क्रीन पर सुधार देते समय उसका दायरा
  ("सभी खर्चों पर लागू") पुष्टि-संवाद में दिखता है।
- **रसीद link की अवधि:** सदस्य के लिए हर signed link 60 सेकंड का; Admin की समापन-सूची के links 5 मिनट के।
  अधिकार वापस लेते ही नया link नहीं बनता और database/storage पहुँच तुरंत बंद होती है, पर पहले से बना
  link अपनी अवधि (अधिकतम 60 सेकंड; Admin के 5 मिनट) तक चलता है — Supabase signed link को बीच में रद्द
  नहीं किया जा सकता। उस बीच डाउनलोड हो चुकी प्रति वापस नहीं ली जा सकती।
- अधिकार हर कार्रवाई पर database से दोबारा पढ़े जाते हैं — लॉगिन रहते भी बदलाव अगली कार्रवाई पर लागू।
- **Admin पहचान:** केवल SQL Editor से `sk_bootstrap_admin(...)` (postgres भूमिका); पूरे रजिस्टर में एक ही
  Admin (unique index); कोई सदस्य/RPC Admin पहचान या Admin के अधिकार नहीं बदल सकता (trigger)।
- मंज़ूरी, अस्वीकृति, अधिकार बदलना, हटाना → `sk_member_audit` (अपरिवर्तनीय)।

## खर्च
- तारीख (भविष्य नहीं), मद, श्रेणी (सूची), राशि (`numeric(14,2)`; UI में पूर्णांक पैसे — float नहीं),
  भुगतानकर्ता, भुगतान का तरीका, वैकल्पिक रसीदें (JPG/PNG/WEBP/PDF/DOCX, 10 MB)।
- **प्रति खर्च अधिकतम 5 रसीदें — server पर दोहरी रोक:** (1) storage नियम उस खर्च के folder में 5 से
  अधिक फ़ाइलें (अधूरे अपलोड सहित) नहीं चढ़ने देता; (2) `sk_attach_receipt` खर्च-पंक्ति lock करके गिनता है,
  इसलिए साथ-साथ दो जोड़ने पर भी 6वीं नहीं जुड़ती (`RECEIPT_LIMIT`)। बाद में रसीद "रसीद जोड़ें (n/5)" से —
  अपना खर्च + Write, या सुधार अधिकार।
- एंट्री करने वाला और समय अपने-आप; स्थायी क्रमांक SK-000001।
- सुधार/रद्द: कारण (≥5 अक्षर) अनिवार्य; version-pinned (बीच में बदलाव हुआ तो रुकता है);
  पुरानी+नई जानकारी, करने वाला, समय → `sk_expense_audit` (अपरिवर्तनीय)। खर्च कभी हटता नहीं।
- रद्द खर्च सूची में (कारण सहित) दिखता है, सक्रिय कुल से बाहर; अलग "रद्द" योग।
- कुल `sk_summary` RPC से database में (numeric, text में लौटता) — पूरा डेटा, कोई 200-सीमा नहीं।

## फ़ाइलें (इस branch में)
| फ़ाइल | काम |
|---|---|
| `supabase/expense-register.sql` | पूरा database: तालिकाएँ, RLS, RPC, trigger, निजी bucket `sk-receipts`, storage नियम |
| `supabase/functions/verify-receipt/index.ts` | रसीद की server-side सामग्री जाँच (magic bytes, PDF script, DOCX macro, sha256) |
| `site/expenses.html`, `site/js/register.js`, `site/js/money.js` | रजिस्टर UI; पैसे/CSV helpers |
| `site/js/filecheck.js` (+ `supabase/functions/_shared/` प्रति) | ब्राउज़र व server की साझा फ़ाइल-जाँच |
| `site/vendor/supabase-js-2.119.0.umd.js` | pinned, npm sha512 से मिलाई, SRI sha384 |
| `site/expenses-config.js` | Surya Kunj project URL + publishable key (अभी placeholder) |
| `ledger/template.html`, `ledger/build.py` | मुख्य हिसाब पेज में "खर्च रजिस्टर" link; ciphertext जस का तस |
| `supabase/tests/`, `tests/` | स्थानीय परीक्षण |

## स्थानीय रूप से चलाना
```bash
# 1) पेज देखना (Supabase के बिना "सुविधा चालू नहीं" दिखेगा — यही अपेक्षित)
cd site && python3 -m http.server 8080      # http://localhost:8080/expenses.html

# 2) Database नियम: स्थानीय PostgreSQL 16 + mock Supabase ढाँचा
sudo -u postgres createdb skreg
sudo -u postgres psql -d skreg -v ON_ERROR_STOP=1 -f supabase/tests/mock_supabase.sql
sudo -u postgres psql -d skreg -v ON_ERROR_STOP=1 -f supabase/expense-register.sql
(cd supabase/tests && sudo -u postgres python3 test_expense_register.py skreg)

# 3) पैसे/CSV और फ़ाइल-जाँच
node tests/money.test.mjs
node tests/filecheck.test.mjs <कृत्रिम-नमूना-फ़ोल्डर>

# 4) ब्राउज़र (Chromium + नकली Supabase client)
python3 tests/register_ui_test.py <कृत्रिम-नमूना-फ़ोल्डर> <screenshot-फ़ोल्डर>
```
कृत्रिम नमूने (bill.jpg/png/webp/pdf/docx, macro.docx, js.pdf आदि) Python/PIL से बनाए जाते हैं — कोई असली दस्तावेज़ नहीं।

## Hosted सेटअप (आलोक की अलग अनुमति के बाद ही)
1. अलग Gmail से अलग Supabase account/org/project (`surya-kunj-…`)। UPPCS Diary का account,
   org, project या connector कभी नहीं।
2. SQL Editor में `expense-register.sql` चलाएँ।
3. Auth: email+password, email confirmation चालू, पासवर्ड ≥10, Admin के लिए MFA।
   (रजिस्टर में self-signup ज़रूरी है ताकि नए सदस्य अनुरोध भेज सकें; अनुमोदन के बिना उन्हें कुछ नहीं मिलता।)
4. Admin bootstrap: `select public.sk_bootstrap_admin('<आपका auth UUID>','आलोक रंजन मिश्र');`
5. `supabase functions deploy verify-receipt` (JWT verification चालू; `ALLOWED_ORIGIN` staging/production URL)।
6. `site/expenses-config.js` में केवल URL + publishable key।
7. Hosted जाँच-सूची (नीचे "लंबित") synthetic users/data से।

## पुराने "साइट खर्च" मॉड्यूल का डेटा
- पुराना मॉड्यूल (PR #1, branch `feature/site-expense-evidence-20261114`) **कभी किसी Supabase project पर
  deploy नहीं हुआ** — config placeholder था, Surya Kunj का कोई project नहीं बना। इसलिए कोई पुराना
  खर्च या रसीद मौजूद नहीं है; PR #1 branch अछूती है।
- अगर कभी उस schema में डेटा बने, तो मिलान-योजना: `site_expenses.approved` → `sk_expenses.active`;
  `rejected` → `cancelled` (कारण = review_note); `pending` → Admin तय करे; `incurred_on/description/amount/
  payment_method` → `expense_date/item/amount/payment_method`; `paid_by_partner` या payer_type → `payer`;
  `ref_no` पुराना क्रमांक audit में; `site_expense_evidence` → `sk_receipts` (वही storage path, नई bucket में
  copy, sha256 मिलाकर)। यह migration अलग अनुमति और dry-run CSV मिलान के बाद ही।

## काम पूरा होने पर समापन (Admin)
1. **CSV / समापन** टैब → "पूरा खर्च रजिस्टर CSV" — मिलान संदेश "मिलान सही ✓" हो तभी आगे बढ़ें।
2. "खर्च बदलाव-रिकॉर्ड CSV" और "सदस्य-रिकॉर्ड CSV" भी निकालें।
3. रसीदें: "रसीदों की सूची बनाएँ" से 5-मिनट links द्वारा सहेजें; या Supabase dashboard → Storage →
   `sk-receipts` से पूरा folder डाउनलोड करें। गिनती CSV/`sk_receipts` से मिलाएँ।
4. तीनों CSV + रसीदें दो जगह सुरक्षित रखें (जैसे अपना PC + Google Drive)।
5. **सदस्य** टैब → हर सदस्य पर "पहुँच हटाएँ" (कारण: "परियोजना समाप्त")। सदस्य-रिकॉर्ड में दर्ज होगा।
6. Supabase Auth में signup बंद करें; ज़रूरत न हो तो project pause करें। Delete केवल तब, जब प्रतियाँ
   दोबारा जाँच ली गई हों (Free plan पर backup नहीं होता)।

## सीमाएँ
- Database owner (dashboard/SQL Editor) trigger बंद कर रिकॉर्ड बदल सकता है — audit app-users से सुरक्षित,
  owner से नहीं। Dashboard पहुँच केवल Admin, 2FA के साथ; समय-समय पर CSV निकालें।
- PDF की compressed हिस्सों में छिपी script पकड़ में नहीं आती; कोई antivirus नहीं।
- CSV download Android Chrome में चलता है; Capacitor APK के WebView में download का परीक्षण नहीं हुआ।
- Free plan: 7 दिन निष्क्रियता पर pause, कोई backup नहीं — नियमित CSV ज़रूरी।
