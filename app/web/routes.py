from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus, urlencode

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import (
    SESSION_COOKIE_NAME,
    check_admin_password,
    make_session,
    read_session,
)
from app.db import get_db
from app.models.client import VpnClient
from app.models.client import as_utc
from app.services.client_service import ClientService, ClientServiceError, gb_from_bytes
from app.services.happ import HappCryptoClient
from app.services.xui import XuiClient, XuiError, XuiInboundOption
from app.web.formatters import format_bytes, format_datetime, status_label

router = APIRouter()

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))
templates.env.filters["bytes"] = format_bytes
templates.env.filters["datetime"] = format_datetime
templates.env.filters["status"] = status_label
templates.env.filters["gb"] = gb_from_bytes


def build_client_service(settings: Settings, inbound_id: int) -> ClientService:
    return ClientService(
        xui=XuiClient(
            base_url=settings.xui_base_url,
            api_token=settings.xui_api_token,
            inbound_id=inbound_id,
            subscription_base_url=settings.xui_subscription_base_url,
            client_flow=settings.xui_client_flow,
            tls_verify=settings.xui_tls_verify,
        ),
        happ=HappCryptoClient(
            api_url=settings.happ_crypto_api_url,
            mode=settings.happ_crypto_mode,
        ),
        public_app_url=settings.public_app_url,
    )


def build_xui_client(settings: Settings, inbound_id: int | None = None) -> XuiClient:
    default_inbound_id = settings.xui_inbound_options[0][0] if settings.xui_inbound_options else 0
    return XuiClient(
        base_url=settings.xui_base_url,
        api_token=settings.xui_api_token,
        inbound_id=inbound_id or default_inbound_id,
        subscription_base_url=settings.xui_subscription_base_url,
        client_flow=settings.xui_client_flow,
        tls_verify=settings.xui_tls_verify,
    )


def get_client_service(settings: Settings = Depends(get_settings)) -> ClientService:
    default_inbound_id = settings.xui_inbound_options[0][0] if settings.xui_inbound_options else 0
    return build_client_service(settings, default_inbound_id)


async def available_inbound_options(settings: Settings) -> list[tuple[int, str]]:
    try:
        options = await build_xui_client(settings).list_inbound_options()
    except XuiError:
        return list(settings.xui_inbound_options)
    return [(option.id, _clean_inbound_label(option)) for option in options]


def _clean_inbound_label(option: XuiInboundOption) -> str:
    label = option.label
    for suffix in (f" / {option.port}", f" / {option.protocol}"):
        label = label.replace(suffix, "")
    return label


def make_inbound_labeler(options: list[tuple[int, str]]):
    labels = {option_id: label for option_id, label in options}

    def label_for(inbound_ids: int | list[int]) -> str:
        ids = [inbound_ids] if isinstance(inbound_ids, int) else inbound_ids
        return ", ".join(labels.get(inbound_id, f"Inbound {inbound_id}") for inbound_id in ids)

    return label_for


def happ_subscription_headers(client: VpnClient, settings: Settings) -> dict[str, str]:
    used_bytes = max(int(client.traffic_used_bytes or 0), 0)
    total_bytes = int(client.traffic_limit_bytes or 0)
    expire_seconds = int(as_utc(client.expires_at).timestamp())
    headers = {
        "profile-title": settings.happ_profile_title[:25],
        "subscription-userinfo": (
            f"upload=0; download={used_bytes}; total={total_bytes}; expire={expire_seconds}"
        ),
        "support-url": settings.happ_support_url,
        "profile-web-page-url": settings.happ_profile_web_page_url,
        "content-disposition": 'attachment; filename="VPN"',
    }
    return {key: value for key, value in headers.items() if value}


def current_admin(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> str:
    username = read_session(request.cookies.get(SESSION_COOKIE_NAME), settings.app_secret_key)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/admin/login"},
        )
    return username


def redirect_with_message(path: str, *, message: str | None = None, error: str | None = None) -> RedirectResponse:
    params = {}
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    suffix = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{path}{suffix}", status_code=status.HTTP_303_SEE_OTHER)


def get_vpn_client(db: Session, client_id: int) -> VpnClient:
    client = db.get(VpnClient, client_id)
    if not client:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    return client


@router.get("/", include_in_schema=False)
async def index() -> RedirectResponse:
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "settings": settings,
            "error": request.query_params.get("error"),
        },
    )


