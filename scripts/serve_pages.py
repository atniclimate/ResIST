"""Preview the static site while editing it: serves pages/ live, with the database from the last build_pages.py run.

Usage:  python scripts/serve_pages.py [port]      (binds 127.0.0.1 only; default port 8765)
"""
import functools
import io
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.storage.database import DATA_DIR  # noqa: E402
from resist.errors import ArtifactError  # noqa: E402
from resist.web.export_files import current_export  # noqa: E402

BUILT = DATA_DIR / "exchange" / "pages"


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript", ".mjs": "text/javascript",
                      ".wasm": "application/wasm", ".woff2": "font/woff2"}

    def send_head(self):
        clean = self.path.partition("?")[0].partition("#")[0]
        if clean not in ("/resolutions.db", "/build.json"):
            return super().send_head()
        try:
            content = current_export(DATA_DIR, clean[1:])
        except ArtifactError as exc:
            self.send_error(503, str(exc))
            return None
        self.send_response(200)
        self.send_header("Content-Type", self.guess_type(clean))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        return io.BytesIO(content)

    def translate_path(self, path):
        clean = path.split("?", 1)[0].split("#", 1)[0]
        return str(BUILT / "capabilities.json") if clean == "/capabilities.json" else super().translate_path(path)

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
