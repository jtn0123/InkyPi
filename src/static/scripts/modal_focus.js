// Shared keyboard and background focus lifecycle for custom dialogs.
(function () {
  const stack = [];
  const inertBefore = new Map();
  const selector = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  const top = () => stack.at(-1);
  function focusables(modal) {
    return Array.from(modal.querySelectorAll(selector)).filter(node =>
      node.getClientRects().length && !node.closest('[hidden], [inert]'));
  }
  function restoreBackground() {
    inertBefore.forEach((value, node) => { node.inert = value; });
    inertBefore.clear();
  }
  function protectBackground() {
    restoreBackground();
    const entry = top();
    if (!entry) return;
    let branch = entry.modal;
    while (branch.parentElement) {
      for (const sibling of branch.parentElement.children) {
        if (sibling !== branch && sibling instanceof HTMLElement) {
          inertBefore.set(sibling, sibling.inert);
          sibling.inert = true;
        }
      }
      branch = branch.parentElement;
      if (branch === document.body) break;
    }
  }
  function focusFirst(entry) {
    const target = focusables(entry.modal)[0] || entry.modal;
    if (target === entry.modal && !target.hasAttribute('tabindex')) target.tabIndex = -1;
    target.focus();
  }
  function activate(modal, trigger, close) {
    if (!modal || stack.some(entry => entry.modal === modal)) return;
    const entry = {modal, trigger: trigger || document.activeElement, close};
    stack.push(entry);
    protectBackground();
    focusFirst(entry);
  }
  function deactivate(modal) {
    const index = stack.findIndex(entry => entry.modal === modal);
    if (index < 0) return;
    const wasTop = index === stack.length - 1;
    const [entry] = stack.splice(index, 1);
    protectBackground();
    if (!wasTop) return;
    if (entry.trigger?.isConnected && !entry.trigger.closest('[inert], [hidden]')) entry.trigger.focus();
    else if (top()) focusFirst(top());
  }
  document.addEventListener('keydown', event => {
    const entry = top();
    if (!entry) return;
    if (event.key === 'Escape' && entry.close) {
      event.preventDefault();
      event.stopImmediatePropagation();
      entry.close();
    } else if (event.key === 'Tab') {
      const nodes = focusables(entry.modal);
      const first = nodes[0] || entry.modal;
      const last = nodes.at(-1) || entry.modal;
      if (!entry.modal.contains(document.activeElement) ||
          (event.shiftKey && document.activeElement === first) ||
          (!event.shiftKey && document.activeElement === last)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    }
  }, true);
  document.addEventListener('focusin', event => {
    const entry = top();
    if (entry && !entry.modal.contains(event.target)) focusFirst(entry);
  });
  globalThis.InkyPiModalFocus = {activate, deactivate};
})();
