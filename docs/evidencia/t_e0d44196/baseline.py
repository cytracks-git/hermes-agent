"""Baseline C2: latencia entre block kind=transient e a proxima retomada (somente leitura).

Conta o evento que a producao grava: `hermes_cli/kanban_db_transient.py` emite
`unblocked` com payload `auto='transient_redispatch'` (AUTO_MARKER). A versao
anterior deste script contava `kind='transient_retry'`, que nenhum codigo emite,
e respondia 0 para sempre. `controle_baseline.py` prova que o contador sobe com
um evento real do C2 e nao sobe com unblock manual.

Uso: python baseline.py [kanban.db] [dias]
"""
import json, sqlite3, statistics, sys, time

# Espelho de hermes_cli.kanban_db_transient.AUTO_MARKER. O script roda sem o
# venv do Hermes; controle_baseline.py reprova se os dois divergirem.
AUTO_MARKER = "transient_redispatch"
DB_PADRAO = "/Users/farantes/.hermes/kanban/boards/atlas/kanban.db"


def _p90(xs):
    return round(sorted(xs)[int(len(xs) * 0.9) - 1], 1) if len(xs) >= 2 else None


def _mediana(xs):
    return round(statistics.median(xs), 1) if xs else None


def medir(db, dias=7, agora=None):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        desde = (int(time.time()) if agora is None else int(agora)) - dias * 86400
        blocos = conn.execute(
            "SELECT id, task_id, kind, created_at FROM task_events WHERE kind IN ('blocked','block_loop_detected') "
            "AND json_extract(payload,'$.kind')='transient' AND created_at >= ? ORDER BY id", (desde,)).fetchall()
        lat_auto, lat_mao, abertos = [], [], 0
        por_tipo = {"blocked": 0, "block_loop_detected": 0}
        for b in blocos:
            por_tipo[b["kind"]] += 1
            nxt = conn.execute(
                "SELECT kind, payload, created_at FROM task_events WHERE task_id=? AND id>? "
                "AND kind IN ('unblocked','claimed','promoted','promoted_manual') ORDER BY id LIMIT 1",
                (b["task_id"], b["id"])).fetchone()
            if nxt is None:
                abertos += 1
                continue
            minutos = (nxt["created_at"] - b["created_at"]) / 60
            auto = nxt["kind"] == "unblocked" and (json.loads(nxt["payload"] or "{}") or {}).get("auto") == AUTO_MARKER
            (lat_auto if auto else lat_mao).append(minutos)
        lat = lat_auto + lat_mao
        eventos_auto = conn.execute(
            "SELECT COUNT(*) FROM task_events WHERE kind='unblocked' "
            "AND json_extract(payload,'$.auto')=? AND created_at >= ?", (AUTO_MARKER, desde)).fetchone()[0]
    finally:
        conn.close()
    return {
        "janela_dias": dias, "blocos_transient": len(blocos), "por_tipo": por_tipo,
        "retomados": len(lat), "retomados_auto": len(lat_auto), "retomados_mao": len(lat_mao),
        "ainda_parados": abertos,
        "latencia_min_mediana": _mediana(lat), "latencia_min_p90": _p90(lat),
        "latencia_auto_min_mediana": _mediana(lat_auto),
        "latencia_mao_min_mediana": _mediana(lat_mao),
        "auto_redespacho_eventos": eventos_auto,
    }


if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else DB_PADRAO
    dias = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    print(json.dumps(medir(db, dias), ensure_ascii=False))
