/**
 * Gera instaladores personalizados do agente com o código de pareamento
 * (máquina nova) ou o token (máquina existente) e o endereço do servidor
 * já embutidos — o usuário só dá dois cliques.
 */

export type InstallerAuth =
  | { code: string; token?: undefined }
  | { token: string; code?: undefined };

function authEnvBat(auth: InstallerAuth): string {
  return auth.code !== undefined
    ? `set "AGENT_ENROLL_CODE=${auth.code}"`
    : `set "AGENT_API_TOKEN=${auth.token}"`;
}

function authEnvSh(auth: InstallerAuth): string {
  return auth.code !== undefined
    ? `AGENT_ENROLL_CODE="${auth.code}"`
    : `AGENT_API_TOKEN="${auth.token}"`;
}

export function isLocalOrigin(): boolean {
  return /^https?:\/\/(localhost|127\.0\.0\.1|\[::1\])(:|$)/i.test(window.location.origin);
}

/**
 * Endereço do servidor visto PELAS OUTRAS MÁQUINAS. Se o painel está sendo
 * acessado por localhost, esse endereço não funciona fora desta máquina —
 * pergunta ao usuário o endereço de rede e memoriza a resposta.
 */
function resolveServerUrl(interactive: boolean): string | null {
  const origin = window.location.origin;
  if (!isLocalOrigin()) return origin;

  const saved = localStorage.getItem("public_server_url");
  if (!interactive) return saved || origin;

  const input = window.prompt(
    "Você está acessando o painel por 'localhost', mas a máquina que vai receber o agente " +
      "precisa do endereço de REDE deste servidor.\n\n" +
      "Digite o endereço que as outras máquinas usarão (ex: http://192.168.0.10:3000):",
    saved || `http://${window.location.hostname}:${window.location.port || "3000"}`
  );
  if (!input) return null;
  const url = input.trim().replace(/\/+$/, "");
  localStorage.setItem("public_server_url", url);
  return url;
}

export function serverOneLiner(auth: InstallerAuth): string {
  const server = resolveServerUrl(false) ?? window.location.origin;
  const param = auth.code !== undefined ? `code=${auth.code}` : `token=${auth.token}`;
  return `curl -fsS "${server}/api/agent/install.sh?${param}&server=${server}" | bash`;
}

export function windowsInstaller(serverUrl: string, auth: InstallerAuth): string {
  const script = `@echo off
title AnomalyDetect - Instalador do Agente
echo ============================================
echo   AnomalyDetect - Instalando o agente...
echo ============================================
echo.

set "SERVER=${serverUrl}"
set "DIR=%LOCALAPPDATA%\\AnomalyDetect"
set "STARTUP=%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"

rem --- 1. Verifica se o Python esta instalado ---
python --version >nul 2>nul
if errorlevel 1 (
    echo Python nao encontrado. Tentando instalar automaticamente...
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo.
        echo ERRO: nao foi possivel instalar o Python automaticamente.
        echo Baixe em https://www.python.org/downloads/ , instale marcando
        echo a opcao "Add python.exe to PATH" e execute este instalador de novo.
        pause
        exit /b 1
    )
    echo.
    echo Python instalado! FECHE esta janela e execute o instalador NOVAMENTE.
    pause
    exit /b 0
)

rem --- 2. Baixa os arquivos do agente ---
mkdir "%DIR%" 2>nul
cd /d "%DIR%"
echo Baixando o agente do servidor...
curl -fsS "%SERVER%/api/agent/download/agent.py" -o agent.py
if errorlevel 1 goto :fail
curl -fsS "%SERVER%/api/agent/download/collector.py" -o collector.py
if errorlevel 1 goto :fail
curl -fsS "%SERVER%/api/agent/download/requirements.txt" -o requirements.txt
if errorlevel 1 goto :fail

rem --- 3. Instala dependencias ---
echo Instalando dependencias (pode levar alguns minutos)...
python -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :fail

rem --- 4. Pareamento com o servidor ---
echo Registrando esta maquina no painel...
set "AGENT_API_URL=%SERVER%"
${authEnvBat(auth)}
python agent.py --enroll-only
if errorlevel 1 goto :fail

rem --- 5. Inicia junto com o Windows (sem janela) ---
(
echo Set sh = CreateObject("WScript.Shell"^)
echo sh.CurrentDirectory = "%DIR%"
echo sh.Run "pythonw agent.py", 0, False
) > "%STARTUP%\\AnomalyDetectAgent.vbs"

rem --- Atalho no Menu Iniciar (para reiniciar apos clicar em "Sair") ---
copy /y "%STARTUP%\\AnomalyDetectAgent.vbs" "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\AnomalyDetect Agent.vbs" >nul

rem --- 6. Encerra instancia antiga (se houver) e inicia agora ---
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*AnomalyDetect*agent.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul
wscript "%STARTUP%\\AnomalyDetectAgent.vbs"

echo.
echo ============================================
echo   Instalacao concluida com sucesso!
echo   A maquina ja deve aparecer no painel.
echo ============================================
pause
exit /b 0

:fail
echo.
echo Ocorreu um erro durante a instalacao.
echo Verifique sua conexao com o servidor e tente novamente.
pause
exit /b 1
`;
  // cmd.exe é mais confiável com CRLF
  return script.replace(/\n/g, "\r\n");
}

