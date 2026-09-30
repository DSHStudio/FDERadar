"use strict";

const githubCategories = {
  ontology: "数据本体建设",
  governance: "数据清洗与治理",
  fde: "FDE 工具与项目",
};

const githubKinds = {
  tool: "工具",
  example: "示例 / 参考项目",
  resource_list: "资料清单",
  framework: "框架",
};

function githubReadmeSaved(resource) {
  return Boolean(
    resource.readmeDocumentId && resource.readmeSha256 && Number(resource.readmeChars) > 0,
  );
}

function githubStatus(value) {
  return (
    {
      PARTIAL: "部分取得",
      COMPLETED_WITH_GAPS: "本轮完成 · 存在缺口",
      NOT_DUE: "尚未到期",
      DEFERRED: "延后获取",
      INTERRUPTED: "采集中断",
      NOT_ATTEMPTED: "尚未获取",
      RATE_LIMITED: "接口限流",
      RATE_LIMIT_DEFERRED: "等待限流解除",
      README_NOT_FOUND: "未找到 README",
    }[String(value || "").toUpperCase()] || status(value)
  );
}

function githubLicense(resource) {
  const value =
    typeof resource.license === "object" && resource.license
      ? resource.license.spdx_id || resource.license.name
      : resource.license;
  const known =
    resource.licenseStatus !== "unknown" &&
    value &&
    !["NOASSERTION", "NONE", "UNKNOWN"].includes(String(value).toUpperCase());
  return { value: known ? String(value) : "许可待确认", filter: known ? "declared" : "unknown" };
}

function githubToolbar(parent) {
  const bar = el("div", "toolbar github-toolbar");
  const input = el("input");
  input.id = "content-search";
  input.type = "search";
  input.placeholder = "检索仓库名称、原始描述、标签与已保存 README…";
  input.setAttribute("aria-label", "检索研究记录");
  input.value = app.query;
  input.addEventListener("input", () => {
    app.query = input.value;
    app.page = 1;
    app.matchedIds = null;
    app.searchQuery = "";
    app.searchError = "";
    clearTimeout(app.searchTimer);
    render();
    const query = app.query.trim();
    if (query) app.searchTimer = setTimeout(() => searchDocuments(query), 250);
  });
  bar.append(input);
  const filters = [
    [
      "category",
      "按资源方向筛选",
      [["全部方向", ""], ...Object.entries(githubCategories).map(([value, name]) => [name, value])],
    ],
    [
      "kind",
      "按资源性质筛选",
      [["全部性质", ""], ...Object.entries(githubKinds).map(([value, name]) => [name, value])],
    ],
    [
      "license",
      "按许可证记录筛选",
      [
        ["全部许可状态", ""],
        ["有许可证标识", "declared"],
        ["许可待确认", "unknown"],
      ],
    ],
    [
      "archived",
      "按仓库归档状态筛选",
      [
        ["全部维护状态", ""],
        ["未归档", "active"],
        ["已归档", "archived"],
      ],
    ],
  ];
  for (const [key, label, options] of filters) {
    const selector = el("select");
    selector.id = "github-filter-" + key;
    selector.setAttribute("aria-label", label);
    options.forEach(([name, value]) => selector.add(new Option(name, value)));
    selector.value = githubFilters[key];
    selector.addEventListener("change", () => {
      githubFilters[key] = selector.value;
      app.page = 1;
      render();
    });
    bar.append(selector);
  }
  parent.append(bar);
}

async function refreshGithub() {
  if (githubRunning()) return;
  githubSubmitting = true;
  render();
  try {
    await api("/api/github/refresh", {});
    message(
      "GitHub 资料采集已提交。仓库元数据与 README 的实际获取结果会逐项显示；失败时保留已有版本。",
    );
    await refresh(false);
  } catch (error) {
    message("GitHub 资料采集未能提交：" + error.message, true);
  } finally {
    githubSubmitting = false;
    render();
  }
}

