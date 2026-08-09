"""Start Sayso: the push-to-talk daemon plus the dashboard.

    python run.py                    start it
    python run.py --no-browser       start without opening the dashboard
    python run.py --install-autostart   start with Windows from now on
    python run.py --remove-autostart    stop doing that
"""

import sys
import threading
import webbrowser

from sayso import autostart
from sayso.config import settings
from sayso.daemon import daemon
from sayso.web import app

BANNER = r"""
   ___
  / __| __ _ _  _ ___ ___
  \__ \/ _` | || (_-</ _ \    offline voice control
  |___/\__,_|\_, /__/\___/
             |__/
"""


def main():
    if "--install-autostart" in sys.argv:
        ok, detail = autostart.install()
        print(BANNER)
        print(f"  {'Starts with Windows now:' if ok else 'Could not set that up:'} {detail}\n")
        return 0 if ok else 1

    if "--remove-autostart" in sys.argv:
        ok, detail = autostart.remove()
        print(BANNER)
        print(f"  {'No longer starts with Windows:' if ok else 'Nothing to remove:'} {detail}\n")
        return 0

    print(BANNER)
    print(f"  Hold {settings.hotkey_label} anywhere to talk. Esc while holding cancels.")
    if autostart.is_installed():
        print("  Starts with Windows.")
    print(f"  Model: {settings.model_size}  (first run downloads it once, then works offline)")
    print(f"  Dashboard: http://127.0.0.1:{settings.web_port}")
    print("  Ctrl+C to quit.\n")

    daemon.start()

    if settings.open_browser_on_start and "--no-browser" not in sys.argv:
        threading.Timer(
            1.5, lambda: webbrowser.open(f"http://127.0.0.1:{settings.web_port}")
        ).start()

    try:
        app.run(
            host="127.0.0.1",
            port=settings.web_port,
            debug=False,
            threaded=True,
            use_reloader=False,
        )
    except KeyboardInterrupt:
        pass
    finally:
        daemon.hotkey.stop()
        print("\n  Sayso stopped.")


if __name__ == "__main__":
    sys.exit(main())
