"""lib — package marker.

Adds `lib` as a regular Python package so `from lib.X import Y` resolves
the sibling `lib/*.py` modules without requiring `sys.path.insert(0, repo)`
at every call site.

Before this marker:
- `from lib.ci_setup import install_ci_config` raised
  `ModuleNotFoundError: No module named 'atomic'` because `atomic.py`
  lives at `lib/atomic.py` (not on sys.path) and `ci_setup.py:41` does
  a bare `from atomic import atomic_write_json`.
- `lib/ci_doctor.py` worked around this with a 13-line
  `importlib.util.spec_from_file_location` shim that no other module
  needs.

After this marker, both the documented import path and the shim's job
are solved by the package boundary itself.
"""
