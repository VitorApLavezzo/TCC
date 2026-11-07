Write-Host '=== AnomalyDetect - Setup ==='

if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    # Chave de sessão e senha do banco próprias desta instalação
    function Gerar { $b = New-Object byte[] 48; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_') }
    $chave = Gerar; $senha = Gerar
    (Get-Content '.env') -replace '^SECRET_KEY=.*', "SECRET_KEY=$chave" -replace '^POSTGRES_PASSWORD=.*', "POSTGRES_PASSWORD=$senha" | Set-Content '.env'
    Write-Host '.env criado com SECRET_KEY e POSTGRES_PASSWORD aleatorias. Configure OLLAMA_MODEL no arquivo .env'
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
