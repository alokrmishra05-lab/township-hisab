// चलाएँ: node tests/filecheck.test.mjs <नमूना-फ़ाइलों का फ़ोल्डर>
// नमूने कृत्रिम हैं (कोई असली वित्तीय दस्तावेज़ नहीं)।
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inspectFile, expectedMime } from '../site/js/filecheck.js';

const here = dirname(fileURLToPath(import.meta.url));
const dir = process.argv[2];
const cases = [
  ['bill.jpg', true], ['bill.png', true], ['bill.webp', true], ['bill.pdf', true], ['bill.docx', true],
  ['js.pdf', false], ['truncated.pdf', false], ['macro.docx', false], ['notword.docx', false],
  ['old.docx', false], ['png_as.pdf', false], ['exe_as.jpg', false], ['html_as.png', false],
  ['empty.jpg', false], ['evil.exe', false], ['big.pdf', false],
];
let pass = 0, fail = 0;
const out = (ok, name, info) => { ok ? pass++ : fail++; console.log(`${ok ? 'PASS' : 'FAIL'}  | ${name}  [${info}]`); };
for (const [f, want] of cases) {
  const r = inspectFile(new Uint8Array(readFileSync(join(dir, f))), f);
  out(r.ok === want, `${f} → ${want ? 'स्वीकार' : 'अस्वीकार'}`, r.reason || r.mime);
}
// Android: खाली/octet-stream type पर extension से MIME; विरोधी type पर रोक
const mt = [
  ['bill.docx', '', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  ['bill.docx', 'application/octet-stream', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  ['photo.webp', '', 'image/webp'], ['IMG.JPG', 'image/jpeg', 'image/jpeg'],
  ['bill.pdf', 'image/png', null], ['old.doc', 'application/msword', null],
];
for (const [n, t, want] of mt) {
  const got = expectedMime(n, t);
  out(got === want, `expectedMime(${n}, "${t}")`, String(got));
}
// ब्राउज़र और Edge Function की प्रति एक जैसी हो
const a = readFileSync(join(here, '../site/js/filecheck.js'), 'utf8');
const b = readFileSync(join(here, '../supabase/functions/_shared/filecheck.js'), 'utf8');
out(a === b, 'ब्राउज़र और server validator हूबहू एक', a === b ? 'same' : 'DIFFERENT');
console.log(`\nकुल ${pass + fail} : PASS ${pass} / FAIL ${fail}`);
process.exit(fail ? 1 : 0);
