#!/bin/bash
set -uo pipefail
exec /Users/farantes/bin/dev-grok.sh \
  -C /Users/farantes/atlas/wt/gate-evidencia \
  -t 1200 \
  /tmp/auditoria-gate-evidencia.md \
  /tmp/auditoria-grok-gate.md
