"use strict";

function claimNeedsAttention(claim) {
  return (
    claim.status === "conflicting" ||
    researchRows(claim.evidence).some((reference) => reference.valid === false)
  );
}

function renderCaseResearch(parent) {
  const entries = researchRows(researchData().cases);
  if (!entries.length) return;
  const section = el("section", "research-module");
  const workspace = el(
    "div",
    "researcher-workspace case-workspace" + (researchUI.caseDetail ? " mobile-detail" : ""),
  );
  const index = el("aside", "research-index");
  index.setAttribute("aria-label", "案例列表");
  add(index, add(el("div", "section-header"), el("h2", null, "重点案例")));
  const filters = el("div", "toolbar");
  const selector = el("select");
  selector.id = "case-evidence-filter";
  selector.setAttribute("aria-label", "按案例证据缺口筛选");
  [
    ["全部重点案例", ""],
    ["存在信息缺口", "missing"],
    ["存在相互冲突的披露", "conflicting"],
    ["存在失效引用", "invalid"],
    ["披露过金额信息", "price"],
  ].forEach(([label, value]) => selector.add(new Option(label, value)));
  selector.value = researchUI.caseFilter;
  selector.addEventListener("change", () => {
    researchUI.caseFilter = selector.value;
    render();
  });
  filters.append(selector);
  index.append(filters);
  const selected = entries.filter((entry) => {
    const claims = researchRows(entry.claims);
    const filter = researchUI.caseFilter;
    return (
      matches(entry) &&
      (!filter ||
        (filter === "missing" &&
          (researchRows(entry.gaps).length ||
            claims.some((claim) => claim.status === "unknown"))) ||
        (filter === "conflicting" && claims.some((claim) => claim.status === "conflicting")) ||
        (filter === "invalid" &&
          claims.some((claim) =>
            researchRows(claim.evidence).some((reference) => reference.valid === false),
          )) ||
        (filter === "price" &&
          claims.some((claim) => claim.key === "price" && claim.status === "disclosed")))
    );
  });
  index.append(el("p", "list-count", selected.length + " / " + entries.length + " 个案例"));
  const retained = selected.find((entry) => entry.id === researchUI.caseId);
  const current = retained || selected[0];
  if (!retained) {
    researchUI.caseDetail = false;
    researchUI.casePane = "facts";
  }
  if (current) researchUI.caseId = current.id;
  workspace.className =
    "researcher-workspace case-workspace" + (researchUI.caseDetail ? " mobile-detail" : "");
  const list = el("div", "research-index-list");
  selected.forEach((entry) => {
    const choice = button(
      "",
      () => {
        if (researchUI.caseId !== entry.id) researchUI.casePane = "facts";
        researchUI.caseId = entry.id;
        researchUI.caseDetail = true;
        render();
        researchFocus("case-detail-title");
      },
      "research-index-item" + (entry.id === current?.id ? " active" : ""),
    );
    choice.id = "case-choice-" + entry.id;
    choice.setAttribute("aria-pressed", String(entry.id === current?.id));
    const claims = researchRows(entry.claims);
    const unknown = claims.filter((claim) => claim.status === "unknown").length;
    const attention = claims.filter(claimNeedsAttention).length;
    add(
      choice,
      el("span", "index-title", entry.title),
      add(
        el("span", "index-meta"),
        badge(unknown ? unknown + " 项待补证" : "已有来源披露"),
        attention ? badge(attention + " 项需复核", "warn") : null,
      ),
    );
    list.append(choice);
  });
  index.append(list);
  if (!selected.length) index.append(empty("没有符合此证据条件的重点条目", "请调整筛选条件。"));
  const detailPane = el("section", "research-detail");
  add(
    detailPane,
    researchBack("case"),
    current ? caseResearchCard(current) : empty("没有符合条件的案例", "可返回列表调整筛选。"),
  );
  add(workspace, index, detailPane);
  section.append(workspace);
  parent.append(section);
}

function caseResearchCard(entry) {
  const card = el("article", "card research-case");
  const claims = researchRows(entry.claims);
  const first = claims
    .flatMap((claim) => researchRows(claim.evidence))
    .find((reference) => safeUrl(reference.url));
  const heading = el("h2");
  heading.id = "case-detail-title";
  heading.tabIndex = -1;
  heading.append(first ? link(entry.title, first.url) : el("span", null, entry.title));
  add(card, badge("来源披露 · 未独立核验"), heading);
  const paneName = ["facts", "sources", "analysis"].includes(researchUI.casePane)
    ? researchUI.casePane
    : "facts";
  const tabs = el("div", "case-tabs");
  tabs.setAttribute("aria-label", "案例内容");
  for (const [name, label] of [
    ["facts", "项目事实"],
    ["sources", "原始资料"],
    ["analysis", "研究解读"],
  ]) {
    const tab = button(
      label,
      () => {
        researchUI.casePane = name;
        render();
        researchFocus("case-tab-" + name);
      },
      name === paneName ? "active" : "",
    );
    tab.id = "case-tab-" + name;
    tab.setAttribute("aria-pressed", String(name === paneName));
    tabs.append(tab);
  }
  card.append(tabs);
  const pane = el("section", "case-pane");
  pane.setAttribute(
    "aria-label",
    { facts: "项目事实", sources: "原始资料", analysis: "研究解读" }[paneName],
  );
  if (paneName === "facts") {
    renderCaseFacts(pane, claims, entry);
  } else if (paneName === "sources") {
    renderCaseSources(pane, claims, entry);
  } else {
    renderCaseAnalysis(pane, claims, entry);
  }
  card.append(pane);
  return card;
}

