// Simple dark mode toggler with system preference fallback
(function(){
  const STORAGE_KEY = 'theme';

  function getStoredTheme(){
    try { return localStorage.getItem(STORAGE_KEY); } catch(e) { return null; }
  }
  function storeTheme(t){
    try { localStorage.setItem(STORAGE_KEY, t); } catch(e) {}
  }

  function getPreferredTheme(){
    const s = getStoredTheme();
    if (s === 'light' || s === 'dark') return s;
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) return 'dark';
    return 'light';
  }

  function applyTheme(theme){
    const html = document.documentElement;
    html.setAttribute('data-theme', theme);
    const btn = document.getElementById('themeToggle');
    if (btn){
      btn.textContent = theme === 'dark' ? 'Light Mode' : 'Dark Mode';
    }
  }

  function init(){
    const theme = getPreferredTheme();
    applyTheme(theme);
    const btn = document.getElementById('themeToggle');
    if (btn){
      btn.addEventListener('click', function(){
        const current = document.documentElement.getAttribute('data-theme') || 'light';
        const next = current === 'dark' ? 'light' : 'dark';
        storeTheme(next);
        applyTheme(next);
      });
    }
    // Update when system preference changes (if not explicitly stored)
    try {
      const mq = window.matchMedia('(prefers-color-scheme: dark)');
      mq.addEventListener('change', function(){
        if (!getStoredTheme()) applyTheme(getPreferredTheme());
      });
    } catch (e) {}
  }

  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();


