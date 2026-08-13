from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.errors import ok
from app.schemas import LoginRequest, RegisterRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/register")
def register(req: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    return ok(auth_service.register(db, req.name, req.password, _client_ip(request)))


@router.post("/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    return ok(auth_service.login(db, req.name, req.password, _client_ip(request)))
