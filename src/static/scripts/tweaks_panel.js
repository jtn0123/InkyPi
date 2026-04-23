(function () {
    'use strict';

    const STORAGE_KEY = 'inkypi_tweaks_v1';
    const DEFAULT_AESTHETIC = 'console';
    const DEFAULT_DENSITY = 'balanced';
    const DEFAULT_ACCENT = 170;
    const MIN_ACCENT = 0;
    const MAX_ACCENT = 360;

    function load() {
        try {
            const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
            if (!raw) return {};
            const parsed = JSON.parse(raw);
            return parsed && typeof parsed === 'object' ? parsed : {};
        } catch {
            // localStorage can throw in private/incognito windows or when
            // quota is exceeded. Fall back to defaults rather than surfacing
            // a blocking error to the user.
            return {};
        }
    }

    function save(state) {
        try {
            globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(state));
        } catch {
            // Intentionally ignore storage failures (quota/private mode) —
            // user-visible tweaks still apply, just won't survive reload.
        }
    }

    function applyAesthetic(aesthetic) {
        const root = document.documentElement;
        if (!aesthetic || aesthetic === 'console') {
            delete root.dataset.aesthetic;
        } else {
            root.dataset.aesthetic = aesthetic;
        }
    }

    function applyDensity(density) {
        const shell = document.querySelector('.shell');
        if (!shell) return;
        shell.classList.remove('density-compact', 'density-balanced', 'density-cozy');
        if (density && density !== 'balanced') {
            shell.classList.add('density-' + density);
        }
    }

    function applyAccent(hue) {
        let h = Number.parseInt(hue, 10);
        if (Number.isNaN(h)) return;
        h = Math.max(MIN_ACCENT, Math.min(MAX_ACCENT, h));
        const root = document.documentElement;
        // Override the default --accent hue while preserving lightness/chroma from tokens
        const isDark = root.dataset.theme !== 'light';
        const l = isDark ? '68%' : '56%';
        const c = '0.08';
        root.style.setProperty('--accent', 'oklch(' + l + ' ' + c + ' ' + h + ')');
        root.style.setProperty('--accent-hover', 'oklch(' + (isDark ? '74%' : '48%') + ' 0.09 ' + h + ')');
    }

    // Trim trailing slash characters without using a regex. Sonar S5852
    // flags `/\/+$/` as potentially ReDoS-vulnerable (false positive, but
    // cheaper to sidestep than to waive per-PR), and this helper is also
    // easier to read than the regex it replaces.
    function trimTrailingSlashes(s) {
        let end = s.length;
        while (end > 0 && s.codePointAt(end - 1) === 47 /* '/' */) {
            end--;
        }
        return end === s.length ? s : s.slice(0, end);
    }

    function highlightActiveNav() {
        const items = document.querySelectorAll('.shell-sidebar .nav-item');
        if (!items.length) return;
        // Normalise by trimming a trailing slash so "/plugins" and "/plugins/"
        // compare equal. Require an exact match or a "/" segment boundary
        // before treating a longer href as active; a bare prefix check would
        // light up "/plugins" when navigating to a sibling route like
        // "/plugins-library".
        const path = trimTrailingSlashes(globalThis.location.pathname || '/') || '/';
        let best = null;
        let bestLen = -1;
        items.forEach(function (a) {
            const href = a.getAttribute('href') || '';
            if (!href || href === '#') return;
            const hrefPath = trimTrailingSlashes(
                new URL(href, globalThis.location.origin).pathname
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
        } else if (path === '/' && items[0]) {
            // Fallback: root path → first nav-item (Dashboard)
            items[0].classList.add('active');
            items[0].setAttribute('aria-current', 'page');
        }
    }

    function init() {
        highlightActiveNav();

        const state = load();
        const aesthetic = state.aesthetic || DEFAULT_AESTHETIC;
        const density = state.density || DEFAULT_DENSITY;
        const accent = typeof state.accent === 'number' ? state.accent : DEFAULT_ACCENT;

        applyAesthetic(aesthetic);
        applyDensity(density);
        if (typeof state.accent === 'number') applyAccent(accent);

        // Selectors scan document-wide so the floating FAB panel in base.html
        // and the Settings > Appearance tab stay in sync (toggling a preset in
        // either location updates the active-class markers in both).
        const aestheticButtons = document.querySelectorAll('.aesthetic-option[data-aesthetic]');
        function syncAestheticActive(val) {
            aestheticButtons.forEach(function (btn) {
                btn.classList.toggle('active', btn.dataset.aesthetic === val);
                btn.setAttribute('aria-pressed', btn.dataset.aesthetic === val ? 'true' : 'false');
            });
        }
        syncAestheticActive(aesthetic);
        aestheticButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                const val = btn.dataset.aesthetic || DEFAULT_AESTHETIC;
                applyAesthetic(val);
                const s = load();
                s.aesthetic = val;
                save(s);
                syncAestheticActive(val);
            });
        });

        // Filter by `[data-density]` so the Reset button (same class,
        // no data-density) isn't treated as a density option.
        const densityButtons = document.querySelectorAll('.density-option[data-density]');
        function syncDensityActive(val) {
            densityButtons.forEach(function (btn) {
                btn.classList.toggle('active', btn.dataset.density === val);
                btn.setAttribute('aria-pressed', btn.dataset.density === val ? 'true' : 'false');
            });
        }
        syncDensityActive(density);
        densityButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                const val = btn.dataset.density || DEFAULT_DENSITY;
                applyDensity(val);
                const s = load();
                s.density = val;
                save(s);
                syncDensityActive(val);
            });
        });

        const accentSliders = document.querySelectorAll('[data-accent-slider]');
        const accentValues = document.querySelectorAll('[data-accent-value]');
        function syncAccent(v) {
            accentSliders.forEach(function (s) { if (s.value !== String(v)) s.value = String(v); });
            accentValues.forEach(function (n) { n.textContent = v + '°'; });
        }
        syncAccent(accent);
        accentSliders.forEach(function (slider) {
            slider.addEventListener('input', function () {
                const v = Number.parseInt(slider.value, 10);
                if (Number.isNaN(v)) return;
                applyAccent(v);
                syncAccent(v);
                const s = load();
                s.accent = v;
                save(s);
            });
        });

        const resetButtons = document.querySelectorAll('[data-tweaks-reset]');
        resetButtons.forEach(function (btn) {
            btn.addEventListener('click', function () {
                save({});
                applyAesthetic(DEFAULT_AESTHETIC);
                applyDensity(DEFAULT_DENSITY);
                document.documentElement.style.removeProperty('--accent');
                document.documentElement.style.removeProperty('--accent-hover');
                syncAestheticActive(DEFAULT_AESTHETIC);
                syncDensityActive(DEFAULT_DENSITY);
                syncAccent(DEFAULT_ACCENT);
            });
        });

        const fab = document.getElementById('tweaksFab');
        const panel = document.getElementById('tweaksPanel');
        if (!fab || !panel) return;

        function setPanelOpen(open) {
            panel.dataset.open = open ? 'true' : 'false';
            fab.setAttribute('aria-expanded', open ? 'true' : 'false');
            // Keep the screen-reader-announced label in sync with the action
            // the next click will perform (CodeRabbit review, PR #570).
            fab.setAttribute(
                'aria-label',
                open ? 'Close appearance tweaks' : 'Open appearance tweaks'
            );
        }

        fab.addEventListener('click', function () {
            const isOpen = panel.dataset.open === 'true';
            setPanelOpen(!isOpen);
        });

        document.addEventListener('click', function (e) {
            if (panel.dataset.open !== 'true') return;
            if (panel.contains(e.target) || fab.contains(e.target)) return;
            setPanelOpen(false);
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && panel.dataset.open === 'true') {
                setPanelOpen(false);
                fab.focus();
            }
        });

        const closeBtn = panel.querySelector('.tweaks-close');
        if (closeBtn) {
            closeBtn.addEventListener('click', function () { setPanelOpen(false); });
        }
    }

    // Apply persisted settings as early as possible to prevent FOUC
    function earlyApply() {
        try {
            const raw = globalThis.localStorage?.getItem(STORAGE_KEY);
            if (!raw) return;
            const state = JSON.parse(raw);
            if (!state) return;
            if (state.aesthetic) applyAesthetic(state.aesthetic);
            if (typeof state.accent === 'number') applyAccent(state.accent);
        } catch {
            // Same rationale as load()/save(): silently fall back when
            // localStorage isn't usable.
        }
    }
    earlyApply();

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
