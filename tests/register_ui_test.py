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
    check('Read: केवल "रजिस्टर" टैब (जोड़ें/सदस्य/CSV नहीं)', 'रजिस्टर' in tabs and 'खर्च जोड़ें' not in tabs and 'सदस्य' not in tabs)
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
