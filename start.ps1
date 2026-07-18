Write-Host '=== AnomalyDetect - Setup ==='

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host '.env criado. Configure OLLAMA_MODEL no arquivo .env'
}

Write-Host 'Iniciando banco de dados...'
docker compose up -d db

Write-Host 'Aguardando PostgreSQL (10s)...'
Start-Sleep -Seconds 10

Write-Host 'Iniciando backend e Ollama...'
docker compose up -d backend ollama

Write-Host 'Aguardando backend (8s)...'
Start-Sleep -Seconds 8

Write-Host 'Iniciando frontend...'
docker compose up -d frontend

Write-Host ''
Write-Host '=== Sistema iniciado! ==='
Write-Host '  Frontend:  http://localhost:3000'
Write-Host '  Backend:   http://localhost:8000'
Write-Host '  API Docs:  http://localhost:8000/docs'
Write-Host ''
Write-Host 'Para baixar o modelo no Ollama:'
Write-Host '  docker exec -it tcc-ollama-1 ollama pull llama3.2'
