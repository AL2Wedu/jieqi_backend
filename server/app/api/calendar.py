from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.errors import ok
from app.services import calendar_service

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/current")
def current(db: Session = Depends(get_db)):
    return ok(calendar_service.current_calendar(db))