function renderGithub(parent) {
  renderGithubSummary(parent);
  githubToolbar(parent);
  const rows = githubResources().filter(
    (resource) =>
      (!githubFilters.category || resource.category === githubFilters.category) &&
      (!githubFilters.kind || resource.kind === githubFilters.kind) &&
      (!githubFilters.license || githubLicense(resource).filter === githubFilters.license) &&
      (!githubFilters.archived ||
        (githubFilters.archived === "archived"
          ? Boolean(resource.archived)
          : resource.archived === false || resource.archived === 0)) &&
      (matches(resource) ||
        (app.searchQuery === app.query.trim() && app.matchedIds?.has(resource.readmeDocumentId))),
  );
  const order = { ontology: 0, governance: 1, fde: 2 };
  rows.sort(
    (a, b) =>
      (order[a.category] ?? 9) - (order[b.category] ?? 9) ||
      Number(githubReadmeSaved(b)) - Number(githubReadmeSaved(a)) ||
      Number(b.stars || 0) - Number(a.stars || 0) ||
      String(a.fullName).localeCompare(String(b.fullName)),
  );
  parent.append(
    el(
      "p",
      "list-count",
      rows.length +
        " 个仓库 · " +
        rows.filter(githubReadmeSaved).length +
        " 个已保存 README。" +
        (app.query.trim()
          ? app.searchError
            ? "README 全文检索暂不可用，当前仅匹配仓库记录：" + app.searchError
            : app.searchQuery === app.query.trim()
              ? "已检索保存的 README。"
              : "正在检索保存的 README…"
          : ""),
    ),
  );
  if (!rows.length)
    parent.append(
      empty(
        githubResources().length ? "没有符合当前筛选的资源" : "尚无已登记的 GitHub 资源",
        githubResources().length
          ? "可调整关键词、资源方向、性质或许可状态。"
          : "仓库登记和真实获取完成后会出现在这里，不以链接清单充当已取得的资料。",
      ),
    );
  else pageList(parent, rows, githubCard);
}

function githubCard(resource) {
  const card = el("article", "card github-card");
  const saved = githubReadmeSaved(resource);
  const license = githubLicense(resource);
  add(
    card,
    add(
      el("div", "badges"),
      badge(githubCategories[resource.category] || "方向待分类"),
      badge(githubKinds[resource.kind] || "性质待分类"),
      resource.registration === "search_candidate" ? badge("候选 · 待复核") : null,
      saved ? null : badge("README 尚未取得"),
      license.filter === "unknown" ? badge("许可待确认") : null,
      resource.archived ? badge("已归档") : null,
    ),
    add(el("h2"), link(resource.fullName || resource.id || "仓库名称未记录", resource.url)),
    el("p", "field-label", "作者原述 · 未实测"),
    el("p", "github-description", resource.description || "仓库未提供描述。"),
  );
  const numeric = (value) =>
    value === null || value === undefined ? "未记录" : Number(value).toLocaleString();
  add(
    card,
    meta(
      "★ " + numeric(resource.stars),
      resource.language,
      license.filter === "declared" ? license.value : null,
      "最近推送 " + date(resource.pushedAt).split(" ")[0],
    ),
  );
  if (resource.error)
    card.append(
      el(
        "p",
        "boundary",
        saved ? "更新失败 · 当前可阅读上次保存的版本" : "资料获取失败 · 原因见采集详情",
      ),
    );
  if (saved) {
    const sourceDoc = documents().find((doc) => doc.id === resource.readmeDocumentId) || {
      id: resource.readmeDocumentId,
      sha256: resource.readmeSha256,
      chars: resource.readmeChars,
    };
    const reason = readingUnavailable(sourceDoc);
    const translate = button("英文转中文", () =>
      openDocument(resource.readmeDocumentId, "translate", true),
    );
    const explain = button("通俗解读", () =>
      openDocument(resource.readmeDocumentId, "explain", true),
    );
    [translate, explain].forEach((node) => {
      node.disabled = Boolean(reason);
      if (reason) node.title = reason;
    });
    const read = button(
      "阅读 README",
      () => openDocument(resource.readmeDocumentId),
      "small primary",
    );
    const key = encodeURIComponent(resource.fullName || resource.id || resource.readmeDocumentId);
    read.id = "github-read-" + key;
    translate.id = "github-translate-" + key;
    explain.id = "github-explain-" + key;
    card.append(add(el("div", "actions"), read, translate, explain));
  } else card.append(add(el("div", "actions"), link("打开 GitHub ↗", resource.url)));
  if (resource.selectionReason)
    card.append(detail("选入理由 · 研究整理", resource.selectionReason));
  const guide = researchData().repoGuides?.find(
    (item) => item.fullName?.toLowerCase() === resource.fullName?.toLowerCase(),
  );
  if (guide) card.append(repoGuidePanel(guide));
  const info = githubAcquisitionDetails(resource, numeric);
  card.append(info);
  return card;
}

