from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.providers import ANTHROPIC_MODELS, OPENAI_MODELS, PRICING
from app.config import get_settings
from app.db import get_db
from app.deps import audit, get_current_user
from app.models import AIUsageLog, Project, ProviderCredential, User
from app.schemas import CredentialIn
from app.security import encrypt_secret

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/ai")
def ai_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = get_settings()
    creds = {c.provider: c for c in db.execute(select(ProviderCredential).where(ProviderCredential.user_id == user.id)).scalars()}
    return {
        "default_provider": s.default_ai_provider,
        "providers": [
            {"provider": "anthropic", "models": ANTHROPIC_MODELS, "default_model": s.default_anthropic_model,
             "env_key_configured": bool(s.anthropic_api_key),
             "stored_key": ({"hint": creds["anthropic"].key_hint, "updated_at": creds["anthropic"].updated_at} if "anthropic" in creds else None)},
            {"provider": "openai", "models": OPENAI_MODELS, "default_model": s.default_openai_model,
             "env_key_configured": bool(s.openai_api_key),
             "stored_key": ({"hint": creds["openai"].key_hint, "updated_at": creds["openai"].updated_at} if "openai" in creds else None)},
        ],
        "pricing_per_million_tokens": {k: {"input": v[0], "output": v[1], "cache_read": v[2]} for k, v in PRICING.items()},
    }


@router.put("/ai/credentials")
def save_credential(body: CredentialIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Keys are encrypted at rest and never returned by the API (only a 4-character hint)."""
    cred = db.execute(select(ProviderCredential).where(ProviderCredential.user_id == user.id,
                                                       ProviderCredential.provider == body.provider)).scalar_one_or_none()
    key = body.api_key.strip()
    if cred is None:
        cred = ProviderCredential(user_id=user.id, provider=body.provider, encrypted_key="")
        db.add(cred)
    cred.encrypted_key = encrypt_secret(key)
    cred.key_hint = "…" + key[-4:]
    audit(db, user, None, "credential.save", provider=body.provider)
    db.commit()
    return {"ok": True, "hint": cred.key_hint}


@router.delete("/ai/credentials/{provider}", status_code=204)
def delete_credential(provider: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cred = db.execute(select(ProviderCredential).where(ProviderCredential.user_id == user.id,
                                                       ProviderCredential.provider == provider)).scalar_one_or_none()
    if cred:
        db.delete(cred)
        audit(db, user, None, "credential.delete", provider=provider)
        db.commit()


@router.get("/usage")
def usage_overview(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Project.id, Project.name, func.count(AIUsageLog.id), func.coalesce(func.sum(AIUsageLog.cost_usd), 0),
               func.coalesce(func.sum(AIUsageLog.input_tokens + AIUsageLog.output_tokens + AIUsageLog.cache_read_tokens), 0))
        .outerjoin(AIUsageLog, AIUsageLog.project_id == Project.id)
        .where(Project.owner_id == user.id).group_by(Project.id, Project.name)
    ).all()
    return [{"project_id": r[0], "project": r[1], "calls": r[2], "cost_usd": round(float(r[3]), 4), "tokens": int(r[4])} for r in rows]
