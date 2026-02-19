from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import json
import os
import socket
import sqlite3
import threading
import urllib.parse
import urllib.request
import uvicorn
from dotenv import load_dotenv
from tools import debug_print, path_from_app_root

app = FastAPI()
_SERVER_LOCK = threading.Lock()
_SERVER_INSTANCE: uvicorn.Server | None = None
_SERVER_THREAD: threading.Thread | None = None

def _load_oauth_env() -> tuple[str, str]:
    env_path = path_from_app_root(".env")
    load_dotenv(dotenv_path=env_path, override=True)
    client_id = (os.getenv("TWITCH_CLIENT_ID", "") or "").strip()
    client_secret = (os.getenv("TWITCH_APP_SECRET", "") or "").strip()
    return client_id, client_secret


def _exchange_code_for_token(code: str, redirect_uri: str) -> dict:
    client_id, client_secret = _load_oauth_env()
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://id.twitch.tv/oauth2/token",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def _validate_token(access_token: str) -> dict:
    req = urllib.request.Request(
        "https://id.twitch.tv/oauth2/validate",
        method="GET",
        headers={"Authorization": f"OAuth {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def _store_tokens(user_id: str, access_token: str, refresh_token: str) -> None:
    db_path = path_from_app_root("data", "maddieply.db")
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens(
                user_id TEXT PRIMARY KEY,
                token TEXT NOT NULL,
                refresh TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO tokens (user_id, token, refresh)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id)
            DO UPDATE SET
                token = excluded.token,
                refresh = excluded.refresh
            """,
            (user_id, access_token, refresh_token),
        )
        conn.commit()
    finally:
        conn.close()


@app.get("/oauth")
async def oauth_callback(request: Request):
    debug_print("OauthServer", "Received OAuth callback request.")
    params = dict(request.query_params)
    code = params.get("code")
    error = params.get("error")
    if error:
        return HTMLResponse(
            f"""
            <h1>Twitch OAuth Error</h1>
            <pre>{params}</pre>
            """
        )
    if not code:
        return HTMLResponse(
            f"""
            <h1>Twitch OAuth Token Missing</h1>
            <pre>{params}</pre>
            """
        )

    redirect_uri = str(request.url).split("?", 1)[0]
    try:
        token_data = _exchange_code_for_token(code, redirect_uri)
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        if not access_token or not refresh_token:
            return HTMLResponse(
                f"""
                <h1>Twitch OAuth Failed</h1>
                <pre>{token_data}</pre>
                """
            )
        validate_data = _validate_token(access_token)
        user_id = validate_data.get("user_id")
        if not user_id:
            return HTMLResponse(
                f"""
                <h1>Twitch OAuth Validation Failed</h1>
                <pre>{validate_data}</pre>
                """
            )
        _store_tokens(user_id, access_token, refresh_token)
        debug_print("OauthServer", f"Stored OAuth tokens for user_id={user_id}.")
        return HTMLResponse(
            f"""
            <h1>Twitch OAuth Complete</h1>
            <p>Tokens stored for user ID: {user_id}</p>
            <pre>{validate_data}</pre>
            """
        )
    except Exception as exc:
        return HTMLResponse(
            f"""
            <h1>Twitch OAuth Error</h1>
            <p>{exc}</p>
            <pre>{params}</pre>
            """
        )


@app.get("/oauth/callback")
async def oauth_callback_alias(request: Request):
    return await oauth_callback(request)


def _is_server_running(host: str = "127.0.0.1", port: int = 4343) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def start_background_server(host: str = "127.0.0.1", port: int = 4343) -> None:
    global _SERVER_INSTANCE, _SERVER_THREAD
    if _is_server_running(host, port):
        debug_print("OauthServer", "OAuth server already running.")
        return

    with _SERVER_LOCK:
        if _SERVER_INSTANCE is not None:
            debug_print("OauthServer", "OAuth server already running.")
            return

    def _run_server() -> None:
        try:
            config = uvicorn.Config(
                "oauth_server:app",
                host=host,
                port=port,
                log_level="warning",
                log_config=None,
            )
            server = uvicorn.Server(config)
            with _SERVER_LOCK:
                _SERVER_INSTANCE = server
            server.run()
        except Exception as exc:
            print(f"OAuth server failed to start: {exc}")
        finally:
            with _SERVER_LOCK:
                _SERVER_INSTANCE = None

    thread = threading.Thread(target=_run_server, daemon=True)
    with _SERVER_LOCK:
        _SERVER_THREAD = thread
    thread.start()


def stop_background_server() -> None:
    with _SERVER_LOCK:
        server = _SERVER_INSTANCE
    if server is None:
        return
    server.should_exit = True

if __name__ == "__main__":
    uvicorn.run("oauth_server:app", host="127.0.0.1", port=4343, reload=False)
