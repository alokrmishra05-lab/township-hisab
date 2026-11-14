# साइट खर्च + प्रमाण — सेटअप (v2)

अलग, स्वीकृति-आधारित खर्च मॉड्यूल। मूल एन्क्रिप्टेड हिसाब (15 एंट्री; निवेश ₹4,00,00,000 +
खर्च ₹1,26,81,755 = ₹5,26,81,755) और साझेदारों की पूँजी/निपटान पर इसका **कोई असर नहीं**।

## पहुँच नियम (database RLS/permissions में लागू)
| भूमिका | देखना | जोड़ना | अपना pending सुधारना | स्वीकृत/अस्वीकृत |
|---|---|---|---|---|
| admin | सब खर्च व प्रमाण | हाँ | हाँ | दूसरों के; **अपना नहीं** |
| partner | सब खर्च व प्रमाण | हाँ | हाँ | केवल `can_review = true` पर, दूसरों के |
| assistant | **केवल अपने** | हाँ | हाँ | कभी नहीं |

## मुख्य सुरक्षा व्यवस्था
- **प्रमाण:** evidence पंक्ति केवल `site_expense_attach_evidence` RPC से बनती है, जो storage में असली
  फ़ाइल, मालिक, आकार (≤10 MB) और MIME↔extension जाँचता है (आकार/MIME storage के रिकॉर्ड से)।
  फिर Edge Function `verify-evidence` फ़ाइल की असली सामग्री जाँचता है (magic bytes; PDF में
  JavaScript/Launch/Embedded नहीं; DOCX में macro/ActiveX/OLE नहीं; ZIP-bomb सीमा) और sha256 दर्ज
  करता है। स्वीकृति तभी जब सभी प्रमाण `verified` हों। अनुमत: JPG, PNG, WEBP, PDF, DOCX (.doc नहीं)।
- **समवर्तीता:** हर बदलाव (नई फ़ाइल सहित) पर `version` +1। Reviewer देखा गया version भेजता है;
  बीच में बदलाव हुआ तो `VERSION_CHANGED` और स्वीकृति रुकती है (row lock के साथ, atomic)।
- **दोहराव:** बिल नंबर सक्रिय खर्चों में unique ('INV-101' = 'inv 101')। उसी तारीख+राशि+श्रेणी या
  उसी फ़ाइल (sha256) वाले दूसरे खर्च पर स्वीकृति के लिए स्पष्ट पुष्टि ज़रूरी (audit में दर्ज)।
- **अपरिवर्तनीयता:** स्वीकृत/अस्वीकृत खर्च, जाँचा हुआ प्रमाण और audit trail — trigger से
  service_role/SQL Editor के लिए भी बदलना/हटाना रुका। storage में फ़ाइल overwrite/delete नहीं।
- **भुगतान स्रोत:** `payer_type` = साझेदार (नाम ज़रूरी) / साइट कैश / परियोजना फंड।
- **स्थिर पहचान:** `id` (UUID) + `ref_no` (SE-000001) भविष्य के मिलान हेतु।
- **supabase-js 2.119.0** रिपो में (`site/vendor/`), npm tarball की sha512 registry से मिलाई गई,
  पेज पर SRI `sha384` के साथ। CDN पर निर्भरता नहीं।

## सेटअप (merge से पहले, अलग/टेस्ट Supabase project पर)
1. नया Supabase project बनाएँ (किसी दूसरे ऐप का database नहीं)।
2. SQL Editor में `supabase/site-expenses.sql` चलाएँ (खाली project पर; पुराना v1 चला हो तो
   पहले उसके टेबल हटाएँ — v1 कभी production में नहीं गया)।
3. Edge Function deploy: `supabase functions deploy verify-evidence`
   (ALLOWED_ORIGIN डिफ़ॉल्ट `https://alokrmishra05-lab.github.io`)।
4. Authentication: public signup बंद; हर व्यक्ति का अलग account invite करें।
5. `site_expense_members` में UUID डालकर भूमिका दें (SQL फ़ाइल के अंत में उदाहरण)। दूसरा
   reviewer = कम से कम एक partner `can_review = true`, ताकि admin के अपने खर्च स्वीकृत हो सकें।
6. `site/expenses-config.js` में project URL और **केवल** publishable/anon key।
7. Storage → bucket `site-expense-evidence` private है और MIME/size सीमा dashboard में जाँचें।
8. नीचे की checklist असली project पर चलाएँ। उसके बाद ही merge।

## मूल हिसाब पेज
`site/index.html` अब `ledger/template.html` से बनता है (साइट खर्च लिंक template में है)।
- डेटा बदले बिना पेज दोबारा बनाना: `python3 ledger/build.py --reuse-blob site/index.html`
- नया हिसाब: `LEDGER_PASSWORD=... python3 ledger/build.py --data <रिपो से बाहर data.json>`

## स्थानीय परीक्षण (इस PR में चलाए गए)
- `supabase/tests/` — mock Supabase पर PostgreSQL 16: `mock_supabase.sql` → `site-expenses.sql`
  (दो बार) → `sudo -u postgres python3 test_site_expenses.py <db>` (87 जाँच)
- `node tests/filecheck.test.mjs <कृत्रिम नमूने>` (23 जाँच)
- `python3 tests/ui_test.py <नमूने> <screenshots>` — Chromium, नकली Supabase client (30 जाँच)

## असली Supabase पर अभी बाकी (NOT TESTED — merge blocker)
- Supabase Auth लॉगिन/सत्र; असली storage API अपलोड, bucket MIME/size सीमा, signed URL 60 सेकंड
- `storage.objects.metadata` में `mimetype`/`size` का वास्तविक रूप (attach RPC इन्हीं पर निर्भर)
- Edge Function का deploy, CORS, service_role से download/update
- APK (Capacitor WebView) में फ़ाइल चुनना/कैमरा, signed link खुलना
- दोहराव/version/स्व-स्वीकृति नियम असली PostgREST के ज़रिए

## सीमाएँ
- PDF जाँच compressed object streams के अंदर छिपे script नहीं पकड़ सकती; संदिग्ध PDF डाउनलोड कर
  ही खोलें। फ़ाइलें malware-scanner से नहीं गुज़रतीं।
- अपलोड बीच में रुके तो फ़ाइल storage में रह जाती है; अपनी pending एंट्री पर "अधूरी फ़ाइलें जोड़ें"
  से उसे जोड़ा जा सकता है। ग़लत फ़ाइल हटाई नहीं जा सकती — reviewer खर्च अस्वीकृत करे और नया बने।
- Backup: Supabase की daily backup (Pro plan) या नियमित `pg_dump` + storage export ज़रूरी।