export function linuxInstaller(serverUrl: string, auth: InstallerAuth): string {
  return `#!/usr/bin/env bash
# AnomalyDetect - Instalador do Agente (Linux)
set -e

SERVER="${serverUrl}"
DIR="$HOME/.anomalydetect"

echo "============================================"
echo "  AnomalyDetect - Instalando o agente..."
echo "============================================"

command -v python3 >/dev/null || { echo "ERRO: instale o python3 primeiro (ex: sudo apt install python3 python3-pip python3-venv)"; exit 1; }

mkdir -p "$DIR"
cd "$DIR"

echo "Baixando o agente do servidor..."
curl -fsS "$SERVER/api/agent/download/agent.py" -o agent.py
curl -fsS "$SERVER/api/agent/download/collector.py" -o collector.py
curl -fsS "$SERVER/api/agent/download/requirements.txt" -o requirements.txt

echo "Instalando dependências..."
# --system-site-packages: deixa o venv usar o PyGObject (gi) do sistema,
# necessário para o ícone de bandeja usar o backend GTK (menu funcional)
if python3 -m venv --system-site-packages venv 2>/dev/null; then
    PY="$DIR/venv/bin/python"
else
    PY="python3"
fi
"$PY" -m pip install --quiet -r requirements.txt

echo "Registrando esta máquina no painel..."
AGENT_API_URL="$SERVER" ${authEnvSh(auth)} "$PY" agent.py --enroll-only

echo "Configurando início automático..."
# Remove o serviço systemd de versões antigas do instalador (respawnava o agente sozinho)
systemctl --user disable --now anomalydetect-agent 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/anomalydetect-agent.service"
systemctl --user daemon-reload 2>/dev/null || true

mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/anomalydetect-agent.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AnomalyDetect Agent
Comment=Monitoramento e detecção de anomalias
Exec=$PY $DIR/agent.py
Path=$DIR
X-GNOME-Autostart-enabled=true
EOF

# Entrada no menu de aplicativos — para reiniciar o agente após clicar em "Sair"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/anomalydetect-agent.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=AnomalyDetect Agent
Comment=Iniciar o monitoramento desta máquina
Exec=$PY $DIR/agent.py
Path=$DIR
Icon=utilities-system-monitor
Categories=Utility;Monitor;
Terminal=false
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Iniciando o agente..."
pkill -f "$DIR/agent.py" 2>/dev/null && sleep 1 || true
nohup "$PY" "$DIR/agent.py" >/dev/null 2>&1 &
disown

echo ""
echo "============================================"
echo "  Instalação concluída com sucesso!"
echo "  A máquina já deve aparecer no painel."
echo ""
echo "  Um ícone azul aparece na bandeja do"
echo "  sistema — para parar o agente, clique"
echo "  nele e escolha 'Sair'."
echo "============================================"
`;
}

