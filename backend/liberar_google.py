"""
Libera o login com Google para uma conta que já existe.

O login com Google passou a prender a conta à identidade Google (o "sub"),
e não mais ao e-mail: antes, quem cadastrasse o e-mail de outra pessoa com
uma senha sua ficava com a conta em que ela entraria pelo Google. Contas
criadas pelo botão do Google antes disso não têm o vínculo e têm uma senha
aleatória que ninguém sabe, então ficam de fora. Este comando marca a conta
para que o próximo login Google com o mesmo e-mail a vincule.

Só libere contas que você sabe serem da pessoa dona do e-mail.

Execute: python liberar_google.py pessoa@exemplo.com
No Docker: docker compose exec backend python liberar_google.py pessoa@exemplo.com
"""
import sys

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.user import User


def liberar(db: Session, email: str) -> bool:
    user = db.query(User).filter(func.lower(User.email) == email.strip().lower()).first()
    if not user or user.google_sub:
        return False
    user.google_link_allowed = True
    db.commit()
    return True


def main(argv) -> int:
    if len(argv) != 2:
        print(__doc__.strip())
        return 2
    from app.core.migrations import upgrade_schema
    from app.database import SessionLocal, engine

    upgrade_schema(engine)
    db = SessionLocal()
    try:
        if liberar(db, argv[1]):
            print(f"Liberado: o próximo login com Google de {argv[1]} vincula a conta.")
            return 0
        print(f"Nada feito: não há conta com {argv[1]}, ou ela já está vinculada a uma conta Google.")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
