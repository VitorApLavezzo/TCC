from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.core.security import decode_token
from app.models.user import User
from app.models.machine import Machine

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if not payload:
        raise credentials_exception
    user_id: int = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user or not user.is_active:
        raise credentials_exception
    return user


def get_machine_by_token(x_agent_token: str = Header(...), db: Session = Depends(get_db)) -> Machine:
    # is_active=False significa "coleta pausada", não "acesso revogado" — o token continua válido
    # e o endpoint de ingest decide descartar os dados
    machine = db.query(Machine).filter(Machine.agent_token == x_agent_token).first()
    if not machine:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid agent token")
    return machine
