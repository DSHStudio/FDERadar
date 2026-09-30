"use strict";

function renderRefreshTime() {
  const node = $("refresh-status");
  node.hidden = !anyTaskRunning();
  node.textContent = anyTaskRunning() ? "资料处理中 · 进度自动更新" : "";
  $("refresh-button").title = "最近同步：" + date(app.lastSeen) + "；点击同步已保存资料";
}

function renderMetrics() {
  $("nav-documents").textContent = documents().length;
  $("nav-pending").textContent = notes().filter((n) => n.status === "pending_review").length;
  $("nav-github").textContent = githubResources().length;
  $("metrics").hidden = app.view !== "sources";
  if (app.view !== "sources") return;
  $("metrics").setAttribute("aria-label", "采集实际进度");
  const ss = sources();
  const latest = new Map();
  [...documents()]
    .sort((a, b) => String(a.retrievedAt).localeCompare(String(b.retrievedAt)))
    .forEach((d) => latest.set(normalized(d.url), d));
  const extracted = [...latest.values()].filter((d) =>
    ["evidence_text", "partial"].includes(d.quality),
  );
  const unique = new Set(extracted.map((d) => normalized(d.url))).size;
  const partial = new Set(
    extracted.filter((d) => d.quality === "partial").map((d) => normalized(d.url)),
  ).size;
  const failed = ss.filter((s) => isFailure(s.lastStatus)).length;
  const pending = ss.filter((s) => !s.lastSuccess).length;
  const metrics = [
    [unique, "已取得资料（含 " + partial + " 份部分文本）"],
    [documents().length, "保存版本 · 含目录与摘要"],
    [pending, "待取得的来源"],
    [failed, "获取存在缺口"],
  ];
  $("metrics").replaceChildren(
    ...metrics.map(([value, label]) =>
      add(el("div", "metric"), el("strong", null, value), el("span", null, label)),
    ),
  );
}

function render() {
  if (!app.data) return;
  const previousView = app.view;
  app.view = views[location.hash.slice(1)] ? location.hash.slice(1) : "intelligence";
  document.querySelectorAll("[data-view]").forEach((node) => {
    node.classList.toggle("active", node.dataset.view === app.view);
    if (node.dataset.view === app.view) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  });
  if ($("view-select")) $("view-select").value = app.view;
  $("page-title").textContent = views[app.view][0];
  $("page-description").textContent = views[app.view][1];
  $("collect-button").textContent =
    app.view === "opensource"
      ? githubRunning()
        ? "正在获取 GitHub 资料…"
        : "更新资源"
      : "更新资料";
  $("collect-button").disabled = app.view === "opensource" && githubRunning();
  $("collect-button").hidden = !["intelligence", "opensource", "sources", "tasks"].includes(
    app.view,
  );
  renderMetrics();
  renderRefreshTime();
  const content = $("content");
  const focused = document.activeElement;
  const focusId = focused && focused.id;
  const selection =
    focused && typeof focused.selectionStart === "number"
      ? [focused.selectionStart, focused.selectionEnd]
      : null;
  // Leave an in-progress form intact while background status refreshes. Explicit actions render normally after focus leaves the form.
  if (
    previousView === app.view &&
    focused &&
    content.contains(focused) &&
    focused.closest("form") &&
    !focused.closest(".toolbar")
  )
    return;
  content.replaceChildren();
  if (app.view === "practice") renderPractice(content);
  else if (app.view === "opensource") renderGithub(content);
  else if (app.view === "sources") {
    renderResearchAudit(content);
    renderSources(content);
  } else if (app.view === "tasks") renderTasks(content);
  else if (app.view === "scenario") {
    renderScenarioResearch(content);
    renderScenarios(content);
  } else {
    if (app.view === "theory") renderLearning(content);
    if (app.view === "case") renderCaseResearch(content);
    if (app.view === "intelligence") {
      renderResearchChanges(content);
      renderDocuments(content);
    } else {
      const library = el("details", "secondary-panel");
      library.append(el("summary", null, "更多原始资料"));
      renderDocuments(library);
      content.append(library);
    }
  }
  if (focusId) {
    const replacement = $(focusId);
    if (replacement) {
      replacement.focus({ preventScroll: true });
      if (selection && replacement.setSelectionRange) replacement.setSelectionRange(...selection);
    }
  }
}

$("close-document").addEventListener("click", () => {
  closeDocument();
  $("document-dialog").close();
});

$("document-dialog").addEventListener("close", () => {
  closeDocument();
  const focus = reader.returnFocusId && $(reader.returnFocusId);
  if (focus) focus.focus({ preventScroll: true });
  reader.returnFocusId = null;
});

$("document-dialog").addEventListener("cancel", closeDocument);

$("close-lab-artifact").addEventListener("click", () => {
  researchUI.artifactGeneration = (researchUI.artifactGeneration || 0) + 1;
  $("lab-artifact-dialog").close();
});

$("lab-artifact-dialog").addEventListener("cancel", () => {
  researchUI.artifactGeneration = (researchUI.artifactGeneration || 0) + 1;
});

for (const mode of ["original", "translate", "explain"])
  $("reader-tab-" + mode).addEventListener("click", () => setReadingMode(mode));

$("refresh-button").addEventListener("click", () => refresh());

$("collect-button").addEventListener("click", () =>
  app.view === "opensource"
    ? refreshGithub()
    : action("/api/collect", {}, "已提交到期信源采集任务，请查看「任务与审核」。"),
);

function navigateView() {
  const next = views[location.hash.slice(1)] ? location.hash.slice(1) : "intelligence";
  if (next !== app.view) {
    const fields = ["query", "host", "track", "page", "matchedIds", "searchQuery", "searchError"];
    app.viewState.set(app.view, {
      ...Object.fromEntries(fields.map((key) => [key, app[key]])),
      githubFilters: { ...githubFilters },
      scroll: window.scrollY || 0,
    });
    const saved = app.viewState.get(next) || {
      query: "",
      host: "",
      track: "",
      page: 1,
      matchedIds: null,
      searchQuery: "",
      searchError: "",
      scroll: 0,
    };
    fields.forEach((key) => {
      app[key] = saved[key];
    });
    if (next === "opensource")
      Object.keys(githubFilters).forEach((key) => {
        githubFilters[key] = saved.githubFilters?.[key] || "";
      });
    clearTimeout(app.searchTimer);
    render();
    if (window.scrollTo) window.scrollTo({ top: saved.scroll, behavior: "instant" });
  } else render();
}

window.addEventListener("hashchange", navigateView);

if ($("view-select"))
  $("view-select").addEventListener("change", (event) => {
    location.hash = event.target.value;
  });

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh(false);
});

refresh();
