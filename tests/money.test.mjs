// चलाएँ: node tests/money.test.mjs — पैसे/CSV helpers (DOM-रहित)
import { toPaise, paiseToText, rupee, csvCell, toCsv, expensesCsv, csvActiveTotalPaise } from '../site/js/money.js';

let pass = 0, fail = 0;
const t = (name, cond, info = '') => { cond ? pass++ : fail++; console.log(`${cond ? 'PASS' : 'FAIL'}  | ${name}${cond ? '' : '  [' + info + ']'}`); };

t('toPaise("2450") = 245000', toPaise('2450') === 245000n);
t('toPaise("2450.5") = 245050', toPaise('2450.5') === 245050n);
t('toPaise("0.01") = 1', toPaise('0.01') === 1n);
t('तीन दशमलव अस्वीकार', toPaise('1.005') === null);
t('ऋण/अक्षर/खाली अस्वीकार', [ '-5', '12a', '', ' . ', '1,000' ].every(v => toPaise(v) === null));
t('paiseToText(2100025) = "21000.25"', paiseToText(2100025n) === '21000.25');
t('rupee: भारतीय अंक-समूह ₹1,23,45,678.90', rupee('12345678.90') === '₹1,23,45,678.90', rupee('12345678.90'));
t('rupee(number 21000.25)', rupee(21000.25) === '₹21,000.25', rupee(21000.25));
t('float जोड़ की गलती नहीं: 0.1+0.2 पैसे में = 0.30', paiseToText(toPaise('0.1') + toPaise('0.2')) === '0.30');
t('CSV formula-injection से बचाव', csvCell('=HYPERLINK("x")').startsWith(`"'=`) && csvCell('+91').startsWith("'") && csvCell('@x') === "'@x");
t('CSV में comma/quote सुरक्षित', csvCell('a,"b"') === '"a,""b"""');
t('CSV में Excel हेतु BOM', toCsv([['a']]).startsWith('﻿'));
const sample = [
  { ref_no: 1, expense_date: '2026-11-01', item: 'सीमेंट, 50 बोरी', category: 'निर्माण सामग्री', amount: 21000.25, payer: 'गगन आचारी', payment_method: 'UPI', status: 'active', created_by_name: 'x', created_at: 't', updated_at: 't', version: 2, id: 'a' },
  { ref_no: 2, expense_date: '2026-11-02', item: '"मजदूरी"', category: 'मजदूरी', amount: 2400, payer: '=साइट कैश', payment_method: 'नकद', status: 'cancelled', cancel_reason: 'दोहरी', created_by_name: 'x', created_at: 't', updated_at: 't', version: 3, id: 'b' },
  { ref_no: 3, expense_date: '2026-10-05', item: 'बिजली', category: 'बिजली / पानी', amount: 1234.56, payer: 'अमरनाथ पाण्डेय', payment_method: 'बैंक ट्रांसफर', status: 'active', created_by_name: 'x', created_at: 't', updated_at: 't', version: 1, id: 'c' },
  { ref_no: 4, expense_date: '2026-10-20', item: 'रजिस्ट्री', category: 'कानूनी / दस्तावेज़', amount: 0.01, payer: 'आलोक रंजन मिश्र', payment_method: 'UPI', status: 'active', created_by_name: 'x', created_at: 't', updated_at: 't', version: 1, id: 'd' },
];
const csv = expensesCsv(sample);
t('CSV से सक्रिय कुल वापस पढ़ा = ₹22,234.82 (रद्द बाहर)', csvActiveTotalPaise(csv) === 2223482n, String(csvActiveTotalPaise(csv)));
t('CSV में रद्द पंक्ति और कारण मौजूद', csv.includes('रद्द') && csv.includes('दोहरी'));
t('CSV में राशि दो दशमलव में', csv.includes(',2400.00,') && csv.includes(',0.01,'));
console.log(`\nकुल ${pass + fail} : PASS ${pass} / FAIL ${fail}`);
process.exit(fail ? 1 : 0);
