#!/bin/sh
# Prepara a credencial do Claude Code CLI antes de subir a API.
#
# Com CLAUDE_CODE_OAUTH_TOKEN (gerado por `claude setup-token`) o servidor tem login
# proprio e nao toca no do computador: os dois renovando o mesmo login derrubavam um
# ao outro. Sem o token, copia o ~/.claude do host, montado somente-leitura em
# /claude-host, para uma pasta do container. Sem nenhum dos dois o container sobe
# normalmente e a cadeia de explicacoes segue para o Ollama.
set -e

HOST_DIR="${CLAUDE_HOST_DIR:-/claude-host}"

if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "[entrypoint] Claude CLI com token de longa duracao do proprio servidor"
elif [ -f "$HOST_DIR/.credentials.json" ]; then
    mkdir -p "$HOME/.claude"
    cp "$HOST_DIR/.credentials.json" "$HOME/.claude/.credentials.json"
    chmod 600 "$HOME/.claude/.credentials.json"
    echo "[entrypoint] credencial do Claude CLI copiada do host"
else
    echo "[entrypoint] sem credencial do Claude CLI — provedor claude-cli ficara indisponivel"
fi

exec "$@"
