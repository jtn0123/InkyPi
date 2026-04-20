(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});
  const PUBLIC_METHODS = {
    "applyFieldErrorFromResponse": "applyFieldErrorFromResponse",
    "closeDeviceCycleModal": "closeDeviceCycleModal",
    "closeModal": "closeModal",
    "closeRefreshModal": "closeRefreshModal",
    "closeThumbnailPreview": "closeThumbnailPreview",
    "createPlaylist": "createPlaylist",
    "deletePlaylist": "deletePlaylist",
    "deletePluginInstance": "deletePluginInstance",
    "displayNextInPlaylist": "displayNextInPlaylist",
    "displayPluginInstance": "displayPluginInstance",
    "openCreateModal": "openCreateModal",
    "openDeleteInstanceModal": "openDeleteInstanceModal",
    "openDeletePlaylistModal": "openDeletePlaylistModal",
    "openDeviceCycleModal": "openDeviceCycleModal",
    "openDisplayNextConfirmModal": "openDisplayNextConfirmModal",
    "openEditModal": "openEditModal",
    "openRefreshModal": "openRefreshModal",
    "saveDeviceCycle": "saveDeviceCycle",
    "saveRefreshSettings": "saveRefreshSettings",
    "showLastProgressGlobal": "showLastProgressGlobal",
    "showThumbnailPreview": "showThumbnailPreview",
    "updatePlaylist": "updatePlaylist",
  };

  function exposeGlobals() {
    Object.entries(PUBLIC_METHODS).forEach(([globalName, nsName]) => {
      global[globalName] = ns[nsName];
    });
  }

  const InkyPiPlaylistPage = {
    bootstrap() {
      if (typeof ns.setConfig === "function") {
        ns.setConfig(global.PLAYLIST_CTX || {});
      }
      ns.initReorderControls?.();
      ns.initFormControls?.();
      ns.initActionDelegation?.();
      ns.initModalLifecycle?.();
      ns.initPlaylistCards?.();
      ns.bindStoredMessageHandler?.();
      ns.initPageEnhancements?.();
    },
  };

  function createPlaylistPage() {
    return InkyPiPlaylistPage;
  }

  function init() {
    createPlaylistPage().bootstrap();
  }

  exposeGlobals();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    try {
      init();
    } catch (_err) {}
  }
})(globalThis);
