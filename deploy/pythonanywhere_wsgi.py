"""Paste this file into the WSGI configuration linked from PythonAnywhere > Web."""
import os
import sys
from pathlib import Path

project = Path.home() / "admin-assist"
sys.path.insert(0, str(project))

# For the EU service, change pythonanywhere.com to eu.pythonanywhere.com.
os.environ["ADMIN_ASSIST_HOST"] = f"{Path.home().name}.pythonanywhere.com"
# Keep the database outside the Git checkout, including when updating the code.
os.environ["ADMIN_ASSIST_DB_PATH"] = str(
    Path.home() / ".local" / "share" / "admin-assist" / "admin-assist.sqlite3"
)

from wsgi import from_environment

application = from_environment()
