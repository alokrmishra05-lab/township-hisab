"""खर्च रजिस्टर UI — Chromium ब्राउज़र परीक्षण (नकली Supabase client; असली backend नहीं)।
चलाएँ: python3 tests/register_ui_test.py <कृत्रिम नमूना-फ़ाइल फ़ोल्डर> <screenshot फ़ोल्डर>
"""
import sys, os, json, re, threading, http.server, functools
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SAMPLES, SHOTS = sys.argv[1], sys.argv[2]
os.makedirs(SHOTS, exist_ok=True)
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 8766), functools.partial(Quiet, directory=os.path.join(ROOT, 'site')))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:8766'
FAKE = open(os.path.join(ROOT, 'tests', 'register_fake_supabase.js'), encoding='utf-8').read()
CFG = 'window.SK_REGISTER_CONFIG={url:"https://abcdefghsuryakunj.supabase.co",anonKey:"' + 'k' * 60 + '"};'
res = []
def check(name, cond, info=''):
    res.append(('PASS' if cond else 'FAIL', name, info))

browser = None
def open_as(p, who, w=390, h=844, fake=True, dark=False, state=None):
    ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=2, accept_downloads=True,
                              color_scheme='dark' if dark else 'light')
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' and not m.text.startswith('Failed to load resource') else None)
    pg.route('**/fonts.googleapis.com/**', lambda r: r.abort())
    if fake:
        pre = f'window.__WHO={json.dumps(who)};' + (f'window.__STATE={json.dumps(state)};' if state else '')
        pg.add_init_script(pre + FAKE)
        pg.route('**/expenses-config.js', lambda r: r.fulfill(body=CFG, content_type='application/javascript'))
        pg.route('**/vendor/supabase-js-*.js', lambda r: r.abort())
    pg.goto(BASE + '/expenses.html'); pg.wait_for_timeout(700)
    return pg, errs

def state_of(pg):
    return pg.evaluate('JSON.parse(JSON.stringify(window.__STATE))')

