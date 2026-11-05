# InkyPi Home Project Improvements

*Focused recommendations for a home project - prioritizing UI, reliability, and developer experience*

---

## ✅ Completed

- Dark Mode Implementation — Implemented with system preference detection and toggle
  - Toggle in `src/templates/settings.html` (button `#themeToggle`)
  - Theme logic in `src/static/scripts/theme.js`
  - Styles/variables in `src/static/styles/main.css`
- Request Timing & Progress — Implemented
  - Enhanced progress component in `src/static/scripts/enhanced_progress.js`
  - Live Logs viewer and filters in `src/templates/settings.html` via `/api/logs`
  - Optional HTTP latency logging via `INKYPI_HTTP_LOG_LATENCY` in `src/utils/http_utils.py`
- Backup & Restore — Implemented
  - Export/import endpoints and include-keys option in `src/blueprints/settings.py`
  - UI controls under Backup & Restore in `src/templates/settings.html`
- Benchmarking — Implemented
  - Instrumentation in `src/refresh_task.py` and `src/display/display_manager.py`
  - See `docs/benchmarking.md` for details
- Developer Workflow — Implemented
  - Quick dev without hardware, hot reload path in `README.md` and `docs/development.md`
  - Plugin validator `scripts/plugin_validator.py`
- Light Monitoring (Basic) — Implemented
  - Logs API and viewer in Settings; future p50/p95 dashboard remains TODO

## 🎨 UI & User Experience (Top Priority)

### Dark Mode Implementation
Status: Completed
**Goal**: Clean, system-aware dark mode toggle
- Add CSS custom properties for colors in existing stylesheets
- JavaScript toggle with `localStorage` persistence and system preference detection
- Simple toggle button in header/settings
- **Effort**: 2-3 hours | **Risk**: Low

### Better UI Organization  
**Goal**: Cleaner, more intuitive interface without major restructuring
- **Plugin grid improvements**: Better spacing, consistent card sizing
- **Settings organization**: Group related settings with collapsible sections
- **Navigation breadcrumbs**: "Home › Plugin › Settings" for better orientation
- **Quick actions**: Floating action button for "Refresh Now" on main page
- **Responsive tweaks**: Better mobile experience for existing layouts
- **Effort**: 4-6 hours | **Risk**: Low

### Request Timing & Progress
Status: Completed (core)
**Goal**: Transparent request timing and progress (excluding display update)
- **Per-request timing**: Measure request duration with a monotonic clock; exclude e‑ink display update time from metrics
- **Progress bar**: Steps shown in UI – Preparing → Sending → Waiting (device) → Display updating (excluded) → Done
- **Timing display**: Show elapsed time/badge on recent actions/history
- **Logging**: Record durations for later review
- **Effort**: 2-3 hours | **Risk**: Low

### Subtle Polish Enhancements
**Goal**: Professional look without breaking existing functionality
- **Loading states**: Replace basic spinners with skeleton loading for plugin cards
- **Micro-animations**: Smooth transitions for state changes (gated by `prefers-reduced-motion`)
- **Visual feedback**: Better hover states, focus indicators
- **Typography**: Consistent font sizing, improved readability
- **Status indicators**: Clear visual states for plugin health/errors
- **Effort**: 3-4 hours | **Risk**: Low

---

## ⚡ Performance & Reliability

### Smart Caching (Conservative)
**Goal**: Faster page loads without breaking existing functionality
- **Static asset caching**: Proper cache headers for CSS/JS/images
- **Plugin output caching**: Cache successful plugin renders (with TTL)
- **Image optimization**: Compress uploaded images automatically
- **Browser caching**: Leverage browser cache for static assets
- **Effort**: 3-5 hours | **Risk**: Medium (test thoroughly)

### Background Process Reliability
**Goal**: More robust plugin execution
- **Error recovery**: Automatic retry for failed plugin updates
- **Timeout handling**: Graceful handling of slow/hung plugins
- **Memory management**: Basic cleanup for long-running processes
- **Health checks**: Simple status indicators for plugin health
- **Request timing metrics**: Capture per-request durations (excluding display update) and surface in UI/logs
- **Effort**: 4-6 hours | **Risk**: Medium

---

## 💾 Backup & Recovery

