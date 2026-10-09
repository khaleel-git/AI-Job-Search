"""Start the web app: ``python -m webapp`` (from the Google-Map folder)."""
import argparse
import webbrowser

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="MapLeads web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not args.no_browser:
        webbrowser.open(f"http://{args.host}:{args.port}")
    uvicorn.run("webapp.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
