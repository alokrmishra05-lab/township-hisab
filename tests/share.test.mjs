import assert from 'node:assert';
import { hisabText, entryText, waUrl } from '../site/js/share.js';
const t = hisabText({ asOf:'2026-11-22', total:52688175500n, invest:1n*100n, spend:0n, partners:[{name:'आलोक',diff:244408200n},{name:'*अ_मर*',diff:-1n},{name:'ग',diff:0n}], other:{total:500n,entries:2}, link:'L' });
assert.ok(t.includes('22-11-2026 तक')); assert.ok(t.includes('₹52,68,81,755')); assert.ok(t.includes('आलोक: +₹24,44,082 (लेना है)'));
assert.ok(t.includes('अमर: −₹0.01 (देना है)')); assert.ok(t.includes('ग: बराबर')); assert.ok(t.includes('अन्य भुगतानकर्ता: ₹5 (2 एंट्री)'));
const e = entryText({ref_no:17,expense_date:'2026-11-16',item:'लैंड\n सर्वेयर',amount:'7000.00',payer:'आलोक',payment_method:'UPI',category:'अन्य',status:'active'},0,'');
assert.strictEqual(e, '*खर्च · SK-000017*\n16-11-2026 · लैंड सर्वेयर\n₹7,000 · आलोक · UPI\nश्रेणी: अन्य');
assert.ok(waUrl('a b&c').endsWith('a%20b%26c'));
console.log('share tests OK');
