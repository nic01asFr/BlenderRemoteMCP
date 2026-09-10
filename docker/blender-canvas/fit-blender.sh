#!/bin/bash
# Colle la fenetre Blender a la geometrie Xvfb (0,0 → W×H).
# Necessaire : le mode « fullscreen » de Blender et les regles Fluxbox
# laissent parfois un offset (ex. y=42), ce qui montre le fond du WM.
set -eu
DISPLAY="${DISPLAY:-:99}"
export DISPLAY

geometrie_ecran() {
  xdpyinfo 2>/dev/null | awk '/dimensions:/{print $2; exit}'
}

attendre_blender() {
  local i=0
  while [ "$i" -lt 60 ]; do
    if xdotool search --class Blender >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done
  return 1
}

ajuster() {
  local geo w h wid
  geo="$(geometrie_ecran || true)"
  [ -n "${geo:-}" ] || return 0
  w="${geo%x*}"
  h="${geo#*x}"
  wid="$(xdotool search --class Blender | head -1 || true)"
  [ -n "${wid:-}" ] || return 0
  xdotool windowmove "$wid" 0 0
  xdotool windowsize "$wid" "$w" "$h"
}

echo "fit-blender: attente de la fenetre Blender…"
attendre_blender || { echo "fit-blender: Blender introuvable"; exit 0; }
ajuster
echo "fit-blender: geometrie appliquee ($(geometrie_ecran))"

# Re-applique periodiquement (resizeSession / redemarrage Blender).
while true; do
  sleep 5
  ajuster || true
done
