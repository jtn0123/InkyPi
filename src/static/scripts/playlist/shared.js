(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

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
    PROGRESS_HIDE_DELAY_MS: 2000,
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
    lastModalTrigger: null,
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

  ns.buildProgressKey = function buildProgressKey(ctx) {
    if (ctx?.page === "playlist") {
      const playlist = ctx.playlist || "_";
      const pluginId = ctx.pluginId || "_";
      const instance = ctx.instance || "_";
      return `INKYPI_LAST_PROGRESS:playlist:${playlist}:${pluginId}:${instance}`;
    }
    return "INKYPI_LAST_PROGRESS";
  };

  ns.normaliseTimeForInput = function normaliseTimeForInput(value) {
    if (!value) return value;
    if (value === "24:00") return "23:59";
    return value;
  };
})(globalThis);
