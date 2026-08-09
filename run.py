"""Start Sayso: the push-to-talk daemon plus the dashboard.

    python run.py
"""

import sys
import threading
import webbrowser

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
    print(BANNER)
    print(f"  Hold {settings.hotkey_label} anywhere to talk.")
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
