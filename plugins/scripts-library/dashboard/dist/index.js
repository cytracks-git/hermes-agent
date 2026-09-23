/**
 * Hermes Scripts library — Dashboard Plugin
 *
 * Read-only view of the scripts already on disk: what each one does, how to run
 * it, and whether it is committed, reviewed and published. Calls the plugin's
 * own backend at /api/plugins/scripts-library/.
 *
 * Plain IIFE, no build step — same shape as the kanban dashboard bundle. Uses
 * window.__HERMES_PLUGIN_SDK__ for React + shared primitives.
 *
 * Esta página existe porque o manifest do dashboard é o que monta o backend:
 * assim que o manifest existe, o dashboard injeta este entry. Entregar só o
 * desktop deixaria uma linha quebrada na aba de Plugins. É a mesma biblioteca,
 * apresentada na superfície do dashboard — não um stub que manda usar o outro
 * lugar.
 */
(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK) return;

  const { React } = SDK;
  const h = React.createElement;
  const { Badge, Button, Card, CardContent, Input } = SDK.components;
  const { useState, useEffect, useCallback } = SDK.hooks;
  const { cn } = SDK.utils;
  const fetchJSON = SDK.fetchJSON;

  const API = "/api/plugins/scripts-library";

  // Verdicts the backend may report for a lifecycle stage. An unmeasured stage
  // is rendered as "Not measured", never hidden and never upgraded to a pass.
  const STAGE_LABEL = {
    committed: "Committed",
    prepared: "On disk",
    published: "Published",
    reviewed: "Reviewed",
  };
  const STATUS_LABEL = { no: "No", unknown: "Not measured", yes: "Yes" };
  const STATUS_CLASS = {
    no: "hermes-scripts-status hermes-scripts-status--no",
    unknown: "hermes-scripts-status hermes-scripts-status--unknown",
    yes: "hermes-scripts-status hermes-scripts-status--yes",
  };

  const SECTIONS = [
    ["usage", "Usage"],
    ["dependencies", "Dependencies"],
    ["environment", "Environment"],
    ["permissions", "Permissions"],
    ["exit_codes", "Exit codes"],
    ["limits", "Limits"],
    ["tests", "Tests"],
    ["notes", "Notes"],
  ];

  function formatBytes(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function Detail(props) {
    const [detail, setDetail] = useState(null);
    const [error, setError] = useState("");

    useEffect(function () {
      let cancelled = false;
      setDetail(null);
      setError("");
      fetchJSON(API + "/scripts/" + encodeURIComponent(props.id))
        .then(function (data) { if (!cancelled) setDetail(data); })
        .catch(function (err) { if (!cancelled) setError(String(err && err.message ? err.message : err)); });
      return function () { cancelled = true; };
    }, [props.id]);

    if (error) {
      return h("p", { className: "hermes-scripts-error" }, "Could not read this script: " + error);
    }
    if (!detail) {
      return h("p", { className: "hermes-scripts-muted" }, "Reading…");
    }

    const commit = detail.vcs && detail.vcs.commit;

    return h(
      "div",
      { className: "hermes-scripts-detail" },
      h("h3", null, detail.name),
      h(
        "p",
        { className: detail.purpose ? "hermes-scripts-purpose" : "hermes-scripts-muted" },
        detail.purpose || "This script has no documentation yet."
      ),

      h("h4", null, "Run command"),
      h(
        "div",
        { className: "hermes-scripts-run" },
        h("code", null, detail.run_command),
        h(
          Button,
          {
            onClick: function () {
              if (navigator.clipboard) navigator.clipboard.writeText(detail.run_command);
            },
            size: "sm",
            variant: "ghost",
          },
          "Copy"
        )
      ),

      h(
        "dl",
        { className: "hermes-scripts-meta" },
        h("dt", null, "Path"), h("dd", null, detail.relpath),
        h("dt", null, "Location"), h("dd", null, detail.root_label),
        h("dt", null, "Language"), h("dd", null, detail.language),
        h("dt", null, "Size"), h("dd", null, formatBytes(detail.size_bytes)),
        h("dt", null, "Version"),
        h(
          "dd",
          null,
          commit
            ? commit.short_sha + " · " + commit.subject
            : "No commit yet — this script exists only on this machine."
        )
      ),

      h("h4", null, "State"),
      h(
        "ul",
        { className: "hermes-scripts-lifecycle" },
        (detail.lifecycle && detail.lifecycle.stages ? detail.lifecycle.stages : []).map(function (stage) {
          return h(
            "li",
            { key: stage.stage },
            h("span", { className: STATUS_CLASS[stage.status] || STATUS_CLASS.unknown },
              STATUS_LABEL[stage.status] || stage.status),
            h("span", { className: "hermes-scripts-stage" }, STAGE_LABEL[stage.stage] || stage.stage),
            // A evidência anda junto do veredito: selo que o operador não pode
            // conferir é pior que selo nenhum.
            h("span", { className: "hermes-scripts-evidence" }, stage.evidence)
          );
        })
      ),

      detail.vcs && detail.vcs.web_url
        ? h("a", { href: detail.vcs.web_url, rel: "noreferrer", target: "_blank" }, "Open on GitHub")
        : null,

      SECTIONS.filter(function (pair) { return detail.sections && detail.sections[pair[0]]; }).map(function (pair) {
        return h(
          "div",
          { key: pair[0] },
          h("h4", null, pair[1]),
          h("pre", { className: "hermes-scripts-block" }, detail.sections[pair[0]])
        );
      }),

      h("h4", null, "History"),
      detail.vcs && detail.vcs.history && detail.vcs.history.length
        ? h(
            "ul",
            { className: "hermes-scripts-history" },
            detail.vcs.history.map(function (entry) {
              return h("li", { key: entry.sha }, h("code", null, entry.short_sha), " " + entry.subject);
            })
          )
        : h("p", { className: "hermes-scripts-muted" }, "No commit history.")
    );
  }

  function ScriptsLibraryPage() {
    const [catalog, setCatalog] = useState(null);
    const [error, setError] = useState("");
    const [search, setSearch] = useState("");
    const [selected, setSelected] = useState("");

    const load = useCallback(function (term) {
      setError("");
      const query = term ? "?q=" + encodeURIComponent(term) : "";
      fetchJSON(API + "/catalog" + query)
        .then(setCatalog)
        .catch(function (err) { setError(String(err && err.message ? err.message : err)); });
    }, []);

    useEffect(function () {
      const timer = setTimeout(function () { load(search); }, 200);
      return function () { clearTimeout(timer); };
    }, [search, load]);

    const scripts = catalog && catalog.scripts ? catalog.scripts : [];
    const missing = catalog && catalog.roots ? catalog.roots.filter(function (r) { return !r.exists; }) : [];

    return h(
      "div",
      { className: "hermes-scripts-page" },
      h(
        "header",
        null,
        h("h2", null, "Scripts"),
        h("p", { className: "hermes-scripts-muted" }, "Read-only library of the scripts on this machine")
      ),

      missing.length
        ? h(
            "p",
            { className: "hermes-scripts-warning" },
            "Configured location not found: " + missing.map(function (r) { return r.label; }).join(", ")
          )
        : null,
      catalog && catalog.truncated
        ? h("p", { className: "hermes-scripts-warning" }, "Too many files — this list is partial.")
        : null,

      h(Input, {
        "aria-label": "Search scripts",
        onChange: function (e) { setSearch(e.target.value); },
        placeholder: "Search name, purpose or path…",
        value: search,
      }),

      error
        ? h(
            Card,
            null,
            h(
              CardContent,
              null,
              h("p", { className: "hermes-scripts-error" }, "Could not read the library."),
              h(
                "p",
                { className: "hermes-scripts-muted" },
                "The backend did not answer. The library is not empty — it could not be read."
              ),
              h(Button, { onClick: function () { load(search); }, size: "sm", variant: "secondary" }, "Try again")
            )
          )
        : h(
            "div",
            { className: "hermes-scripts-body" },
            h(
              "ul",
              { className: "hermes-scripts-list" },
              scripts.map(function (script) {
                return h(
                  "li",
                  { key: script.id },
                  h(
                    "button",
                    {
                      className: cn(
                        "hermes-scripts-row",
                        script.id === selected ? "hermes-scripts-row--active" : ""
                      ),
                      onClick: function () { setSelected(script.id); },
                      type: "button",
                    },
                    h("span", { className: "hermes-scripts-name" }, script.name),
                    h(Badge, { variant: "secondary" }, script.vcs_state)
                  )
                );
              }),
              catalog && scripts.length === 0
                ? h(
                    "li",
                    { className: "hermes-scripts-muted" },
                    search ? "Nothing matches this search" : "No scripts found"
                  )
                : null
            ),
            h(
              "div",
              { className: "hermes-scripts-pane" },
              selected
                ? h(Detail, { id: selected })
                : h("p", { className: "hermes-scripts-muted" }, "Select a script to see its documentation.")
            )
          )
    );
  }

  if (window.__HERMES_PLUGINS__ && typeof window.__HERMES_PLUGINS__.register === "function") {
    window.__HERMES_PLUGINS__.register("scripts-library", ScriptsLibraryPage);
  }
})();
