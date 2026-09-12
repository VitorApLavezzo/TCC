#!/usr/bin/env bash
# Harness de validação: sobe uma máquina Linux descartável (via cbox/distrobox)
# com um problema específico injetado, instala o agente do AnomalyDetect nela,
# espera o tempo necessário e confere na API real se a anomalia esperada foi
# detectada — depois derruba tudo e (opcionalmente) repete N vezes para medir
# consistência entre execuções.
#
# Requisitos no host: cbox (https://github.com/Rynaro/cardboard-box), distrobox
# >=1.6, podman ou docker, curl, jq, python3.
#
# Uso:
#   ./run_scenarios.sh                    # roda todos os cenários, 1x cada
#   ./run_scenarios.sh cpu_loop           # roda só um cenário
#   REPEATS=5 ./run_scenarios.sh cpu_loop # roda 5x para medir repetibilidade
#
# Variáveis de ambiente (todas opcionais):
#   SERVER    endereço do backend do AnomalyDetect (padrão: http://localhost:8000)
#   USERNAME  conta dedicada para os testes (padrão: cbox_harness)
#   PASSWORD  senha dessa conta (padrão: harnessTest123)
#   REPEATS   quantas vezes repetir cada cenário (padrão: 1)

set -uo pipefail

SERVER="${SERVER:-http://localhost:8000}"
USERNAME="${USERNAME:-cbox_harness}"
PASSWORD="${PASSWORD:-harnessTest123}"
REPEATS="${REPEATS:-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# name -> "arquivo.toml|anomaly_type esperado|segundos de espera"
# O tempo de espera é calculado a partir do requisito mínimo de histórico de
# cada detector em behavior_analyzer.py, com folga — ver comentários em cada
# Boxfile para o raciocínio exato.
#
# Os detectores passaram a exigir uma JANELA DE TEMPO mínima, não só um número
# de coletas: com COLLECTION_INTERVAL=5, "3 de 5 coletas" eram 25 s de pico —
# pouco para chamar de programa travado. `detect_cpu_loop` agora quer pelo
# menos 60 s de CPU dominante sustentada, então a espera subiu de 60 s para
# 180 s (detecção observada por volta de 100–120 s).
#
# Só o cenário cpu_loop está incluído aqui — é o único validado de ponta a
# ponta até agora (3/3 detecções corretas). Os outros 4 (memory_leak,
# ddos_indicator, suspicious_process, behavioral_change) estão em progresso
# na branch feat/cbox-more-scenarios, aguardando validação.
declare -A SCENARIOS=(
  [cpu_loop]="cpu_loop.Boxfile.toml|cpu_loop|180"
)

# >&2: run_once() é chamada dentro de $(...) para capturar SÓ a linha de
# resultado — qualquer coisa em stdout (inclusive isto) seria engolida junto
# com o valor de retorno em vez de aparecer na tela ao vivo.
log() { echo "[$(date +%H:%M:%S)] $*" >&2; }

api_login() {
  curl -sf -X POST "$SERVER/api/auth/register" -H 'Content-Type: application/json' \
    -d "{\"email\":\"${USERNAME}@example.com\",\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" \
    >/dev/null 2>&1 || true # ignora erro se a conta já existir
  JWT=$(curl -sf -X POST "$SERVER/api/auth/login" -F "username=$USERNAME" -F "password=$PASSWORD" | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
  if [ -z "$JWT" ]; then
    echo "ERRO: não foi possível logar em $SERVER — confira SERVER/USERNAME/PASSWORD" >&2
    exit 1
  fi
}

api_enroll_code() {
  curl -sf -X POST "$SERVER/api/machines/enroll-code" -H "Authorization: Bearer $JWT" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['code'])"
}

