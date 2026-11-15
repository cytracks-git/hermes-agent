"""Baseline C2: latencia entre block kind=transient e o proximo unblock/claim (somente leitura)."""
import json, sqlite3, statistics, sys, time

db = sys.argv[1] if len(sys.argv) > 1 else "/Users/farantes/.hermes/kanban/boards/atlas/kanban.db"
dias = int(sys.argv[2]) if len(sys.argv) > 2 else 7
conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row
desde = int(time.time()) - dias * 86400
blocos = conn.execute(
    "SELECT id, task_id, kind, created_at FROM task_events WHERE kind IN ('blocked','block_loop_detected') "
    "AND json_extract(payload,'$.kind')='transient' AND created_at >= ? ORDER BY id", (desde,)).fetchall()
lat, abertos, por_tipo = [], 0, {"blocked": 0, "block_loop_detected": 0}
for b in blocos:
    por_tipo[b["kind"]] += 1
    nxt = conn.execute(
        "SELECT kind, created_at FROM task_events WHERE task_id=? AND id>? AND kind IN ('unblocked','claimed','promoted','promoted_manual') "
        "ORDER BY id LIMIT 1", (b["task_id"], b["id"])).fetchone()
    if nxt is None:
        abertos += 1
    else:
        lat.append((nxt["created_at"] - b["created_at"]) / 60)
print(json.dumps({
    "janela_dias": dias, "blocos_transient": len(blocos), "por_tipo": por_tipo,
    "retomados": len(lat), "ainda_parados": abertos,
    "latencia_min_mediana": round(statistics.median(lat), 1) if lat else None,
    "latencia_min_p90": round(sorted(lat)[int(len(lat) * 0.9) - 1], 1) if len(lat) >= 2 else None,
    "auto_redespacho_eventos": conn.execute(
        "SELECT COUNT(*) FROM task_events WHERE kind='transient_retry' AND created_at >= ?", (desde,)).fetchone()[0],
}, ensure_ascii=False))
