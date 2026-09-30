"use strict";

function toolbar(parent, includeTrack = false) {
  const bar = el("div", "toolbar");
  const input = el("input");
  input.id = "content-search";
  input.type = "search";
  input.placeholder = "搜索原文、标题或来源…";
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
  const selector = el("select");
  selector.id = "host-filter";
  selector.setAttribute("aria-label", "按来源域名筛选");
  add(selector, new Option("全部来源", ""));
  [...new Set([...documents().map((d) => host(d.url)), ...sources().map((s) => host(s.url))])]
    .sort()
    .forEach((value) => selector.add(new Option(value, value)));
  selector.value = app.host;
  selector.addEventListener("change", () => {
    app.host = selector.value;
    app.page = 1;
    render();
  });
  add(bar, input, selector);
  if (includeTrack) {
    const tracks = el("select");
    tracks.setAttribute("aria-label", "按研究主线筛选");
    [
      ["全部主线", ""],
      ["理论", "theory"],
      ["案例", "case"],
      ["场景", "scenario"],
      ["尚未归类", "unclassified"],
    ].forEach(([name, value]) => tracks.add(new Option(name, value)));
    tracks.value = app.track;
    tracks.addEventListener("change", () => {
      app.track = tracks.value;
      app.page = 1;
      render();
    });
    bar.append(tracks);
  }
  parent.append(bar);
}

async function searchDocuments(query) {
  try {
    const result = await api("/api/search?q=" + encodeURIComponent(query));
    if (app.query.trim() !== query) return;
    app.matchedIds = new Set(result.ids || []);
    app.searchQuery = query;
    app.searchError = "";
    render();
  } catch (error) {
    if (app.query.trim() !== query) return;
    app.searchError = error.message;
    render();
  }
}

function pageList(parent, items, renderer) {
  const max = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  app.page = Math.min(app.page, max);
  const cards = el("div", "cards");
  items
    .slice((app.page - 1) * PAGE_SIZE, app.page * PAGE_SIZE)
    .forEach((item) => cards.append(renderer(item)));
  parent.append(cards);
  if (max > 1) {
    const previous = button("上一页", () => {
      app.page--;
      render();
    });
    previous.disabled = app.page <= 1;
    const next = button("下一页", () => {
      app.page++;
      render();
    });
    next.disabled = app.page >= max;
    parent.append(
      add(el("div", "pagination"), previous, el("span", null, app.page + " / " + max), next),
    );
  }
}

function renderDocuments(parent) {
  toolbar(parent, app.view === "intelligence");
  const selectedTrack = app.view === "intelligence" ? app.track : app.view;
  const docs = documents()
    .filter((doc) => {
      const tracks = documentTracks(doc);
      const related = boundNotes(doc);
      return (
        (!selectedTrack ||
          (selectedTrack === "unclassified" ? !tracks.size : tracks.has(selectedTrack))) &&
        (!app.host || host(doc.url) === app.host) &&
        (matches(doc) ||
          related.some(matches) ||
          (app.searchQuery === app.query.trim() && app.matchedIds?.has(doc.id)))
      );
    })
    .sort((a, b) => String(b.retrievedAt).localeCompare(String(a.retrievedAt)));
  parent.append(
    el(
      "p",
      "list-count",
      docs.length +
        " 份资料版本" +
        (app.query.trim()
          ? app.searchError
            ? "全文检索失败，当前仅匹配标题 / 摘录：" + app.searchError
            : app.searchQuery === app.query.trim()
              ? "已检索保存的正文。"
              : "正在检索保存的正文…"
          : ""),
    ),
  );
  if (!docs.length)
    parent.append(
      empty(
        "此范围尚无已取得的原文",
        "已登记的材料仍可在下方研究索引查看。选择「采集到期信源」获取内容，或调整筛选。",
      ),
    );
  else pageList(parent, docs, documentCard);
  if (app.view !== "intelligence") renderHistorical(parent, app.view);
}