function repoGuidePanel(guide) {
  const panel = el("details", "research-editorial");
  panel.append(el("summary", null, "使用路径与适配判断 · 研究整理"));
  for (const [key, label] of [
    ["purpose", "要解决的问题"],
    ["fit", "适用前提"],
    ["notFit", "不适用情形"],
  ])
    if (guide[key])
      panel.append(
        researchSection(
          label,
          Array.isArray(guide[key]) ? researchList(guide[key]) : researchText(guide[key]),
        ),
      );
  if (researchRows(guide.steps).length)
    panel.append(researchSection("建议上手步骤", researchList(guide.steps, true)));
  if (guide.verification)
    panel.append(el("p", "boundary", "验证状态：" + researchText(guide.verification)));
  if (researchRows(guide.artifacts).length) {
    panel.append(el("h3", null, "实际资料与示例入口"));
    guide.artifacts.forEach((artifact, index) =>
      panel.append(researchEvidence(artifact, { key: guide.fullName + "-" + index })),
    );
  }
  return panel;
}

function renderGithubGaps(intro, data) {
  const gaps = Array.isArray(data.gaps) ? data.gaps : data.gaps ? [data.gaps] : [];
  if (gaps.length) {
    const box = el("details", "github-gaps");
    box.append(el("summary", null, "当前尚未取得或存在缺口的仓库（" + gaps.length + "）"));
    const list = el("ul");
    gaps.forEach((gap) => {
      const row = el("li");
      if (typeof gap === "string") row.textContent = gap;
      else {
        const title =
          gap.fullName || gap.repo || gap.title || gap.url || gap.category || "采集缺口";
        add(
          row,
          safeUrl(gap.url) ? link(title, gap.url) : el("span", null, title),
          el(
            "span",
            null,
            "：" +
              (gap.error ||
                gap.message ||
                gap.reason ||
                (gap.metadataStatus || gap.readmeStatus
                  ? "元数据 " +
                    githubStatus(gap.metadataStatus) +
                    " / README " +
                    githubStatus(gap.readmeStatus)
                  : githubStatus(gap.status))),
          ),
        );
      }
      list.append(row);
    });
    box.append(list);
    intro.append(box);
  }
}

function renderGithubDiscovery(intro, data) {
  const discovery = data.discovery;
  if (discovery?.queries?.length) {
    const box = el("details");
    box.append(
      el("summary", null, "查看最近检索范围与实际结果（" + discovery.queries.length + " 条检索）"),
    );
    box.append(
      el(
        "p",
        "subtle",
        discovery.scope || "有界检索只覆盖记录中的查询与分页，不代表全部相关仓库。",
      ),
    );
    discovery.queries.forEach((query) => {
      const item = el("section", "github-query");
      add(
        item,
        link(query.query || "GitHub 仓库检索", query.url),
        meta(
          githubStatus(query.status),
          "取得 " + (query.obtained ?? "未取得") + " 个结果",
          "第 " + (query.page ?? "未记录") + " 页",
          query.totalCount !== undefined
            ? "GitHub 报告匹配 " + Number(query.totalCount).toLocaleString() + " 条"
            : null,
        ),
      );
      if (query.incompleteResults) item.append(el("p", "subtle", "GitHub 标记本次结果不完整。"));
      if (query.error) item.append(el("p", "reading-error", query.error));
      box.append(item);
    });
    intro.append(box);
  }
}

