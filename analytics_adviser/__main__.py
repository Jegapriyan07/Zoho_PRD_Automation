"""Start the Analytics Adviser web UI: py -m analytics_adviser [--port 8765]."""
import argparse
import threading
import webbrowser

from analytics_adviser.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Analytics Adviser local web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Analytics Adviser running at {url} (Ctrl+C to stop)")
    create_app().run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