function documentCard(doc) {
  const card = el("article", "card document-card");
  const ns = boundNotes(doc);
  const labels = [...documentTracks(doc)].filter((t) => views[t]).map((t) => badge(views[t][0]));
  const quality =
    doc.quality === "evidence_text" ? null : badge(status(doc.quality || "范围待确认"), "warn");
  add(
    card,
    meta(
      host(doc.url),
      doc.publishedAt
        ? "来源标注 " + date(doc.publishedAt).split(" ")[0] + "（待核对）"
        : "采集于 " + date(doc.retrievedAt).split(" ")[0],
    ),
    add(el("h2"), link(doc.title || "来源未提供标题", doc.url)),
    add(el("div", "badges"), ...labels, quality, badge("未独立核验")),
  );
  const quote = ns.find((n) => n.payload.quote)?.payload.quote;
  if (quote) card.append(el("blockquote", null, quote));
  if (isFailure(doc.access) && !quality) card.append(badge(status(doc.access), "warn"));
  const readButton = button("阅读原文", () => openDocument(doc.id), "small primary");
  readButton.id = "read-" + doc.id;
  const translateButton = button("英文转中文", () => openDocument(doc.id, "translate", true));
  translateButton.id = "translate-" + doc.id;
  const explainButton = button("通俗解读", () => openDocument(doc.id, "explain", true));
  explainButton.id = "explain-" + doc.id;
  const readingLimit = readingUnavailable(doc);
  [translateButton, explainButton].forEach((node) => {
    node.disabled = Boolean(readingLimit);
    if (readingLimit) node.title = readingLimit;
  });
  add(card, add(el("div", "actions"), readButton, translateButton, explainButton));
  const info = el("details", "technical-details");
  add(
    info,
    el("summary", null, "来源详情"),
    meta(
      "采集于 " + date(doc.retrievedAt),
      status(doc.access),
      doc.format ? status(doc.format) : null,
      (doc.chars ?? doc.totalChars ?? "—") + " 字符",
    ),
  );
  if (doc.contentScope) info.append(el("p", "subtle", doc.contentScope));
  if (doc.publishedAt)
    info.append(el("p", "subtle", "来源所标日期（未核验）：" + date(doc.publishedAt)));
  add(
    info,
    el("p", "source-path", "SHA-256：" + (doc.sha256 || "未记录")),
    link("打开来源 ↗", doc.url),
  );
  if (readingLimit) info.append(el("p", "subtle", "AI 阅读暂不可用：" + readingLimit));
  card.append(info);
  ns.forEach((n) => card.append(noteAnalysis(n)));
  return card;
}

function noteAnalysis(note, forReview = false) {
  const p = note.payload;
  const box = el("details");
  add(box, el("summary", null, "AI 分析 · " + status(note.status)));
  const body = el("div", "analysis");
  add(body, badge("引用匹配不等于主张属实"));
  for (const [label, field] of [
    ["研究分析", "analysis"],
    ["证据边界", "limitations"],
    ["下一步", "nextStep"],
  ])
    if (p[field]) add(body, el("div", "analysis-label", label), el("div", null, p[field]));
  if (p.scenarioTested === false || note.track === "scenario")
    body.append(
      el("p", "boundary", "研究假设：未用企业数据进行实测，不能作为已经落地或收益已验证的项目。"),
    );
  body.append(
    meta("笔记 " + date(note.createdAt), "引用版本 " + String(p.sha256 || "未记录").slice(0, 12)),
  );
  if (forReview) body.append(reviewButtons(note));
  box.append(body);
  return box;
}

function renderHistorical(parent, track) {
  const rows = (app.data.records || []).filter(
    (r) =>
      recordTrack(r) === track &&
      matches(r) &&
      (!app.host || host(payload(r).url || payload(r).sourceUrl) === app.host),
  );
  const box = el("details", "historical card");
  add(box, el("summary", null, "历史研究整理 · " + rows.length + " 条"));
  rows.forEach((row) => {
    const p = payload(row);
    const item = el("section", "card historical");
    add(
      item,
      el("h3", null, p.title || p.name || p.project || row.id),
      meta("历史研究条目 " + row.id, p.classification || p.source_type || "研究索引"),
      el("p", "subtle", p.limits || p.limitations || "本条包含研究整理内容；具体事实请核对来源。"),
    );
    const url =
      p.url || p.sourceUrl || (p.sources && p.sources[0] && (p.sources[0].url || p.sources[0]));
    if (url) item.append(link("查看登记的来源 ↗", url));
    item.append(detail("展开完整历史记录（整理资料）", JSON.stringify(p, null, 2)));
    box.append(item);
  });
  parent.append(box);
}

function renderResearchChanges(parent) {
  const changes = researchRows(researchData().changes);
  if (!changes.length) return;
  const box = el("details", "card research-module secondary-panel");
  add(
    box,
    el("summary", null, "原文更新（" + changes.length + "）"),
    el(
      "p",
      "boundary",
      "这里只比较已保存文本的版本；页面改动可能只是导航、排版或措辞变化，不能直接视为理论、产品功能或项目实质变化。",
    ),
  );
  changes.forEach((change) => {
    const row = el("section", "research-change");
    add(
      row,
      add(el("h3"), link(change.title || change.url, change.url)),
      meta("取得 " + date(change.retrievedAt)),
      el("p", "subtle", change.meaning || "原文版本变化，尚未核对语义"),
    );
    const actions = el("div", "actions");
    if (change.oldDocumentId)
      actions.append(button("阅读旧版本", () => openDocument(change.oldDocumentId)));
    if (change.newDocumentId)
      actions.append(button("阅读新版本", () => openDocument(change.newDocumentId)));
    add(
      row,
      actions,
      el(
        "p",
        "source-path",
        "旧版本 " + (change.oldHash || "未记录") + " → 新版本 " + (change.newHash || "未记录"),
      ),
    );
    box.append(row);
  });
  parent.append(box);
}
