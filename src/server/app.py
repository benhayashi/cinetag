import hmac
import logging
import os
import secrets
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from src.core.config import load_config, save_config, is_loopback_host
from src.core.paths import get_app_root, get_logs_dir
from src.server.api import router as api_router

# Configure logging with persistent rotating file handler (5MB cap, 3 backups)
log_file = get_logs_dir() / "video_describer.log"
file_handler = RotatingFileHandler(
    str(log_file),
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
console_handler.setLevel(logging.INFO)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
if not any(isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
    root_logger.addHandler(file_handler)
if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in root_logger.handlers):
    root_logger.addHandler(console_handler)

logger = logging.getLogger(__name__)

from src.core.version import __version__

TOKEN_COOKIE = "cinetag_token"
# Hostnames accepted in the Host header while bound to loopback (anti DNS-rebinding).
LOOPBACK_HOST_HEADERS = {"localhost", "127.0.0.1", "::1", "[::1]", "testserver"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def resolve_access_token(bind_host: str) -> str:
    """
    Return the shared token the server must enforce, or "" when none is required.

    A token is required whenever the server is reachable beyond this machine
    (bind host is not loopback). It comes from CINETAG_TOKEN, else the config, else
    it is generated once and persisted so the user can find it in config.json.
    """
    if is_loopback_host(bind_host):
        return os.environ.get("CINETAG_TOKEN", "").strip()
    token = os.environ.get("CINETAG_TOKEN", "").strip()
    if token:
        return token
    cfg = load_config()
    if cfg.access_token:
        return cfg.access_token
    cfg.access_token = secrets.token_urlsafe(24)
    save_config(cfg)
    logger.warning("Generated a new access token for LAN mode (stored in config.json).")
    return cfg.access_token


_boot_cfg = load_config()
BIND_HOST = os.environ.get("CINETAG_BIND_HOST", _boot_cfg.host)

app = FastAPI(
    title="CineTag",
    description="Local-first video understanding, sidecar metadata generator, and safe collection organizer.",
    version=__version__
)

# Security state (tests may override these on app.state)
app.state.access_token = resolve_access_token(BIND_HOST)
app.state.bind_loopback = is_loopback_host(BIND_HOST)
app.state.extra_origins = set(o.rstrip("/") for o in _boot_cfg.cors_allowed_origins)

# Same-origin needs no CORS. Only explicitly configured origins may call cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(app.state.extra_origins),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "Authorization", "X-CineTag-Token"],
)


def _token_from_request(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (
        request.headers.get("x-cinetag-token")
        or request.cookies.get(TOKEN_COOKIE)
        or ""
    )


def _token_ok(supplied: str, expected: str) -> bool:
    return bool(supplied) and hmac.compare_digest(supplied.encode(), expected.encode())


LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>CineTag - Access Token</title>
<style>body{font-family:system-ui;background:#0f172a;color:#e2e8f0;display:grid;place-items:center;height:100vh;margin:0}
form{background:#1e293b;padding:2rem;border-radius:12px;max-width:420px;width:90%}
input{width:100%;padding:.6rem;margin:.75rem 0;border-radius:6px;border:1px solid #475569;background:#0f172a;color:#e2e8f0;box-sizing:border-box}
button{padding:.6rem 1.2rem;border:0;border-radius:6px;background:#3b82f6;color:#fff;cursor:pointer}
small{color:#94a3b8}</style></head><body><form method="get" action="/">
<h2>🔒 CineTag</h2><p>This server is reachable on your network and requires an access token.</p>
<input name="token" type="password" placeholder="Access token" autofocus required>
<button type="submit">Unlock</button>
<p><small>Find it in <code>config.json</code> (<code>access_token</code>) or the server console output.</small></p>
</form></body></html>"""


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    host_header = (urlparse("//" + (request.headers.get("host") or "")).hostname or "").lower()

    # 1. Anti DNS-rebinding: while loopback-only, the Host header must be a loopback name.
    if app.state.bind_loopback and host_header and host_header not in LOOPBACK_HOST_HEADERS:
        return JSONResponse({"detail": "Invalid Host header"}, status_code=421)

    # 2. Origin check for state-changing requests (blocks CSRF incl. simple multipart posts).
    if request.method in UNSAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and origin != "null":
            origin_host = urlparse(origin).netloc.lower()
            same_origin = origin_host == (request.headers.get("host") or "").lower()
            if not same_origin and origin.rstrip("/") not in app.state.extra_origins:
                return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)
        elif origin == "null":
            return JSONResponse({"detail": "Cross-origin request blocked"}, status_code=403)

    # 3. Access token (only enforced when configured / reachable from the network).
    expected = app.state.access_token
    if expected and not path.startswith("/static/") and path != "/health":
        supplied = _token_from_request(request)
        query_token = request.query_params.get("token", "")
        if not _token_ok(supplied, expected):
            if request.method == "GET" and path == "/" and _token_ok(query_token, expected):
                resp = RedirectResponse("/", status_code=303)
                resp.set_cookie(TOKEN_COOKIE, expected, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 30)
                return resp
            if path == "/":
                return HTMLResponse(LOGIN_PAGE, status_code=401)
            return JSONResponse({"detail": "Access token required"}, status_code=401)

    return await call_next(request)


# API Routes
app.include_router(api_router)

# Static Web Assets
web_dir = get_app_root() / "src" / "web"
static_dir = web_dir / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/health")
def health():
    """Unauthenticated liveness probe (used by the Docker HEALTHCHECK). Reveals nothing sensitive."""
    return {"status": "ok", "version": __version__}


@app.get("/")
def serve_index():
    index_file = web_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "CineTag API running. Web interface not found."}