/**
 * Variante SILENCIOSA do instalador Windows, para distribuição em massa via GPO
 * (script de inicialização do computador, rodando como SYSTEM antes do login).
 * Diferenças da variante interativa:
 * - Nenhum `pause`/prompt — precisa rodar sem ninguém na frente da tela
 * - Não tenta instalar Python via winget (winget é pouco confiável em contexto
 *   SYSTEM/sem sessão interativa) — assume Python já presente na imagem/baseline de TI
 * - Sem ícone de bandeja (`--no-tray`): sessão SYSTEM não tem área de trabalho
 * - Usa o Agendador de Tarefas (schtasks, gatilho ONSTART como SYSTEM) em vez da
 *   pasta Startup — assim o agente roda sempre, mesmo sem nenhum usuário logado
 */
export function windowsSilentInstaller(serverUrl: string, auth: InstallerAuth): string {
  const script = `@echo off
setlocal
set "SERVER=${serverUrl}"
set "DIR=%ProgramData%\\AnomalyDetect"
set "LOG=%DIR%\\install.log"

where python >nul 2>nul
if errorlevel 1 (
    echo [%date% %time%] Python nao encontrado - instale via imagem/baseline de TI antes de distribuir. >> "%LOG%"
    exit /b 1
)

mkdir "%DIR%" 2>nul
cd /d "%DIR%"
curl -fsS "%SERVER%/api/agent/download/agent.py" -o agent.py >> "%LOG%" 2>&1
curl -fsS "%SERVER%/api/agent/download/collector.py" -o collector.py >> "%LOG%" 2>&1
curl -fsS "%SERVER%/api/agent/download/requirements.txt" -o requirements.txt >> "%LOG%" 2>&1
python -m pip install --quiet --disable-pip-version-check -r requirements.txt >> "%LOG%" 2>&1

set "AGENT_API_URL=%SERVER%"
${authEnvBat(auth)}
python agent.py --enroll-only >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [%date% %time%] Falha no pareamento >> "%LOG%"
    exit /b 1
)

schtasks /create /tn "AnomalyDetect Agent" /tr "pythonw \\"%DIR%\\agent.py\\" --no-tray" /sc onstart /ru SYSTEM /rl highest /f >> "%LOG%" 2>&1
schtasks /run /tn "AnomalyDetect Agent" >> "%LOG%" 2>&1

echo [%date% %time%] Instalacao concluida >> "%LOG%"
exit /b 0
`;
  return script.replace(/\n/g, "\r\n");
}

/**
 * Script para instalar em N computadores de uma vez via PowerShell Remoting (WinRM),
 * a partir de UMA máquina de TI com credenciais de administrador — em vez de logar
 * em cada computador individualmente. Usa a chave reutilizável de instalação em massa.
 */
export function massDeployPowerShell(serverUrl: string, bulkKeyCode: string): string {
  return `# AnomalyDetect - Instalacao em massa via PowerShell Remoting (WinRM)
#
# PRE-REQUISITOS:
# - WinRM habilitado nos computadores de destino (em dominios AD, normalmente ja
#   esta ou pode ser ligado via GPO "Windows Remote Management"; para testar em
#   1 maquina: Enable-PSRemoting -Force)
# - Voce precisa ter permissao de administrador nessas maquinas (conta de dominio)
# - Python 3 instalado nos computadores de destino (baseline/imagem de TI)
#
# USO:
# 1. Crie um arquivo computadores.txt com um hostname ou IP por linha
# 2. Ajuste $server e $bulkKey abaixo se necessario
# 3. Execute este script em uma janela do PowerShell "Executar como administrador"

$computers = Get-Content ".\\computadores.txt"
$server = "${serverUrl}"
$bulkKey = "${bulkKeyCode}"

$installScript = {
    param($server, $bulkKey)
    $dir = "$env:ProgramData\\AnomalyDetect"
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Set-Location $dir
    Invoke-WebRequest "$server/api/agent/download/agent.py" -OutFile agent.py -UseBasicParsing
    Invoke-WebRequest "$server/api/agent/download/collector.py" -OutFile collector.py -UseBasicParsing
    Invoke-WebRequest "$server/api/agent/download/requirements.txt" -OutFile requirements.txt -UseBasicParsing
    python -m pip install --quiet --disable-pip-version-check -r requirements.txt

    $env:AGENT_API_URL = $server
    $env:AGENT_ENROLL_CODE = $bulkKey
    python agent.py --enroll-only

    schtasks /create /tn "AnomalyDetect Agent" /tr "pythonw \`"$dir\\agent.py\`" --no-tray" /sc onstart /ru SYSTEM /rl highest /f
    schtasks /run /tn "AnomalyDetect Agent"
}

foreach ($c in $computers) {
    Write-Host "Instalando em $c..." -NoNewline
    try {
        Invoke-Command -ComputerName $c -ScriptBlock $installScript -ArgumentList $server, $bulkKey -ErrorAction Stop
        Write-Host " OK" -ForegroundColor Green
    } catch {
        Write-Host " FALHOU: $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Concluido. As maquinas que tiveram sucesso ja devem aparecer no painel."
`;
}

