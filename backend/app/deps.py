from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, Page, Project, User
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)


def get_current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    uid = decode_access_token(creds.credentials)
    user = db.get(User, uid) if uid else None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session")
    return user


def get_project(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Project:
    """Every project-scoped route goes through this: projects are only visible to their owner."""
    project = db.execute(select(Project).where(Project.id == project_id, Project.owner_id == user.id)).scalar_one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    return project


def get_page(project: Project, page_id: int, db: Session) -> Page:
    page = db.execute(select(Page).where(Page.id == page_id, Page.project_id == project.id)).scalar_one_or_none()
    if page is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found in this project")
    return page


def audit(db: Session, user: User | None, project_id: int | None, action: str, **details) -> None:
    db.add(AuditLog(user_id=user.id if user else None, project_id=project_id, action=action, details=details))
