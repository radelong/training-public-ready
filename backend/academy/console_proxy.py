"""Same-origin Guacamole gateway with login and per-token VM authorization."""
import asyncio
import logging
import time
from urllib.parse import parse_qs, urlencode
import httpx
from fastapi import Request, WebSocket, HTTPException
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from .db import Login, User, ConsoleGrant, LabSession, HttpTunnel
from .security import digest


def authorize(factory, cookie, token=None, token_hash=None):
    with factory() as db:
        login = db.get(Login, digest(cookie)) if cookie else None
        user = db.get(User, login.user_id) if login else None
        now = time.time()
        if not login or login.expires < now or not user or not user.enabled:
            raise HTTPException(401, "Sign in to use the lab console")
        if token is None and token_hash is None:
            return
        grant = db.get(ConsoleGrant, token_hash or digest(token))
        session = db.get(LabSession, grant.session_id) if grant else None
        if (not grant or grant.login_hash != login.token_hash or grant.expires < now or not session
                or session.user_id != user.id or session.state != "ready" or session.expires < now
                or session.generation != grant.generation):
            raise HTTPException(403, "Console access expired; reconnect from your lab")


def mount_console(app, factory, settings):
    @app.api_route("/console/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def proxy(path: str, request: Request):
        body = await request.body()
        query = dict(request.query_params)
        form = parse_qs(body.decode(errors="replace")) if "application/x-www-form-urlencoded" in request.headers.get("content-type", "") else {}
        token = (query.get("token") or query.get("GUAC_AUTH")
                 or (form.get("token") or form.get("GUAC_AUTH") or [None])[0]
                 or request.headers.get("Guacamole-Token"))
        if path.startswith("api/tokens/"):
            token = path.split("/")[-1]
        if path.rstrip("/") == "api/tokens" and (not token or set(form) != {"token"}):
            raise HTTPException(403, "Open the console from your lab workspace")
        cookie = request.cookies.get("academy_session")
        tunnel_hash = None
        if path == "tunnel" and not token:
            parts = request.url.query.split(":")
            if len(parts) > 1 and parts[0] in ("read", "write"):
                with factory() as db:
                    tunnel = db.get(HttpTunnel, parts[1])
                    tunnel_hash = tunnel.token_hash if tunnel else None
            if not tunnel_hash:
                raise HTTPException(403, "Unknown console tunnel")
        # Static files and the Guacamole shell have no token. Dynamic API/tunnel calls must.
        if path.startswith("api/") and not token:
            # Guacamole loads language definitions and client patches before authentication.
            if not path.startswith(("api/languages", "api/patches")):
                route = "/".join(path.split("/")[:4])
                logging.getLogger("academy.console").warning(
                    "Console API missing token on %s; query keys=%s; header names=%s",
                    route, sorted(query),
                    sorted(k for k in request.headers if k.lower() in ("guacamole-token", "authorization", "x-guacamole-token")))
                raise HTTPException(403, "Missing console connection token")
        authorize(factory, cookie, token, tunnel_hash)
        if request.method not in ("GET", "HEAD"):
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
                raise HTTPException(403, "Cross-site console request blocked")
        if ".." in path.split("/"):
            raise HTTPException(400, "Invalid console path")
        url = settings.guac_url.rstrip("/") + "/" + path
        if request.url.query:
            url += "?" + request.url.query
        client = httpx.AsyncClient(timeout=httpx.Timeout(75, connect=15))
        headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ("host", "cookie", "authorization", "content-length", "connection", "accept-encoding")}
        try:
            upstream = await client.send(client.build_request(request.method, url, content=body, headers=headers), stream=True)
        except httpx.HTTPError:
            await client.aclose()
            raise HTTPException(503, "Console service is unavailable")

        async def close():
            await upstream.aclose()
            await client.aclose()

        if path == "tunnel" and request.url.query == "connect" and upstream.status_code == 200:
            value = await upstream.aread()
            tunnel_id = value.decode().strip()
            if len(tunnel_id) <= 128 and token:
                with factory() as db:
                    db.merge(HttpTunnel(id=tunnel_id, token_hash=digest(token)))
                    db.commit()
            await close()
            from fastapi import Response
            return Response(value, status_code=upstream.status_code, media_type="text/plain")

        async def chunks():
            async for chunk in upstream.aiter_bytes():
                authorize(factory, cookie, token, tunnel_hash)
                yield chunk

        response_headers = {k: v for k, v in upstream.headers.items()
                            if k.lower() not in ("transfer-encoding", "connection", "content-length", "content-encoding", "set-cookie")}
        return StreamingResponse(chunks(), status_code=upstream.status_code,
                                 headers=response_headers, background=BackgroundTask(close))

    @app.websocket("/console/websocket-tunnel")
    async def socket_proxy(socket: WebSocket):
        import websockets
        token = socket.query_params.get("token") or socket.query_params.get("GUAC_AUTH")
        try:
            if not token:
                raise HTTPException(403, "Missing connection token")
            authorize(factory, socket.cookies.get("academy_session"), token)
            origin = socket.headers.get("origin")
            if origin and origin.rstrip("/") != str(socket.url).split("/console/")[0].replace("wss://", "https://").replace("ws://", "http://"):
                raise HTTPException(403, "Cross-site console blocked")
        except HTTPException as exc:
            logging.getLogger("academy.console").warning("Console websocket authorization rejected: %s", exc.status_code)
            await socket.close(code=1008)
            return
        target = settings.guac_url.replace("http://", "ws://").replace("https://", "wss://")
        target += "/websocket-tunnel?" + str(socket.query_params)
        stage = "upstream connect"
        try:
            async with websockets.connect(target, subprotocols=["guacamole"], max_size=8 * 1024 * 1024) as upstream:
                stage = "browser accept"
                await socket.accept(subprotocol="guacamole")

                async def browser_to_server():
                    while True:
                        await upstream.send(await socket.receive_text())

                async def server_to_browser():
                    async for message in upstream:
                        await socket.send_text(message)

                async def revocation_guard():
                    while True:
                        await asyncio.sleep(2)
                        authorize(factory, socket.cookies.get("academy_session"), token)

                stage = "tunnel forwarding"
                tasks = [asyncio.create_task(c()) for c in (browser_to_server, server_to_browser, revocation_guard)]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as exc:
            logging.getLogger("academy.console").warning(
                "Console websocket failed during %s: %s", stage, type(exc).__name__)
            try:
                await socket.close(code=1000)
            except RuntimeError:
                pass