function renderGithubExclusions(intro, data) {
  if (Array.isArray(data.excluded) && data.excluded.length) {
    const box = el("details", "github-gaps");
    box.append(el("summary", null, "已排除检索结果（" + data.excluded.length + "）"));
    box.append(el("p", "subtle", "这些结果不计入当前资源清单；已经取得的原文仍保留在资料库中。"));
    const list = el("ul");
    data.excluded.forEach((resource) => {
      const row = el("li");
      add(
        row,
        link(resource.fullName || resource.id || "仓库名称未记录", resource.url),
        el("span", null, "：" + (resource.exclusionReason || "排除原因未记录")),
      );
      list.append(row);
    });
    box.append(list);
    intro.append(box);
  }
}

function renderGithubSummary(parent) {
  const data = githubData();
  const run = data.lastRun;
  const intro = el("details", "secondary-panel github-summary");
  const orphaned = !githubRunning() && isActive(run?.status);
  const updateStatus = githubRunning()
    ? "正在更新"
    : orphaned
      ? "更新中断"
      : run
        ? githubStatus(run.status)
        : "尚未更新";
  add(
    intro,
    el(
      "summary",
      null,
      "每周更新 · " +
        updateStatus +
        (githubResources().some((r) => !githubReadmeSaved(r))
          ? " · " +
            githubResources().filter((r) => !githubReadmeSaved(r)).length +
            " 份 README 待补齐"
          : ""),
    ),
    meta("最近更新 " + date(run?.endedAt || run?.startedAt), "下次到期 " + date(data.nextDueAt)),
  );
  intro.append(
    el(
      "p",
      "subtle",
      "每周一 09:00（纽约时间）随现有日程更新，设备和应用需可运行。已取得仓库资料和 README，未审计或运行源码；清单仍在扩充。",
    ),
  );
  if (run?.error)
    intro.append(
      el(
        "p",
        "reading-error",
        typeof run.error === "string" ? run.error : JSON.stringify(run.error),
      ),
    );
  renderGithubGaps(intro, data);
  renderGithubDiscovery(intro, data);
  renderGithubExclusions(intro, data);
  parent.append(intro);
}

function githubAcquisitionDetails(resource, numeric) {
  const info = el("details", "technical-details");
  add(
    info,
    el("summary", null, "采集详情"),
    meta(
      "最近尝试 " + date(resource.lastAttempt),
      "最近完整取得 " + date(resource.lastSuccess),
      githubStatus(resource.lastStatus || "NOT_ATTEMPTED"),
    ),
    meta(
      "元数据：" + githubStatus(resource.metadataStatus),
      "README：" + githubStatus(resource.readmeStatus),
    ),
  );
  if (resource.error)
    info.append(
      el(
        "p",
        "reading-error",
        typeof resource.error === "string" ? resource.error : JSON.stringify(resource.error),
      ),
    );
  add(
    info,
    el(
      "p",
      "source-path",
      "README：" +
        numeric(resource.readmeChars) +
        " 字符 · SHA-256：" +
        (resource.readmeSha256 || "未取得"),
    ),
    meta("Fork " + numeric(resource.forks), "默认分支 " + (resource.defaultBranch || "未记录")),
    link("打开 GitHub ↗", resource.url),
    resource.readmeUrl ? link("README 来源 ↗", resource.readmeUrl) : null,
  );
  if (resource.tags?.length) info.append(el("p", "subtle", resource.tags.join(" · ")));
  return info;
}
