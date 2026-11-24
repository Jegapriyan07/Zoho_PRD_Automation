(() => {
const STAGES = {
  1: "Case intake", 2: "Document parsing", 3: "Transcript analysis & clarification",
  4: "Requirement reconciliation", 5: "Requirement decomposition", 6: "Data need specification",
  7: "Metadata mapping & query design", 8: "Validation workbook", 9: "Validation import",
  10: "Gap & clarification analysis", 11: "PRD generation", 12: "Human acceptance",
};
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) e.append(kid instanceof Node ? kid : document.createTextNode(kid ?? ""));
  return e;
};

const files = { transcripts: [], requirements: [], metadata: [] };
let job = null, since = 0, timer = null;
let stages = {}, lastLoadedView = null, insightKey = "", accepted = false;

// ---------- setup view ----------
function setupDrop(id, key) {
  const box = $(id), input = $("input", box), list = $(".files", box);
  const single = box.dataset.single === "1";
  const allowed = box.dataset.accept.split(",");
  const render = () => {
    list.replaceChildren(...files[key].map((f, i) => el("li", {},
      el("span", {}, `${f.name} (${Math.ceil(f.size / 1024)} KB)`),
      el("button", { title: "Remove", onclick: e => { e.stopPropagation(); files[key].splice(i, 1); render(); } }, "×"))));
    $("#startBtn").disabled = files.transcripts.length === 0;
  };
  const add = fl => {
    const ok = [...fl].filter(f => allowed.includes("." + f.name.split(".").pop().toLowerCase()));
    if (ok.length < fl.length) showError("Some files were skipped: unsupported type.");
    files[key] = single ? ok.slice(0, 1) : files[key].concat(ok);
    render();
  };
  box.addEventListener("click", () => input.click());
  input.addEventListener("change", () => { add(input.files); input.value = ""; });
  box.addEventListener("dragover", e => { e.preventDefault(); box.classList.add("over"); });
  box.addEventListener("dragleave", () => box.classList.remove("over"));
  box.addEventListener("drop", e => { e.preventDefault(); box.classList.remove("over"); add(e.dataTransfer.files); });
}
setupDrop("#drop-transcripts", "transcripts");
setupDrop("#drop-requirements", "requirements");
setupDrop("#drop-metadata", "metadata");

document.querySelectorAll("input[name=engine]").forEach(r => r.addEventListener("change", () => {
  const engine = document.querySelector("input[name=engine]:checked").value;
  $("#ollamaModel").classList.toggle("hidden", engine !== "ollama");
  $("#headroom").classList.toggle("hidden", engine === "mock");
}));
$("#useRag").addEventListener("change", e => { $("#ragKb").disabled = !e.target.checked; });

$("#startBtn").addEventListener("click", async () => {
  hideError();
  const fd = new FormData();
  files.transcripts.forEach(f => fd.append("transcripts", f));
  files.requirements.forEach(f => fd.append("requirements", f));
  files.metadata.forEach(f => fd.append("metadata", f));
  fd.append("mode", document.querySelector("input[name=mode]:checked").value);
  fd.append("engine", document.querySelector("input[name=engine]:checked").value);
  fd.append("ollama_model", $("#ollamaModel").value);
  fd.append("headroom", $("#headroom").value);
  fd.append("use_rag", $("#useRag").checked);
  fd.append("rag_kb", $("#ragKb").value);
  $("#startBtn").disabled = true;
  try {
    const data = await api("/api/jobs", { method: "POST", body: fd });
    startPolling(data.id);
  } catch (e) { showError(e.message); $("#startBtn").disabled = false; }
});

$("#newRunBtn").addEventListener("click", () => location.reload());
$("#cancelBtn").addEventListener("click", () => api(`/api/jobs/${job}/cancel`, { method: "POST" }));
$("#retryBtn").addEventListener("click", async () => {
  hideError();
  try { await api(`/api/jobs/${job}/retry`, { method: "POST" }); poll(); } catch (e) { showError(e.message); }
});

// ---------- helpers ----------
async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  let data = {};
  try { data = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) throw new Error(data.error || data.message || `Request failed (${res.status})`);
  return data;
}
const postJson = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
function showError(msg) { const b = $("#errorBanner"); b.textContent = msg; b.classList.remove("hidden"); }
function hideError() { $("#errorBanner").classList.add("hidden"); }
function showView(name) {
  document.querySelectorAll(".view").forEach(v => v.classList.toggle("hidden", v.id !== `view-${name}`));
}

