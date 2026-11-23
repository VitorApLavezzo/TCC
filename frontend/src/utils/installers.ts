/**
 * Gera instaladores personalizados do agente com o código de pareamento
 * (máquina nova) ou o token (máquina existente) e o endereço do servidor
 * já embutidos — o usuário só dá dois cliques.
 */

export type InstallerAuth =
  | { code: string; token?: undefined }
  | { token: string; code?: undefined };

/**
 * Arquivos do agente.
 *
 * `CORE` é o mínimo para o agente rodar — se algum falhar, a instalação para
 * com erro. `EXTRAS` são os sensores avançados (identidade de executáveis,
 * arquivos-isca, caixa-preta, ações): o agente importa cada um com `try`, e um
 * servidor de versão anterior simplesmente não os tem. Por isso a falha neles
 * é ignorada, em vez de derrubar a instalação inteira.
 */
const CORE_FILES = ["agent.py", "collector.py", "privacy.py", "requirements.txt"];
const EXTRA_FILES = ["sensors.py", "security.py", "inventory.py", "actions.py", "blackbox.py", "updater.py", "localguard.py"];

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
    "Você está acessando o painel por 'localhost', mas o computador que vai receber o agente " +
      "precisa do endereço de REDE deste servidor.\n\n" +
      "Digite o endereço que os outros computadores usarão (ex: http://192.168.0.10:3000):",
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

rem --- 1. Acha um Python que funcione ---
rem Perguntar a versao ao "python" do PATH nao serve: o winget instala o Python fora do
rem PATH, e sem ele "python" e o atalho da Microsoft Store, que nao executa nada. PY guarda
rem o comando encontrado e PYW o mesmo sem janela.
call :findpy
if not defined PY (
    echo Python nao encontrado. Instalando o Python 3.12, pode levar alguns minutos...
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    call :findpy
)
if not defined PY (
    echo.
    echo ERRO: nao foi possivel instalar o Python automaticamente.
    echo Baixe o Python 3.12 em https://www.python.org/downloads/ , instale marcando
    echo a opcao "Add python.exe to PATH" e execute este instalador de novo.
    pause
    exit /b 1
)
rem Dentro de um texto do VBS, as aspas do caminho precisam ser dobradas
set "PYW_VBS=%PYW:"=""%"

rem --- 2. Baixa os arquivos do agente ---
mkdir "%DIR%" 2>nul
cd /d "%DIR%"
echo Baixando o agente do servidor...
rem "if errorlevel" (sem %%) le o codigo no momento da execucao, entao funciona dentro do for
for %%F in (${CORE_FILES.join(" ")}) do (
    curl -fsS "%SERVER%/api/agent/download/%%F" -o "%%F"
    if errorlevel 1 goto :fail
)
rem Sensores avancados: servidor antigo pode nao te-los, e o agente funciona sem
for %%F in (${EXTRA_FILES.join(" ")}) do (
    curl -fsS "%SERVER%/api/agent/download/%%F" -o "%%F" 2>nul
)

rem --- 3. Instala dependencias ---
echo Instalando dependencias (pode levar alguns minutos)...
%PY% -m pip install --quiet --disable-pip-version-check --no-warn-conflicts -r requirements.txt
if errorlevel 1 goto :fail

rem --- 4. Pareamento com o servidor ---
echo Registrando esta maquina no painel...
set "AGENT_API_URL=%SERVER%"
${authEnvBat(auth)}
%PY% agent.py --enroll-only
if errorlevel 1 goto :fail

rem --- 5. Inicia junto com o Windows (sem janela) ---
(
echo Set sh = CreateObject("WScript.Shell"^)
echo sh.CurrentDirectory = "%DIR%"
echo sh.Run "%PYW_VBS% agent.py", 0, False
) > "%STARTUP%\\AnomalyDetectAgent.vbs"

rem --- Atalho no Menu Iniciar (para reiniciar apos clicar em "Sair") ---
copy /y "%STARTUP%\\AnomalyDetectAgent.vbs" "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\AnomalyDetect Agent.vbs" >nul

