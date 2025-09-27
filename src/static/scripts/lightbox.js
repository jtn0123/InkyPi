// Shared Lightbox Module
// Provides a consistent fullscreen image preview with:
// - Click to open
// - Esc or outside click to close
// - Double-click on the preview image to toggle native sizing
(function(){
  'use strict';

  const MODAL_ID = 'imagePreviewModal';
  const IMG_ID = 'imagePreviewImg';
  let escHandlerAttached = false;

  function ensureModal(){
    let modal = document.getElementById(MODAL_ID);
    if (!modal){
      modal = document.createElement('div');
      modal.id = MODAL_ID;
      modal.className = 'modal image-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.style.display = 'none';
      const content = document.createElement('div');
      content.className = 'modal-content';
      const close = document.createElement('span');
      close.className = 'close-button';
      close.setAttribute('aria-label', 'Close');
      close.textContent = '×';
      close.addEventListener('click', closeLightbox);
      const img = document.createElement('img');
      img.id = IMG_ID;
      img.alt = 'Large preview';
      img.style.maxWidth = '92vw';
      img.style.maxHeight = '85vh';
      img.style.display = 'block';
      img.style.margin = '0 auto';
      // Double-click toggles native sizing
      img.addEventListener('dblclick', toggleNativeSizing);
      content.appendChild(close);
      content.appendChild(img);
      modal.appendChild(content);
      document.body.appendChild(modal);
    } else {
      // ensure dblclick handler present
      const img = document.getElementById(IMG_ID);
      if (img && !img._dblInit){
        img.addEventListener('dblclick', toggleNativeSizing);
        img._dblInit = true;
      }
    }
    return modal;
  }

  function openLightbox(url, alt){
    const modal = ensureModal();
    const img = document.getElementById(IMG_ID);
    if (!modal || !img) return;
    img.src = url;
    img.alt = alt || 'Preview';
    // Reset any native toggle state
    img.style.maxWidth = '92vw';
    img.style.maxHeight = '85vh';
    img.style.width = '';
    img.style.height = '';
    modal.style.display = 'block';
    trapEsc();
  }

  function closeLightbox(){
    const modal = document.getElementById(MODAL_ID);
    if (modal) modal.style.display = 'none';
  }

  function toggleNativeSizing(e){
    const img = e?.currentTarget || document.getElementById(IMG_ID);
    if (!img) return;
    const isNative = img.getAttribute('data-native') === '1';
    if (isNative){
      img.removeAttribute('data-native');
      img.style.maxWidth = '92vw';
      img.style.maxHeight = '85vh';
      img.style.width = '';
      img.style.height = '';
      img.style.cursor = 'zoom-in';
    } else {
      img.setAttribute('data-native', '1');
      img.style.maxWidth = 'none';
      img.style.maxHeight = 'none';
      img.style.width = 'auto';
      img.style.height = 'auto';
      img.style.cursor = 'zoom-out';
    }
  }

  function trapEsc(){
    if (escHandlerAttached) return;
    const esc = function(e){ if (e.key === 'Escape') { closeLightbox(); } };
    document.addEventListener('keydown', esc, { once: true });
    escHandlerAttached = true;
    setTimeout(() => { escHandlerAttached = false; }, 1000);
  }

  // Outside click closes the modal
  window.addEventListener('click', function(ev){
    const modal = document.getElementById(MODAL_ID);
    if (modal && ev.target === modal) { closeLightbox(); }
  });

  function bind(selector, options){
    const els = document.querySelectorAll(selector);
    els.forEach(el => {
      const handler = (e) => {
        // Respect modifiers
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        const url = (options && typeof options.getUrl === 'function') ? options.getUrl(el) : (el.getAttribute('href') || el.src);
        const alt = (options && typeof options.getAlt === 'function') ? options.getAlt(el) : (el.getAttribute('aria-label') || el.getAttribute('alt') || 'Preview');
        if (url) openLightbox(url, alt);
      };
      el.addEventListener('click', handler);
      if (el.tagName === 'DIV' || el.getAttribute('role') === 'button'){
        el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(e); } });
      }
    });
  }

  // Expose API
  window.Lightbox = {
    open: openLightbox,
    close: closeLightbox,
    bind
  };
})();


