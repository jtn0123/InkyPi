/**
 * InkyPi lightweight reactive store.
 *
 * Usage example:
 *   const store = window.InkyPiStore.createStore({ count: 0, name: 'InkyPi' });
 *
 *   // Subscribe to changes on a specific key
 *   const unsub = store.subscribe('count', (newVal, oldVal) => {
 *     console.log('count changed:', oldVal, '->', newVal);
 *   });
 *
 *   // Read whole state or a single key
 *   store.get();           // { count: 0, name: 'InkyPi' }
 *   store.get('count');    // 0
 *
 *   // Update via plain object (merged) or updater function
 *   store.set({ count: 1 });
 *   store.set(prev => ({ count: prev.count + 1 }));
 *
 *   // Unsubscribe when done
 *   unsub();
 */

(function () {
  'use strict';

  /**
   * Create a minimal reactive store.
   *
   * @param {Object} initialState - Plain object representing the initial state.
   * @returns {{ get: Function, set: Function, subscribe: Function }}
   */
  function createStore(initialState) {
    var _state = Object.assign({}, initialState);
    // Map of key -> array of subscriber functions
    var _listeners = {};

    /**
     * Read the whole state or a single key.
     *
     * @param {string} [key] - Optional key to read.
     * @returns {*} Whole state object, or the value for the given key.
     */
    function get(key) {
      if (key === undefined) {
        return Object.assign({}, _state);
      }
      return _state[key];
    }

    /**
     * Update state. Fires subscribers for changed keys only (shallow compare).
     *
     * @param {Object|Function} updater - Plain object to merge, or function (prev) => next.
     */
    function set(updater) {
      var prev = Object.assign({}, _state);
      var patch = typeof updater === 'function' ? updater(prev) : updater;
      var next = Object.assign({}, _state, patch);

      // Collect changed keys before mutating state
      var changed = Object.keys(patch).filter(function (k) {
        return prev[k] !== next[k];
      });

      _state = next;

      // Notify subscribers for each changed key
      changed.forEach(function (k) {
        var fns = _listeners[k] || [];
        fns.forEach(function (fn) {
          try {
            fn(next[k], prev[k]);
          } catch (e) {
            console.warn('InkyPiStore subscriber error for key "' + k + '":', e);
          }
        });
      });
    }

    /**
     * Subscribe to changes on a specific key.
     *
     * @param {string} key - The state key to watch.
     * @param {Function} fn - Callback invoked with (newValue, oldValue).
     * @returns {Function} Unsubscribe function.
     */
    function subscribe(key, fn) {
      if (!_listeners[key]) {
        _listeners[key] = [];
      }
      _listeners[key].push(fn);
      return function unsubscribe() {
        _listeners[key] = (_listeners[key] || []).filter(function (f) {
          return f !== fn;
        });
      };
    }

    return { get: get, set: set, subscribe: subscribe };
  }

  // Expose as a plain script global — the project uses classic script tags, not ES modules.
  if (typeof window !== 'undefined') {
    window.InkyPiStore = { createStore: createStore };
  }
  // Also expose on globalThis for service-worker / test contexts.
  if (typeof globalThis !== 'undefined') {
    globalThis.InkyPiStore = { createStore: createStore };
  }
})();