function renderCaseFacts(pane, claims, entry) {
  pane.append(el("p", "subtle", "按字段核对来源原文。公开金额不等于方案报价。"));
  const claimList = el("div", "case-facts");
  const labels = { disclosed: "来源披露", unknown: "待补证", conflicting: "披露有冲突" };
  for (const claim of claims) {
    const references = researchRows(claim.evidence);
    const validQuotes = references.filter(
      (reference) => reference.valid === true && reference.quote,
    );
    const meaningful = validQuotes.filter(evidenceHasExcerpt);
    const excerpts = meaningful.length ? meaningful : validQuotes;
    const claimBox = el("section", "case-fact");
    const attention = claimNeedsAttention(claim);
    const label = labels[claim.status] || "待核对";
    add(
      claimBox,
      add(
        el("div", "case-fact-header"),
        el("h3", "claim-label", claim.label || claim.key),
        badge(label, attention ? "warn" : ""),
      ),
    );
    if (excerpts.length)
      excerpts.forEach((reference, index) => {
        const read = button("定位原文", () => researchOpenEvidence(reference), "linklike");
        read.id = researchControlId("evidence", entry.id + "-" + claim.key + "-" + index);
        if (evidenceHasExcerpt(reference)) claimBox.append(el("blockquote", null, reference.quote));
        else claimBox.append(el("p", "subtle", "定位词：" + reference.quote + " · 需结合上下文"));
        claimBox.append(read);
      });
    else claimBox.append(el("p", "subtle", "尚无该项的充分原句依据。"));
    if (attention)
      claimBox.append(
        el(
          "p",
          "boundary",
          claim.status === "conflicting"
            ? "来源披露存在冲突，需结合完整资料核对。"
            : "部分引用未匹配，暂不作为已核对事实。",
        ),
      );
    claimList.append(claimBox);
  }
  pane.append(claimList);
}

function renderCaseSources(pane, claims, entry) {
  const references = claims.flatMap((claim) => researchRows(claim.evidence));
  if (references.length) pane.append(sourceMaterialList(references));
  else pane.append(empty("尚未取得来源资料", ""));
  const pending = references.filter((reference) => reference.valid === false || reference.stale);
  if (pending.length) {
    const review = researchDetails("需复核的引用（" + pending.length + "）");
    pending.forEach((reference, index) =>
      review.append(researchEvidence(reference, { key: entry.id + "-pending-" + index })),
    );
    pane.append(review);
  }
}

function renderCaseAnalysis(pane, claims, entry) {
  pane.className += " research-editorial";
  pane.append(el("p", "field-label", "研究整理 · 以下为中文解读，非来源原文"));
  if (entry.classification)
    pane.append(researchSection("研究分类", researchText(entry.classification)));
  if (entry.editorialNote)
    pane.append(researchSection("整理说明", researchText(entry.editorialNote)));
  const values = el("dl", "research-definition");
  for (const claim of claims)
    add(
      values,
      el("dt", null, claim.label || claim.key),
      el("dd", null, researchText(claim.value) || "尚未取得充分披露。"),
    );
  pane.append(values);
  if (entry.transfer) {
    for (const [key, label] of [
      ["usable", "可借鉴部分"],
      ["conditions", "迁移前提"],
      ["notProven", "尚未证明"],
    ])
      if (entry.transfer[key])
        pane.append(researchSection(label, researchList(entry.transfer[key])));
  }
  const gaps = researchRows(entry.gaps);
  const nextSources = researchRows(entry.nextAcquisition);
  if (gaps.length || nextSources.length) {
    const acquisition = researchDetails(
      gaps.length
        ? "待补证 · " + gaps.length + " 项缺口"
        : "补充资料 · " + nextSources.length + " 个来源",
    );
    if (gaps.length) acquisition.append(researchList(gaps));
    if (nextSources.length) {
      acquisition.append(el("h3", null, "可补充的资料"));
      nextSources.forEach((item) => acquisition.append(researchAcquisition(item)));
    }
    pane.append(acquisition);
  }
}
