(function (global) {
  global.InkyPiPlaylist = global.InkyPiPlaylist || {};
  const ns = global.InkyPiPlaylist;

  function mergePlaylistConfig(baseConfig, overrideConfig) {
    const merged = {};
    if (baseConfig && typeof baseConfig === "object") {
      Object.assign(merged, baseConfig);
    }
    if (overrideConfig && typeof overrideConfig === "object") {
      Object.assign(merged, overrideConfig);
    }
    return merged;
  }

  ns.constants = ns.constants || {
    THUMB_PREFETCH_MARGIN: "200px",
    PLAYLIST_NAME_RE: /^[A-Za-z0-9 _-]+$/,
    PLAYLIST_NAME_ERROR:
      "Playlist name can only contain ASCII letters, numbers, spaces, underscores, and hyphens",
  };

  ns.config = mergePlaylistConfig(global.PLAYLIST_CTX, ns.config);
  ns.mobileQuery =
    ns.mobileQuery ||
    (global.matchMedia
      ? global.matchMedia("(max-width: 768px)")
      : { matches: false, addEventListener() {} });
  ns.state = ns.state || {
    expandedPlaylist: null,
    currentEditPlaylist: "",
    currentEditPluginId: "",
    currentEditInstance: "",
  };
  ns.runtime = ns.runtime || {
    actionDelegationBound: false,
    cardsBound: false,
    deviceClockTimer: null,
    formControlsBound: false,
    modalLifecycleBound: false,
    mobileSyncBound: false,
    pageEnhancementsBound: false,
    playlistRefreshManager: null,
    storedMessageBound: false,
  };

  ns.setConfig = function setConfig(config) {
    ns.config = mergePlaylistConfig(global.PLAYLIST_CTX, config);
    return ns.config;
  };

  ns.parseRefreshSettings = function parseRefreshSettings(rawValue) {
    if (!rawValue) return {};
    try {
      return JSON.parse(rawValue);
    } catch (error) {
      console.debug("Failed to parse playlist refresh settings:", error);
      return {};
    }
  };

  ns.normaliseTimeForInput = function normaliseTimeForInput(value) {
    if (!value) return value;
    if (value === "24:00") return "23:59";
    return value;
  };
})(globalThis);
