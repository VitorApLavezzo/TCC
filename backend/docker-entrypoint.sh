#!/bin/sh
# Prepara a credencial do Claude Code CLI antes de subir a API.
#
# O diretorio ~/.claude do host e montado como somente-leitura em /claude-host.
# Copiamos a credencial para um diretorio proprio do container, de modo que a
# renovacao automatica do token escreva na copia e nunca no arquivo do host.
# Sem credencial o container sobe normalmente: o provedor claude-cli falha e a
# cadeia de explicacoes segue para o Ollama.
set -e

if [ -f /claude-host/.credentials.json ]; then
    mkdir -p /root/.claude
    cp /claude-host/.credentials.json /root/.claude/.credentials.json
    chmod 600 /root/.claude/.credentials.json
    echo "[entrypoint] credencial do Claude CLI copiada do host"
else
    echo "[entrypoint] sem credencial do Claude CLI — provedor claude-cli ficara indisponivel"
fi

exec "$@"
