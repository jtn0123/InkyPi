// Shared Lightbox Module
// Provides a consistent fullscreen image preview with:
// - Click to open
// - Esc or outside click to close
// - Double-click on the preview image to toggle native sizing
// - Focus trap for accessibility
// - Loading state with spinner
(function(){
  'use strict';

  const MODAL_ID = 'imagePreviewModal';
  const IMG_ID = 'imagePreviewImg';
  const VISIBLE_CLASS = 'lightbox-img-visible';
  let triggerElement = null;

  function showImage(img) {
    img.classList.add(VISIBLE_CLASS);
  }

  function hideImage(img) {
    img.classList.remove(VISIBLE_CLASS);
  }

  function bindImageLoadHandlers(img, content) {
    img.addEventListener('load', function() {
      const l = content.querySelector('.lightbox-loading');
      const e = content.querySelector('.lightbox-error');
      if (l) l.style.display = 'none';
      if (e) e.style.display = 'none';
      showImage(img);
    });
    img.addEventListener('error', function() {
      const l = content.querySelector('.lightbox-loading');
      const e = content.querySelector('.lightbox-error');
      if (l) l.style.display = 'none';
      hideImage(img);
      if (e) e.style.display = 'block';
    });
  }

  function addFocusTrap(modal) {
    modal.addEventListener('keydown', function(e) {
      if (e.key === 'Tab') {
        const focusable = modal.querySelectorAll('button, [tabindex]:not([tabindex="-1"])');
        if (focusable.length === 0) return;
        var first = focusable[0];
        var last = focusable[focusable.length - 1];
        if (e.shiftKey) {
          if (document.activeElement === first) { e.preventDefault(); last.focus(); }
        } else {
          if (document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }
    });
  }

  function ensureModal(){
    let modal = document.getElementById(MODAL_ID);
    if (!modal){
      modal = document.createElement('div');
      modal.id = MODAL_ID;
      modal.className = 'modal image-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-label', 'Image preview');
      modal.style.display = 'none';
      const content = document.createElement('div');
      content.className = 'modal-content';

      const close = document.createElement('button');
      close.className = 'close-button';
      close.type = 'button';
      close.setAttribute('aria-label', 'Close');
      close.innerHTML = '<span class="close-icon"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="currentColor"><path d="M205.66,194.34a8,8,0,0,1-11.32,11.32L128,139.31,61.66,205.66a8,8,0,0,1-11.32-11.32L116.69,128,50.34,61.66A8,8,0,0,1,61.66,50.34L128,116.69l66.34-66.35a8,8,0,0,1,11.32,11.32L139.31,128Z"/></svg></span>';
      close.addEventListener('click', closeLightbox);

      const loader = document.createElement('div');
      loader.className = 'lightbox-loading';
      loader.innerHTML = '<div class="loading-indicator"></div>';

      const errorEl = document.createElement('div');
      errorEl.className = 'lightbox-error';
      errorEl.style.display = 'none';
      errorEl.textContent = 'Failed to load image';

      const img = document.createElement('img');
      img.id = IMG_ID;
      img.className = 'lightbox-preview-image';
      img.alt = 'Large preview';
      img.style.cursor = 'zoom-out';
      // Single click closes lightbox, double-click toggles native sizing
      img.addEventListener('click', closeLightbox);
      img.addEventListener('dblclick', toggleNativeSizing);

      bindImageLoadHandlers(img, content);

      content.appendChild(close);
      content.appendChild(loader);
      content.appendChild(errorEl);
      content.appendChild(img);
      modal.appendChild(content);
      document.body.appendChild(modal);

      addFocusTrap(modal);
    } else {
      const content = modal.querySelector('.modal-content');
      const img = document.getElementById(IMG_ID);
      if (img && !img._lbInit) {
        img.style.cursor = 'zoom-out';
        img.addEventListener('click', closeLightbox);
        img.addEventListener('dblclick', toggleNativeSizing);

        // Inject loading/error elements if missing
        if (!content.querySelector('.lightbox-loading')) {
          const loader = document.createElement('div');
          loader.className = 'lightbox-loading';
          loader.innerHTML = '<div class="loading-indicator"></div>';
          content.insertBefore(loader, img);
        }
        if (!content.querySelector('.lightbox-error')) {
          const errorEl = document.createElement('div');
          errorEl.className = 'lightbox-error';
          errorEl.style.display = 'none';
          errorEl.textContent = 'Failed to load image';
          content.insertBefore(errorEl, img);
        }

        bindImageLoadHandlers(img, content);

        // Upgrade close <span> to <button> if needed
        const closeSpan = content.querySelector('span.close-button');
        if (closeSpan) {
          const closeBtn = document.createElement('button');
          closeBtn.className = closeSpan.className;
          closeBtn.type = 'button';
          closeBtn.setAttribute('aria-label', 'Close');
          closeBtn.innerHTML = closeSpan.innerHTML;
          closeBtn.addEventListener('click', closeLightbox);
          closeSpan.replaceWith(closeBtn);
        }

        addFocusTrap(modal);

        img._lbInit = true;
      }
    }
    return modal;
  }

  function syncModalOpen() {
    var ui = window.InkyPiUI;
    if (ui && ui.syncModalOpenState) ui.syncModalOpenState();
  }

  function openLightbox(url, alt){
    const modal = ensureModal();
    const img = document.getElementById(IMG_ID);
    if (!modal || !img) return;

    triggerElement = document.activeElement;

    // Show loading state
    const loader = modal.querySelector('.lightbox-loading');
    const errorEl = modal.querySelector('.lightbox-error');
    if (loader) loader.style.display = 'flex';
    if (errorEl) errorEl.style.display = 'none';
    hideImage(img);

    img.src = url;
    img.alt = alt || 'Preview';
    // Reset any native toggle state
    img.style.maxWidth = '';
    img.style.maxHeight = '';
    img.style.width = '';
    img.style.height = '';
    img.removeAttribute('data-native');
    img.style.cursor = '';
    modal.removeAttribute('hidden');
    modal.style.display = 'block';
    modal.classList.add('is-open');
    syncModalOpen();

    // Make background inert for accessibility
    Array.from(document.body.children).forEach(function(el) {
      if (el !== modal && el.nodeType === 1) el.inert = true;
    });

    // If already cached, trigger load immediately
    if (img.complete && img.naturalWidth > 0) {
      if (loader) loader.style.display = 'none';
      showImage(img);
    }

    // Focus the close button for keyboard users
    const closeBtn = modal.querySelector('.close-button');
    if (closeBtn) closeBtn.focus();
  }

  function closeLightbox(){
    const modal = document.getElementById(MODAL_ID);
    if (modal) {
      modal.style.display = 'none';
      modal.setAttribute('hidden', '');
      modal.classList.remove('is-open');
    }
    // Remove inert from background
    Array.from(document.body.children).forEach(function(el) {
      if (el.nodeType === 1) el.inert = false;
    });
    syncModalOpen();
    // Restore focus to the element that opened the lightbox
    if (triggerElement && typeof triggerElement.focus === 'function') {
      triggerElement.focus();
      triggerElement = null;
    }
  }

  function toggleNativeSizing(e){
    const img = e?.currentTarget || document.getElementById(IMG_ID);
    if (!img) return;
    const isNative = img.getAttribute('data-native') === '1';
    if (isNative){
      img.removeAttribute('data-native');
      img.style.maxWidth = '';
      img.style.maxHeight = '';
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

  // Persistent Esc handler — checks if modal is open
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      const modal = document.getElementById(MODAL_ID);
      if (modal && modal.style.display !== 'none') {
        closeLightbox();
      }
    }
  });

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
