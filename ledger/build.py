"""मूल हिसाब पेज (site/index.html) ledger/template.html से बनाता है।

दो तरीके:
  1) डेटा बदले बिना पेज दोबारा बनाना (लिंक/डिज़ाइन बदलाव) — मौजूदा ciphertext जस का तस:
       python3 ledger/build.py --reuse-blob site/index.html
  2) नया/अपडेटेड हिसाब एन्क्रिप्ट करना (data.json रिपो में कभी नहीं):
       LEDGER_PASSWORD=... python3 ledger/build.py --data /सुरक्षित/जगह/data.json
"""
import argparse, base64, json, os, re, sys

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(here)
ap = argparse.ArgumentParser()
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument('--reuse-blob', metavar='HTML')
g.add_argument('--data', metavar='JSON')
a = ap.parse_args()

if a.reuse_blob:
    m = re.search(r'const BLOB = (\{.*?\});', open(a.reuse_blob, encoding='utf-8').read())
    if not m:
        sys.exit('पुराने पेज में BLOB नहीं मिला')
    blob = m.group(1)
else:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    pw = os.environ.get('LEDGER_PASSWORD') or sys.exit('LEDGER_PASSWORD सेट करें')
    plain = json.dumps(json.load(open(a.data, encoding='utf-8')), ensure_ascii=False).encode()
    ITER = 300_000
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITER).derive(pw.encode())
    b = lambda x: base64.b64encode(x).decode()
    blob = json.dumps({'salt': b(salt), 'iv': b(iv), 'iter': ITER, 'ct': b(AESGCM(key).encrypt(iv, plain, None))})

tpl = open(os.path.join(here, 'template.html'), encoding='utf-8').read()
if '__BLOB__' not in tpl or 'expenses.html' not in tpl:
    sys.exit('template में BLOB स्थान या साइट खर्च लिंक नहीं')
open(os.path.join(root, 'site', 'index.html'), 'w', encoding='utf-8').write(tpl.replace('__BLOB__', blob))
print('site/index.html बना')