rem --- 6. Encerra instancia antiga (se houver) e inicia agora ---
rem O padrao e montado em pedacos de proposito: escrito inteiro, a linha de
rem comando deste PowerShell casaria com a propria busca e ele se mataria antes
rem de encerrar o agente, deixando duas instancias rodando.
powershell -NoProfile -Command "$meu=$PID; $alvo='agent'+'.py'; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $meu -and $_.Name -match 'python' -and $_.CommandLine -like ('*'+$alvo+'*') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>nul
ping -n 3 127.0.0.1 >nul
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

rem Primeiro o Python 3.12 (o que o winget instala e o que as dependencias esperam),
rem depois qualquer 3.9 a 3.13 que ja esteja no PATH
:findpy
set "PY="
set "PYW="
call :trycmd "py -3.12" "pyw -3.12"
call :trydir "%LOCALAPPDATA%\\Programs\\Python\\Python312"
call :trydir "%ProgramFiles%\\Python312"
call :trycmd "python" "pythonw"
call :trycmd "py -3" "pyw -3"
exit /b 0

rem Comando no PATH. So vale se executar codigo: o atalho da Store devolve erro
:trycmd
if defined PY exit /b 0
%~1 -c "import sys; sys.exit(0 if (3, 9) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PY=%~1"
set "PYW=%~2"
exit /b 0

rem Pasta de instalacao do python.org, fora do PATH
:trydir
if defined PY exit /b 0
if not exist "%~1\\python.exe" exit /b 0
"%~1\\python.exe" -c "import sys; sys.exit(0 if (3, 9) <= sys.version_info[:2] <= (3, 13) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set PY="%~1\\python.exe"
set PYW="%~1\\pythonw.exe"
exit /b 0
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
for f in ${CORE_FILES.join(" ")}; do
    curl -fsS "$SERVER/api/agent/download/$f" -o "$f"
done
# Sensores avançados: servidor antigo pode não tê-los, e o agente funciona sem
for f in ${EXTRA_FILES.join(" ")}; do
    curl -fsS "$SERVER/api/agent/download/$f" -o "$f" 2>/dev/null || true
done

echo "Instalando dependências..."
# --system-site-packages: deixa o venv usar o PyGObject (gi) do sistema,
# necessário para o ícone de bandeja usar o backend GTK (menu funcional)
if python3 -m venv --system-site-packages venv 2>/dev/null; then
    PY="$DIR/venv/bin/python"
else
    PY="python3"
fi
"$PY" -m pip install --quiet --disable-pip-version-check --no-warn-conflicts -r requirements.txt

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
REM So SYSTEM e Administradores: o agente roda como SYSTEM e importa modulos daqui.
REM Herdando de ProgramData, um usuario comum podia criar arquivos na pasta.
icacls "%DIR%" /setowner *S-1-5-32-544 /T /C >> "%LOG%" 2>&1
icacls "%DIR%" /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F /T /C >> "%LOG%" 2>&1
cd /d "%DIR%"
for %%F in (${[...CORE_FILES, ...EXTRA_FILES].join(" ")}) do (
    curl -fsS "%SERVER%/api/agent/download/%%F" -o "%%F" >> "%LOG%" 2>&1
)
python -m pip install --quiet --disable-pip-version-check --no-warn-conflicts -r requirements.txt >> "%LOG%" 2>&1

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
    # Só SYSTEM e Administradores: o agente roda como SYSTEM e importa módulos daqui
    icacls $dir /setowner '*S-1-5-32-544' /T /C | Out-Null
    icacls $dir /inheritance:r /grant:r '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' /T /C | Out-Null
    Set-Location $dir
    foreach ($f in @(${[...CORE_FILES, ...EXTRA_FILES].map((f) => `"${f}"`).join(", ")})) {
        try { Invoke-WebRequest "$server/api/agent/download/$f" -OutFile $f -UseBasicParsing } catch {}
    }
    python -m pip install --quiet --disable-pip-version-check --no-warn-conflicts -r requirements.txt

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

