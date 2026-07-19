#!/bin/bash
# Script de inicialização rápida para desenvolvimento

set -e

echo "=== AnomalyDetect - Setup ==="

if [ ! -f .env ]; then
    cp .env.example .env
    echo "✓ .env criado a partir do .env.example"
    echo "  → Configure OLLAMA_BASE_URL e CLOUD_LLM_API_KEY no .env"
fi

echo ""
echo "Iniciando serviços com Docker Compose..."
docker compose up -d db

echo "Aguardando PostgreSQL..."
sleep 5

docker compose up -d backend
echo "Aguardando backend..."
sleep 5

docker compose up -d frontend

echo ""
echo "=== Sistema iniciado! ==="
echo "  Frontend:  http://localhost:3000"
echo "  Backend:   http://localhost:8000"
echo "  API Docs:  http://localhost:8000/docs"
echo ""
echo "Para rodar o agente localmente:"
echo "  cd agent"
echo "  pip install -r requirements.txt"
echo "  AGENT_API_TOKEN=<token-da-maquina> python agent.py"