@router.post("/admin/login")
async def login(
    username: str = Form(...),
    password: str = Form(...),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if username != settings.admin_username or not check_admin_password(
        password,
        settings.admin_password_hash,
        settings.admin_password,
    ):
        return RedirectResponse(
            "/admin/login?error=Неверный логин или пароль",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    response = RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        make_session(username, settings.app_secret_key, settings.session_ttl_seconds),
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_seconds,
    )
    return response


@router.post("/admin/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@router.get("/admin", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    q: str = "",
    db: Session = Depends(get_db),
    _: str = Depends(current_admin),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    stmt = select(VpnClient).order_by(VpnClient.created_at.desc())
    if q.strip():
        needle = f"%{q.strip()}%"
        stmt = stmt.where(or_(VpnClient.display_name.ilike(needle), VpnClient.xui_email.ilike(needle)))
    clients = list(db.scalars(stmt))
    stats = ClientService.dashboard_stats(db)
    inbound_options = await available_inbound_options(settings)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "settings": settings,
            "clients": clients,
            "stats": stats,
            "q": q,
            "inbound_options": inbound_options,
            "inbound_label": make_inbound_labeler(inbound_options),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/admin/clients")
async def create_client(
    display_name: str = Form(...),
    inbound_ids: list[int] = Form(...),
    duration_days: int = Form(...),
    traffic_limit_gb: int = Form(0),
    db: Session = Depends(get_db),
    admin: str = Depends(current_admin),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    inbound_ids = list(dict.fromkeys(int(inbound_id) for inbound_id in inbound_ids if inbound_id))
    allowed_inbound_ids = {option_id for option_id, _ in await available_inbound_options(settings)}
    if not inbound_ids:
        return redirect_with_message("/admin", error="Выберите хотя бы один сервер")
    if not set(inbound_ids).issubset(allowed_inbound_ids):
        return redirect_with_message("/admin", error="Выбранный inbound не разрешен настройками")
    service = build_client_service(settings, inbound_ids[0])
    try:
        result = await service.create_client(
            db,
            display_name=display_name,
            inbound_ids=inbound_ids,
            duration_days=duration_days,
            traffic_limit_gb=traffic_limit_gb or None,
            actor=admin,
        )
    except ClientServiceError as exc:
        db.rollback()
        return redirect_with_message("/admin", error=str(exc))
    warning = f"Подключение создано, но шифрование Happ нужно повторить: {result.warning}" if result.warning else None
    if warning:
        return redirect_with_message(f"/admin/clients/{result.client.id}", error=warning)
    return redirect_with_message(f"/admin/clients/{result.client.id}", message="Подключение создано")


@router.get("/admin/clients/{client_id}", response_class=HTMLResponse)
async def client_detail(
    request: Request,
    client_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(current_admin),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    client = get_vpn_client(db, client_id)
    inbound_options = await available_inbound_options(settings)
    share_url = None
    if client.happ_link:
        text = f"Ваше VPN-подключение для Happ: {client.happ_link}"
        share_url = f"https://t.me/share/url?url={quote_plus(client.happ_link)}&text={quote_plus(text)}"
    return templates.TemplateResponse(
        request,
        "client_detail.html",
        {
            "request": request,
            "settings": settings,
            "client": client,
            "inbound_label": make_inbound_labeler(inbound_options)(client.inbound_id_list),
            "share_url": share_url,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/admin/clients/{client_id}/block")
async def block_client(
    client_id: int,
    db: Session = Depends(get_db),
    admin: str = Depends(current_admin),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    client = get_vpn_client(db, client_id)
    service = build_client_service(settings, client.xui_inbound_id)
    try:
        await service.block_client(db, client, actor=admin)
    except ClientServiceError as exc:
        db.rollback()
        return redirect_with_message(f"/admin/clients/{client_id}", error=str(exc))
    return redirect_with_message(f"/admin/clients/{client_id}", message="Клиент заблокирован")


@router.post("/admin/clients/{client_id}/extend")
async def extend_client(
    client_id: int,
    extra_days: int = Form(...),
    db: Session = Depends(get_db),
    admin: str = Depends(current_admin),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    client = get_vpn_client(db, client_id)
    service = build_client_service(settings, client.xui_inbound_id)
    try:
        await service.extend_client(db, client, extra_days=extra_days, actor=admin)
    except ClientServiceError as exc:
        db.rollback()
        return redirect_with_message(f"/admin/clients/{client_id}", error=str(exc))
    return redirect_with_message(f"/admin/clients/{client_id}", message="Срок продлен")


@router.post("/admin/clients/{client_id}/reissue")
async def reissue_link(
    client_id: int,
    db: Session = Depends(get_db),
    admin: str = Depends(current_admin),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    client = get_vpn_client(db, client_id)
    service = build_client_service(settings, client.xui_inbound_id)
    try:
        await service.issue_happ_link(db, client, actor=admin, raise_on_error=True)
        db.commit()
    except ClientServiceError as exc:
        db.rollback()
        return redirect_with_message(f"/admin/clients/{client_id}", error=str(exc))
    return redirect_with_message(f"/admin/clients/{client_id}", message="Ссылка перевыпущена")


@router.post("/admin/clients/{client_id}/sync")
async def sync_traffic(
    client_id: int,
    db: Session = Depends(get_db),
    admin: str = Depends(current_admin),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    client = get_vpn_client(db, client_id)
    service = build_client_service(settings, client.xui_inbound_id)
    try:
        await service.sync_traffic(db, client, actor=admin)
    except ClientServiceError as exc:
        db.rollback()
        return redirect_with_message(f"/admin/clients/{client_id}", error=str(exc))
    return redirect_with_message(f"/admin/clients/{client_id}", message="Трафик обновлен")


@router.get("/admin/clients/{client_id}/qr.svg")
async def client_qr(
    client_id: int,
    db: Session = Depends(get_db),
    _: str = Depends(current_admin),
) -> Response:
    client = get_vpn_client(db, client_id)
    if not client.happ_link:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Happ link is not available")
    image = qrcode.make(client.happ_link, image_factory=qrcode.image.svg.SvgPathImage)
    return Response(
        content=image.to_string(encoding="unicode"),
        media_type="image/svg+xml",
    )


@router.get("/sub/{token}")
async def subscription(
    token: str,
    db: Session = Depends(get_db),
    service: ClientService = Depends(get_client_service),
    settings: Settings = Depends(get_settings),
) -> Response:
    try:
        client, body, content_type = await service.fetch_subscription(db, token)
    except ClientServiceError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subscription not found")
    return Response(
        content=body,
        media_type=content_type,
        headers=happ_subscription_headers(client, settings),
    )
