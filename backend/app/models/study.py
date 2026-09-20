from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func
from app.database import Base


class StudySession(Base):
    """Uma pessoa participando do estudo de compreensão.

    A tese do trabalho é que um leigo entende a explicação da IA melhor do que
    entende a métrica crua. Isso não se demonstra com a opinião de quem
    programou: cada participante recebe os mesmos avisos, metade com explicação
    e metade só com os números, em ordem sorteada, e o sistema mede tempo,
    acerto da causa e confiança — além do questionário SUS no fim.
    """
    __tablename__ = "study_sessions"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Código anônimo do participante (P01, P02); nada que identifique alguém
    participant_code = Column(String, nullable=False)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))

    # Autodeclarado, para separar leigos de quem é da área
    expertise = Column(String)  # leigo | intermediario | tecnico
    # Sorteio: quais itens vieram com explicação e quais vieram crus
    assignment = Column(JSON)
    # As 10 respostas do SUS (1 a 5) e a nota calculada (0 a 100)
    sus_answers = Column(JSON)
    sus_score = Column(Float)
    notes = Column(Text)


class StudyResponse(Base):
    """Resposta de um participante a um item do estudo."""
    __tablename__ = "study_responses"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(Integer, ForeignKey("study_sessions.id"), nullable=False, index=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), nullable=True)
    item_index = Column(Integer, nullable=False)
    # ai = viu a explicação; raw = viu apenas as métricas
    arm = Column(String, nullable=False)

    shown_at = Column(DateTime(timezone=True), server_default=func.now())
    answered_at = Column(DateTime(timezone=True))
    seconds = Column(Float)

    chosen_cause = Column(String)
    correct_cause = Column(String)
    is_correct = Column(Boolean)
    # A ação que a pessoa tomaria, e o quanto confia nela (1 a 5)
    chosen_action = Column(String)
    confidence = Column(Integer)
    helpful = Column(Integer)
