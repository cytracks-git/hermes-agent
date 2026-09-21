/* Superfície web: o SDK fornece React e transporte autenticado do dashboard. */
export function createApprovalPanel(SDK) {
  const { React } = SDK;
  const h = React.createElement;
  const { useState, useEffect, useRef } = React;
  const { Button } = SDK.components;

  function Diagnostics({ diagnostics, retryNotice, busy }) {
    // Só renderiza com projeção do backend: um servidor anterior a t_78aaa333
    // omite o campo, e calar é mais honesto que inventar "OK".
    const stamp = value => value ? new Date(value * 1000).toLocaleString() : "Not observed";
    const attempts = diagnostics.delivery_attempts;
    return h("dl", { "aria-label": "Wait diagnostics" },
      h("dt", null, "Stage"), h("dd", null, diagnostics.phase_label),
      h("dt", null, "Next action"), h("dd", null, diagnostics.next_action || "None"),
      h("dt", null, "Last transition"), h("dd", null, stamp(diagnostics.last_transition_at)),
      h("dt", null, "Last evidence"), h("dd", null, stamp(diagnostics.last_evidence_at)),
      // Rótulo de TRANSPORTE; recibo não prova leitura humana.
      h("dt", null, "Notice"),
      h("dd", null,
        diagnostics.delivery_label + (attempts ? ` (${attempts} attempt${attempts === 1 ? "" : "s"})` : ""),
        diagnostics.delivery_status === "exhausted"
          && h(Button, { disabled: busy, onClick: retryNotice }, "Retry notice")),
      // NÃO MEDIDO em produção; zero seria mentira.
      h("dt", null, "Resource cost"),
      h("dd", null, diagnostics.resource_cost === null || diagnostics.resource_cost === undefined
        ? "Unavailable (not measured)" : String(diagnostics.resource_cost)));
  }

  function Item({ item, decide, retryNotice, busy }) {

    let payload;
    try {
      payload = JSON.parse(item.payload_json);
      if (!Array.isArray(payload.targets)) throw new Error("Invalid approval");
    } catch {
      return h("p", { role: "alert" }, "Approval content is invalid. No decision is available.");
    }
    return h("article", { className: "hermes-kanban-section" },
      h("h4", null, `${payload.op} · ${item.state}`),
      h("p", null, `Request ${item.request_id} · Run ${item.run_id} · ${item.profile_home}`),
      h("p", { style: { overflowWrap: "anywhere" } }, `SHA-256: ${item.request_hash}`),
      h("p", null, (payload.reasons || []).join(" · ")),
      payload.targets.map(target => h("details", { key: target.path_input, open: true },
        h("summary", null, target.path_real),
        h("p", { style: { overflowWrap: "anywhere" } }, `Before: ${target.pre_sha256 || "New file"}`),
        h("p", { style: { overflowWrap: "anywhere" } }, `After: ${target.post_sha256}`),
        h("pre", { style: { overflow: "auto", maxHeight: 240, whiteSpace: "pre-wrap" } }, target.diff_unified),
        h("details", null, h("summary", null, "Full proposed content"),
          h("pre", { style: { overflow: "auto", maxHeight: 240, whiteSpace: "pre-wrap" } }, target.post_blob)))),
      item.decided_by && h("p", null, `Decision by ${item.decided_by}`),
      item.state === "granted" && h("p", null, "Approved. Waiting for the original worker and available capacity."),
      item.state === "consumed" && h("p", null, item.applied_at ? "Written and verified." : "Consumed. Write receipt pending; do not retry."),
      item.diagnostics && h(Diagnostics, {
        diagnostics: item.diagnostics, busy, retryNotice: () => retryNotice(item)
      }),
      item.state === "pending" && h("div", { className: "flex gap-2" },
        h(Button, { disabled: busy, onClick: () => decide(item, "granted") }, "Approve once"),
        h(Button, { disabled: busy, onClick: () => decide(item, "denied") }, "Deny"),
        h(Button, { disabled: busy, onClick: () => decide(item, "cancelled") }, "Cancel request")),
      item.state === "pending" && h("p", null, "Approve only this exact content once. Changed files invalidate approval. This does not approve the task or any future command."));
  }

  return function ApprovalPanel({ task, boardSlug, onRefresh }) {
    const [items, setItems] = useState(null);
    const [error, setError] = useState("");
    const [busy, setBusy] = useState(false);
    const [revision, setRevision] = useState(0);
    const lastState = useRef(null);
    const stateKey = items && items.map(item => `${item.request_id}:${item.state}:${item.applied_at}`).join("|");
    useEffect(() => {
      if (stateKey === null) return;
      const previous = lastState.current;
      lastState.current = stateKey;
      if (previous !== null && previous !== stateKey) onRefresh();
    }, [stateKey, onRefresh]);
    const base = `/api/plugins/kanban/tasks/${encodeURIComponent(task.id)}/approvals`;
    const board = `?board=${encodeURIComponent(boardSlug || "default")}`;
    useEffect(() => {
      let active = true;
      const load = async () => {
        try {
          const data = await SDK.fetchJSON(base + board);
          if (active) { setItems(data.approvals); setError(""); }
        } catch (err) {
          if (active) { setError(String(err)); setItems(null); }
        }
      };
      void load();
      const timer = setInterval(load, task.status === "waiting_approval" ? 2000 : 8000);
      return () => { active = false; clearInterval(timer); };
    }, [base, board, revision, task.status]);
    const decide = async (item, decision) => {
      setBusy(true);
      try {
        await SDK.fetchJSON(`${base}/${item.request_id}/decision${board}`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision, request_hash: item.request_hash })
        });
        setRevision(value => value + 1);
        onRefresh();
      } catch (err) { setError(String(err)); }
      finally { setBusy(false); }
    };
    const retryNotice = async (item) => {
      // Reabre o orçamento de AVISO. Não decide nem reescreve nada.
      setBusy(true);
      try {
        await SDK.fetchJSON(`${base}/${item.request_id}/notice-retry${board}`, { method: "POST" });
        setRevision(value => value + 1);
      } catch (err) { setError(String(err)); }
      finally { setBusy(false); }
    };
    if (error) return h("div", { role: "alert" }, `File approvals unavailable: ${error}`,
      h(Button, { onClick: () => setRevision(value => value + 1) }, "Retry"));
    if (items === null) return h("p", { role: "status" }, "Loading file approvals…");
    if (!items.length) return task.status === "waiting_approval" ? h("p", null, "No approval request is available. Refresh before taking action.") : null;
    return h("section", { "aria-label": "File approvals" }, h("h3", null, "File approvals"),
      items.map(item => h(Item, { key: item.request_id, item, busy, decide, retryNotice })));
  };
}
