"""Backward-compatible Streamlit entrypoint for the unified Synthex application.

The researcher-facing product now lives in ``platform_app.py``. Keeping this file means
older launch commands continue to open the same current Synthex workspace instead of a
separate/versioned gas-sensing interface.
"""

from platform_app import *  # noqa: F401,F403
