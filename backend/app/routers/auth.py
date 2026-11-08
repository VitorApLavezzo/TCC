import secrets
import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt as jose_jwt
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserOut, Token
from app.core.security import get_password_hash, verify_password, create_access_token
from app.core.dependencies import get_current_user
from app.core.ratelimit import limit

router = APIRouter(prefix="/api/auth", tags=["auth"])

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleLogin(BaseModel):
    credential: str


@router.get("/config")
def auth_config():
    """Configurações públicas de autenticação para o frontend."""
    return {"google_client_id": settings.GOOGLE_CLIENT_ID or None}


def _claims_google(credential: str) -> dict:
    """Confere a assinatura e o destinatário do token do Google; devolve as claims."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Login com Google não configurado")
    try:
        certs = httpx.get(GOOGLE_CERTS_URL, timeout=10).json()
        header = jose_jwt.get_unverified_header(credential)
        key = next((k for k in certs["keys"] if k["kid"] == header["kid"]), None)
        if not key:
            raise ValueError("Chave de assinatura não encontrada")
        claims = jose_jwt.decode(
            credential,
            key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
        )
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise ValueError("Emissor inválido")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Token do Google inválido")
    if not claims.get("email") or claims.get("email_verified") is not True or not claims.get("sub"):
        raise HTTPException(status_code=401, detail="E-mail do Google não verificado")
    return claims


@router.post("/google", response_model=Token, dependencies=[Depends(limit("google", 20, 300))])
def google_login(body: GoogleLogin, db: Session = Depends(get_db)):
    claims = _claims_google(body.credential)
    email, sub = claims["email"], claims["sub"]

    user = db.query(User).filter(User.google_sub == sub).first()
    if not user:
        existing = db.query(User).filter(func.lower(User.email) == email.lower()).first()
        if existing and existing.google_link_allowed and not existing.google_sub:
            # O administrador conferiu que a conta é desta pessoa
            existing.google_sub = sub
            existing.google_link_allowed = False
            db.commit()
            user = existing
        elif existing:
            # Conta de senha com este e-mail: quem a criou não provou posse do e-mail, então o
            # vínculo é feito de dentro da conta ou pelo administrador.
            raise HTTPException(
                status_code=409,
                detail="Já existe uma conta com este e-mail. Se ela foi criada pelo botão do Google, "
                       "peça ao administrador do servidor para liberar o vínculo.",
            )
    if not user:
        # Primeiro acesso: cria a conta automaticamente
        base_username = email.split("@")[0]
        username = base_username
        suffix = 1
        while db.query(User).filter(User.username == username).first():
            suffix += 1
            username = f"{base_username}{suffix}"
        user = User(
            email=email,
            username=username,
            google_sub=sub,
            # Senha aleatória — conta Google entra sempre pelo botão do Google
            hashed_password=get_password_hash(secrets.token_urlsafe(24)),
        )
        db.add(user)
        db.commit()
        db.refresh(user)

    if not user.is_active:
        raise HTTPException(status_code=401, detail="Usuário desativado")

    token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.post("/google/link", status_code=status.HTTP_204_NO_CONTENT)
def google_link(body: GoogleLogin, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Vincula a conta Google à conta em que a pessoa já entrou com senha."""
    claims = _claims_google(body.credential)
    other = db.query(User).filter(User.google_sub == claims["sub"], User.id != current_user.id).first()
    if other:
        raise HTTPException(status_code=409, detail="Esta conta Google já está vinculada a outra conta.")
    current_user.google_sub = claims["sub"]
    db.commit()


# Cadastro e login são os dois pontos abertos a quem não tem conta: sem limite,
# adivinhar senha ou criar contas em massa custa só tempo de CPU do servidor.
@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(limit("register", 5, 3600))])
def register(user_in: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user_in.email).first():
        raise HTTPException(status_code=400, detail="Já existe uma conta com este e-mail")
    if db.query(User).filter(User.username == user_in.username).first():
        raise HTTPException(status_code=400, detail="Este nome de usuário já está em uso")
    user = User(
        email=user_in.email,
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token, dependencies=[Depends(limit("login", 10, 300))])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
