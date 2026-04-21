(function () {
    'use strict';

    var STORAGE_KEY = 'inkypi_tweaks_v1';
    var DEFAULT_AESTHETIC = 'console';
    var DEFAULT_DENSITY = 'balanced';
    var DEFAULT_ACCENT = 170;
    var MIN_ACCENT = 0;
    var MAX_ACCENT = 360;

    function load() {
        try {
            var raw = window.localStorage && window.localStorage.getItem(STORAGE_KEY);
            if (!raw) return {};
            var parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch (e) {
            return {};
        }
    }

    function save(state) {
        try {
            window.localStorage && window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch (e) { /* no-op */ }
    }

    function applyAesthetic(aesthetic) {
        var root = document.documentElement;
        if (!aesthetic || aesthetic === 'console') {
            root.removeAttribute('data-aesthetic');
        } else {
            root.setAttribute('data-aesthetic', aesthetic);
        }
    }

    function applyDensity(density) {
        var shell = document.querySelector('.shell');
        if (!shell) return;
        shell.classList.remove('density-compact', 'density-balanced', 'density-cozy');
        if (density && density !== 'balanced') {
            shell.classList.add('density-' + density);
        }
    }

    function applyAccent(hue) {
        var h = parseInt(hue, 10);
        if (isNaN(h)) return;
        h = Math.max(MIN_ACCENT, Math.min(MAX_ACCENT, h));
        var root = document.documentElement;
        // Override the default --accent hue while preserving lightness/chroma from tokens
        var isDark = root.getAttribute('data-theme') !== 'light';
        var l = isDark ? '68%' : '56%';
        var c = '0.08';
        root.style.setProperty('--accent', 'oklch(' + l + ' ' + c + ' ' + h + ')');
        root.style.setProperty('--accent-hover', 'oklch(' + (isDark ? '74%' : '48%') + ' 0.09 ' + h + ')');
    }

    // Trim trailing slash characters without using a regex. Sonar S5852
    // flags `/\/+$/` as potentially ReDoS-vulnerable (false positive, but
    // cheaper to sidestep than to waive per-PR), and this helper is also
    // easier to read than the regex it replaces.
    function trimTrailingSlashes(s) {
        var end = s.length;
        while (end > 0 && s.charCodeAt(end - 1) === 47 /* '/' */) {
            end--;
        }
        return end === s.length ? s : s.slice(0, end);
    }

    function highlightActiveNav() {
        var items = document.querySelectorAll('.shell-sidebar .nav-item');
        if (!items.length) return;
        // Normalise by trimming a trailing slash so "/plugins" and "/plugins/"
        // compare equal. Require an exact match or a "/" segment boundary
        // before treating a longer href as active; a bare prefix check would
        // light up "/plugins" when navigating to a sibling route like
        // "/plugins-library".
        var path = trimTrailingSlashes(window.location.pathname || '/') || '/';
        var best = null;
        var bestLen = -1;
        items.forEach(function (a) {
            var href = a.getAttribute('href') || '';
            if (!href || href === '#') return;
            var hrefPath = trimTrailingSlashes(
                new URL(href, window.location.origin).pathname
            ) || '/';
            if (
                path === hrefPath
                || (hrefPath !== '/' && path.indexOf(hrefPath + '/') === 0)
            ) {
                if (hrefPath.length > bestLen) {
                    best = a;
                    bestLen = hrefPath.length;
                }
            }
        });
        items.forEach(function (a) { a.classList.remove('active'); a.removeAttribute('aria-current'); });
        if (best) {
            best.classList.add('active');
            best.setAttribute('aria-current', 'page');
        } else {
            // Fallback: root path → first nav-item (Dashboard)
            if (path === '/' && items[0]) {
                items[0].classList.add('active');
                items[0].setAttribute('aria-current', 'page');
            }
        }
    }

    function init() {
        highlightActiveNav();

        var state = load();
        var aesthetic = state.aesthetic || DEFAULT_AESTHETIC;
        var density = state.density || DEFAULT_DENSITY;
        var accent = typeof state.accent === 'number' ? state.accent : DEFAULT_ACCENT;

        applyAesthetic(aesthetic);
        applyDensity(density);
        if (typeof state.accent === 'number') applyAccent(accent);

        var fab = document.getElementById('tweaksFab');
        var panel = document.getElementById('tweaksPanel');
        if (!fab || !panel) return;

        function setPanelOpen(open) {
            panel.setAttribute('data-open', open ? 'true' : 'false');
            fab.setAttribute('aria-expanded', open ? 'true' : 'false');
        }

        fab.addEventListener('click', function () {
            var isOpen = panel.getAttribute('data-open') === 'true';
            setPanelOpen(!isOpen);
        });

        document.addEventListener('click', function (e) {
            if (panel.getAttribute('data-open') !== 'true') return;
            if (panel.contains(e.target) || fab.contains(e.target)) return;
            setPanelOpen(false);
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && panel.getAttribute('data-open') === 'true') {
                setPanelOpen(false);
                fab.focus();
            }
        });

        var closeBtn = panel.querySelector('.tweaks-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function () { setPanelOpen(false); });
        }

        // Aesthetic buttons
        var aestheticButtons = panel.querySelectorAll('.aesthetic-option');
        function syncAestheticActive(val) {
            aestheticButtons.forEach(function (btn) {
                btn.classList.toggle('active', btn.getAttribute('data-aesthetic') === val);
                btn.setAttribute('aria-pressed', btn.getAttribute('data-aesthetic') === val ? 'true' : 'false');
            });
        }
        syncAestheticActive(aesthetic);
        aestheticButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var val = btn.getAttribute('data-aesthetic') || DEFAULT_AESTHETIC;
                applyAesthetic(val);
                var s = load();
                s.aesthetic = val;
                save(s);
                syncAestheticActive(val);
            });
        });

        // Density buttons
        var densityButtons = panel.querySelectorAll('.density-option');
        function syncDensityActive(val) {
            densityButtons.forEach(function (btn) {
                btn.classList.toggle('active', btn.getAttribute('data-density') === val);
                btn.setAttribute('aria-pressed', btn.getAttribute('data-density') === val ? 'true' : 'false');
            });
        }
        syncDensityActive(density);
        densityButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                var val = btn.getAttribute('data-density') || DEFAULT_DENSITY;
                applyDensity(val);
                var s = load();
                s.density = val;
                save(s);
                syncDensityActive(val);
            });
        });

        // Accent slider
        var accentSlider = panel.querySelector('#accentHueSlider');
        var accentValue = panel.querySelector('#accentHueValue');
        if (accentSlider) {
            accentSlider.value = String(accent);
            if (accentValue) accentValue.textContent = accent + '°';
            accentSlider.addEventListener('input', function () {
                var v = parseInt(accentSlider.value, 10);
                if (isNaN(v)) return;
                applyAccent(v);
                if (accentValue) accentValue.textContent = v + '°';
                var s = load();
                s.accent = v;
                save(s);
            });
        }

        var resetBtn = panel.querySelector('#tweaksReset');
        if (resetBtn) {
            resetBtn.addEventListener('click', function () {
                save({});
                applyAesthetic(DEFAULT_AESTHETIC);
                applyDensity(DEFAULT_DENSITY);
                document.documentElement.style.removeProperty('--accent');
                document.documentElement.style.removeProperty('--accent-hover');
                syncAestheticActive(DEFAULT_AESTHETIC);
                syncDensityActive(DEFAULT_DENSITY);
                if (accentSlider) accentSlider.value = String(DEFAULT_ACCENT);
                if (accentValue) accentValue.textContent = DEFAULT_ACCENT + '°';
            });
        }
    }

    // Apply persisted settings as early as possible to prevent FOUC
    function earlyApply() {
        try {
            var raw = window.localStorage && window.localStorage.getItem(STORAGE_KEY);
            if (!raw) return;
            var state = JSON.parse(raw);
            if (!state) return;
            if (state.aesthetic) applyAesthetic(state.aesthetic);
            if (typeof state.accent === 'number') applyAccent(state.accent);
        } catch (e) { /* no-op */ }
    }
    earlyApply();

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