with sync_playwright() as p:
    browser = p.chromium.launch()
    # बिना config
    pg, errs = open_as(p, 'admin', fake=False)
    check('config के बिना "सुविधा चालू नहीं" सूचना, कोई अनुरोध नहीं', pg.is_visible('#setup') and not pg.is_visible('#workspace'))
    check('config के बिना JS त्रुटि नहीं', not errs, str(errs))
    # SRI से असली लाइब्रेरी लोड
    pg, errs = open_as(p, 'admin', fake=False)
    check('vendored supabase-js 2.119.0 SRI के साथ लोड', pg.evaluate('typeof window.supabase?.createClient') == 'function')

    # Pending सदस्य
    pg, errs = open_as(p, 'pending')
    check('Pending: रजिस्टर नहीं, केवल प्रतीक्षा संदेश', pg.is_visible('#joinBox') and not pg.is_visible('#workspace') and 'Pending' in pg.inner_text('#joinState'))
    # बिना सदस्यता वाला नया user: अनुरोध भेजे
    pg, errs = open_as(p, 'none')
    pg.fill('#joinName', 'नया व्यक्ति (परीक्षण)'); pg.click('#joinBtn'); pg.wait_for_timeout(400)
    check('नया user जुड़ने का अनुरोध भेजता है → Pending', 'Pending' in pg.inner_text('#joinState') and not pg.is_visible('#workspace'))

    # Admin: मंज़ूरी, अधिकार, CSV
    pg, errs = open_as(p, 'admin', 360, 780)
    tabs = pg.inner_text('#tabs')
    check('Admin: चारों टैब (जोड़ें/रजिस्टर/सदस्य/CSV)', all(t in tabs for t in ['खर्च जोड़ें', 'रजिस्टर', 'सदस्य', 'CSV']), tabs)
    pg.click('#tabs button[data-t="members"]'); pg.wait_for_timeout(400)
    check('Admin: pending अनुरोध दिखता है', 'नया सदस्य (परीक्षण)' in pg.inner_text('#pendingList'))
    pg.uncheck('#pr-u-pend'); pg.click('.apBtn'); pg.wait_for_timeout(300)
    check('बिना अधिकार चुने मंज़ूरी नहीं भेजी जाती', not any(c[1] == 'sk_admin_decide' for c in pg.evaluate('window.__calls')))
    pg.check('#pr-u-pend'); pg.check('#pw-u-pend'); pg.click('.apBtn'); pg.wait_for_timeout(500)
    st = state_of(pg); m = [x for x in st['sk_members'] if x['user_id'] == 'u-pend'][0]
    check('Admin ने Read+Write के साथ मंज़ूर किया (सुधार नहीं)', m['status'] == 'active' and m['can_read'] and m['can_write'] and not m['can_correct'])
    check('मंज़ूरी का रिकॉर्ड दिखता है', 'मंज़ूर' in pg.inner_text('#memberAudit'))
    pg.screenshot(path=f'{SHOTS}/1_admin_members_360.png', full_page=True)
    pg.click('#tabs button[data-t="register"]'); pg.wait_for_timeout(500)
    total_screen = pg.inner_text('#activeTotal')
    check('स्क्रीन पर सक्रिय कुल = ₹22,735.31 (रद्द ₹2,400 बाहर)', total_screen == '₹22,735.31', total_screen)
    check('महीने और श्रेणी के कुल दिखते हैं', '2026-11' in pg.inner_text('#byMonth') and 'निर्माण सामग्री' in pg.inner_text('#byCategory'))
    check('रद्द खर्च सूची में कारण सहित दिखता है', 'दोहरी एंट्री' in pg.inner_text('#entries'))
    check('क्षैतिज scroll नहीं (360px)', pg.evaluate('document.documentElement.scrollWidth <= innerWidth'))
    pg.screenshot(path=f'{SHOTS}/2_admin_register_360.png', full_page=True)
    # फ़िल्टर
    pg.fill('#qFrom', '2026-10-01'); pg.fill('#qTo', '2026-10-31'); pg.fill('#qPayer', 'अमरनाथ पाण्डेय'); pg.click('#applyFilter'); pg.wait_for_timeout(400)
    check('फ़िल्टर (तारीख+भुगतानकर्ता) → ₹1,234.56, 1 खर्च', pg.inner_text('#activeTotal') == '₹1,234.56' and 'खर्च (1)' in pg.inner_text('#listTitle'))
    pg.click('#clearFilter'); pg.wait_for_timeout(400)
    # सुधार: कारण बिना नहीं
    pg.click('#it-e1 .fixBtn'); pg.wait_for_selector('#modal:not([hidden])')
    pg.fill('#cAmount', '21000.25'); pg.click('#modalOk'); pg.wait_for_timeout(200)
    check('सुधार: कारण बिना नहीं भेजा जाता', pg.is_visible('#modal') and not any(c[1] == 'sk_correct_expense' for c in pg.evaluate('window.__calls')))
    pg.fill('#cReason', 'दुकानदार ने छूट दी'); pg.click('#modalOk'); pg.wait_for_timeout(600)
    cc = [c for c in pg.evaluate('window.__calls') if c[1] == 'sk_correct_expense']
    check('सुधार RPC: देखा गया version (2) और राशि text "21000.25"', cc and cc[0][2]['p_expected_version'] == 2 and cc[0][2]['p_amount'] == '21000.25', str(cc))
    check('सुधार के बाद सक्रिय कुल ठीक ₹500.50 घटा → ₹22,234.81', pg.inner_text('#activeTotal') == '₹22,234.81', pg.inner_text('#activeTotal'))
    pg.click('#it-e1 .histBtn'); pg.wait_for_timeout(300)
    h = pg.inner_text('#au-e1')
    check('इतिहास में पुरानी→नई राशि, कारण, करने वाला', '₹21,500.75 → ₹21,000.25' in h and 'छूट' in h and 'आलोक' in h, h)
    # रद्द
    pg.click('#it-e2 .cancelBtn'); pg.wait_for_selector('#modal:not([hidden])'); pg.fill('#xReason', 'गलत महीने में दर्ज'); pg.click('#modalOk'); pg.wait_for_timeout(600)
    check('रद्द के बाद सक्रिय कुल ₹1,234.56 घटा → ₹21,000.25', pg.inner_text('#activeTotal') == '₹21,000.25', pg.inner_text('#activeTotal'))
    # CSV + मिलान
    pg.click('#tabs button[data-t="export"]'); pg.wait_for_timeout(300)
    with pg.expect_download() as d:
        pg.click('#csvExpenses')
    csv_path = d.value.path(); csv = open(csv_path, encoding='utf-8-sig').read()
    rec = pg.inner_text('#reconcile')
    check('CSV डाउनलोड हुई (सभी 3 खर्च, रद्द सहित)', csv.count('\n') == 4 and 'रद्द' in csv, str(csv.count('\n')))
    act = sum(float(x.split(',')[4]) * 100 for x in csv.strip().split('\n')[1:] if ',सक्रिय,' in x)
    check('CSV का सक्रिय योग (स्वतंत्र गणना) = ₹21,000.25 = स्क्रीन', round(act) == 2100025, str(act))
    check('ऐप का मिलान संदेश: "मिलान सही ✓"', 'मिलान सही' in rec, rec)
    with pg.expect_download() as d2:
        pg.click('#csvAudit')
    check('बदलाव-रिकॉर्ड CSV में सुधार और रद्द', all(w in open(d2.value.path(), encoding='utf-8-sig').read() for w in ['corrected', 'cancelled', 'दुकानदार ने छूट दी']))
    pg.screenshot(path=f'{SHOTS}/3_admin_export.png', full_page=True)
    check('Admin सत्र में JS त्रुटि नहीं', not errs, str(errs))

    # Reader: जोड़/सुधार नहीं
    pg, errs = open_as(p, 'reader')
    tabs = pg.inner_text('#tabs')
    check('Read: "कुल हिसाब" + "रजिस्टर" टैब (जोड़ें/सदस्य/CSV नहीं)', 'कुल हिसाब' in tabs and 'रजिस्टर' in tabs and 'खर्च जोड़ें' not in tabs and 'सदस्य' not in tabs)
    pg.click('#tabs button[data-t="register"]'); pg.wait_for_timeout(500)
    check('Read: सुधारें/रद्द बटन नहीं', pg.locator('.fixBtn, .cancelBtn').count() == 0)
    check('Read: कुल दिखता है', pg.is_visible('#activeTotal'))
    # Writer: केवल जोड़ना, रसीद के साथ
    pg, errs = open_as(p, 'writer')
    tabs = pg.inner_text('#tabs')
    check('Write-only: केवल "खर्च जोड़ें" टैब', tabs.strip() == 'खर्च जोड़ें', tabs)
    pg.fill('#fAmount', '1500.505'); pg.fill('#fItem', 'JCB 1 घंटा'); pg.select_option('#fCategory', 'मशीन / वाहन'); pg.select_option('#fMethod', 'नकद'); pg.fill('#fPayer', 'साइट कैश')
    pg.click('#addBtn'); pg.wait_for_timeout(300)
    check('तीन दशमलव वाली राशि UI में रुकती है', 'दो दशमलव' in pg.inner_text('#message'))
    pg.evaluate("document.getElementById('fDate').value='2099-01-01'"); pg.fill('#fAmount', '1500.50'); pg.click('#addBtn'); pg.wait_for_timeout(300)
    check('भविष्य की तारीख UI में रुकती है', 'भविष्य' in pg.inner_text('#message'))
    pg.fill('#fDate', '2026-11-12')
    pg.set_input_files('#fReceipt', files=[{'name': 'macro.docx', 'mimeType': '', 'buffer': open(f'{SAMPLES}/macro.docx', 'rb').read()}])
    pg.click('#addBtn'); pg.wait_for_timeout(400)
    check('macro वाली DOCX रसीद ब्राउज़र में ही रुकती है', 'macro' in pg.inner_text('#message'))
    pg.set_input_files('#fReceipt', files=[{'name': 'bill.docx', 'mimeType': '', 'buffer': open(f'{SAMPLES}/bill.docx', 'rb').read()}])
    pg.click('#addBtn'); pg.wait_for_timeout(800)
    calls = pg.evaluate('window.__calls')
    add = [c for c in calls if c[1] == 'sk_add_expense']; up = [c for c in calls if c[0] == 'upload']
    check('Write: खर्च जुड़ा, राशि text "1500.50"', add and add[0][2]['p_amount'] == '1500.50' and 'सहेजा गया' in pg.inner_text('#message'), pg.inner_text('#message')[:100])
    check('Android: खाली MIME वाली DOCX सही MIME से अपलोड, path <user>/<खर्च>/<uuid>.docx', up and up[0][2].endswith('wordprocessingml.document') and re.match(r'^u-writer/n\d+/[0-9a-f-]{36}\.docx$', up[0][1]), str(up))
    pg.evaluate("window.__wa=[];HTMLAnchorElement.prototype.click=function(){if(this&&this.href)window.__wa.push([String(this.href),String(this.target),String(this.rel)])}")
    pg.click('#addedList .waNew'); wa = pg.evaluate('window.__wa')
    from urllib.parse import unquote
    wt = unquote(wa[0][0].split('text=', 1)[1]) if wa else ''
    check('नई एंट्री: "WhatsApp पर भेजें" → wa.me, नया टैब, noopener', wa and wa[0][0].startswith('https://wa.me/?text=') and wa[0][1] == '_blank' and 'noopener' in wa[0][2], str(wa))
    check('नई एंट्री संदेश: क्रमांक, तारीख DD-MM-YYYY, सामान, राशि, भुगतानकर्ता, तरीका, श्रेणी, रसीद', all(w in wt for w in ['SK-', '12-11-2026', 'JCB 1 घंटा', '₹1,500.50', 'साइट कैश', 'नकद', 'मशीन / वाहन', 'रसीद: 1', '/expenses']), wt)
    rs = [c for c in calls if c[1] == 'sk_reserve_receipt_slot']
    check('अपलोड से पहले server पर जगह आरक्षित; upload उसी आरक्षित path पर', rs and rs[0][2]['p_ext'] == 'docx' and up and up[0][1].startswith('u-writer/'), str(rs))
    # upload विफल → जगह तुरंत वापस
    pg.fill('#fAmount', '99.00'); pg.fill('#fItem', 'नेटवर्क विफल परीक्षण'); pg.select_option('#fCategory', 'अन्य'); pg.select_option('#fMethod', 'नकद'); pg.fill('#fPayer', 'साइट कैश')
    pg.evaluate('window.__FAIL_UPLOAD = true')
    pg.set_input_files('#fReceipt', files=[{'name': 'bill.pdf', 'mimeType': 'application/pdf', 'buffer': open(f'{SAMPLES}/bill.pdf', 'rb').read()}])
    pg.click('#addBtn'); pg.wait_for_timeout(700)
    calls = pg.evaluate('window.__calls')
    check('upload विफल होने पर आरक्षित जगह तुरंत छोड़ी गई (sk_release_receipt_slot)', any(c[1] == 'sk_release_receipt_slot' for c in calls) and 'जगह वापस' in pg.inner_text('#message'), pg.inner_text('#message')[:120])
    check('…कोई लंबित आरक्षण नहीं बचा', all(x['status'] != 'reserved' for x in pg.evaluate('window.__STATE.slots')))
    pg.evaluate('window.__FAIL_UPLOAD = false; window.__FAIL_ATTACH = true')
    pg.fill('#fAmount', '98.00'); pg.fill('#fItem', 'जुड़ना विफल परीक्षण'); pg.select_option('#fCategory', 'अन्य'); pg.select_option('#fMethod', 'नकद'); pg.fill('#fPayer', 'साइट कैश')
    pg.set_input_files('#fReceipt', files=[{'name': 'bill.pdf', 'mimeType': 'application/pdf', 'buffer': open(f'{SAMPLES}/bill.pdf', 'rb').read()}])
    pg.click('#addBtn'); pg.wait_for_timeout(700); pg.evaluate('window.__FAIL_ATTACH = false')
    pg.evaluate("document.querySelector('#tabs button').click()"); pg.wait_for_timeout(500)
    check('फ़ाइल चढ़ी पर जुड़ी नहीं → "अधूरे अपलोड" बॉक्स में "जोड़ें / हटाएँ"', pg.is_visible('#openSlots') and 'जुड़ी नहीं' in pg.inner_text('#openSlots') and pg.locator('.slotAttach').count() == 1)
    pg.click('.slotDelete'); pg.wait_for_timeout(500)
    calls = pg.evaluate('window.__calls')
    check('"हटाएँ": storage से अधूरी फ़ाइल हटाई और जगह वापस', any(c[0] == 'remove' for c in calls) and 'जगह वापस' in pg.inner_text('#message') and not pg.is_visible('#openSlots'))
    check('रसीद attach और server-जाँच बुलाई', any(c[1] == 'sk_attach_receipt' for c in calls) and any(c[0] == 'invoke' and c[1] == 'verify-receipt' for c in calls))
    check('Write-only सत्र में JS त्रुटि नहीं', not errs, str(errs))
    pg.screenshot(path=f'{SHOTS}/4_writer_390.png', full_page=True)
    # अधिकार वापस: Admin ने writer का Write हटाया → उसी सत्र में अगला टैब-बदल/कार्रवाई
    pg.evaluate("window.__STATE.sk_members.find(m => m.user_id === 'u-writer').can_write = false")  # Admin की ओर से (server पर)
    pg.evaluate("document.querySelector('#tabs button')?.click()"); pg.wait_for_timeout(400)
    check('Write वापस लेते ही उसी लॉगिन में "जोड़ें" टैब ग़ायब', 'खर्च जोड़ें' not in pg.inner_text('#tabs') and 'कोई अधिकार नहीं' in pg.inner_text('#message'))
    # केवल-सुधार सदस्य: सूची/कुल नहीं; क्रमांक से खोलना
    pg, errs = open_as(p, 'corrector')
    check('केवल-सुधार: "क्रमांक से खोलें" बॉक्स, सूची/कुल/फ़िल्टर छिपे', pg.is_visible('#openBox') and not pg.is_visible('#listCard')
          and not pg.is_visible('#summaryCard') and not pg.is_visible('#filterCard'))
    check('केवल-सुधार: सीधे सूची लोड करने की कोशिश भी नहीं', not any(c[1] == 'sk_summary' for c in pg.evaluate('window.__calls')))
    pg.fill('#openRef', 'SK-000001'); pg.click('#openBtn'); pg.wait_for_timeout(400)
    check('SK-000001 खुला: खर्च, रसीद और "रसीद जोड़ें (1/5)"', 'सीमेंट 50 बोरी' in pg.inner_text('#openResult') and 'bill.pdf' in pg.inner_text('#openResult')
          and 'रसीद जोड़ें (1/5)' in pg.inner_text('#openResult'), pg.inner_text('#openResult')[:150])
    pg.click('#openResult .addRcBtn'); pg.wait_for_selector('#modal:not([hidden])')
    big = [{'name': f'r{i}.pdf', 'mimeType': 'application/pdf', 'buffer': open(f'{SAMPLES}/bill.pdf', 'rb').read()} for i in range(5)]
    pg.set_input_files('#rcFiles', files=big); pg.click('#modalOk'); pg.wait_for_timeout(500)
    check('UI: 1 मौजूद + 5 नई = 6 → "केवल 4 और" कहकर रुका, कुछ अपलोड नहीं',
          'केवल 4' in pg.inner_text('#message') and not any(c[0] == 'upload' for c in pg.evaluate('window.__calls')), pg.inner_text('#message')[:100])
    pg.click('#openResult .addRcBtn'); pg.wait_for_selector('#modal:not([hidden])')
    pg.set_input_files('#rcFiles', files=big[:1]); pg.click('#modalOk'); pg.wait_for_timeout(700)
    check('1 रसीद जुड़ी → कार्ड पर "रसीद जोड़ें (2/5)"', 'रसीद जोड़ें (2/5)' in pg.inner_text('#openResult'), pg.inner_text('#openResult')[:200])
    pg.click('#openResult .fixBtn'); pg.wait_for_selector('#modal:not([hidden])')
    pg.fill('#cAmount', '21400.75'); pg.fill('#cReason', 'बिल दोबारा मिलाया'); pg.click('#modalOk'); pg.wait_for_timeout(700)
    check('केवल-सुधार: सुधार के बाद वही खर्च दोबारा खुला, नई राशि ₹21,400.75 और इतिहास में कारण',
          '₹21,400.75' in pg.inner_text('#openResult') and 'बिल दोबारा मिलाया' in pg.inner_text('#openResult'), pg.inner_text('#openResult')[:200])
    pg.fill('#openRef', '999'); pg.click('#openBtn'); pg.wait_for_timeout(300)
    check('अनजान क्रमांक पर साफ़ संदेश', 'नहीं मिला' in pg.inner_text('#message'))
    check('केवल-सुधार सत्र में JS त्रुटि नहीं', not errs, str(errs))
    pg.screenshot(path=f'{SHOTS}/6_corrector_only.png', full_page=True)
    # 5/5 पर UI में बटन ही नहीं
    pg, errs = open_as(p, 'admin')
    pg.evaluate("""for (let i=0;i<4;i++) window.__STATE.sk_receipts.push({id:'x'+i,expense_id:'e1',storage_path:'u-admin/e1/'+i+'.pdf',original_filename:'f'+i+'.pdf',verification_status:'pending',uploaded_by:'u-admin'})""")
    pg.click('#tabs button[data-t="register"]'); pg.wait_for_timeout(400)
    check('5/5 रसीदें: "रसीद जोड़ें" बटन नहीं, "सीमा पूरी" संदेश', pg.locator('#it-e1 .addRcBtn').count() == 0 and '5/5' in pg.inner_text('#it-e1'))
    # Admin: सुधार देते समय स्पष्ट पुष्टि
    pg.click('#tabs button[data-t="members"]'); pg.wait_for_timeout(400)
    check('Admin सदस्य-स्क्रीन पर "सुधार = सभी खर्चों पर लागू" साफ़ लिखा', 'सभी खर्चों पर लागू' in pg.inner_text('#v-members'))
    pg.check('#pc-u-pend'); pg.uncheck('#pr-u-pend'); pg.click('.apBtn'); pg.wait_for_selector('#modal:not([hidden])')
    body = pg.inner_text('#modalBody')
    check('सुधार (Read के बिना) देते समय पुष्टि-संवाद: सभी खर्चों पर लागू + सूची नहीं', 'सभी खर्चों पर लागू' in body and 'Read नहीं है' in body, body[:160])
    pg.screenshot(path=f'{SHOTS}/7_admin_confirm_correct.png')
    pg.click('#modalCancel'); pg.wait_for_timeout(200)
    check('पुष्टि रद्द → कोई मंज़ूरी नहीं भेजी', not any(c[1] == 'sk_admin_decide' for c in pg.evaluate('window.__calls')))
    pg.check('#ac-u-rd')
    btn = pg.locator('.saveBtn[data-u="u-rd"]'); btn.click(); pg.wait_for_selector('#modal:not([hidden])')
    check('Read वाले को सुधार देते समय: "सभी खर्च और सभी रसीदें दिखेंगी"', 'सभी रसीदें' in pg.inner_text('#modalBody'))
    pg.click('#modalOk'); pg.wait_for_timeout(500)
    m = [x for x in pg.evaluate('window.__STATE.sk_members') if x['user_id'] == 'u-rd'][0]
    check('पुष्टि के बाद अधिकार सहेजे गए (Read+सुधार)', m['can_read'] and m['can_correct'])

    # लॉगिन: यूज़र आईडी → अस्थायी ईमेल; पासवर्ड भूलने पर Admin से अनुरोध
    pg, errs = open_as(p, 'loggedout')
    check('लॉगिन फ़ॉर्म "यूज़र आईडी" माँगता है, signup बटन नहीं', 'यूज़र आईडी' in pg.inner_text('#loginBox') and pg.locator('#toggleAuth').count() == 0)
    pg.fill('#email', 'Amarnath'); pg.fill('#password', '123456'); pg.click('#authBtn'); pg.wait_for_timeout(400)
    si = [c for c in pg.evaluate('window.__calls') if c[0] == 'signin']
    check('यूज़र आईडी "Amarnath" → amarnath@suryakunj.example.com से लॉगिन (6 अंकों का पासवर्ड स्वीकार)', si and si[0][1] == 'amarnath@suryakunj.example.com', str(si))
    pg, errs = open_as(p, 'loggedout')
    pg.click('#forgotBtn'); pg.fill('#forgotId', 'writer'); pg.fill('#forgotNote', 'लेखक'); pg.click('#forgotSend'); pg.wait_for_timeout(400)
    rs = state_of(pg).get('resets', [])
    check('"पासवर्ड भूल गए" → Admin को अनुरोध दर्ज, सफलता संदेश', len(rs) == 1 and rs[0]['login'] == 'writer' and 'Admin' in pg.inner_text('#message'), str(rs))
    check('लॉगिन/रीसेट पेज में JS त्रुटि नहीं', not errs, str(errs))
    # Admin: नया सदस्य (साझेदार = Read+Write, सहायक = केवल Write) और रीसेट अनुरोध
    st = state_of(pg)
    pg, errs = open_as(p, 'admin', state=st)
    pg.click('#tabs button[data-t="members"]'); pg.wait_for_timeout(500)
    check('Admin: "नया सदस्य बनाएँ" और 6 अंकों का पासवर्ड पहले से भरा', pg.is_visible('#newMember') and len(pg.input_value('#nmPin')) == 6 and pg.input_value('#nmPin').isdigit())
    pg.fill('#nmName', 'अमरनाथ पाण्डेय'); pg.fill('#nmLogin', 'amarnath'); pg.select_option('#nmRole', 'partner'); pg.fill('#nmPin', '482915')
    pg.click('#nmBtn'); pg.wait_for_timeout(500)
    iv = [c for c in pg.evaluate('window.__calls') if c[0] == 'invoke' and c[1] == 'sk-admin-users']
    check('साझेदार: Read+Write (सुधार नहीं), आईडी/पासवर्ड function को', iv and iv[-1][2] == {'action': 'create', 'login': 'amarnath', 'name': 'अमरनाथ पाण्डेय', 'password': '482915', 'read': True, 'write': True, 'correct': False}, str(iv))
    check('बनने पर आईडी और पासवर्ड Admin को दिखे', pg.is_visible('#modal') and 'amarnath' in pg.inner_text('#modalBody') and '482915' in pg.inner_text('#modalBody'))
    pg.click('#modalOk'); pg.wait_for_timeout(400)
    pg.fill('#nmName', 'सहायक'); pg.fill('#nmLogin', 'helper'); pg.select_option('#nmRole', 'assistant'); pg.fill('#nmPin', '000123'); pg.click('#nmBtn'); pg.wait_for_timeout(500)
    iv = [c for c in pg.evaluate('window.__calls') if c[0] == 'invoke' and c[1] == 'sk-admin-users']
    check('सहायक: केवल Write', iv[-1][2]['read'] is False and iv[-1][2]['write'] is True and iv[-1][2]['correct'] is False, str(iv[-1]))
    pg.click('#modalOk'); pg.wait_for_timeout(300)
    n0 = len(iv); pg.fill('#nmLogin', 'Bad Id'); pg.fill('#nmName', 'x y'); pg.fill('#nmPin', '12ab56'); pg.click('#nmBtn'); pg.wait_for_timeout(300)
    check('गलत आईडी/पासवर्ड पर function नहीं बुलाया', len([c for c in pg.evaluate('window.__calls') if c[0] == 'invoke']) == n0)
    check('रीसेट अनुरोध Admin को सदस्य-नाम सहित दिखा', 'writer' in pg.inner_text('#resetList') and 'लेखक (परीक्षण)' in pg.inner_text('#resetList'))
    pg.click('.rsBtn'); pg.wait_for_selector('#modal:not([hidden])'); pg.fill('#pinIn', '654321'); pg.click('#modalOk'); pg.wait_for_timeout(500)
    iv = [c for c in pg.evaluate('window.__calls') if c[0] == 'invoke' and c[1] == 'sk-admin-users']
    check('नया पासवर्ड: set_password (सदस्य, 6 अंक, अनुरोध-ID)', iv[-1][2] == {'action': 'set_password', 'user_id': 'u-writer', 'password': '654321', 'request_id': 1}, str(iv[-1]))
    check('पासवर्ड बदलने के बाद अनुरोध सूची से हटा', 'कोई खुला अनुरोध नहीं' in pg.inner_text('#resetList'))
    check('हर गैर-Admin सदस्य पर "पासवर्ड बदलें" बटन, Admin पर नहीं', pg.locator('.pinBtn').count() >= 4 and pg.locator('.pinBtn[data-u="u-admin"]').count() == 0)
    pg.screenshot(path=f'{SHOTS}/6_admin_new_member.png', full_page=True)
    check('Admin सदस्य-स्क्रीन में JS त्रुटि नहीं', not errs, str(errs))

    # कुल हिसाब टैब
    pg, errs = open_as(p, 'admin')
    check('Admin: "कुल हिसाब" टैब पहला', pg.locator('#tabs button').first.inner_text() == 'कुल हिसाब')
    pg.click('#tabs button[data-t="hisab"]'); pg.wait_for_timeout(500)
    hb = pg.inner_text('#hisabBox')
    check('कुल हिसाब: तीनों साझेदार, योगदान/तय हिस्सा/अंतर', all(w in hb for w in ['आलोक रंजन मिश्र', 'अमरनाथ पाण्डेय', 'गगन आचारी', 'तय हिस्सा', 'अंतर']), hb[:200])
    check('कुल हिसाब: साझेदार-कुल ₹22,735.31 (गगन+अमरनाथ), साइट कैश अलग', '₹22,735.31' in hb, hb[:300])
    check('कुल हिसाब: ऋण अंतर "देना है" (आलोक −₹7,578.44), धन अंतर "लेना है"', '−₹7,578.44' in hb and 'देना है' in hb and '+₹13,922.31' in hb and 'लेना है' in hb, hb[:400])
    check('ऊपर "मुख्य हिसाब" link नहीं, ब्रांड "सूर्य कुंज" और शीर्षक "हिसाब-किताब"', pg.locator('header a').count() == 0 and 'सूर्य कुंज' in pg.inner_text('header') and pg.inner_text('h1') == 'हिसाब-किताब')
    check('लोड होने के बाद "खुल रहा है…" छिपा', not pg.is_visible('#boot'))
    check('कुल हिसाब में साझेदार क्रम: आलोक, अमरनाथ, गगन', hb.index('आलोक रंजन मिश्र') < hb.index('अमरनाथ पाण्डेय') < hb.index('गगन आचारी'))
    check('कुल हिसाब: "WhatsApp पर भेजें" बटन दिखता है', pg.is_visible('#waHisab'))
    pg.evaluate("window.__wa=[];HTMLAnchorElement.prototype.click=function(){if(this&&this.href)window.__wa.push([String(this.href),String(this.target),String(this.rel)])}")
    pg.click('#waHisab'); wa = pg.evaluate('window.__wa')
    wt = unquote(wa[0][0].split('text=', 1)[1]) if wa else ''
    check('हिसाब संदेश: शीर्षक, कुल, तीनों साझेदार ±, लेना/देना, लिंक; अन्य (रद्द) नहीं', all(w in wt for w in ['कुल हिसाब', 'कुल (साझेदारों से): ₹22,735.31', 'आलोक रंजन मिश्र: −₹7,578.44 (देना है)', '+₹13,922.31 (लेना है)', 'गगन आचारी', '/expenses']) and 'अन्य भुगतानकर्ता' not in wt, wt[-300:])
    check('हिसाब संदेश में HTML नहीं', '<' not in wt, wt[:200])
    pg.click('#tabs button[data-t="register"]'); pg.wait_for_timeout(500)
    check('रजिस्टर: सक्रिय एंट्री पर WhatsApp बटन, रद्द पर नहीं', pg.locator('.item.active .waBtn').count() >= 1 and pg.locator('.item.cancelled .waBtn').count() == 0)
    pg.evaluate("window.__wa=[];HTMLAnchorElement.prototype.click=function(){if(this&&this.href)window.__wa.push([String(this.href),String(this.target),String(this.rel)])}")
    pg.locator('.item.active .waBtn').first.click(); wa = pg.evaluate('window.__wa')
    check('रजिस्टर एंट्री → wa.me संदेश में क्रमांक और राशि', wa and 'SK-' in unquote(wa[0][0]) and '₹' in unquote(wa[0][0]), str(wa)[:200])
    pg.click('#tabs button[data-t="hisab"]'); pg.wait_for_timeout(400)
    pg.screenshot(path=f'{SHOTS}/7_hisab.png', full_page=True)
    check('कुल हिसाब में JS त्रुटि नहीं', not errs, str(errs))
    pg, errs = open_as(p, 'writer')
    check('केवल-Write (सहायक) को "कुल हिसाब" टैब नहीं', 'कुल हिसाब' not in pg.inner_text('#tabs'))

    # थीम: Auto → Light → Dark → Auto (फ़ोन dark पर)
    pg, errs = open_as(p, 'admin', dark=True)
    bg = lambda: pg.evaluate("getComputedStyle(document.body).backgroundColor")
    check('थीम: शुरू में Auto, फ़ोन dark → गहरा रंग', pg.evaluate("document.documentElement.getAttribute('data-theme')") is None and bg() == 'rgb(17, 20, 16)' and 'Auto' in pg.inner_text('#themeBtn'), bg())
    pg.click('#themeBtn'); pg.wait_for_timeout(100)
    check('थीम: Light चुनने पर फ़ोन dark होते हुए भी हल्का रंग', pg.evaluate("document.documentElement.dataset.theme") == 'light' and bg() == 'rgb(246, 245, 240)' and 'Light' in pg.inner_text('#themeBtn'), bg())
    pg.click('#themeBtn'); pg.wait_for_timeout(100)
    check('थीम: Dark', pg.evaluate("document.documentElement.dataset.theme") == 'dark' and bg() == 'rgb(17, 20, 16)')
    pg.reload(); pg.wait_for_timeout(700)
    check('थीम: पसंद reload के बाद भी याद (Dark)', pg.evaluate("document.documentElement.dataset.theme") == 'dark' and 'Dark' in pg.inner_text('#themeBtn'))
    pg.click('#themeBtn'); pg.wait_for_timeout(100)
    check('थीम: फिर Auto', pg.evaluate("document.documentElement.getAttribute('data-theme')") is None and 'Auto' in pg.inner_text('#themeBtn'))
    pg2, errs2 = open_as(p, 'loggedout')
    check('थीम बटन लॉगिन पेज पर भी', pg2.is_visible('#themeBtn'))
    check('थीम में JS त्रुटि नहीं', not errs and not errs2, str(errs + errs2))

    # बहु-रिपोर्ट: पार्टी-वार, श्रेणी-वार, अवधि-विकल्प
    pg, errs = open_as(p, 'admin')
    check('रिपोर्ट विकल्प: प्रकार 3, अवधि 6, पार्टी और श्रेणी फ़िल्टर', pg.locator('#rpType option').count() == 3 and pg.locator('#rpPeriod option').count() == 6
          and pg.locator('#rpPayer option').count() >= 4 and pg.locator('#rpCategory option').count() >= 15)
    pg.evaluate("""() => { window.__pages = []; import('./js/report.js').then(m => { window.__rp = m; }); }"""); pg.wait_for_timeout(300)
    html = pg.evaluate("""() => window.__rp.buildPages({type:'payer',details:true,from:'',to:'',label:'पूरी अवधि',by:'x',when:'y'},
        [{kind:'all',invest:'0',spend:'3',total:'3'},{kind:'other',total:'0'}],
        [{ref_no:1,expense_date:'2026-11-01',item:'सीमेंट',category:'निर्माण सामग्री',amount:'100.00',payer:'गगन आचारी',payment_method:'UPI',status:'active'},
         {ref_no:2,expense_date:'2026-11-02',item:'बालू',category:'निर्माण सामग्री',amount:'50.00',payer:'आलोक रंजन मिश्र',payment_method:'नकद',status:'active'},
         {ref_no:3,expense_date:'2026-11-03',item:'मजदूर',category:'मजदूरी',amount:'25.50',payer:'आलोक रंजन मिश्र',payment_method:'नकद',status:'active'}]).join('')""")
    check('पार्टी-वार: समूह-शीर्षक, उप-योग, आलोक पहले', 'पार्टी-वार' in html and 'उप-योग: आलोक रंजन मिश्र' in html and '₹75.50' in html and html.index('आलोक रंजन मिश्र — 2 एंट्री') < html.index('गगन आचारी — 1 एंट्री'), html[:200])
    html = pg.evaluate("""() => window.__rp.buildPages({type:'category',details:true,from:'2026-11-01',to:'2026-11-30',label:'इस महीने',category:'निर्माण सामग्री',by:'x',when:'y'},
        [{kind:'all'},{kind:'other',total:'0'}],
        [{ref_no:1,expense_date:'2026-11-01',item:'सीमेंट',category:'निर्माण सामग्री',amount:'100.00',payer:'गगन आचारी',payment_method:'UPI',status:'active'}]).join('')""")
    check('श्रेणी-वार: शीर्षक, फ़िल्टर, अवधि, उप-योग, साझेदार-तालिका नहीं', 'श्रेणी / सामग्री-वार रिपोर्ट' in html and 'श्रेणी: <b>निर्माण सामग्री</b>' in html and 'इस महीने' in html and 'उप-योग: निर्माण सामग्री' in html and 'कुल हिसाब — साझेदार-वार' not in html)
    pg.select_option('#rpType', 'payer'); pg.select_option('#rpPayer', 'गगन आचारी'); pg.select_option('#rpPeriod', 'full'); pg.check('#rpCancelled')
    with pg.expect_download(timeout=60000) as dl:
        pg.click('#rpMake')
    d = dl.value; data = open(d.path(), 'rb').read(); open(f'{SHOTS}/party.pdf', 'wb').write(data)
    check('पार्टी-वार PDF (गगन) डाउनलोड, नाम में party', data[:5] == b'%PDF-' and 'party' in d.suggested_filename and 'पार्टी-वार' in pg.inner_text('#rpStatus'), d.suggested_filename + ' ' + pg.inner_text('#rpStatus'))
    check('फ़िल्टर का असर: केवल गगन की एंट्री', ' एंट्री)' in pg.inner_text('#rpStatus'), pg.inner_text('#rpStatus'))
    pg.select_option('#rpType', 'category'); pg.select_option('#rpPayer', ''); pg.select_option('#rpPeriod', 'day')
    pg.click('#rpMake'); pg.wait_for_timeout(2500)
    check('"आज" की रिपोर्ट (कोई एंट्री नहीं) भी बनती है', '0 एंट्री' in pg.inner_text('#rpStatus'), pg.inner_text('#rpStatus'))
    pg.select_option('#rpPeriod', 'custom'); pg.fill('#rpFrom', ''); pg.fill('#rpTo', ''); pg.click('#rpMake'); pg.wait_for_timeout(300)
    check('कस्टम में तारीख खाली हो तो रोक', 'दोनों तारीख' in pg.inner_text('#message'))
    check('बहु-रिपोर्ट में JS त्रुटि नहीं', not errs, str(errs))
    # रसीद: कैमरा से फ़ोटो (बिना extension वाला नाम भी)
    pg, errs = open_as(p, 'writer')
    check('खर्च फ़ॉर्म में "कैमरा से फ़ोटो" (capture=environment)', pg.is_visible('label[for="fCamera"]') and pg.get_attribute('#fCamera', 'capture') == 'environment')
    jpg = open(f'{SAMPLES}/bill.jpg', 'rb').read()
    pg.set_input_files('#fCamera', files=[{'name': 'image', 'mimeType': 'image/jpeg', 'buffer': jpg}]); pg.wait_for_timeout(200)
    pg.set_input_files('#fCamera', files=[{'name': 'IMG_2001.jpg', 'mimeType': 'image/jpeg', 'buffer': jpg}]); pg.wait_for_timeout(200)
    check('कैमरा की 2 फ़ोटो सूची में', 'कैमरा से 2 फ़ोटो' in pg.inner_text('#camList'), pg.inner_text('#camList'))
    pg.select_option('#fCategory', 'निर्माण सामग्री'); pg.select_option('#fMethod', index=1)
    pg.fill('#fAmount', '640'); pg.fill('#fItem', 'कैमरा परीक्षण'); pg.fill('#fPayer', 'गगन आचारी'); pg.click('#addBtn'); pg.wait_for_timeout(800)
    st = state_of(pg); names = [r['original_filename'] for r in st['sk_receipts']]
    check('कैमरा की फ़ोटो रसीद बनकर जुड़ीं (बिना extension → camera-*.jpg)', any(n.startswith('camera-') and n.endswith('.jpg') for n in names) and 'IMG_2001.jpg' in names and '2 रसीद' in pg.inner_text('#message'), str(names) + pg.inner_text('#message'))
    check('सहेजने के बाद कैमरा-सूची खाली', pg.inner_text('#camList').strip() == '')
    check('कैमरा में JS त्रुटि नहीं', not errs, str(errs))

    # swipe से टैब बदलना
    pg, errs = open_as(p, 'admin')
    def swipe(sel, dx, dy=0):
        pg.evaluate("""([sel, dx, dy]) => { const el = document.querySelector(sel), r = el.getBoundingClientRect();
          const x = r.left + r.width / 2, y = r.top + Math.min(r.height / 2, 200);
          const mk = (cx, cy) => new Touch({ identifier: 1, target: el, clientX: cx, clientY: cy });
          el.dispatchEvent(new TouchEvent('touchstart', { touches: [mk(x, y)], changedTouches: [mk(x, y)], bubbles: true }));
          el.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [mk(x + dx, y + dy)], bubbles: true })); }""", [sel, dx, dy])
        pg.wait_for_timeout(500)
    cur = lambda: pg.locator('#tabs button.on').get_attribute('data-t')
    swipe('#hisabBox', -150)
    check('बाएँ swipe → अगला टैब (कुल हिसाब → खर्च जोड़ें)', cur() == 'add', cur())
    swipe('#v-add h2', -150)
    check('फिर बाएँ swipe → रजिस्टर', cur() == 'register', cur())
    swipe('#listCard h2', 150)
    check('दाएँ swipe → पिछला टैब (खर्च जोड़ें)', cur() == 'add', cur())
    swipe('#fItem', -150)
    check('फ़ॉर्म के खाने पर swipe से टैब नहीं बदलता', cur() == 'add', cur())
    swipe('#v-add h2', -40, 0)
    check('छोटा खिसकाव (40px) टैब नहीं बदलता', cur() == 'add', cur())
    swipe('#v-add h2', -150, 200)
    check('ऊपर-नीचे scroll जैसा खिसकाव टैब नहीं बदलता', cur() == 'add', cur())
    swipe('#v-add h2', 150); swipe('#hisabBox', 150)
    check('पहले टैब पर दाएँ swipe → वहीं रहता है', cur() == 'hisab', cur())
    check('swipe में JS त्रुटि नहीं', not errs, str(errs))

    # PDF रिपोर्ट
    pg, errs = open_as(p, 'admin')
    check('PDF रिपोर्ट कार्ड "कुल हिसाब" टैब में', pg.is_visible('#reportCard') and pg.is_visible('#rpMake'))
    with pg.expect_download(timeout=60000) as dl:
        pg.click('#rpMake')
    d = dl.value; path = d.path(); data = open(path, 'rb').read(); open(f'{SHOTS}/report.pdf', 'wb').write(data)
    import re as _re
    npages = len(_re.findall(rb'/Type\s*/Page[^s]', data))
    check('PDF डाउनलोड: असली PDF, नाम सही, ≥2 पृष्ठ (सार + एंट्री)', data[:5] == b'%PDF-' and d.suggested_filename.startswith('surya-kunj-hisab-report-') and npages >= 2, f'{d.suggested_filename} pages={npages} size={len(data)}')
    pg.wait_for_timeout(300)
    check('PDF बनने के बाद संदेश और कोई अस्थायी पन्ना नहीं बचा', 'तैयार' in pg.inner_text('#rpStatus') and pg.locator('.rp').count() == 0, pg.inner_text('#rpStatus'))
    check('कस्टम तारीख-खाने केवल "कस्टम" अवधि पर', not pg.is_visible('#rpFrom'))
    pg.select_option('#rpPeriod', 'custom')
    check('कस्टम चुनते ही तारीख-खाने दिखे', pg.is_visible('#rpFrom') and pg.is_visible('#rpTo'))
    pg.fill('#rpFrom', '2026-12-01'); pg.fill('#rpTo', '2026-01-01'); pg.click('#rpMake'); pg.wait_for_timeout(300)
    check('उलटी तारीखों पर रोक', 'पहले' in pg.inner_text('#message'))
    pg.evaluate("window.Capacitor = { isNativePlatform: () => true }")
    pg.select_option('#rpPeriod', 'full'); pg.click('#rpMake'); pg.wait_for_timeout(300)
    check('APK के अंदर: "Chrome में खोलें" विकल्प (डाउनलोड नहीं)', pg.is_visible('#rpOpen') and 'Chrome' in pg.inner_text('#rpStatus'))
    check('रिपोर्ट में JS त्रुटि नहीं', not errs, str(errs))
    pg.click('#tabs button[data-t="register"]'); pg.wait_for_timeout(300)
    check('दूसरे टैब पर रिपोर्ट कार्ड छिपा', not pg.is_visible('#reportCard'))

    # Dark + desktop
    pg, errs = open_as(p, 'admin', 1280, 900, dark=True)
    pg.click('#tabs button[data-t="register"]'); pg.wait_for_timeout(400)
    pg.screenshot(path=f'{SHOTS}/5_desktop_dark.png')
    check('desktop dark mode रेंडर', pg.is_visible('#entries'))
    # मुख्य हिसाब पेज
    pg, errs = open_as(p, 'admin', fake=False)
    pg.goto(BASE + '/index.html'); pg.wait_for_timeout(400)
    check('मुख्य हिसाब पेज पर "खर्च रजिस्टर" link', 'खर्च रजिस्टर' in pg.content() and pg.locator('a[href="./expenses.html"]').count() >= 1)
    check('मुख्य पेज में JS त्रुटि नहीं', not errs, str(errs))
    browser.close()

srv.shutdown()
for s, n, i in res:
    print(f'{s:5} | {n}' + (f'  [{i[:140]}]' if i and s == 'FAIL' else ''))
pp = sum(r[0] == 'PASS' for r in res)
print(f'\nकुल {len(res)} : PASS {pp} / FAIL {len(res) - pp}')
sys.exit(0 if pp == len(res) else 1)
