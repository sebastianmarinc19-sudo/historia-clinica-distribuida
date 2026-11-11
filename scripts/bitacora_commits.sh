#!/usr/bin/env bash
# Tabla de contribución por autor sacada del historial REAL de git (no se escribe a mano): commits, líneas, primer y último commit.
#   bash scripts/bitacora_commits.sh            # Markdown listo para pegar en docs/BITACORA.md
#   bash scripts/bitacora_commits.sh --por-fase # además, los commits en orden cronológico (para ver las 5 fases)
set -euo pipefail
cd "$(dirname "$0")/.."
git rev-parse --git-dir >/dev/null 2>&1 || { echo "no es un repositorio git"; exit 1; }
if [ -z "$(git log --oneline -1 2>/dev/null)" ]; then echo "El repositorio aún no tiene commits."; exit 0; fi
echo "| Autor | Commits | Líneas añadidas | Líneas borradas | Primer commit | Último commit |"
echo "|---|---|---|---|---|---|"
git log --format='%aN' | sort -u | while IFS= read -r autor; do
  n=$(git log --author="$autor" --format='%H' | wc -l)
  lineas=$(git log --author="$autor" --numstat --format= | awk '{a += $1; d += $2} END {print a+0 " " d+0}')
  primero=$(git log --author="$autor" --format='%as' | tail -1); ultimo=$(git log --author="$autor" --format='%as' | head -1)
  printf '| %s | %s | %s | %s | %s | %s |\n' "$autor" "$n" "${lineas% *}" "${lineas#* }" "$primero" "$ultimo"
done
if [ "${1:-}" = "--por-fase" ]; then
  echo; echo "Commits en orden cronológico:"; echo
  git log --reverse --format='- %as · %aN · %s'
fi
