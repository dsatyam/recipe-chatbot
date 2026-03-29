"""
The `app` package groups all Python modules for this service.

Why it exists:
  - Running `uvicorn app.main:app` tells Python to import the submodule `main`
    inside the package `app` (see `app/main.py`).
  - Other modules use package-relative imports like `from app.config import ...`.

You do not need to import this file directly; the docstring is here to teach the layout.
"""
