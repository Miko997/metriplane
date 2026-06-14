// SPDX-FileCopyrightText: 2025-2026 Miko Parkkinen
// SPDX-License-Identifier: MIT

(function () {
  const RUNNER = new URLSearchParams(location.search).get("runner") || "http://localhost:9000";
  const DONE = new Set(["succeeded", "failed", "timed_out", "cancelled"]);
  const jobs = new Map();
  const commandRegistry = new Map();

  function all(selector) {
    return Array.from(document.querySelectorAll(selector));
  }

  function setAll(selector, text) {
    for (const el of all(selector)) el.textContent = text;
  }

  function cardFor(el) {
    return el.closest(".mp-action-card") || el.closest(".mp-guide-card") || el.closest(".mp-command-card");
  }

  function statusTone(status) {
    if (status === "succeeded") return "ok";
    if (status === "running") return "running";
    if (status === "cancelled") return "warn";
    if (status === "failed" || status === "timed_out") return "error";
    return "idle";
  }

  function setCardStatus(card, status, detail) {
    if (!card) return;
    const statusEl = card.querySelector("[data-job-status]");
    const detailEl = card.querySelector("[data-job-detail]");
    if (statusEl) {
      statusEl.textContent = status || "idle";
      statusEl.dataset.state = statusTone(status);
    }
    if (detailEl) detailEl.textContent = detail || "";
  }

  function setOutput(card, text) {
    if (!card) return;
    const out = card.querySelector("[data-job-output]");
    if (!out) return;
    out.textContent = (text || "").trim() || "(no output yet)";
  }

  async function jsonFetch(url, options) {
    const res = await fetch(url, options);
    let data = {};
    try {
      data = await res.json();
    } catch (err) {
      data = {};
    }
    if (!res.ok) {
      throw new Error(data.error || `${res.status} ${res.statusText}`);
    }
    return data;
  }

  async function refreshRunnerStatus() {
    try {
      const status = await jsonFetch(`${RUNNER}/status`, { cache: "no-store" });
      jsonFetch(`${RUNNER}/operator/runner-status`, { cache: "no-store" }).catch(() => null);
      document.body.classList.add("runner-online");
      document.body.classList.remove("runner-offline");
      setAll("[data-runner-status]", status.status === "running" ? "runner busy" : "runner ready");
      setAll("[data-runner-detail]", status.current_job ? status.current_job.command_id : "localhost :9000");
      return status;
    } catch (err) {
      document.body.classList.remove("runner-online");
      document.body.classList.add("runner-offline");
      setAll("[data-runner-status]", "runner offline");
      setAll("[data-runner-detail]", "start with metriplane start");
      return null;
    }
  }

  function applyCommandRegistry(commands) {
    commandRegistry.clear();
    for (const command of commands || []) {
      commandRegistry.set(command.id, command);
    }
    for (const button of all("[data-command-id]")) {
      const command = commandRegistry.get(button.dataset.commandId);
      const card = cardFor(button);
      if (!command) {
        button.disabled = true;
        button.classList.add("is-disabled");
        button.title = "This action is not available in the local runner";
        setCardStatus(card, "disabled", "not in action registry");
        continue;
      }
      if (command.enabled === false) {
        button.disabled = true;
        button.classList.add("is-disabled");
        button.setAttribute("aria-disabled", "true");
        button.title = command.disabled_reason || "Action is disabled";
        setCardStatus(card, "disabled", command.disabled_reason || "disabled");
      } else if (!jobs.has(command.id) && !button.hasAttribute("data-needs-atlas")) {
        button.classList.remove("is-disabled");
        button.setAttribute("aria-disabled", "false");
        if (!button.dataset.readyTitle) button.dataset.readyTitle = button.getAttribute("title") || "";
        button.title = button.dataset.readyTitle;
      }
    }
  }

  async function refreshCommandRegistry() {
    try {
      const data = await jsonFetch(`${RUNNER}/commands`, { cache: "no-store" });
      applyCommandRegistry(data.commands || []);
      return data.commands || [];
    } catch (err) {
      return [];
    }
  }

  function renderJobs(payload) {
    for (const el of all("[data-jobs-list]")) {
      const jobs = (payload && payload.jobs) || [];
      if (!jobs.length) {
        el.innerHTML = `<div class="mp-empty-line">No recent runner jobs.</div>`;
        continue;
      }
      el.innerHTML = jobs.slice(0, 5).map((job) => {
        const status = job.status || "unknown";
        const command = job.command_id || "unknown";
        const exit = job.exit_code == null ? "" : `exit ${job.exit_code}`;
        return `<div class="mp-job-history-row"><strong>${command}</strong><span data-state="${statusTone(status)}">${status}</span><small>${exit}</small></div>`;
      }).join("");
    }
  }

  async function refreshJobs() {
    try {
      const data = await jsonFetch(`${RUNNER}/jobs?limit=5`, { cache: "no-store" });
      renderJobs(data);
      return data;
    } catch (err) {
      renderJobs({ jobs: [] });
      return null;
    }
  }

  async function runCommand(button) {
    if (button.disabled || button.classList.contains("is-disabled")) return;
    const commandId = button.dataset.commandId;
    if (!commandId || jobs.has(commandId)) return;

    const card = cardFor(button);
    setCardStatus(card, "starting", commandId);
    setOutput(card, "");
    button.disabled = true;

    try {
      const job = await jsonFetch(`${RUNNER}/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command_id: commandId }),
      });
      jobs.set(commandId, job.job_id);
      setCardStatus(card, "running", job.job_id);
      pollJob(job.job_id, commandId, card, button);
    } catch (err) {
      button.disabled = false;
      setCardStatus(card, "failed", err.message);
      setOutput(card, err.message);
      refreshRunnerStatus();
    }
  }

  async function pollJob(jobId, commandId, card, button) {
    const tick = async () => {
      try {
        const job = await jsonFetch(`${RUNNER}/jobs/${jobId}`, { cache: "no-store" });
        const elapsed = typeof job.elapsed_s === "number" ? `${job.elapsed_s.toFixed(1)}s` : "";
        setCardStatus(card, job.status, elapsed);
        setOutput(card, `${job.stdout || ""}${job.stderr ? "\n--- stderr ---\n" + job.stderr : ""}`.slice(-12000));

        if (DONE.has(job.status)) {
          jobs.delete(commandId);
          button.disabled = false;
          refreshCommandRegistry();
          refreshJobs();
          refreshRunnerStatus();
          if (job.status === "succeeded" && button.dataset.refreshAtlas !== "false") {
            refreshAtlasArtifacts();
          }
          return;
        }
        window.setTimeout(tick, 900);
      } catch (err) {
        jobs.delete(commandId);
        button.disabled = false;
        setCardStatus(card, "failed", err.message);
        setOutput(card, err.message);
      }
    };
    tick();
  }

  function setAtlasField(name, value) {
    for (const el of all(`[data-atlas-field="${name}"]`)) {
      el.textContent = value == null || value === "" ? "-" : String(value);
    }
  }

  function setAtlasDependent(enabled) {
    for (const el of all("[data-needs-atlas]")) {
      el.disabled = !enabled;
      el.classList.toggle("is-disabled", !enabled);
      el.setAttribute("aria-disabled", enabled ? "false" : "true");
      if (!el.dataset.readyTitle) el.dataset.readyTitle = el.getAttribute("title") || "";
      el.setAttribute("title", enabled ? el.dataset.readyTitle : "Build the evidence sample first");
      const card = cardFor(el);
      if (card) card.classList.toggle("is-disabled", !enabled);
    }
  }

  function mountTopContext() {
    const nav = document.querySelector(".mp-product-nav");
    if (!nav || nav.querySelector(".mp-product-nav-context")) return;
    const title = nav.querySelector(".mp-product-nav-title") || nav.firstElementChild;
    const context = document.createElement("div");
    context.className = "mp-product-nav-context";
    context.innerHTML = `
      <span><b>Runner</b><strong data-runner-status>checking</strong></span>
      <span><b>Live Stream</b><strong>optional</strong></span>
      <span><b>Health</b><strong>local</strong></span>
      <span><b>Current Run</b><strong data-atlas-field="run_id">-</strong></span>
      <span><b>Workspace</b><strong data-atlas-field="cell_id">-</strong></span>
    `;
    if (title && title.nextSibling) nav.insertBefore(context, title.nextSibling);
    else nav.appendChild(context);
  }

  async function refreshAtlasArtifacts() {
    try {
      const res = await fetch(`atlas_run/atlas_manifest.json?ts=${Date.now()}`, { cache: "no-store" });
      if (!res.ok) throw new Error("missing atlas manifest");
      const manifest = await res.json();
      document.body.classList.add("has-atlas-artifacts");
      document.body.classList.remove("missing-atlas-artifacts");
      setAll("[data-atlas-status]", "evidence ready");
      setAtlasDependent(true);
      setAtlasField("run_id", manifest.run_id);
      setAtlasField("cell_id", manifest.cell_id);
      setAtlasField("events", manifest.event_count);
      setAtlasField("incidents", manifest.incident_count);
      setAtlasField("deviations", manifest.deviation_count);
      setAtlasField("frames", manifest.frame_count);
      setAtlasField("pack", manifest.domain_pack);
      return manifest;
    } catch (err) {
      document.body.classList.remove("has-atlas-artifacts");
      document.body.classList.add("missing-atlas-artifacts");
      setAll("[data-atlas-status]", "build evidence sample first");
      setAtlasDependent(false);
      setAtlasField("run_id", "-");
      setAtlasField("cell_id", "-");
      setAtlasField("events", "-");
      setAtlasField("incidents", "-");
      setAtlasField("deviations", "-");
      setAtlasField("frames", "-");
      setAtlasField("pack", "-");
      return null;
    }
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-command-id]");
    if (!button) return;
    event.preventDefault();
    runCommand(button);
  });

  document.addEventListener("DOMContentLoaded", () => {
    mountTopContext();
    setAll("[data-runner-url]", RUNNER);
    refreshRunnerStatus();
    refreshCommandRegistry();
    refreshJobs();
    refreshAtlasArtifacts();
    window.setInterval(refreshRunnerStatus, 5000);
    window.setInterval(refreshJobs, 10000);
  });

  window.MPConsoleActions = {
    refreshRunnerStatus,
    refreshCommandRegistry,
    refreshJobs,
    refreshAtlasArtifacts,
    runCommand,
  };
})();
