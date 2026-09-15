"""FastAPI backend for JIRA Cloud UI.

Wraps testJIRACloud.JiraClient so the frontend never talks to
Atlassian directly (avoids browser CORS issues).

Run:
    venv/bin/python for_JIRA/jira_server.py
    # serves UI + API on http://localhost:8099
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Allow `import testJIRACloud` when run as `python for_JIRA/jira_server.py`
# and when run as a module.
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from testJIRACloud import (  # noqa: E402
    AUTHORIZATION_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    REDIRECT_URI,
    RESOURCES_URL,
    SCOPES,
    TOKEN_URL,
    JiraClient,
    get_jira_site,
    load_token,
    save_token,
)
import testJIRACloud as _jira_mod  # noqa: E402

# Pin the token file to this directory so load/save work no matter
# where the server process is launched from.
_jira_mod.TOKEN_FILE = str(BASE_DIR / "jira_token.json")

# ---------------------------------------------------------------------------
# Redirect URIs. Port 8000 is the OAuth callback (matches testJIRACloud.py
# and the Atlassian Developer Console configuration — no console change needed).
# The API runs on 8099, so a tiny background listener on port 8000 catches
# the Atlassian redirect and forwards it to the 8099 /callback handler.
# Token exchange tries :8000 first, then :8099 as a fallback.
# ---------------------------------------------------------------------------
PRIMARY_REDIRECT_URI = "http://localhost:8000/callback"
ALT_REDIRECT_URI = "http://localhost:8099/callback"
WEB_REDIRECT_URI = PRIMARY_REDIRECT_URI  # alias: default callback is :8000
LEGACY_REDIRECT_URI = REDIRECT_URI  # http://localhost:8000/callback (same)

app = FastAPI(
    title="JIRA Cloud Client",
    description="FastAPI backend wrapping testJIRACloud.JiraClient",
    version="1.0.0",
)

FRONTEND_DIR = BASE_DIR / "frontend"

# ---------------------------------------------------------------------------
# In-memory connection state (mirrors jira_token.json + discovered site)
# ---------------------------------------------------------------------------
state: dict[str, Any] = {
    "access_token": None,
    "refresh_token": None,
    "cloud_id": None,
    "site_name": None,
    "site_url": None,
}


def _load_initial_state() -> None:
    """Pre-load token + try to resolve site from stored token."""
    token_data = None
    # testJIRACloud.load_token() uses a relative TOKEN_FILE path, so it
    # depends on CWD. Try it first, then fall back to for_JIRA/jira_token.json
    # explicitly so the server works regardless of where it is launched from.
    try:
        token_data = load_token()
    except Exception:
        token_data = None
    if not token_data:
        candidate = BASE_DIR / "jira_token.json"
        if candidate.exists():
            try:
                token_data = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:
                token_data = None
    if token_data:
        state["access_token"] = token_data.get("access_token")
        state["refresh_token"] = token_data.get("refresh_token")
    # Best-effort site discovery (offline-safe: ignore failures).
    if state["access_token"]:
        try:
            site = get_jira_site(state["access_token"])
            state["cloud_id"] = site["cloud_id"]
            state["site_name"] = site["name"]
            state["site_url"] = site["jira_url"]
        except Exception:
            pass


_load_initial_state()


def require_client() -> JiraClient:
    if not state["access_token"]:
        raise HTTPException(
            status_code=401,
            detail="Not connected. Paste an access token or complete OAuth first.",
        )
    if not state["cloud_id"]:
        raise HTTPException(
            status_code=400,
            detail="Cloud ID missing. Click 'Discover site' first.",
        )
    return JiraClient(
        access_token=state["access_token"],
        cloud_id=state["cloud_id"],
    )


def adf_to_text(adf: Any) -> str:
    """Server-side ADF -> plain text (correct implementation)."""
    if not adf:
        return ""
    out: list[str] = []

    def walk(node: Any) -> None:
        if node is None:
            return
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "text":
            out.append(node.get("text", ""))
        for child in node.get("content", []) or []:
            walk(child)
        if node.get("type") in (
            "paragraph",
            "heading",
            "blockquote",
            "bulletList",
            "orderedList",
            "listItem",
            "codeBlock",
        ):
            out.append("\n")
        if node.get("type") == "hardBreak":
            out.append("\n")

    walk(adf)
    return "".join(out).strip()


def _jira_error(e: requests.HTTPError) -> HTTPException:
    """Pass through Jira error body with its status code."""
    status = 502
    detail: Any = str(e)
    resp = getattr(e, "response", None)
    if resp is not None:
        status = resp.status_code if resp.status_code < 600 else 502
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:2000]
    return HTTPException(status_code=status, detail=detail)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class ExchangeRequest(BaseModel):
    code: str


class ConnectRequest(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    cloud_id: Optional[str] = None


class CreateIssueRequest(BaseModel):
    project_key: str
    summary: str
    description: str = ""
    issue_type: str = "Task"


class UpdateIssueRequest(BaseModel):
    summary: Optional[str] = None
    description: Optional[str] = None


class DescriptionRequest(BaseModel):
    description: str


class PriorityRequest(BaseModel):
    priority: str


class CommentRequest(BaseModel):
    comment: str


# ---------------------------------------------------------------------------
# Static UI + health
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "service": "jira-server", "port": 8099}


@app.get("/api/jira/status")
def jira_status() -> dict[str, Any]:
    return {
        "connected": bool(state["access_token"] and state["cloud_id"]),
        "has_token": bool(state["access_token"]),
        "has_refresh_token": bool(state["refresh_token"]),
        "cloud_id": state["cloud_id"],
        "site_name": state["site_name"],
        "site_url": state["site_url"],
    }


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _build_auth_url(redirect_uri: str) -> str:
    params = {
        "audience": "api.atlassian.com",
        "client_id": CLIENT_ID,
        "scope": " ".join(SCOPES),
        "redirect_uri": redirect_uri,
        "state": secrets.token_urlsafe(32),
        "response_type": "code",
        "prompt": "consent",
    }
    return AUTHORIZATION_URL + "?" + urlencode(params)


def _exchange_code_for_token(code: str) -> dict[str, Any]:
    """Exchange an authorization code, trying :8000 first then :8099.

    Atlassian requires the exact redirect_uri used in the authorize step,
    so try the primary port-8000 callback first with :8099 as fallback.
    """
    last_error: str = ""
    for redirect_uri in (PRIMARY_REDIRECT_URI, ALT_REDIRECT_URI):
        try:
            resp = requests.post(
                TOKEN_URL,
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "authorization_code",
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json()
            last_error = resp.text[:2000]
        except Exception as e:
            last_error = str(e)
    raise HTTPException(
        status_code=400,
        detail=f"Code exchange failed with both redirect URIs. Last error: {last_error}",
    )


def _store_token_and_discover(token_data: dict[str, Any]) -> Optional[dict[str, Any]]:
    save_token(token_data)
    state["access_token"] = token_data.get("access_token")
    state["refresh_token"] = token_data.get("refresh_token")
    site = None
    try:
        site = get_jira_site(state["access_token"])
        state["cloud_id"] = site["cloud_id"]
        state["site_name"] = site["name"]
        state["site_url"] = site["jira_url"]
    except Exception:
        pass
    return site


@app.get("/api/jira/auth/url")
def auth_url() -> dict[str, str]:
    return {
        "authorization_url": _build_auth_url(PRIMARY_REDIRECT_URI),
        "redirect_uri": PRIMARY_REDIRECT_URI,
        "alt_authorization_url": _build_auth_url(ALT_REDIRECT_URI),
        "alt_redirect_uri": ALT_REDIRECT_URI,
        # Back-compat aliases (previous UI builds used these keys).
        "legacy_authorization_url": _build_auth_url(LEGACY_REDIRECT_URI),
        "legacy_redirect_uri": LEGACY_REDIRECT_URI,
        "console_note": (
            "Callback uses http://localhost:8000/callback — already in the "
            "Atlassian Developer Console, no change needed."
        ),
    }


@app.post("/api/jira/auth/exchange")
def auth_exchange(req: ExchangeRequest) -> dict[str, Any]:
    code = req.code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Authorization code is required.")
    token_data = _exchange_code_for_token(code)
    site = _store_token_and_discover(token_data)
    return {"token": {"has_refresh_token": bool(state["refresh_token"])}, "site": site}


@app.get("/callback", include_in_schema=False)
def oauth_callback(
    code: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    state_param: Optional[str] = Query(default=None, alias="state"),
) -> HTMLResponse:
    """OAuth redirect target (served via the port-8000 listener, which
    forwards to this http://localhost:8099/callback handler).

    Atlassian redirects here after the user approves access. We exchange the
    code server-side (no CORS) and show a friendly result page instead of a
    browser connection error.
    """
    _ = state_param  # state is generated per-URL; not strictly validated here.
    if error:
        return HTMLResponse(
            f"""<html><body style="font-family:sans-serif;padding:2rem">
            <h2>Authorization failed</h2><p>Atlassian returned: {error}</p>
            <p><a href="/">Back to JIRA Client</a></p></body></html>""",
            status_code=400,
        )
    if not code:
        return HTMLResponse(
            """<html><body style="font-family:sans-serif;padding:2rem">
            <h2>No authorization code received</h2>
            <p><a href="/">Back to JIRA Client</a></p></body></html>""",
            status_code=400,
        )
    try:
        token_data = _exchange_code_for_token(code)
    except HTTPException as e:
        detail = e.detail if isinstance(e.detail, str) else "exchange failed"
        return HTMLResponse(
            f"""<html><body style="font-family:sans-serif;padding:2rem">
            <h2>Token exchange failed</h2><p>{detail}</p>
            <p>Code (single-use, may already be consumed): {code[:20]}...</p>
            <p><a href="/">Back to JIRA Client</a></p></body></html>""",
            status_code=400,
        )
    site = _store_token_and_discover(token_data)
    site_line = (
        f"Connected to {site['name']} ({site['jira_url']})" if site else "Token saved (site discovery pending)"
    )
    return HTMLResponse(
        f"""<html><body style="font-family:sans-serif;padding:2rem">
        <h2>Login successful</h2><p>{site_line}.</p>
        <p>You can close this tab and return to the <a href="/">JIRA Client</a>.</p>
        </body></html>"""
    )


@app.post("/api/jira/auth/refresh")
def auth_refresh() -> dict[str, Any]:
    if not state["refresh_token"]:
        # Try reloading from disk in case server restarted.
        try:
            token_data = load_token()
            if token_data and token_data.get("refresh_token"):
                state["refresh_token"] = token_data["refresh_token"]
        except Exception:
            pass
    if not state["refresh_token"]:
        raise HTTPException(status_code=400, detail="No refresh token stored.")
    try:
        resp = requests.post(
            TOKEN_URL,
            headers={"Content-Type": "application/json"},
            json={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "refresh_token": state["refresh_token"],
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail=resp.text[:2000])
        token_data = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Atlassian may rotate refresh tokens; keep old one if absent.
    if "refresh_token" not in token_data and state["refresh_token"]:
        token_data["refresh_token"] = state["refresh_token"]
    save_token(token_data)
    state["access_token"] = token_data.get("access_token")
    state["refresh_token"] = token_data.get("refresh_token")
    return {"ok": True, "has_refresh_token": bool(state["refresh_token"])}


@app.post("/api/jira/connect")
def connect(req: ConnectRequest) -> dict[str, Any]:
    """Manual connect: paste tokens from jira_token.json / OAuth flow."""
    token = req.access_token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="access_token is required.")
    state["access_token"] = token
    if req.refresh_token:
        state["refresh_token"] = req.refresh_token.strip() or state["refresh_token"]
    if req.cloud_id:
        state["cloud_id"] = req.cloud_id.strip()
        return {"ok": True, **jira_status()}
    # No cloud id supplied -> discover it.
    try:
        site = get_jira_site(token)
    except requests.HTTPError as e:
        raise _jira_error(e)
    state["cloud_id"] = site["cloud_id"]
    state["site_name"] = site["name"]
    state["site_url"] = site["jira_url"]
    return {"ok": True, "site": site, **jira_status()}


@app.get("/api/jira/site")
def discover_site() -> dict[str, Any]:
    if not state["access_token"]:
        raise HTTPException(status_code=401, detail="Access token missing.")
    try:
        site = get_jira_site(state["access_token"])
    except requests.HTTPError as e:
        raise _jira_error(e)
    state["cloud_id"] = site["cloud_id"]
    state["site_name"] = site["name"]
    state["site_url"] = site["jira_url"]
    return site


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
@app.get("/api/jira/projects")
def list_projects() -> JSONResponse:
    jira = require_client()
    try:
        return JSONResponse(content=jira.get_projects())
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.get("/api/jira/projects/{project_key}")
def get_project(project_key: str) -> JSONResponse:
    jira = require_client()
    try:
        return JSONResponse(content=jira.get_projects_new(project_key))
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.post("/api/jira/permissions/project")
def permitted_projects() -> JSONResponse:
    jira = require_client()
    try:
        return JSONResponse(content=jira.get_permitted_projects())
    except requests.HTTPError as e:
        raise _jira_error(e)


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------
@app.post("/api/jira/issues", status_code=201)
def create_issue(req: CreateIssueRequest) -> JSONResponse:
    jira = require_client()
    if not req.project_key.strip() or not req.summary.strip():
        raise HTTPException(status_code=400, detail="project_key and summary are required.")
    try:
        created = jira.create_issue(
            project_key=req.project_key.strip(),
            summary=req.summary.strip(),
            description=req.description or "",
            issue_type=req.issue_type or "Task",
        )
        return JSONResponse(status_code=201, content=created)
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.get("/api/jira/issues/{issue_key}")
def get_issue(issue_key: str) -> JSONResponse:
    jira = require_client()
    try:
        return JSONResponse(content=jira.get_issue(issue_key))
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.put("/api/jira/issues/{issue_key}")
def update_issue(issue_key: str, req: UpdateIssueRequest) -> dict[str, Any]:
    jira = require_client()
    if not req.summary and not req.description:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    try:
        jira.update_issue(issue_key, summary=req.summary, description=req.description)
        return {"ok": True}
    except requests.HTTPError as e:
        raise _jira_error(e)


# ---------------------------------------------------------------------------
# Description helpers
# ---------------------------------------------------------------------------
@app.get("/api/jira/issues/{issue_key}/description")
def get_description(issue_key: str) -> dict[str, Any]:
    jira = require_client()
    try:
        adf = jira.get_description(issue_key)
        return {"adf": adf, "text": adf_to_text(adf)}
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.put("/api/jira/issues/{issue_key}/description")
def update_description(issue_key: str, req: DescriptionRequest) -> dict[str, Any]:
    jira = require_client()
    try:
        jira.update_description(issue_key, req.description)
        return {"ok": True}
    except requests.HTTPError as e:
        raise _jira_error(e)


# ---------------------------------------------------------------------------
# Priority  (new backend methods from testJIRACloud.py)
# ---------------------------------------------------------------------------
@app.get("/api/jira/priorities")
def list_priorities() -> JSONResponse:
    jira = require_client()
    try:
        return JSONResponse(content=jira.get_priorities())
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.put("/api/jira/issues/{issue_key}/priority")
def update_priority(issue_key: str, req: PriorityRequest) -> dict[str, Any]:
    jira = require_client()
    if not req.priority.strip():
        raise HTTPException(status_code=400, detail="priority is required.")
    try:
        jira.update_priority(issue_key, req.priority.strip())
        return {"ok": True}
    except requests.HTTPError as e:
        raise _jira_error(e)


# ---------------------------------------------------------------------------
# Comments  (new backend methods from testJIRACloud.py)
# ---------------------------------------------------------------------------
@app.get("/api/jira/issues/{issue_key}/comments")
def list_comments(issue_key: str) -> JSONResponse:
    jira = require_client()
    try:
        return JSONResponse(content=jira.get_comments(issue_key))
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.post("/api/jira/issues/{issue_key}/comments", status_code=201)
def add_comment(issue_key: str, req: CommentRequest) -> JSONResponse:
    jira = require_client()
    if not req.comment.strip():
        raise HTTPException(status_code=400, detail="comment is required.")
    try:
        created = jira.add_comment(issue_key, req.comment)
        return JSONResponse(status_code=201, content=created)
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.put("/api/jira/issues/{issue_key}/comments/{comment_id}")
def update_comment(issue_key: str, comment_id: str, req: CommentRequest) -> JSONResponse:
    jira = require_client()
    if not req.comment.strip():
        raise HTTPException(status_code=400, detail="comment is required.")
    try:
        updated = jira.update_comment(issue_key, comment_id, req.comment)
        if isinstance(updated, dict):
            return JSONResponse(content=updated)
        return JSONResponse(content={"ok": True})
    except requests.HTTPError as e:
        raise _jira_error(e)


@app.delete("/api/jira/issues/{issue_key}/comments/{comment_id}")
def delete_comment(issue_key: str, comment_id: str) -> dict[str, Any]:
    jira = require_client()
    try:
        jira.delete_comment(issue_key, comment_id)
        return {"ok": True}
    except requests.HTTPError as e:
        raise _jira_error(e)


# ---------------------------------------------------------------------------
# Port-8000 callback listener.
# The OAuth callback is http://localhost:8000/callback (same as
# testJIRACloud.py and the Atlassian console entry). The API itself runs on
# 8099, so this tiny listener (same process, background thread) catches the
# Atlassian redirect on :8000 and forwards it to the real
# http://localhost:8099/callback handler, preserving the query string
# (?code=...&state=...). Without it the browser shows "Unable to connect".
# ---------------------------------------------------------------------------
class _LegacyRedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path or "/"
        # Preserve query string (?code=...&state=...).
        target = f"http://localhost:8099/callback{path[len('/callback'):]}" if path.startswith("/callback") else "http://localhost:8099/"
        self.send_response(302)
        self.send_header("Location", target)
        self.end_headers()

    def log_message(self, format, *args):
        pass


def _start_legacy_forwarder() -> None:
    def _serve():
        try:
            server = HTTPServer(("127.0.0.1", 8000), _LegacyRedirectHandler)
            server.serve_forever()
        except OSError:
            # Port 8000 already in use (e.g. testJIRACloud.py running) — skip.
            pass

    thread = threading.Thread(target=_serve, daemon=True, name="legacy-8000-forwarder")
    thread.start()


@app.on_event("startup")
def _startup_legacy_forwarder():
    _start_legacy_forwarder()


# ---------------------------------------------------------------------------
# Serve frontend (must be mounted AFTER api routes)
# ---------------------------------------------------------------------------
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend-static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(
            status_code=500,
            content={"detail": "frontend/index.html not found"},
        )
    return FileResponse(str(index_file))


def run() -> None:
    import uvicorn

    _start_legacy_forwarder()
    uvicorn.run(app, host="0.0.0.0", port=8099, reload=False)


if __name__ == "__main__":
    run()
