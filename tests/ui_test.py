"""साइट खर्च UI का ब्राउज़र परीक्षण (Chromium, नकली Supabase; असली backend नहीं)।
चलाएँ: python3 tests/ui_test.py <नमूना-फ़ाइल फ़ोल्डर> <screenshot फ़ोल्डर>
"""
import sys, os, json, threading, http.server, functools
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
SAMPLES, SHOTS = sys.argv[1], sys.argv[2]
os.makedirs(SHOTS, exist_ok=True)
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
handler = functools.partial(Quiet, directory=os.path.join(ROOT, 'site'))
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 8765), handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:8765'
FAKE = open(os.path.join(ROOT, 'tests', 'ui_fake_supabase.js'), encoding='utf-8').read()
CFG = 'window.SITE_EXPENSE_CONFIG={url:"https://abcdefgh.supabase.co",anonKey:"' + 'x' * 60 + '"};'
res = []
def check(name, cond, info=''):
    res.append(('PASS' if cond else 'FAIL', name, info))

def page_for(p, role, width=390, height=844, fake=True):
    ctx = p.chromium.launch().new_context(viewport={'width': width, 'height': height}, device_scale_factor=2)
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    # जानबूझकर रोके गए अनुरोध (fonts / नकली client हेतु vendor) की "Failed to load resource" गिनती नहीं
    pg.on('console', lambda m: errs.append(m.text) if m.type == 'error' and not m.text.startswith('Failed to load resource') else None)
    if fake:
        pg.add_init_script(f'window.__ROLE={json.dumps(role)};' + FAKE)
        pg.route('**/expenses-config.js', lambda r: r.fulfill(body=CFG, content_type='application/javascript'))
        pg.route('**/vendor/supabase-js-*.js', lambda r: r.abort())   # असली client की जगह नकली
    pg.route('**/fonts.googleapis.com/**', lambda r: r.abort())
    return pg, errs

