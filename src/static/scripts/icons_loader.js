(function(){
  function hasPhosphor(){
    try {
      var test = document.createElement('i');
      test.className = 'ph ph-gear-six ph-thin';
      test.style.position = 'absolute';
      test.style.left = '-9999px';
      document.body.appendChild(test);
      var style = window.getComputedStyle(test, '::before');
      var content = style && style.getPropertyValue('content');
      document.body.removeChild(test);
      return content && content !== 'none' && content !== 'normal' && content !== '""';
    } catch (e) { return false; }
  }
  function injectStylesheet(href){
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
    return link;
  }
  function ensureIcons(){
    if (hasPhosphor()) return;
    // Try jsDelivr fallback
    injectStylesheet('https://cdn.jsdelivr.net/npm/@phosphor-icons/web@2.0.3/src/style.css');
    // Re-check after a tick
    setTimeout(function(){
      if (hasPhosphor()) return;
      // Final attempt: legacy package path
      injectStylesheet('https://unpkg.com/phosphor-icons@1.4.2/src/css/phosphor.css');
    }, 300);
  }
  if (document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', ensureIcons);
  } else {
    ensureIcons();
  }
})();


