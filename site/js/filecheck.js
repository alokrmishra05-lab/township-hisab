// सूर्य कुंज | प्रमाण फ़ाइल की सामग्री-जाँच (magic bytes + संरचना)।
// यही फ़ाइल ब्राउज़र (पहली जाँच) और Edge Function verify-evidence (अंतिम, भरोसेमंद
// जाँच) दोनों में चलती है। ब्राउज़र की जाँच केवल सुविधा है — असली निर्णय server पर।
// supabase/functions/_shared/filecheck.js इसकी हूबहू प्रति है (टेस्ट जाँचता है)।

export const MAX_BYTES = 10 * 1024 * 1024;

export const TYPES = {
  jpg:  'image/jpeg',
  jpeg: 'image/jpeg',
  png:  'image/png',
  webp: 'image/webp',
  pdf:  'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
};

export function extOf(name) {
  const m = /\.([a-z0-9]{1,5})$/i.exec(String(name || ''));
  return m ? m[1].toLowerCase() : '';
}

// Android कई बार .docx/.webp का type खाली या octet-stream देता है:
// तब extension से MIME तय करें; असली सत्यापन सामग्री से होता है।
export function expectedMime(name, browserType) {
  const byExt = TYPES[extOf(name)];
  if (!byExt) return null;
  const t = String(browserType || '').toLowerCase();
  if (!t || t === 'application/octet-stream' || t === 'application/zip' || t === byExt) return byExt;
  if (byExt === 'image/jpeg' && t === 'image/jpg') return byExt;
  return null; // नाम और ब्राउज़र का type आपस में विरोधी
}

const startsWith = (b, sig, at = 0) => sig.every((v, i) => b[at + i] === v);
const ascii = s => [...s].map(c => c.charCodeAt(0));
const latin1 = (b, from = 0, to = b.length) => {
  let s = '';
  for (let i = from; i < to; i += 8192) s += String.fromCharCode.apply(null, b.subarray(i, Math.min(to, i + 8192)));
  return s;
};
const u16 = (b, o) => b[o] | (b[o + 1] << 8);
const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;

function checkPdf(b) {
  if (!startsWith(b, ascii('%PDF-'))) return 'PDF का हेडर नहीं मिला';
  const tail = latin1(b, Math.max(0, b.length - 2048));
  if (!tail.includes('%%EOF')) return 'PDF अधूरी/कटी हुई है';
  const all = latin1(b);
  // सक्रिय/छिपी सामग्री वाली PDF बिल के रूप में स्वीकार नहीं
  const bad = [/\/JavaScript\b/, /\/JS\b/, /\/Launch\b/, /\/EmbeddedFiles?\b/, /\/RichMedia\b/, /\/XFA\b/];
  for (const re of bad) if (re.test(all)) return 'PDF में script/embedded सामग्री है';
  return null;
}

function checkDocx(b) {
  if (!startsWith(b, [0x50, 0x4b, 0x03, 0x04])) {
    if (startsWith(b, [0xd0, 0xcf, 0x11, 0xe0])) return 'पुराना .doc या पासवर्ड-सुरक्षित फ़ाइल — DOCX नहीं';
    return 'DOCX (ZIP) संरचना नहीं मिली';
  }
  // End of Central Directory खोजें (अंतिम 66 KB में)
  let eocd = -1;
  for (let i = b.length - 22; i >= Math.max(0, b.length - 65557); i--) {
    if (u32(b, i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) return 'DOCX की ZIP निर्देशिका नहीं मिली';
  const count = u16(b, eocd + 10);
  let off = u32(b, eocd + 16);
  if (count === 0 || count > 2000 || off >= b.length) return 'DOCX संरचना असामान्य';
  const names = [];
  let total = 0;
  for (let n = 0; n < count; n++) {
    if (off + 46 > b.length || u32(b, off) !== 0x02014b50) return 'DOCX निर्देशिका टूटी है';
    const flags = u16(b, off + 8);
    if (flags & 0x1) return 'एन्क्रिप्टेड DOCX स्वीकार नहीं';
    total += u32(b, off + 24);
    const nl = u16(b, off + 28), el = u16(b, off + 30), cl = u16(b, off + 32);
    names.push(latin1(b, off + 46, off + 46 + nl));
    off += 46 + nl + el + cl;
  }
  if (total > 200 * 1024 * 1024) return 'DOCX का खुला आकार असामान्य रूप से बड़ा (zip bomb)';
  if (!names.includes('[Content_Types].xml') || !names.includes('word/document.xml')) {
    return 'यह Word (DOCX) दस्तावेज़ नहीं है';
  }
  const risky = names.find(n => /vbaProject|vbaData|activeX|oleObject|\/embeddings\/|\.(bin|exe|dll|js|vbs|ps1|bat|cmd|scr)$/i.test(n));
  if (risky) return 'DOCX में macro/embedded सामग्री है: ' + risky;
  return null;
}

// bytes: Uint8Array (पूरी फ़ाइल)। लौटाता है {ok, mime, reason}
export function inspectFile(bytes, filename) {
  const b = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const ext = extOf(filename);
  const mime = TYPES[ext];
  if (!mime) return { ok: false, mime: null, reason: 'केवल JPG, PNG, WEBP, PDF, DOCX स्वीकार' };
  if (b.length === 0) return { ok: false, mime, reason: 'फ़ाइल खाली है' };
  if (b.length > MAX_BYTES) return { ok: false, mime, reason: 'फ़ाइल 10 MB से बड़ी है' };
  let reason = null;
  if (mime === 'image/jpeg') {
    if (!startsWith(b, [0xff, 0xd8, 0xff])) reason = 'JPG का हेडर नहीं मिला';
  } else if (mime === 'image/png') {
    if (!startsWith(b, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]) || !startsWith(b, ascii('IHDR'), 12)) {
      reason = 'PNG का हेडर नहीं मिला';
    }
  } else if (mime === 'image/webp') {
    if (!startsWith(b, ascii('RIFF')) || !startsWith(b, ascii('WEBP'), 8)) reason = 'WEBP का हेडर नहीं मिला';
  } else if (mime === 'application/pdf') {
    reason = checkPdf(b);
  } else {
    reason = checkDocx(b);
  }
  return reason ? { ok: false, mime, reason: 'फ़ाइल अस्वीकार: ' + reason } : { ok: true, mime, reason: null };
}
