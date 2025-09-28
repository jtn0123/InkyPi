# AI Image Plugin Import Failure

## Problem Summary
- Launching the web UI via `scripts/web_only.sh` raises `ModuleNotFoundError: No module named 'src'` when loading `plugins.ai_image.ai_image`.
- The shell helpers (`scripts/venv.sh`, `scripts/dev.sh`, `scripts/web_only.sh`) only append `src/` to `PYTHONPATH`, so namespace imports like `from src.utils.app_utils import ...` cannot resolve when the interpreter starts from within `src/`.
- Tests work because `tests/conftest.py` injects both the repo root and `src/` onto `sys.path`.

## Constraints & Considerations
- Maintain compatibility with existing tests and runtime scripts.
- Avoid regressing other plugins or tooling that rely on `PYTHONPATH` being set.
- Prefer a comprehensive fix so modules can safely use either `utils.*` or `src.utils.*` imports.
- Follow user instructions: incremental changes with documentation, automated tests after each checkpoint.

## Proposed Sub-Tasks
1. Audit existing repository scripts to understand how `PYTHONPATH` is constructed (`scripts/venv.sh`, `scripts/dev.sh`, `scripts/web_only.sh`).
2. Update environment setup so both the repository root and `src/` directory are included in `PYTHONPATH` consistently.
3. Verify no other modules rely on the previous `PYTHONPATH` value; adjust documentation or comments where necessary.
4. Run targeted automated tests (at minimum, plugin-related unit tests) to confirm imports work in test harnesses.
5. Re-run `scripts/web_only.sh` or equivalent smoke test to ensure the server starts without import errors.
6. Document results and summarize follow-up considerations.