export function downloadMassDeployScript(bulkKeyCode: string) {
  const serverUrl = resolveServerUrl(true);
  if (!serverUrl) return;
  const content = massDeployPowerShell(serverUrl, bulkKeyCode);
  const blob = new Blob([content], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "instalar-em-massa.ps1";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function downloadSilentInstaller(bulkKeyCode: string) {
  const serverUrl = resolveServerUrl(true);
  if (!serverUrl) return;
  const content = windowsSilentInstaller(serverUrl, { code: bulkKeyCode });
  const blob = new Blob([content], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "instalar-silencioso-gpo.bat";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function windowsUninstaller(serverUrl: string, token: string): string {
  const script = `@echo off
title AnomalyDetect - Remover monitoramento
echo ============================================
echo   AnomalyDetect - Removendo o monitoramento
echo ============================================
echo.

echo Encerrando o agente...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*AnomalyDetect*agent.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>nul

echo Removendo este computador do painel...
curl -fsS -X DELETE "${serverUrl}/api/agent/self" -H "X-Agent-Token: ${token}" >nul 2>nul

echo Apagando os arquivos...
rmdir /s /q "%LOCALAPPDATA%\\AnomalyDetect" 2>nul
del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\AnomalyDetectAgent.vbs" 2>nul
del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\AnomalyDetect Agent.vbs" 2>nul

echo.
echo ============================================
echo   Pronto! O monitoramento foi removido e o
echo   computador ja sumiu do painel.
echo ============================================
pause
`;
  return script.replace(/\n/g, "\r\n");
}

export function linuxUninstaller(serverUrl: string, token: string): string {
  return `#!/usr/bin/env bash
# AnomalyDetect - Remover monitoramento deste computador
echo "============================================"
echo "  AnomalyDetect - Removendo o monitoramento"
echo "============================================"

echo "Encerrando o agente..."
pkill -f ".anomalydetect/agent.py" 2>/dev/null || true
pkill -f ".anomalydetect/venv" 2>/dev/null || true

echo "Removendo este computador do painel..."
curl -fsS -X DELETE "${serverUrl}/api/agent/self" -H "X-Agent-Token: ${token}" >/dev/null 2>&1 || true

echo "Apagando os arquivos..."
rm -rf "$HOME/.anomalydetect"
rm -f "$HOME/.config/autostart/anomalydetect-agent.desktop"
rm -f "$HOME/.local/share/applications/anomalydetect-agent.desktop"
systemctl --user disable --now anomalydetect-agent 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/anomalydetect-agent.service"
( crontab -l 2>/dev/null | grep -v "anomalydetect/agent.py" ) | crontab - 2>/dev/null || true

echo ""
echo "============================================"
echo "  Pronto! O monitoramento foi removido e o"
echo "  computador já sumiu do painel."
echo "============================================"
`;
}

export function downloadUninstaller(os: "windows" | "linux", token: string) {
  const serverUrl = resolveServerUrl(true);
  if (!serverUrl) return;
  const isWin = os === "windows";
  const content = isWin ? windowsUninstaller(serverUrl, token) : linuxUninstaller(serverUrl, token);
  const blob = new Blob([content], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = isWin ? "remover-anomalydetect.bat" : "remover-anomalydetect.sh";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function downloadInstaller(os: "windows" | "linux", auth: InstallerAuth) {
  const serverUrl = resolveServerUrl(true);
  if (!serverUrl) return;
  const isWin = os === "windows";
  const content = isWin
    ? windowsInstaller(serverUrl, auth)
    : linuxInstaller(serverUrl, auth);
  const blob = new Blob([content], { type: "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = isWin ? "instalar-anomalydetect.bat" : "instalar-anomalydetect.sh";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