// ---------- polling ----------
function startPolling(id) {
  job = id;
  $("#newRunBtn").classList.remove("hidden");
  showView("run");
  renderStepper({ status: "running" });
  poll();
}
async function poll() {
  clearTimeout(timer);
  let s;
  try { s = await api(`/api/jobs/${job}?since=${since}`); }
  catch (e) { showError(e.message); timer = setTimeout(poll, 2000); return; }
  since = s.next;
  if (s.case_id) { const b = $("#caseBadge"); b.textContent = s.case_id; b.classList.remove("hidden"); }
  appendLog(s.lines);
  trackStages(s);
  renderStepper(s);
  renderRunHeader(s);
  await route(s);
  if (s.status === "running") timer = setTimeout(poll, 700);
}

function appendLog(lines) {
  const out = $("#console");
  for (const l of lines) {
    const cls = /^\[Stage/.test(l.text) ? "stage" : l.kind;
    out.append(el("span", { class: cls }, l.text + "\n"));
  }
  if (lines.length) { out.scrollTop = out.scrollHeight; $("#logCount").textContent = out.children.length + " lines"; }
}

function trackStages(s) {
  for (const l of s.lines) {
    const m = l.text.match(/^\[Stage (\d+)\]/);
    if (!m) continue;
    const n = +m[1];
    for (const k in stages) if (stages[k].start && !stages[k].end && +k !== n) stages[k].end = l.t;
    stages[n] = { start: l.t, end: null };
  }
  if (s.status !== "running") {
    const now = Date.now() / 1000;
    for (const k in stages) if (!stages[k].end) stages[k].end = s.lines.length ? s.lines[s.lines.length - 1].t : now;
  }
}

function renderStepper(s) {
  const list = $("#stepper");
  list.replaceChildren(...Object.entries(STAGES).map(([n, label]) => {
    n = +n;
    const st = stages[n];
    let cls = "", mark = n;
    if (st && st.end) { cls = "done"; mark = "✓"; }
    else if (st) { cls = "active"; }
    if (n === 12 && s.status === "done" && !st) { cls = accepted ? "done" : "waiting"; mark = accepted ? "✓" : "!"; }
    if (st && s.status === "error" && !st.ok && isLastStage(n)) { cls = "error"; mark = "×"; }
    const dur = st && st.end ? `${Math.max(1, Math.round(st.end - st.start))}s` : (st ? "…" : "");
    return el("li", { class: cls }, el("span", { class: "dot" }, mark), label, el("span", { class: "time" }, dur));
  }));
}
const isLastStage = n => Math.max(...Object.keys(stages).map(Number)) === n;

function renderRunHeader(s) {
  const spinner = $("#spinner");
  spinner.className = "spinner";
  const started = Object.keys(stages).map(Number);
  const cur = started.length ? Math.max(...started) : null;
  let title = "Starting…", sub = "";
  if (s.status === "running") {
    title = cur ? `Stage ${cur}: ${STAGES[cur]}` : "Preparing case…";
    sub = "Working on it — watch the live log below.";
  } else if (s.status === "error") {
    title = "Something went wrong"; sub = s.error || ""; spinner.classList.add("bad");
    showError(s.error || "The pipeline stopped with an error. See the log below.");
  } else if (s.status === "cancelled") { title = "Stopped"; spinner.classList.add("bad"); }
  else { title = "Waiting for you"; spinner.classList.add("warn"); }
  $("#nowTitle").textContent = title; $("#nowSub").textContent = sub;
  const running = s.status === "running";
  $("#cancelBtn").classList.toggle("hidden", !running);
  $("#retryBtn").classList.toggle("hidden", !(s.status === "error" || s.status === "cancelled"));
}

async function route(s) {
  let view = "run";
  if (s.status === "waiting") view = s.step;
  else if (s.status === "done") view = "done";
  if (s.status === "running") hideError();
  if (view !== lastLoadedView || s.status === "running") {
    if (view === "run") {
      showView("run");
      await refreshInsights(s);
    } else if (view !== lastLoadedView) {
      lastLoadedView = view;
      hideError();
      showView(view);
      try { await ({ clarify: loadClarify, validate: loadValidate, gaps: loadGaps, done: loadDone })[view](); }
      catch (e) { showError(e.message); }
    }
  }
  if (view === "run") lastLoadedView = "run";
}

// ---------- insights ----------
async function refreshInsights(s) {
  if (!s.case_id) return;
  const key = Object.keys(stages).join(",") + s.status;
  if (key === insightKey) return;
  insightKey = key;
  const d = await api(`/api/jobs/${job}/insights`);
  const box = $("#insights");
  const cards = [];
  if (d.analysis) cards.push(card("Transcript analysis", d.analysis.summary,
    list("Confirmed signals", d.analysis.signals), list("Ambiguity risks", d.analysis.risks)));
  if (d.baseline) cards.push(card("Requirement baseline", d.baseline.summary,
    list("In scope", d.baseline.in_scope), list("Out of scope", d.baseline.out_of_scope)));
  if (d.requirements.length) cards.push(card(`${d.requirements.length} atomic requirements`, "",
    el("div", {}, d.requirements.slice(0, 30).map(r => el("span", { class: "pill", title: r.title }, `${r.id} · ${r.category || ""}`)))));
  if (d.data_needs || d.queries) cards.push(card("Data & metadata", "",
    el("div", { class: "stat" }, el("div", {}, el("b", {}, d.data_needs), "data needs"), el("div", {}, el("b", {}, d.queries), "query designs"))));
  if (d.gaps) cards.push(card("Gap assessment", `Overall readiness: ${d.gaps.readiness || "n/a"}`,
    list("Missing data", d.gaps.missing), list("Conflicts", d.gaps.conflicts)));
  box.className = "insights";
  box.replaceChildren(...cards);
}
const card = (title, text, ...kids) => el("div", { class: "card" }, el("h2", {}, title), text ? el("p", { class: "muted" }, text) : "", ...kids);
const list = (title, items) => items && items.length
  ? el("div", {}, el("strong", {}, title), el("ul", {}, items.slice(0, 6).map(i => el("li", {}, i)))) : "";

// ---------- clarify ----------
let clarifyData = [];
async function loadClarify() {
  const d = await api(`/api/jobs/${job}/clarifications`);
  clarifyData = d.questions;
  const box = $("#clarifyList");
  if (!clarifyData.length) { box.replaceChildren(el("p", { class: "muted" }, "No clarification questions were raised. Continue to reconciliation.")); return; }
  box.replaceChildren(...clarifyData.map(q => {
    const ta = el("textarea", { class: "input", rows: 2, "data-id": q.id, placeholder: "Your answer…" }, q.answer);
    return el("div", { class: "q" },
      el("h3", {}, el("span", { class: `tag ${q.priority}` }, q.priority), `${q.id}: ${q.question}`),
      el("div", { class: "meta" }, `Ambiguity: ${q.ambiguity} · Impact: ${q.impact}`),
      q.options.length ? el("div", { class: "chips" }, q.options.map(o => el("button", { class: "chip", onclick: () => { ta.value = o; } }, o))) : "",
      ta);
  }));
}
async function submitClarify(auto) {
  hideError();
  const answers = {};
  document.querySelectorAll("#clarifyList textarea").forEach(t => { answers[t.dataset.id] = t.value; });
  try { await postJson(`/api/jobs/${job}/clarifications`, { answers, auto }); resume(); } catch (e) { showError(e.message); }
}
$("#clarifySubmit").addEventListener("click", () => submitClarify(false));
$("#clarifyAuto").addEventListener("click", () => submitClarify(true));

// ---------- validate ----------
async function loadValidate() {
  const d = await api(`/api/jobs/${job}/validation`);
  $("#wbDownload").href = `/api/jobs/${job}/files/validation_workbook_${$("#caseBadge").textContent}.xlsx`;
  $("#validateList").replaceChildren(...d.rows.map(r => {
    const sel = el("select", { class: "input small", "data-row": r.row }, el("option", { value: "" }, "Select status…"),
      d.statuses.map(s => el("option", { value: s, ...(s === r.status ? { selected: "" } : {}) }, s)));
    return el("div", { class: "req", "data-row": r.row },
      el("div", { class: "req-head" }, el("b", {}, r.id), el("span", { class: "grow" }, r.title),
        el("span", { class: "badge" }, r.grounding || "n/a"), sel),
      el("div", { class: "req-body" },
        el("div", {}, r.description),
        r.paths ? el("div", {}, el("strong", {}, "Metadata path: "), r.paths) : el("div", { class: "muted" }, "No metadata path mapped."),
        el("div", { class: "muted" }, r.mapping),
        r.query ? el("details", {}, el("summary", {}, "Validation query"), el("pre", {}, r.query)) : "",
        el("input", { class: "input notes", placeholder: "Notes (data-quality issues, caveats)", value: r.notes }),
        el("input", { class: "input answer", placeholder: "Client clarification / answer", value: r.answer })));
  }));
}
$("#validateSubmit").addEventListener("click", async () => {
  hideError();
  const rows = [...document.querySelectorAll("#validateList .req")].map(r => ({
    row: +r.dataset.row, status: $("select", r).value, notes: $(".notes", r).value, answer: $(".answer", r).value,
  }));
  try { await postJson(`/api/jobs/${job}/validation`, { rows }); resume(); } catch (e) { showError(e.message); }
});
$("#validateAuto").addEventListener("click", async () => {
  hideError();
  try { await postJson(`/api/jobs/${job}/validation`, { auto: true }); resume(); } catch (e) { showError(e.message); }
});
$("#wbUpload").addEventListener("change", async e => {
  hideError();
  const fd = new FormData(); fd.append("workbook", e.target.files[0]);
  try { await api(`/api/jobs/${job}/workbook`, { method: "POST", body: fd }); resume(); } catch (err) { showError(err.message); }
  e.target.value = "";
});

// ---------- gaps ----------
async function loadGaps() {
  const d = await api(`/api/jobs/${job}/gaps`);
  $("#gapList").replaceChildren(...d.rows.map(r => el("div", { class: "q" },
    el("h3", {}, r.question), el("div", { class: "meta" }, `Related: ${r.requirement}`),
    el("textarea", { class: "input", rows: 2, "data-row": r.row, placeholder: "Your answer…" }, r.answer))));
}
async function submitGaps(auto) {
  hideError();
  const rows = [...document.querySelectorAll("#gapList textarea")].map(t => ({ row: +t.dataset.row, answer: t.value }));
  try { await postJson(`/api/jobs/${job}/gaps`, { rows, auto }); resume(); } catch (e) { showError(e.message); }
}
$("#gapsSubmit").addEventListener("click", () => submitGaps(false));
$("#gapsAuto").addEventListener("click", () => submitGaps(true));

function resume() { lastLoadedView = null; insightKey = ""; showView("run"); poll(); }

// ---------- results ----------
async function loadDone() {
  const d = await api(`/api/jobs/${job}/results`);
  const labels = [
    [/^final_prd_.*\.md$/, "Final PRD", "Markdown", true],
    [/^client_ready_prd_.*\.docx$/, "Client-ready PRD", "Word document", true],
    [/^client_ready_prd_.*\.pdf$/, "Client-ready PRD", "PDF", false],
    [/^validation_workbook_.*\.xlsx$/, "Validation workbook", "Excel", false],
    [/^transcript_analysis_report_.*\.md$/, "Questions analyser", "Markdown", false],
    [/^analytical_assessment_.*\.md$/, "Analytical assessment", "Markdown", false],
  ];
  const links = [];
  for (const [re, title, kind, primary] of labels) {
    const f = d.files.find(n => re.test(n));
    if (f) links.push(el("a", { class: "dl" + (primary ? " primary" : ""), href: `/api/jobs/${job}/files/${encodeURIComponent(f)}` },
      el("b", {}, title), el("span", {}, kind), el("small", {}, f)));
  }
  $("#downloads").replaceChildren(...links);
  $("#prdPreview").innerHTML = renderMarkdown(d.prd || "_PRD not found._");
  if (d.feedback) { accepted = d.feedback.accepted; $("#feedbackMsg").textContent = accepted ? "Accepted." : "Changes requested."; }
}
async function sendFeedback(ok) {
  try {
    await postJson(`/api/jobs/${job}/feedback`, { accepted: ok, notes: $("#feedbackNotes").value });
    accepted = ok; $("#feedbackMsg").textContent = ok ? "Accepted — recorded." : "Feedback recorded.";
    renderStepper({ status: "done" });
  } catch (e) { showError(e.message); }
}
$("#acceptBtn").addEventListener("click", () => sendFeedback(true));
$("#rejectBtn").addEventListener("click", () => sendFeedback(false));

// ---------- minimal markdown renderer ----------
function esc(t) { return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
function inline(t) {
  return esc(t).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<i>$2</i>");
}
function renderMarkdown(md) {
  const lines = md.replace(/\r/g, "").split("\n"); const out = []; let i = 0;
  while (i < lines.length) {
    const ln = lines[i];
    const h = ln.match(/^(#{1,6})\s+(.*)/);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^\s*\|/.test(ln) && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] || "")) {
      const cells = r => r.trim().replace(/^\||\|$/g, "").split("|").map(c => inline(c.trim()));
      let t = "<table><thead><tr>" + cells(ln).map(c => `<th>${c}</th>`).join("") + "</tr></thead><tbody>"; i += 2;
      while (i < lines.length && /^\s*\|/.test(lines[i])) { t += "<tr>" + cells(lines[i]).map(c => `<td>${c}</td>`).join("") + "</tr>"; i++; }
      out.push(t + "</tbody></table>"); continue;
    }
    if (/^\s*[-*]\s+/.test(ln)) {
      let u = "<ul>"; while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) { u += `<li>${inline(lines[i].replace(/^\s*[-*]\s+/, ""))}</li>`; i++; }
      out.push(u + "</ul>"); continue;
    }
    if (/^\s*\d+\.\s+/.test(ln)) {
      let u = "<ol>"; while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) { u += `<li>${inline(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`; i++; }
      out.push(u + "</ol>"); continue;
    }
    if (ln.trim()) out.push(`<p>${inline(ln)}</p>`);
    i++;
  }
  return out.join("\n");
}
renderStepper({ status: "idle" });
})();
