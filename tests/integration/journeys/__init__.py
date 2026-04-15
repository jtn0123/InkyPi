# pyright: reportMissingImports=false
"""Multi-step user-journey integration tests (JTN-719 epic).

Each module here exercises ONE real user flow end-to-end with step-level
assertions — distinct from the click-sweep (JTN-679/693/698) which only
verifies handlers fire without error.  Journey tests assert the *end state*
of each step (config persisted, history entry present, etc.) so regressions
that leave the app functional-but-wrong are caught.
"""
