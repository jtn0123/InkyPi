(function (global) {
  const ns = (global.InkyPiPlaylist = global.InkyPiPlaylist || {});

  ns.constants = ns.constants || {
    NEXT_IN_REFRESH_MS: 60000,
    THUMB_PREFETCH_MARGIN: "200px",
    PROGRESS_HIDE_DELAY_MS: 2000,
    PLAYLIST_NAME_RE: /^[A-Za-z0-9 _-]+$/,
    PLAYLIST_NAME_ERROR:
      "Playlist name can only contain ASCII letters, numbers, spaces, underscores, and hyphens",
  };

  ns.config = Object.assign({}, global.PLAYLIST_CTX || {}, ns.config || {});
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
    nextInTimer: null,
    pageEnhancementsBound: false,
    playlistRefreshManager: null,
    storedMessageBound: false,
  };

  ns.setConfig = function setConfig(config) {
    ns.config = Object.assign({}, global.PLAYLIST_CTX || {}, config || {});
    return ns.config;
  };

  ns.parseRefreshSettings = function parseRefreshSettings(rawValue) {
    if (!rawValue) return {};
    try {
      return JSON.parse(rawValue);
    } catch (_err) {
      return {};
    }
  };

  ns.buildProgressKey = function buildProgressKey(ctx) {
    try {
      if (ctx && ctx.page === "playlist") {
        const playlist = ctx.playlist || "_";
        const pluginId = ctx.pluginId || "_";
        const instance = ctx.instance || "_";
        return `INKYPI_LAST_PROGRESS:playlist:${playlist}:${pluginId}:${instance}`;
      }
    } catch (_err) {}
    return "INKYPI_LAST_PROGRESS";
  };

  ns.normaliseTimeForInput = function normaliseTimeForInput(value) {
    if (!value) return value;
    if (value === "24:00") return "23:59";
    return value;
  };
})(globalThis);
