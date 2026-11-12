from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.crawler.url_utils import UnsafeURLError, assert_public_url, ensure_scheme, normalize_url
from app.db import get_db
from app.deps import audit, get_current_user, get_project
from app.models import GuidelineVersion, Project, User
from app.schemas import GuidelineIn, GuidelineOut, ProjectIn, ProjectOut, ProjectUpdate
from app.seo.guidelines import (
    DEFAULT_BRAND_CONTEXT,
    DEFAULT_GUARDRAILS,
    DEFAULT_SEO_GUIDELINES,
    active_guideline,
    merge_defaults,
)

router = APIRouter(prefix="/projects", tags=["projects"])


def _validate_base_url(raw: str) -> tuple[str, str]:
    url = normalize_url(ensure_scheme(raw))
    if not url:
        raise HTTPException(422, "Enter a valid http(s) website URL, e.g. https://www.example.com")
    try:
        assert_public_url(url, get_settings().allow_private_networks)
    except UnsafeURLError as exc:
        raise HTTPException(422, f"This URL cannot be crawled: {exc}") from exc
    return url, urlsplit(url).hostname or ""


@router.get("", response_model=list[ProjectOut])
def list_projects(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.execute(select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc())).scalars().all()


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    url, host = _validate_base_url(body.base_url)
    p = Project(owner_id=user.id, name=body.name.strip(), base_url=url, domain=host,
                primary_market=body.primary_market, language=body.language, target_country=body.target_country,
                target_audience=body.target_audience, business_category=body.business_category,
                crawl_settings=body.crawl_settings.model_dump(), ai_settings=body.ai_settings.model_dump())
    db.add(p)
    db.flush()
    # Every project starts with its own, independent guideline set (v1).
    db.add(GuidelineVersion(project_id=p.id, version=1, is_active=True,
                            brand_context={**DEFAULT_BRAND_CONTEXT, "brand_name": body.name.strip(),
                                           "brand_category": body.business_category,
                                           "target_audience": body.target_audience,
                                           "target_geography": body.target_country},
                            seo_guidelines=DEFAULT_SEO_GUIDELINES, guardrails=DEFAULT_GUARDRAILS, keywords=[],
                            custom_instructions="", change_note="Initial defaults", created_by=user.id))
    audit(db, user, p.id, "project.create", base_url=url)
    db.commit()
    db.refresh(p)
    return p


@router.get("/{project_id}", response_model=ProjectOut)
def get_one(project: Project = Depends(get_project)):
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(body: ProjectUpdate, project: Project = Depends(get_project), user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        if v is not None:
            setattr(project, k, v)
    audit(db, user, project.id, "project.update", fields=list(data))
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(project: Project = Depends(get_project), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    audit(db, user, None, "project.delete", project_id=project.id, name=project.name)
    db.delete(project)
    db.commit()


# ------------------------------------------------------------------ Brand SEO Intelligence


@router.get("/{project_id}/guidelines", response_model=GuidelineOut | None)
def current_guidelines(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    g = active_guideline(db, project.id)
    if g is None:
        return None
    out = GuidelineOut.model_validate(g)
    out.brand_context = merge_defaults(DEFAULT_BRAND_CONTEXT, g.brand_context)
    out.seo_guidelines = merge_defaults(DEFAULT_SEO_GUIDELINES, g.seo_guidelines)
    out.guardrails = merge_defaults(DEFAULT_GUARDRAILS, g.guardrails)
    return out


@router.get("/{project_id}/guidelines/versions", response_model=list[GuidelineOut])
def guideline_versions(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    return db.execute(select(GuidelineVersion).where(GuidelineVersion.project_id == project.id)
                      .order_by(GuidelineVersion.version.desc())).scalars().all()


@router.post("/{project_id}/guidelines", response_model=GuidelineOut, status_code=201)
def save_guidelines(body: GuidelineIn, project: Project = Depends(get_project), user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Saving always creates a new version; previous versions are kept for comparison/restore."""
    last = db.execute(select(GuidelineVersion.version).where(GuidelineVersion.project_id == project.id)
                      .order_by(GuidelineVersion.version.desc())).scalars().first() or 0
    db.execute(update(GuidelineVersion).where(GuidelineVersion.project_id == project.id).values(is_active=False))
    g = GuidelineVersion(
        project_id=project.id, version=last + 1, is_active=True,
        brand_context=merge_defaults(DEFAULT_BRAND_CONTEXT, body.brand_context),
        seo_guidelines=merge_defaults(DEFAULT_SEO_GUIDELINES, body.seo_guidelines),
        guardrails=merge_defaults(DEFAULT_GUARDRAILS, body.guardrails),
        keywords=[k.model_dump() for k in body.keywords],
        custom_instructions=body.custom_instructions, change_note=body.change_note, created_by=user.id,
    )
    db.add(g)
    audit(db, user, project.id, "guidelines.save", version=last + 1)
    db.commit()
    db.refresh(g)
    return g


@router.post("/{project_id}/guidelines/{version}/restore", response_model=GuidelineOut, status_code=201)
def restore_guidelines(version: int, project: Project = Depends(get_project), user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    src = db.execute(select(GuidelineVersion).where(GuidelineVersion.project_id == project.id,
                                                    GuidelineVersion.version == version)).scalar_one_or_none()
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    body = GuidelineIn(brand_context=src.brand_context, seo_guidelines=src.seo_guidelines, guardrails=src.guardrails,
                       keywords=src.keywords, custom_instructions=src.custom_instructions,
                       change_note=f"Restored from v{version}")
    return save_guidelines(body, project, user, db)
