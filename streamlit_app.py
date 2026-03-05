# Entry point for Streamlit Community Cloud.
# Cloud expects streamlit_app.py at the repo root by default.
# This file simply re-executes dashboard/app.py so the app URL is clean.

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "dashboard" / "app.py"), run_name="__main__")
