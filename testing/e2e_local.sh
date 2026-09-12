#!/usr/bin/env bash
#
# Teste ponta a ponta local: sobe o backend de verdade (uvicorn + SQLite),
# roda o AGENTE REAL contra ele e confere o que chegou.
#
# Diferente dos testes de unidade (que usam mocks) e do harness cbox (que usa
# containers Linux), este valida o contrato agente↔servidor na máquina em que
# você está, sem Docker e sem PostgreSQL — em menos de um minuto.
#
# Foi escrito depois de encontrar, exatamente assim, quatro problemas que
# nenhum teste de unidade pegou:
#   1. o pareamento quebrava com SQLite (data com fuso × sem fuso);
#   2. os instaladores não baixavam os módulos novos do agente;
#   3. o inventário pesado rodava dentro do laço e travava a coleta;
#   4. a caixa-preta varria todos os processos a cada 2 s.
#
# Uso:
#   ./testing/e2e_local.sh                 # usa o python do PATH
#   PY=/caminho/python ./testing/e2e_local.sh
#
# Requisitos: as dependências do backend (requirements.txt) e do agente
# (psutil, requests) no mesmo interpretador.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${PY:-python}"
PORT="${PORT:-8099}"
SECONDS_RUNNING="${SECONDS_RUNNING:-45}"
API="http://127.0.0.1:$PORT"
WORK="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/anomalydetect-e2e")"
mkdir -p "$WORK/agentdata"

# O Python no Windows não entende caminhos do Git Bash (/c/...)
to_native() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi
}
WORK_NATIVE="$(to_native "$WORK")"

echo "== subindo o backend (SQLite em $WORK) =="
cd "$ROOT/backend"
DATABASE_URL="sqlite:///$WORK_NATIVE/e2e.db" SECRET_KEY=e2e-secret PYTHONPATH=. \
  "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning \
  > "$WORK/server.log" 2>&1 &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" 2>/dev/null
  [ -n "${AGENT_PID:-}" ] && kill "$AGENT_PID" 2>/dev/null
  wait 2>/dev/null
  echo "(logs e banco em $WORK)"
}
trap cleanup EXIT

for _ in $(seq 1 40); do
  curl -sf "$API/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -sf "$API/health" >/dev/null || { echo "FALHA: o backend não subiu"; tail -20 "$WORK/server.log"; exit 1; }
echo "backend no ar"

echo "== criando conta e código de pareamento =="
curl -sf -X POST "$API/api/auth/register" -H 'Content-Type: application/json' \
  -d '{"email":"e2e@example.com","username":"e2e","password":"e2epass123"}' >/dev/null
JWT=$(curl -sf -X POST "$API/api/auth/login" -F username=e2e -F password=e2epass123 \
  | "$PY" -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
[ -n "$JWT" ] || { echo "FALHA: login"; exit 1; }
CODE=$(curl -sf -X POST "$API/api/machines/enroll-code" -H "Authorization: Bearer $JWT" \
  | "$PY" -c "import sys,json;print(json.load(sys.stdin)['code'])")
echo "código de pareamento: $CODE"

echo "== rodando o agente real por ${SECONDS_RUNNING}s =="
cd "$ROOT/agent"
AGENT_API_URL="$API" AGENT_ENROLL_CODE="$CODE" AGENT_CONFIG_DIR="$WORK_NATIVE/agentdata" \
  COLLECTION_INTERVAL=5 AGENT_NO_TRAY=1 "$PY" agent.py --no-tray > "$WORK/agent.log" 2>&1 &
AGENT_PID=$!
sleep "$SECONDS_RUNNING"

echo ""
echo "== conferindo o que chegou =="
"$PY" - "$API" "$JWT" <<'PY'
import json, sys, urllib.request

api, jwt = sys.argv[1], sys.argv[2]

def get(path):
    req = urllib.request.Request(api + path, headers={"Authorization": "Bearer " + jwt})
    return json.load(urllib.request.urlopen(req, timeout=15))

ok = True
def check(label, cond, extra=""):
    global ok
    print(("  OK   " if cond else "FALHA  ") + label + (f" - {extra}" if extra else ""))
    ok = ok and bool(cond)

machines = get("/api/machines")
check("máquina registrada pelo agente", len(machines) == 1, machines[0]["name"] if machines else "nenhuma")
if not machines:
    sys.exit(1)
m = machines[0]
check("sistema operacional detectado", bool(m.get("os_pretty")), m.get("os_pretty"))
check("informações do sistema recebidas", isinstance(m.get("system_info"), dict))
check("versão do agente registrada", bool(m.get("agent_version")), m.get("agent_version"))

metrics = get(f"/api/metrics/{m['id']}?hours=1")
check("leituras ingeridas", len(metrics) >= 4, f"{len(metrics)} leituras")
check("processador medido", isinstance(metrics[-1].get("cpu_percent"), (int, float)))

latest = get(f"/api/metrics/{m['id']}/latest")
check("boot_time enviado (base do desligamento inesperado)", bool(latest.get("boot_time")))
check("intervalo informado", bool(latest.get("interval_seconds")), latest.get("interval_seconds"))

frames = get(f"/api/metrics/{m['id']}/window?center={latest['timestamp']}&minutes=10").get("frames", [])
check("janela do replay", len(frames) >= 4, f"{len(frames)} quadros")
check("programas por quadro", sum(len(f.get('processes', [])) for f in frames) > 0)

learning = get(f"/api/metrics/{m['id']}/learning")
check("progresso do aprendizado", learning.get("collected", 0) >= 4,
      f"{learning.get('collected')} de {learning.get('needed')}")
check("faixa aprendida responde", "ready" in get(f"/api/metrics/{m['id']}/baseline"))
check("preferências da conta", get("/api/account/preferences")["preferences"]["language_level"] == "leigo")

manifest = json.load(urllib.request.urlopen(api + "/api/agent/manifest", timeout=10))
check("manifesto do agente (autoatualização)", len(manifest["files"]) >= 9, f"{len(manifest['files'])} arquivos")

print("\nRESULTADO:", "TUDO OK" if ok else "HOUVE FALHA")
sys.exit(0 if ok else 1)
PY
RESULT=$?

echo ""
echo "== identidade dos executáveis gravada =="
"$PY" - "$WORK_NATIVE/e2e.db" <<'PY'
import sqlite3, sys
cur = sqlite3.connect(sys.argv[1]).cursor()
total, com_caminho, com_hash, assinados = cur.execute(
    "select count(*), sum(exe is not null), sum(sha256 is not null), sum(signed='signed') from processes"
).fetchone()
print(f"  processos: {total} | com caminho: {com_caminho} | com hash: {com_hash} | assinados: {assinados}")
print("  identidades distintas:", cur.execute("select count(*) from process_identities").fetchone()[0])
print("  entradas de reputação:", cur.execute("select count(*) from hash_reputation").fetchone()[0])
PY

echo ""
echo "== últimas linhas do log do agente =="
tail -5 "$WORK/agent.log"
exit $RESULT
