from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.security import IpAllowlist, ensure_allowed_ip
from app.web.routes import router


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    allowlist = IpAllowlist.from_csv(settings.admin_ip_allowlist)

    @app.middleware("http")
    async def admin_ip_allowlist(request: Request, call_next):
        if request.url.path.startswith("/admin"):
            try:
                ensure_allowed_ip(
                    request,
                    allowlist,
                    trust_proxy_headers=settings.trust_proxy_headers,
                )
            except Exception:
                return PlainTextResponse("Forbidden", status_code=403)
        return await call_next(request)

    app.include_router(router)
    return app


app = create_app()

