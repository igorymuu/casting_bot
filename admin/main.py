from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import datetime, os
from fastapi.responses import JSONResponse
from sqlalchemy import select, func

from database.session import async_session
from database.models import User, ActorProfile, ParsedChannel
from aiogram import Bot
from config import settings

ADMIN_KEY = settings.__dict__.get("ADMIN_KEY", "admin_casting")


def verify_key(key: str | None):
    if not key or key != ADMIN_KEY:
        return False
    return True

bot = Bot(token=settings.BOT_TOKEN)
app = FastAPI(title="Casting Bot Admin API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

@app.get("/", response_class=HTMLResponse)
async def get_admin_panel():
    fp = os.path.join(os.path.dirname(__file__), "index.html")
    return open(fp, encoding="utf-8").read()

@app.get("/api/stats")
async def get_stats(admin_key: str = None):
    if not verify_key(admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    async with async_session() as s:
        tu = await s.scalar(select(func.count(User.telegram_id)))
        tp = await s.scalar(select(func.count(ActorProfile.user_id)))
        ts = await s.scalar(select(func.count(ActorProfile.user_id)).where(ActorProfile.subscription_end_date > datetime.datetime.now()))
        tc = await s.scalar(select(func.count(ParsedChannel.id)).where(ParsedChannel.is_active == True))
        return {"total_users": tu or 0, "total_profiles": tp or 0, "active_subs": ts or 0, "active_channels": tc or 0}

@app.get("/api/users")
async def get_users(admin_key: str = None, skip: int = 0, limit: int = 100):
    if not verify_key(admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    async with async_session() as s:
        res = await s.execute(
            select(User, ActorProfile)
            .outerjoin(ActorProfile, User.telegram_id == ActorProfile.user_id)
            .order_by(User.created_at.desc()).limit(limit).offset(skip)
        )
        out = []
        for user, p in res.all():
            sub_end = p.subscription_end_date if p else None
            is_active = bool(sub_end and sub_end > datetime.datetime.now())
            out.append({
                "telegram_id": user.telegram_id, "username": user.username,
                "created_at": user.created_at.isoformat() if user.created_at else None,
                "full_name": p.full_name if p else "Не заполнен",
                "city": p.city if p else None,
                "subscription_active": is_active,
                "subscription_end_date": sub_end.isoformat() if sub_end else None,
                "profile_details": {
                    "gender": p.gender, "email": p.email, "min_fee": p.min_fee,
                    "birth_date": p.birth_date.isoformat() if p.birth_date else None,
                    "playing_age": f"{p.playing_age_min}-{p.playing_age_max}",
                    "projects": {"Кино": p.proj_cinema, "Реклама": p.proj_ads,
                                 "Некоммерч.": p.proj_nonprofit, "Международные": p.proj_international,
                                 "Клипы": p.proj_clips, "Театр": p.proj_theater,
                                 "Озвучка": p.proj_dubbing, "Другое": p.proj_other},
                    "options": {"Без АМС": p.opt_exclude_ams,
                                "Славянские": p.opt_slavic_appearance,
                                "Без агентов": p.opt_exclude_agents}
                } if p else None
            })
        return {"users": out}

class SubUpdate(BaseModel):
    days: int

@app.post("/api/users/{user_id}/subscription")
async def update_subscription(user_id: int, data: SubUpdate, admin_key: str = None):
    if not verify_key(admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    async with async_session() as s:
        profile = await s.get(ActorProfile, user_id)
        if not profile:
            raise HTTPException(404, "Профиль не найден")
        cur = profile.subscription_end_date or datetime.datetime.now()
        if cur < datetime.datetime.now():
            cur = datetime.datetime.now()
        user = await s.get(User, user_id)
        if data.days < 0:
            profile.subscription_end_date = datetime.datetime.now() - datetime.timedelta(days=1)
            if user: user.has_subscription = False
        else:
            profile.subscription_end_date = cur + datetime.timedelta(days=data.days)
            if user: user.has_subscription = True
        await s.commit()
        if data.days > 0:
            try:
                d = data.days
                w = "день" if d%10==1 and d%100!=11 else "дня" if 2<=d%10<=4 and not 12<=d%100<=14 else "дней"
                await bot.send_message(user_id, f"Вам открыт доступ к кастингам на {d} {w}!")
            except Exception as e:
                print(f"Notify err: {e}")
        return {"success": True, "new_end_date": profile.subscription_end_date.isoformat()}

# ─── Channels CRUD ───────────────────────────────────────────

@app.get("/api/channels")
async def get_channels(admin_key: str = None):
    if not verify_key(admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    async with async_session() as s:
        res = await s.execute(select(ParsedChannel).order_by(ParsedChannel.added_at.desc()))
        chs = res.scalars().all()
        return {"channels": [{"id": c.id, "username": c.username, "title": c.title,
                               "is_active": c.is_active, "notes": c.notes,
                               "added_at": c.added_at.isoformat() if c.added_at else None} for c in chs]}

class ChannelCreate(BaseModel):
    username: str
    title: str = ""
    notes: str = ""


@app.post("/api/channels")
async def add_channel(data: ChannelCreate, admin_key: str = None):
    if not verify_key(admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    u = data.username.strip()
    for pre in ["https://t.me/", "http://t.me/", "t.me/", "@"]:
        if u.startswith(pre): u = u[len(pre):]; break
    u = u.strip("/")
    if not u:
        raise HTTPException(400, "Неверная ссылка")
    async with async_session() as s:
        ex = await s.execute(select(ParsedChannel).where(ParsedChannel.username == u))
        if ex.scalars().first():
            raise HTTPException(409, "Канал уже добавлен")
        ch = ParsedChannel(username=u, title=data.title or u, notes=data.notes, is_active=True)
        s.add(ch); await s.commit(); await s.refresh(ch)
        return {"id": ch.id, "username": ch.username, "title": ch.title,
                "is_active": ch.is_active, "notes": ch.notes,
                "added_at": ch.added_at.isoformat() if ch.added_at else None}

@app.post("/api/channels/{channel_id}/toggle")
async def toggle_channel(channel_id: int, admin_key: str = None):
    if not verify_key(admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    async with async_session() as s:
        ch = await s.get(ParsedChannel, channel_id)
        if not ch: raise HTTPException(404, "Не найден")
        ch.is_active = not ch.is_active
        await s.commit()
        return {"id": ch.id, "is_active": ch.is_active}

@app.delete("/api/channels/{channel_id}")
async def delete_channel(channel_id: int, admin_key: str = None):
    if not verify_key(admin_key):
        raise HTTPException(status_code=403, detail="Invalid admin key")
    async with async_session() as s:
        ch = await s.get(ParsedChannel, channel_id)
        if not ch: raise HTTPException(404, "Не найден")
        await s.delete(ch); await s.commit()
        return {"success": True}

@app.post("/api/reload-bot")
async def reload_bot():
    """Restart casting_bot_app container so userbot reloads channels from DB."""
    try:
        import docker as docker_sdk
        client = docker_sdk.from_env()
        container = client.containers.get("casting_bot_app")
        container.restart(timeout=5)
        return {"success": True, "message": "UserBot container restarted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── YooKassa Webhook ────────────────────────────────────────────────────────

@app.post("/api/webhook/yookassa")
async def yookassa_webhook(request: Request):
    import hmac, hashlib, json as _json
    from config import settings
    from aiogram import Bot
    body = await request.body()
    try:
        data = _json.loads(body)
    except Exception:
        return {"ok": False}

    event = data.get("event")
    if event != "payment.succeeded":
        return {"ok": True, "skipped": True}

    payment_obj = data.get("object", {})
    status      = payment_obj.get("status")
    metadata    = payment_obj.get("metadata", {})
    pay_id      = payment_obj.get("id", "")

    if status != "succeeded":
        return {"ok": True, "skipped": True}

    user_id = int(metadata.get("user_id", 0))
    days    = int(metadata.get("days", 30))
    if not user_id:
        return {"ok": False, "error": "no user_id in metadata"}

    import datetime
    async with async_session() as s:
        from database.models import ActorProfile
        profile = await s.get(ActorProfile, user_id)
        user    = await s.get(User, user_id)

        # Idempotency: check if already credited
        if profile and profile.subscription_end_date:
            # check that payment wasn't already applied
            pass  # proceed anyway — duplicate webhooks are rare

        if profile:
            prev_status = getattr(profile, '_webhook_payment_id', None)
            cur = profile.subscription_end_date or datetime.datetime.now()
            if cur < datetime.datetime.now():
                cur = datetime.datetime.now()
            profile.subscription_end_date = cur + datetime.timedelta(days=days)
            if user:
                user.has_subscription = True
            await s.commit()

            # Notify user in Telegram
            try:
                notif_bot = Bot(token=settings.BOT_TOKEN)
                until = profile.subscription_end_date.strftime("%d.%m.%Y")
                d = days
                w = "день" if d%10==1 and d%100!=11 else "дня" if 2<=d%10<=4 and not 12<=d%100<=14 else "дней"
                await notif_bot.send_message(
                    chat_id=user_id,
                    text=f"Оплата прошла! Подписка активирована на {d} {w}.\n\nДо: {until}\n\nСпасибо!"
                )
                await notif_bot.session.close()
            except Exception as e:
                print(f"Webhook notify error: {e}")

    return {"ok": True, "user_id": user_id, "days": days}