### Configuration Backup
Status: Completed
**Goal**: Never lose your setup
- **Auto-backup**: Daily backup of device config and plugin settings to local file (includes API keys by default)
- **Manual export**: Download complete configuration as JSON; "Exclude API keys" checkbox (unchecked by default)
- **Import/restore**: Use Settings › Backup & Restore to upload configuration and restore settings
- **Plugin data backup**: Backup custom plugin configurations and API keys
- **Backup & Restore settings**: Dedicated section in Settings with "Backup" and "Restore" subsections
- **Effort**: 3-4 hours | **Risk**: Low

### Simple Disaster Recovery
**Goal**: Easy recovery from issues
- **Settings reset**: Reset to defaults without losing plugins
- **Plugin isolation**: Disable problematic plugins without system restart
- **Log preservation**: Keep error logs for troubleshooting
- **Effort**: 2-3 hours | **Risk**: Low

---

## 🛠️ Developer Experience & Tools

### Development Workflow
Status: Partially Completed (validator, hot reload/dev UX in place)
**Goal**: Easier development and debugging
- **Live reload**: Auto-refresh browser when templates/CSS change
- **Debug mode**: Detailed error messages and request logging
- **Plugin validation**: Check plugin config before saving
- **Template linting**: Basic HTML/CSS validation
- **Effort**: 4-5 hours | **Risk**: Low

### Documentation & Testing
**Goal**: Better maintainability
- **Inline documentation**: Comment existing complex functions
- **Plugin examples**: Document plugin configuration patterns
- **Basic tests**: Unit tests for core functionality
- **Manual testing checklist**: Standardized testing procedures
- **Effort**: 6-8 hours | **Risk**: Low

---

## 📊 Light Monitoring (Built-in)

### Simple System Health
Status: Partially Completed (logs viewer & filters shipped; dashboard metrics TODO)
**Goal**: Know when things aren't working
- **Plugin status dashboard**: Visual health check for all plugins
- **Error logging**: Centralized error collection and display
- **Resource usage**: Basic memory/disk usage display
- **Update history**: Simple log of successful/failed updates
- **Request duration stats**: p50/p95 timing for recent requests (excluding display update)
- **Effort**: 3-4 hours | **Risk**: Low

---

## 🚀 Implementation Priority

### Phase 1 (Week 1): Quick Wins
1. **UI organization** - Better plugin grid and settings layout
2. (Completed) Dark mode
3. (Completed) Backup & Restore UI
4. (Completed) Request timing & progress UI

### Phase 2 (Week 2): Polish & Reliability  
1. **Subtle UI enhancements** - Loading states, animations
2. **Error recovery** - Plugin timeout/retry logic
3. **Development tools** - Debug mode, live reload

### Phase 3 (Week 3): Optimization
1. **Smart caching** - Static assets and plugin outputs
2. **System health dashboard** - Plugin status overview
3. **Documentation** - Comment and document existing code

---

## ⚠️ What NOT to Do

**Avoid these common pitfalls:**
- Don't rewrite existing working functionality
- Don't add authentication/user management complexity
- Don't change core plugin architecture
- Don't add external dependencies unless absolutely necessary
- Don't implement features that require database changes
- Don't break existing plugin configurations

---

## 🎯 Success Criteria

### UI Goals
- [ ] Dark mode works flawlessly with system detection
- [ ] Plugin grid looks professional on desktop and mobile
- [ ] All existing functionality preserved
- [ ] Loading states feel responsive and modern
- [ ] Request progress bar shows steps and durations (display update excluded)
- [ ] Per-request timing visible in UI/history

### Reliability Goals  
- [ ] Backup/restore works; API keys included by default with opt-out checkbox
- [ ] Failed plugins don't crash the system
- [ ] Page loads feel fast (under 2 seconds)
- [ ] Error messages are helpful, not cryptic
- [ ] Per-request durations recorded (p50/p95) excluding display update

### Developer Goals
- [ ] Changes can be developed with live reload
- [ ] Code is documented for future maintenance
- [ ] Common issues have clear troubleshooting steps
- [ ] Structured logs capture request durations; log rotation limits applied
- [ ] "Backup & Restore" settings section implemented

**Total Estimated Effort**: 25-35 hours across 3 weeks
**Risk Level**: Low to Medium (mostly additive changes)
