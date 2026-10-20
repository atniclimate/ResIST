"""Preview the static site while editing it: serves pages/ live, with the database from the last build_pages.py run.

Usage:  python scripts/serve_pages.py [port]      (binds 127.0.0.1 only; default port 8765)
"""
import functools
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.storage.database import DATA_DIR  # noqa: E402

BUILT = DATA_DIR / "exchange" / "pages"
FROM_BUILD = {"/resolutions.db", "/build.json", "/capabilities.json"}  # corpus-derived, so they exist only in the pool


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".woff2": "font/woff2"}

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        return str(BUILT / clean.lstrip("/")) if clean in FROM_BUILD else super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


if __name__ == "__main__":
    if not (BUILT / "resolutions.db").exists():
        sys.exit(f"no built database in {BUILT}; run scripts/build_pages.py first")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=str(ROOT / "pages")))
    print(f"http://127.0.0.1:{port}/", flush=True)
    server.serve_forever()
