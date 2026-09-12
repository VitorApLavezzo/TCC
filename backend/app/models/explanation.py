from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class AIExplanation(Base):
    __tablename__ = "ai_explanations"

    id = Column(Integer, primary_key=True, index=True)
    anomaly_id = Column(Integer, ForeignKey("anomalies.id"), unique=True, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    model_used = Column(String)

    summary = Column(Text, nullable=False)
    detailed_explanation = Column(Text)
    possible_causes = Column(JSON)
    recommendations = Column(JSON)
    severity_justification = Column(Text)

    # Nível de linguagem desta versão ("leigo", "intermediario", "tecnico") e as
    # outras versões já pedidas, por nível
    language_level = Column(String)
    variants = Column(JSON)

    # Fatos numerados que a IA pode citar, e o resultado da checagem de que os
    # números do texto existem de fato nos dados
    evidence = Column(JSON)
    verification = Column(JSON)
    # "Se você fechar X, a memória cai para Y"
    counterfactual = Column(JSON)

    # Auditoria: texto exatamente como foi enviado, resposta crua, tentativas
    prompt_text = Column(Text)
    raw_response = Column(Text)
    provider_attempts = Column(JSON)
    data_destination = Column(String)  # local | cloud | none
    duration_ms = Column(Integer)

    # Avaliação: nota da pessoa e da IA-juíza
    user_rating = Column(Integer)  # 1 útil, -1 não ajudou
    user_rating_comment = Column(Text)
    judge_scores = Column(JSON)
    judge_model = Column(String)

    anomaly = relationship("Anomaly", back_populates="explanation")