with sync_playwright() as p:
    # 1) बिना config: setup सूचना, कोई त्रुटि नहीं
    pg, errs = page_for(p, 'admin', fake=False)
    pg.goto(BASE + '/expenses.html'); pg.wait_for_timeout(800)
    check('बिना Supabase config: "सुविधा चालू नहीं" सूचना दिखती है', pg.is_visible('#setup'))
    check('बिना config: कोई JS त्रुटि नहीं', not [e for e in errs if 'fonts' not in e], str(errs))

    # 2) SRI: बदली हुई supabase-js फ़ाइल ब्राउज़र रोक देता है
    pg, errs = page_for(p, 'admin', fake=False)
    pg.route('**/vendor/supabase-js-*.js', lambda r: r.fulfill(body='window.supabase={createClient(){}};', content_type='application/javascript'))
    pg.route('**/expenses-config.js', lambda r: r.fulfill(body=CFG, content_type='application/javascript'))
    pg.goto(BASE + '/expenses.html'); pg.wait_for_timeout(800)
    check('SRI: छेड़छाड़ की गई supabase-js लोड नहीं होती', pg.evaluate('typeof window.supabase') == 'undefined',
          'integrity errors: ' + str([e for e in errs if 'integrity' in e.lower()][:1]))

    # 3) असली vendored फ़ाइल SRI के साथ लोड होती है
    pg, errs = page_for(p, 'admin', fake=False)
    pg.route('**/expenses-config.js', lambda r: r.fulfill(body=CFG, content_type='application/javascript'))
    pg.goto(BASE + '/expenses.html'); pg.wait_for_timeout(1500)
    check('असली supabase-js 2.119.0 integrity के साथ लोड होता है', pg.evaluate('typeof window.supabase?.createClient') == 'function',
          str([e for e in errs if 'integrity' in e.lower()][:1]))

    # 4) admin/reviewer (360px Android चौड़ाई)
    pg, errs = page_for(p, 'admin', 360, 780)
    pg.goto(BASE + '/expenses.html'); pg.wait_for_selector('#workspace:not([hidden])', timeout=5000); pg.wait_for_timeout(500)
    check('admin: workspace दिखता है', pg.is_visible('#workspace'))
    check('admin: पूरे database का योग दिखता है (RPC)', '₹5,000' in pg.inner_text('#totals') and '₹1,14,700' in pg.inner_text('#totals'), pg.inner_text('#totals'))
    check('admin: दूसरे का pending — स्वीकृति बटन', pg.locator('#it-e-1 .approveBtn').count() == 1)
    check('admin: अपने pending पर स्वीकृति बटन नहीं (self-approval)', pg.locator('#it-e-3 .approveBtn').count() == 0)
    check('admin: approved पर बदलाव/समीक्षा बटन नहीं', pg.locator('#it-e-2 .editBtn, #it-e-2 .approveBtn').count() == 0)
    check('क्षैतिज scroll नहीं (360px)', pg.evaluate('document.documentElement.scrollWidth <= innerWidth'))
    pg.screenshot(path=f'{SHOTS}/1_admin_360.png', full_page=True)
    # अस्वीकृति बिना कारण नहीं भेजी जाती
    pg.click('#it-e-1 .rejectBtn'); pg.wait_for_selector('#modal:not([hidden])')
    pg.click('#modalOk'); pg.wait_for_timeout(300)
    check('अस्वीकृति: कारण बिना संवाद बंद नहीं होता', pg.is_visible('#modal')
          and not any(c[0] == 'rpc' and c[1] == 'site_expense_review' for c in pg.evaluate('window.__calls')))
    pg.click('#modalCancel')
    # स्वीकृति: दोहराव पुष्टि ज़रूरी, version पिन
    pg.click('#it-e-1 .approveBtn'); pg.wait_for_selector('#modal:not([hidden])'); pg.wait_for_timeout(300)
    pg.screenshot(path=f'{SHOTS}/2_approve_dialog.png')
    check('स्वीकृति संवाद में संभावित दोहराव चेतावनी', 'संभावित दोहराव' in pg.inner_text('#modalBody'))
    pg.click('#modalOk'); pg.wait_for_timeout(200)
    check('दोहराव पुष्टि बिना स्वीकृति नहीं भेजी जाती', not any(c[1] == 'site_expense_review' for c in pg.evaluate('window.__calls')))
    pg.check('#dupOk'); pg.click('#modalOk'); pg.wait_for_timeout(500)
    rv = [c for c in pg.evaluate('window.__calls') if c[1] == 'site_expense_review']
    check('स्वीकृति RPC में देखा गया version (3) और पुष्टि भेजी गई', rv and rv[0][2]['p_expected_version'] == 3
          and rv[0][2]['p_confirm_duplicate'] is True, str(rv))
    # अधूरा अपलोड recovery
    check('अपने pending में अधूरे अपलोड की recovery सूचना', 'अधूरा अपलोड' in pg.inner_text('#it-e-3'))
    check('JS त्रुटि नहीं (admin)', not [e for e in errs if 'fonts' not in e], str(errs))

    # 5) फ़ॉर्म: भविष्य तारीख, payer, Android docx (खाली MIME), macro docx
    pg.fill('#amount', '1500'); pg.select_option('#category', 'निर्माण सामग्री'); pg.select_option('#method', 'नकद')
    pg.fill('#description', 'सीमेंट 5 बोरी (परीक्षण)'); pg.select_option('#payerType', 'partner')
    check('साझेदार चुनने पर नाम-सूची खुलती है', pg.is_visible('#partner'))
    pg.evaluate("document.getElementById('date').value='2099-01-01'")
    pg.set_input_files('#proof', files=[{'name': 'bill.docx', 'mimeType': '', 'buffer': open(f'{SAMPLES}/bill.docx', 'rb').read()}])
    pg.click('#submitBtn'); pg.wait_for_timeout(300)
    check('भविष्य की तारीख UI में रुकती है', 'भविष्य' in pg.inner_text('#message'))
    pg.fill('#date', '2026-11-10'); pg.click('#submitBtn'); pg.wait_for_timeout(300)
    check('साझेदार का नाम न चुनने पर रोक', 'साझेदार का नाम' in pg.inner_text('#message'))
    pg.select_option('#partner', 'गगन आचारी')
    pg.set_input_files('#proof', files=[{'name': 'macro.docx', 'mimeType': '', 'buffer': open(f'{SAMPLES}/macro.docx', 'rb').read()}])
    pg.click('#submitBtn'); pg.wait_for_timeout(500)
    check('macro वाला DOCX ब्राउज़र में ही रुकता है', 'macro' in pg.inner_text('#message'), pg.inner_text('#message')[:120])
    pg.set_input_files('#proof', files=[{'name': 'bill.docx', 'mimeType': '', 'buffer': open(f'{SAMPLES}/bill.docx', 'rb').read()}])
    pg.click('#submitBtn'); pg.wait_for_timeout(1200)
    calls = pg.evaluate('window.__calls')
    ins = [c for c in calls if c[0] == 'insert']
    up = [c for c in calls if c[0] == 'upload']
    check('Android: खाली MIME वाला DOCX सही MIME के साथ अपलोड', up and up[-1][2].endswith('wordprocessingml.document'), str(up[-1:]))
    check('अपलोड path: <user>/<expense>/<uuid>.docx', up and up[-1][1].endswith('.docx') and '/new-1/' in up[-1][1])
    check('insert में payer_type=partner और साझेदार नाम', ins and ins[-1][2]['payer_type'] == 'partner' and ins[-1][2]['paid_by_partner'] == 'गगन आचारी')
    check('अपलोड के बाद attach RPC और server जाँच बुलाई गई',
          any(c[1] == 'site_expense_attach_evidence' for c in calls) and any(c[0] == 'invoke' and c[1] == 'verify-evidence' for c in calls))
    check('सफलता संदेश', 'खर्च सुरक्षित' in pg.inner_text('#message'), pg.inner_text('#message')[:120])

    # 6) assistant: समीक्षा बटन नहीं
    pg, errs = page_for(p, 'assistant', 390, 844)
    pg.goto(BASE + '/expenses.html'); pg.wait_for_selector('#workspace:not([hidden])', timeout=5000); pg.wait_for_timeout(500)
    check('assistant: कोई स्वीकृति/अस्वीकृति बटन नहीं', pg.locator('.approveBtn, .rejectBtn').count() == 0)
    check('assistant: "केवल अपनी एंट्री" सूचना', 'केवल अपनी एंट्री' in pg.inner_text('#identity'))
    pg.screenshot(path=f'{SHOTS}/3_assistant_390.png', full_page=True)

    # 7) desktop + dark mode
    ctx = p.chromium.launch().new_context(viewport={'width': 1280, 'height': 900}, color_scheme='dark')
    pg = ctx.new_page(); pg.add_init_script('window.__ROLE="admin";' + FAKE)
    pg.route('**/expenses-config.js', lambda r: r.fulfill(body=CFG, content_type='application/javascript'))
    pg.route('**/vendor/supabase-js-*.js', lambda r: r.abort()); pg.route('**/fonts.googleapis.com/**', lambda r: r.abort())
    pg.goto(BASE + '/expenses.html'); pg.wait_for_selector('#workspace:not([hidden])'); pg.wait_for_timeout(400)
    pg.screenshot(path=f'{SHOTS}/4_desktop_dark.png')
    check('desktop dark mode में रेंडर', pg.is_visible('#workspace'))

    # 8) मुख्य हिसाब पेज: लिंक व lock स्क्रीन
    pg, errs = page_for(p, 'admin', fake=False)
    pg.goto(BASE + '/index.html'); pg.wait_for_timeout(500)
    check('मुख्य पेज की lock स्क्रीन पर साइट खर्च लिंक', pg.locator('a[href="./expenses.html"]').count() >= 1)
    check('मुख्य पेज: JS त्रुटि नहीं', not [e for e in errs if 'fonts' not in e], str(errs))

srv.shutdown()
for s, n, i in res:
    print(f'{s:5} | {n}' + (f'  [{i[:120]}]' if i and s == 'FAIL' else ''))
pp = sum(r[0] == 'PASS' for r in res)
print(f'\nकुल {len(res)} : PASS {pp} / FAIL {len(res) - pp}')
sys.exit(0 if pp == len(res) else 1)