echo [1/4] Encerrando o agente...
rem O filtro do processo NAO pode conter as palavras que ele procura: a linha de
rem comando do proprio PowerShell conteria o padrao, ele se encontraria na busca
rem e se mataria antes de encerrar o agente (foi exatamente o que acontecia).
rem Por isso o padrao e montado em pedacos, e o proprio PID fica de fora.
powershell -NoProfile -Command "$meu=$PID; $alvo='agent'+'.py'; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $meu -and $_.Name -match 'python' -and $_.CommandLine -like ('*'+$alvo+'*') } | ForEach-Object { Write-Host ('  encerrando PID '+$_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
rem Da tempo de o processo soltar os arquivos antes de apagar a pasta
ping -n 3 127.0.0.1 >nul

echo [2/4] Removendo a inicializacao automatica...
del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\AnomalyDetectAgent.vbs" 2>nul
del /f /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\AnomalyDetect Agent.vbs" 2>nul
schtasks /delete /tn "AnomalyDetect Agent" /f >nul 2>nul

echo [3/4] Removendo este computador do painel...
set "REMOVIDO=1"
curl -fsS -X DELETE "${serverUrl}/api/agent/self" -H "X-Agent-Token: ${token}" >nul 2>nul
if errorlevel 1 set "REMOVIDO="
if not defined REMOVIDO echo   Nao foi possivel remover pelo servidor.

echo [4/4] Apagando os arquivos...
set "SOBROU="
rem Arquivos-isca criados nas pastas pessoais
for %%D in ("%USERPROFILE%\\Documents" "%USERPROFILE%\\Documentos" "%USERPROFILE%\\Pictures" "%USERPROFILE%\\Imagens") do (
    if exist "%%~D\\_AnomalyDetect_protecao" rmdir /s /q "%%~D\\_AnomalyDetect_protecao"
)
rem As duas pastas possiveis: instalacao normal e instalacao em massa (GPO)
for %%P in ("%LOCALAPPDATA%\\AnomalyDetect" "%ProgramData%\\AnomalyDetect") do (
    if exist "%%~P" (
        rmdir /s /q "%%~P"
        if exist "%%~P" set "SOBROU=%%~P"
    )
)

echo.
if defined SOBROU (
    echo ============================================
    echo   ATENCAO: nao consegui apagar:
    echo   %SOBROU%
    echo.
    echo   Isso costuma ser porque o agente ainda esta
    echo   rodando ou a pasta exige administrador.
    echo   Clique com o botao direito neste arquivo e
    echo   escolha "Executar como administrador".
    echo ============================================
) else (
    echo ============================================
    if defined REMOVIDO (
        echo   Pronto! O monitoramento foi removido e o
        echo   computador ja sumiu do painel.
    ) else (
        echo   O monitoramento foi removido deste computador,
        echo   mas ele continua no painel: remova pela
        echo   lixeira em Computadores.
    )
    echo ============================================
)
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
if curl -fsS -X DELETE "${serverUrl}/api/agent/self" -H "X-Agent-Token: ${token}" >/dev/null 2>&1; then
    REMOVIDO=1
else
    REMOVIDO=
    echo "  Nao foi possivel remover pelo servidor."
fi

echo "Apagando os arquivos..."
rm -rf "$HOME/.anomalydetect"
# Pastas de arquivos-isca criadas nas pastas pessoais
for d in "$HOME/Documents" "$HOME/Documentos" "$HOME/Pictures" "$HOME/Imagens"; do
    rm -rf "$d/_AnomalyDetect_protecao"
done
rm -f "$HOME/.config/autostart/anomalydetect-agent.desktop"
rm -f "$HOME/.local/share/applications/anomalydetect-agent.desktop"
systemctl --user disable --now anomalydetect-agent 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/anomalydetect-agent.service"
( crontab -l 2>/dev/null | grep -v "anomalydetect/agent.py" ) | crontab - 2>/dev/null || true

echo ""
echo "============================================"
if [ -n "$REMOVIDO" ]; then
    echo "  Pronto! O monitoramento foi removido e o"
    echo "  computador já sumiu do painel."
else
    echo "  O monitoramento foi removido deste computador,"
    echo "  mas ele continua no painel: remova pela"
    echo "  lixeira em Computadores."
fi
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
