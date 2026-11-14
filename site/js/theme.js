// सूर्य कुंज | थीम: Auto (फ़ोन की सेटिंग) → Light → Dark। पसंद इसी फ़ोन/ब्राउज़र में याद रहती है।
// <head> में पहले ही लोड होता है ताकि पेज खुलते समय रंग न झपके।
(() => {
  const KEY = 'sk-theme', MODES = ['auto', 'light', 'dark'];
  const LABEL = { auto: '◐ Auto', light: '☀ Light', dark: '☾ Dark' };
  const read = () => { try { const v = localStorage.getItem(KEY); return MODES.includes(v) ? v : 'auto'; } catch { return 'auto'; } };
  const dark = m => m === 'dark' || (m === 'auto' && matchMedia('(prefers-color-scheme: dark)').matches);
  function apply(m) {
    const root = document.documentElement;
    if (m === 'auto') root.removeAttribute('data-theme'); else root.setAttribute('data-theme', m);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = dark(m) ? '#111410' : '#14532d';
    const b = document.getElementById('themeBtn');
    if (b) { b.textContent = LABEL[m]; b.setAttribute('aria-label', `थीम: ${LABEL[m]} — बदलने के लिए दबाएँ`); }
  }
  let mode = read();
  apply(mode);
  matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => { if (mode === 'auto') apply(mode); });
  document.addEventListener('DOMContentLoaded', () => {
    apply(mode);
    const b = document.getElementById('themeBtn');
    if (b) b.addEventListener('click', () => {
      mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
      try { localStorage.setItem(KEY, mode); } catch { /* storage बंद हो तो इसी बार के लिए */ }
      apply(mode);
    });
  });
})();
