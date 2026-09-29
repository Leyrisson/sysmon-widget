#!/bin/bash
# limpar.sh — limpeza automática de lixo e arquivos temporários do disco do SO.
# Seguro e sem sudo: só remove lixeira, /tmp, /var/tmp e caches do usuário.
set -u
LOG="$HOME/.local/state/sysmon/limpar.log"
mkdir -p "$(dirname "$LOG")"

{
  echo "=== limpeza $(date '+%F %T') ==="

  # 1) Lixeira do usuário
  if [ -d "$HOME/.local/share/Trash" ]; then
    rm -rf "$HOME/.local/share/Trash/files/"* "$HOME/.local/share/Trash/info/"* 2>/dev/null
    echo "lixeira: limpa"
  else
    echo "lixeira: não existe"
  fi

  # 2) Arquivos temporários — /tmp e /var/tmp com mais de 1 dia
  before=$(df -B1 / | tail -1 | awk '{print $3}')
  find /tmp /var/tmp -xdev -type f -mtime +1 -delete 2>/dev/null
  find /tmp /var/tmp -xdev -depth -mindepth 1 -type d -empty -delete 2>/dev/null

  # 3) Cache do usuário — arquivos com mais de 7 dias
  find "$HOME/.cache" -xdev -type f -mtime +7 -delete 2>/dev/null
  find "$HOME/.cache" -xdev -depth -mindepth 1 -type d -empty -delete 2>/dev/null

  after=$(df -B1 / | tail -1 | awk '{print $3}')
  echo "temp/cache: liberados $(( (before - after) / 1024 / 1024 )) MiB de /"

  # 4) Journal do usuário — limitar a 200 MiB
  journalctl --user --vacuum-size=200M >/dev/null 2>&1 && echo "journal usuário: 200 MiB"

  echo "concluído $(date '+%F %T')"
} >> "$LOG" 2>&1

echo "limpeza concluída — log em $LOG"