api_find_machine_id() {
  local hostname="$1"
  for _ in $(seq 1 10); do
    local id
    id=$(curl -sf "$SERVER/api/machines" -H "Authorization: Bearer $JWT" \
      | python3 -c "import sys,json
for m in json.load(sys.stdin):
    if m['hostname'] == '$hostname':
        print(m['id']); break")
    if [ -n "$id" ]; then echo "$id"; return 0; fi
    sleep 3
  done
  return 1
}

api_anomaly_types() {
  local machine_id="$1"
  curl -sf "$SERVER/api/anomalies?machine_id=$machine_id&hours=1" -H "Authorization: Bearer $JWT" \
    | python3 -c "import sys,json
for a in json.load(sys.stdin):
    print(f\"{a['anomaly_type']}:{a['severity']}\")" 2>/dev/null
}

api_delete_machine() {
  curl -sf -X DELETE "$SERVER/api/machines/$1" -H "Authorization: Bearer $JWT" >/dev/null 2>&1 || true
}

# Remove o box tanto pelo cbox quanto direto no backend de containers.
# Necessário porque `cbox rm` só reconhece boxes que ELE criou (tem os labels
# cbox.managed=true) — um container com o mesmo nome criado por fora (ex: via
# `distrobox create` manual, comum ao depurar) fica invisível para `cbox rm` e
# quebra a próxima tentativa com "needs a recreate". Isso garante idempotência
# de verdade entre execuções, seja qual for a origem do container.
full_cleanup() {
  local box_name="$1"
  cbox rm "$box_name" -y >/dev/null 2>&1 || true
  if command -v podman >/dev/null 2>&1; then
    podman rm -f "$box_name" >/dev/null 2>&1 || true
  fi
  if command -v docker >/dev/null 2>&1; then
    docker rm -f "$box_name" >/dev/null 2>&1 || true
  fi
}

run_once() {
  local scenario="$1" boxfile="$2" expected_type="$3" wait_seconds="$4" attempt="$5"
  local box_name="test-${scenario//_/-}"
  local boxfile_path="$SCRIPT_DIR/$boxfile"

  log "[$scenario #$attempt] limpando execução anterior (se houver)..."
  full_cleanup "$box_name"

  log "[$scenario #$attempt] subindo container com o Boxfile ($boxfile)..."
  if ! cbox up "$box_name" --file "$boxfile_path" -y >&2; then
    echo "$scenario|$attempt|ERRO_CBOX_UP|-|-"
    return
  fi

  local code
  code=$(api_enroll_code)
  log "[$scenario #$attempt] instalando o agente dentro do container..."
  # COLLECTION_INTERVAL=5: os tempos de espera de cada cenário (e os comentários
  # nos Boxfiles) foram calculados assumindo coletas a cada 5s — sem isso o
  # agente usa o padrão de 10s e os prazos ficam apertados ou insuficientes.
  if ! cbox enter "$box_name" -- bash -c "export COLLECTION_INTERVAL=5; curl -fsS '$SERVER/api/agent/install.sh?code=${code}&server=${SERVER}' | bash" >&2; then
    echo "$scenario|$attempt|ERRO_INSTALL|-|-"
    full_cleanup "$box_name"
    return
  fi

  local machine_id
  machine_id=$(api_find_machine_id "$box_name")
  if [ -z "$machine_id" ]; then
    echo "$scenario|$attempt|ERRO_MACHINE_NAO_APARECEU|-|-"
    full_cleanup "$box_name"
    return
  fi
  log "[$scenario #$attempt] máquina registrada (id=$machine_id). Aguardando detecção (até ${wait_seconds}s)..."

  local start_ts elapsed found=""
  start_ts=$(date +%s)
  while [ "$(($(date +%s) - start_ts))" -lt "$wait_seconds" ]; do
    local types
    types=$(api_anomaly_types "$machine_id")
    if echo "$types" | grep -q "^${expected_type}:"; then
      found=$(echo "$types" | grep "^${expected_type}:" | head -1)
      break
    fi
    sleep 5
  done
  elapsed=$(($(date +%s) - start_ts))

  if [ -n "$found" ]; then
    log "[$scenario #$attempt] DETECTADO em ${elapsed}s: $found"
    echo "$scenario|$attempt|OK|${elapsed}s|$found"
  else
    log "[$scenario #$attempt] NÃO detectado dentro do prazo (${wait_seconds}s)"
    echo "$scenario|$attempt|FALHOU|${elapsed}s|-"
  fi

  api_delete_machine "$machine_id"
  full_cleanup "$box_name"
}

main() {
  command -v cbox >/dev/null || { echo "ERRO: cbox não encontrado no PATH"; exit 1; }
  command -v python3 >/dev/null || { echo "ERRO: python3 necessário para falar com a API"; exit 1; }

  api_login
  log "Logado em $SERVER como $USERNAME"

  local -a to_run=("$@")
  [ ${#to_run[@]} -eq 0 ] && to_run=("${!SCENARIOS[@]}")

  local results=()
  for scenario in "${to_run[@]}"; do
    local entry="${SCENARIOS[$scenario]:-}"
    if [ -z "$entry" ]; then
      echo "Cenário desconhecido: $scenario (opções: ${!SCENARIOS[*]})" >&2
      continue
    fi
    IFS='|' read -r boxfile expected_type wait_seconds <<< "$entry"
    for attempt in $(seq 1 "$REPEATS"); do
      results+=("$(run_once "$scenario" "$boxfile" "$expected_type" "$wait_seconds" "$attempt")")
    done
  done

  echo ""
  echo "=== Resumo ==="
  printf "%-22s %-8s %-10s %-10s %s\n" "CENÁRIO" "TENTATIVA" "RESULTADO" "TEMPO" "ANOMALIA"
  local ok=0 total=0
  for r in "${results[@]}"; do
    IFS='|' read -r scenario attempt status elapsed anomaly <<< "$r"
    printf "%-22s %-8s %-10s %-10s %s\n" "$scenario" "$attempt" "$status" "$elapsed" "$anomaly"
    total=$((total + 1))
    [ "$status" = "OK" ] && ok=$((ok + 1))
  done
  echo ""
  echo "Detectado corretamente: $ok / $total"
}

main "$@"
