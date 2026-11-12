import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import audit, get_current_user, get_project
from app.models import ExportRecord, Project, User
from app.services.exporter import EXPORT_TYPES, build_sheets, to_csv, to_xlsx

router = APIRouter(prefix="/projects/{project_id}/exports", tags=["exports"])


@router.get("/types")
def export_types(_project: Project = Depends(get_project)):
    return [{"key": k, "label": v} for k, v in EXPORT_TYPES.items()]


@router.get("/history")
def history(project: Project = Depends(get_project), db: Session = Depends(get_db)):
    rows = db.execute(select(ExportRecord).where(ExportRecord.project_id == project.id).order_by(ExportRecord.id.desc()).limit(100)).scalars()
    return [{"id": r.id, "export_type": r.export_type, "label": EXPORT_TYPES.get(r.export_type, r.export_type),
             "file_format": r.file_format, "row_count": r.row_count, "filename": r.filename, "created_at": r.created_at} for r in rows]


@router.get("/{export_type}")
def export(export_type: str, format: str = Query("xlsx", pattern="^(xlsx|csv)$"), project: Project = Depends(get_project),
           user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if export_type not in EXPORT_TYPES:
        raise HTTPException(404, "Unknown export type")
    sheets = build_sheets(db, project.id, export_type)
    slug = re.sub(r"[^a-z0-9]+", "-", project.domain.lower()).strip("-")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    filename = f"{slug}-{export_type.replace('_', '-')}-{stamp}.{format}"
    if format == "xlsx":
        data = to_xlsx(project, export_type, sheets)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        data = to_csv(sheets)
        media = "text/csv; charset=utf-8"
    db.add(ExportRecord(project_id=project.id, user_id=user.id, export_type=export_type, file_format=format,
                        row_count=len(sheets[0][2]) if sheets else 0, filename=filename))
    audit(db, user, project.id, "export", export_type=export_type, format=format)
    db.commit()
    return Response(content=data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
