#!/usr/bin/env bash
# Renova o login do Claude pouco antes de expirar. A CLI só renova quando é usada perto do
# vencimento; sem isso, em períodos sem uso, as explicações saem como texto estático.
#
# Rode no computador que hospeda o servidor, a cada 3 minutos:
#   */3 * * * * /caminho/do/projeto/scripts/renew_claude_login.sh
set -u

RENEW_WITHIN_SECONDS=240

seconds_left=$(python3 -I -c '
import json, os, time
path = os.path.expanduser("~/.claude/.credentials.json")
print(int(json.load(open(path))["claudeAiOauth"]["expiresAt"] / 1000 - time.time()))
' 2>/dev/null) || exit 0

[ "$seconds_left" -gt "$RENEW_WITHIN_SECONDS" ] && exit 0

claude_bin=$(command -v claude ||
  ls -d "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | sort -V | tail -1)
[ -n "$claude_bin" ] || exit 1

cd "$HOME" || exit 1
timeout 120 "$claude_bin" -p ok --model haiku </dev/null >/dev/null 2>&1
status=$?

mkdir -p "$HOME/.cache"
echo "$(date -u '+%F %T UTC') faltavam ${seconds_left}s, resultado ${status}" >> "$HOME/.cache/renew_claude_login.log"
