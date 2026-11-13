"""Owner-only campaign administration for the Telegram Mini App API.

The owner identity is an explicit server-side configuration, never a client
provided owner_id. No advertiser may manage another channel or campaign.
"""
import logging
import os
import sqlite3
import time

from aiogram import Bot
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from api.campaign_revocations import dispatch_campaign_revocations
from config import get_settings
from services.campaign_telegram import create_campaign_invite, revoke_campaign_invite


class DraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chat_id: int
    mode: str
    starts_at: float
    ends_at: float
    target_joins: int | None = None


class StateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: str


def owner_identity(user_id: int) -> int:
    raw = os.getenv("FILESHAPE_OWNER_ID", "")
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 19:
        raise HTTPException(status_code=503, detail="Owner configuration unavailable")
    owner_id = int(raw)
    if not 0 < owner_id <= 2**63 - 1:
        raise HTTPException(status_code=503, detail="Owner configuration unavailable")
    if user_id != owner_id:
        raise HTTPException(status_code=403, detail="Owner access required")
    return owner_id


def make_campaign_router(authenticated_user, get_store):
    router = APIRouter(prefix="/api/v1/owner/campaigns", tags=["owner"])

    def authorized_store(user_id: int = Depends(authenticated_user)):
        owner_id = owner_identity(user_id)
        store = get_store()
        if store is None or not hasattr(store, "create_campaign"):
            raise HTTPException(status_code=503, detail="Campaign storage unavailable")
        return store, owner_id

    @router.get("/analytics")
    async def owner_analytics(owner=Depends(authorized_store)):
        store, owner_id = owner
        try:
            return store.campaign_analytics(actor_id=owner_id, owner_id=owner_id)
        except (sqlite3.Error, OSError):
            raise HTTPException(
                status_code=503, detail="Campaign analytics unavailable"
            ) from None

    @router.get("")
    async def list_owner_campaigns(
        limit: int = Query(default=20, ge=1, le=30),
        offset: int = Query(default=0, ge=0, le=10000),
        owner=Depends(authorized_store),
    ):
        store, owner_id = owner
        try:
            return store.list_campaigns(
                actor_id=owner_id, owner_id=owner_id,
                limit=limit, offset=offset,
            )
        except (sqlite3.Error, OSError):
            raise HTTPException(
                status_code=503, detail="Campaign storage unavailable"
            ) from None

    @router.post("/drafts")
    async def create_draft(data: DraftRequest, owner=Depends(authorized_store)):
        store, owner_id = owner
        try:
            campaign_id = store.create_campaign(
                actor_id=owner_id, owner_id=owner_id, chat_id=data.chat_id,
                mode=data.mode, starts_at=data.starts_at, ends_at=data.ends_at,
                target_joins=data.target_joins,
            )
        except (ValueError, TypeError, OverflowError):
            raise HTTPException(status_code=422, detail="Invalid campaign") from None
        except (sqlite3.Error, OSError):
            raise HTTPException(status_code=503, detail="Campaign storage unavailable") from None
        return {"campaign_id": campaign_id, "state": "draft"}

    @router.post("/{campaign_id}/invite")
    async def create_invite(campaign_id: str, owner=Depends(authorized_store)):
        store, owner_id = owner
        try:
            snapshot = store.campaign_snapshot(
                actor_id=owner_id, owner_id=owner_id, campaign_id=campaign_id)
            if snapshot["state"] != "draft" or snapshot["invite_link"] is not None:
                raise HTTPException(status_code=409, detail="Campaign already bound")
            bot = Bot(token=get_settings().bot_token)
            try:
                link = await create_campaign_invite(
                    bot, chat_id=snapshot["chat_id"], campaign_id=campaign_id)
                try:
                    store.bind_campaign_invite(
                        actor_id=owner_id, owner_id=owner_id,
                        campaign_id=campaign_id, invite_link=link)
                except BaseException:
                    # Avoid leaving an untracked invitation after a failed bind.
                    try:
                        await revoke_campaign_invite(
                            bot, chat_id=snapshot["chat_id"], invite_link=link)
                    except Exception:
                        # Telegram may be unavailable: do not falsely claim cleanup.
                        raise HTTPException(
                            status_code=503,
                            detail="Invite binding failed; manual Telegram revocation required",
                        ) from None
                    raise
            finally:
                await bot.session.close()
        except HTTPException:
            raise
        except KeyError:
            raise HTTPException(status_code=404, detail="Campaign not found") from None
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid campaign or invite") from None
        except (sqlite3.Error, OSError):
            raise HTTPException(status_code=503, detail="Campaign storage unavailable") from None
        except Exception:
            raise HTTPException(status_code=502, detail="Telegram invite unavailable") from None
        return {"campaign_id": campaign_id, "invite_link": link}

    @router.post("/{campaign_id}/state")
    async def change_state(campaign_id: str, data: StateRequest, owner=Depends(authorized_store)):
        store, owner_id = owner
        if data.action not in {"start", "pause", "resume", "stop"}:
            raise HTTPException(status_code=422, detail="Invalid action")
        try:
            state = store.change_campaign_state(
                actor_id=owner_id, owner_id=owner_id,
                campaign_id=campaign_id, action=data.action)
        except KeyError:
            raise HTTPException(status_code=404, detail="Campaign not found") from None
        except ValueError:
            raise HTTPException(status_code=409, detail="Invalid campaign transition") from None
        except (sqlite3.Error, OSError):
            raise HTTPException(status_code=503, detail="Campaign storage unavailable") from None
        result = {"campaign_id": campaign_id, "state": state}
        if data.action == "stop":
            try:
                await dispatch_campaign_revocations(store, limit=5)
            except (sqlite3.Error, OSError, ValueError, RuntimeError):
                logging.getLogger(__name__).warning(
                    "Campaign invite revocation deferred; retry is persisted"
                )
            result["invite_revocation"] = store.campaign_snapshot(
                actor_id=owner_id, owner_id=owner_id,
                campaign_id=campaign_id,
            )["invite_revocation"]
        return result

    @router.get("/{campaign_id}")
    async def snapshot(campaign_id: str, owner=Depends(authorized_store)):
        store, owner_id = owner
        try:
            return store.campaign_snapshot(
                actor_id=owner_id, owner_id=owner_id, campaign_id=campaign_id)
        except (KeyError, ValueError):
            raise HTTPException(status_code=404, detail="Campaign not found") from None
        except (sqlite3.Error, OSError):
            raise HTTPException(status_code=503, detail="Campaign storage unavailable") from None

    return router
