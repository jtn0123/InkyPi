(function (global) {
  global.InkyPiPlaylist = global.InkyPiPlaylist || {};
  const ns = global.InkyPiPlaylist;

  function initThumbnailPreviewHandlers() {
    document.querySelectorAll(".plugin-thumbnail-container").forEach((box) => {
      if (box.dataset.playlistPreviewBound === "1") return;
      // The thumbnail is a <button>, so Enter and Space open it too. The
      // shared lightbox shows the image the thumbnail already loaded, and
      // hands focus back to the thumbnail when it closes.
      box.addEventListener("click", (event) => {
        const img = event.currentTarget.querySelector("img.plugin-thumbnail");
        const url = img?.getAttribute("src");
        if (url) global.Lightbox?.open(url, img.alt);
      });
      box.dataset.playlistPreviewBound = "1";
    });

    document.querySelectorAll(".plugin-thumbnail").forEach((img) => {
      if (img.dataset.playlistPreviewBound === "1") return;
      img.addEventListener("load", () => {
        const skeleton = img.previousElementSibling;
        if (skeleton) skeleton.style.display = "none";
        img.hidden = false;
      });
      img.addEventListener("error", () => {
        const container = img.closest(".plugin-thumbnail-container");
        if (container) container.hidden = true;
      });
      img.dataset.playlistPreviewBound = "1";
    });
  }

  function initPageEnhancements() {
    if (ns.runtime.pageEnhancementsBound) return;
    initThumbnailPreviewHandlers();
    ns.runtime.pageEnhancementsBound = true;
  }

  Object.assign(ns, {
    initPageEnhancements,
    initThumbnailPreviewHandlers,
  });
})(globalThis);
