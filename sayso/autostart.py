"""Start SaySo when Windows starts.

A background app you have to launch by hand every morning is only half a
background app. This writes a shortcut into the user's own Startup folder -
no registry, no admin rights, and you can delete it from Explorer if you would
rather not use the command.

It launches pythonw.exe rather than python.exe so no console window appears.
"""

import os
import sys
from pathlib import Path

from .config import ROOT

STARTUP_DIR = (
    Path(os.environ.get("APPDATA", Path.home()))
    / "Microsoft/Windows/Start Menu/Programs/Startup"
)
SHORTCUT = STARTUP_DIR / "SaySo.lnk"


def _pythonw():
    """The windowless interpreter next to the one running this."""
    windowless = Path(sys.executable).with_name("pythonw.exe")
    return windowless if windowless.exists() else Path(sys.executable)


def is_installed():
    return SHORTCUT.exists()


def install():
    if not STARTUP_DIR.is_dir():
        return False, f"no Startup folder at {STARTUP_DIR}"

    try:
        import win32com.client
    except ImportError:
        return False, "pywin32 is needed to create the shortcut"

    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        link = shell.CreateShortCut(str(SHORTCUT))
        link.Targetpath = str(_pythonw())
        link.Arguments = f'"{ROOT / "run.py"}" --no-browser'
        link.WorkingDirectory = str(ROOT)
        link.Description = "SaySo - offline voice control"
        link.IconLocation = str(ROOT / "extension" / "icons" / "icon128.png")
        link.save()
    except Exception as exc:
        return False, str(exc)

    return True, str(SHORTCUT)


def remove():
    if not SHORTCUT.exists():
        return False, "was not set to start with Windows"
    try:
        SHORTCUT.unlink()
    except OSError as exc:
        return False, str(exc)
    return True, str(SHORTCUT)
