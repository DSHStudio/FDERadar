"use strict";

function researchData() {
  return app.data?.research || {};
}

function researchRows(value) {
  return Array.isArray(value) ? value : [];
}

function researchText(value) {
  return typeof value === "string"
    ? value
    : value === undefined || value === null
      ? ""
      : typeof value === "object"
        ? JSON.stringify(value, null, 2)
        : String(value);
}

function researchList(values, ordered = false) {
  const list = el(ordered ? "ol" : "ul", "research-list");
  (Array.isArray(values) ? values : values ? [values] : []).forEach((value) =>
    list.append(el("li", null, researchText(value))),
  );
  return list;
}

function researchSection(title, content) {
  return add(
    el("section", "research-section"),
    el("h3", null, title),
    typeof content === "string" ? el("p", null, content) : content,
  );
}

function researchDetails(title, ...children) {
  return add(el("details", "secondary-panel"), el("summary", null, title), ...children);
}

function researchTechnical(title, ...children) {
  const panel = researchDetails(title, ...children);
  panel.className = "secondary-panel technical-details";
  return panel;
}

function researchOpenEvidence(reference) {
  return typeof openEvidence === "function"
    ? openEvidence(reference)
    : openDocument(reference.documentId);
}

function evidenceHasExcerpt(reference) {
  const quote = String(reference.quote || "").trim();
  return (
    quote.length >= 12 &&
    (quote.split(/\s+/).length >= 3 || (quote.match(/[\u3400-\u9fff]/g) || []).length >= 6)
  );
}

function researchControlId(prefix, key) {
  return prefix + "-" + encodeURIComponent(String(key)).replace(/%/g, "_");
}

function researchSourceDate(value) {
  const raw = String(value || "");
  return raw.match(/^\d{4}-\d{2}-\d{2}/)?.[0] || raw;
}

function sourceMaterial(reference) {
  const doc = documents().find((item) => item.id === reference.documentId) || {};
  const title = reference.title || doc.title || reference.label || reference.url || "来源资料";
  const url = reference.url || doc.url;
  const material = el("article", "source-material");
  if (reference.documentId) {
    const read = button(
      title,
      () => researchOpenEvidence(reference),
      "linklike source-material-title",
    );
    read.id = researchControlId("source-material", reference.documentId);
    material.append(read);
  } else material.append(add(el("h3", "source-material-title"), link(title, url)));
  const publisher =
    reference.publisher || doc.publisher || (safeUrl(url) ? host(url) : "来源未记录");
  const published = reference.publishedAt || doc.publishedAt;
  const collected = reference.retrievedAt || doc.retrievedAt;
  add(
    material,
    meta(
      publisher,
      published
        ? "来源标注 " + researchSourceDate(published) + "（待核对）"
        : collected
          ? "采集于 " + researchSourceDate(collected)
          : null,
      reference.valid === false ? badge("引用待核对", "warn") : null,
    ),
  );
  if (safeUrl(url)) material.append(link("原站 ↗", url));
  return material;
}

function sourceMaterialList(references) {
  const selected = new Map();
  for (const reference of references) {
    const key = reference.documentId || reference.url;
    if (!key) continue;
    const previous = selected.get(key);
    if (
      !previous ||
      (reference.valid &&
        (!previous.valid || (evidenceHasExcerpt(reference) && !evidenceHasExcerpt(previous))))
    )
      selected.set(key, reference);
  }
  const list = el("div", "source-materials");
  [...selected.values()].forEach((reference) => list.append(sourceMaterial(reference)));
  return list;
}

function researchFocus(id) {
  const node = $(id);
  if (node?.focus) node.focus({ preventScroll: true });
}

function researchBack(kind) {
  const buttonNode = button(
    kind === "case" ? "返回案例列表" : "返回学习目录",
    () => {
      if (kind === "case") researchUI.caseDetail = false;
      else researchUI.lessonDetail = false;
      render();
      researchFocus(
        kind + "-choice-" + (kind === "case" ? researchUI.caseId : researchUI.lessonId),
      );
    },
    "quiet research-back",
  );
  return buttonNode;
}

function researchEvidence(reference, { compact = false, key = "" } = {}) {
  const row = el("section", "evidence-reference");
  const valid = reference.valid === true;
  const invalid = reference.valid === false;
  add(
    row,
    add(
      el("div", "badges"),
      badge(
        valid
          ? reference.quote
            ? "引文已匹配"
            : "版本已匹配"
          : invalid
            ? "引用需重新核对"
            : "引用待核对",
        valid ? "good" : invalid ? "warn" : "",
      ),
      badge("未独立核验"),
    ),
  );
  if (reference.quote) {
    if (evidenceHasExcerpt(reference))
      add(
        row,
        !valid ? el("p", "field-label", "登记引文 · 尚未匹配，不作为已核对原句") : null,
        el("blockquote", null, reference.quote),
      );
    else
      row.append(el("p", "subtle", (valid ? "原文定位词：" : "待核对定位词：") + reference.quote));
  }
  add(row, el("p", "subtle", reference.title || reference.label || "来源资料"));
  if (reference.scope) row.append(el("p", "subtle", "取得范围：" + researchText(reference.scope)));
  if (reference.reason)
    row.append(el("p", invalid ? "boundary" : "subtle", researchText(reference.reason)));
  if (reference.stale) row.append(el("p", "boundary", "来源已有新版本，此处保留历史引文。"));
  const actions = el("div", "actions");
  if (reference.documentId) {
    const read = button(invalid ? "打开保存原文核对" : "定位原文", () =>
      researchOpenEvidence(reference),
    );
    if (key) read.id = researchControlId("evidence", key);
    actions.append(read);
  }
  if (reference.stale && reference.latestDocumentId)
    actions.append(button("比较最新原文", () => openDocument(reference.latestDocumentId)));
  if (safeUrl(reference.url)) actions.append(link("打开来源 ↗", reference.url));
  if (actions.childElementCount) row.append(actions);
  if (!reference.documentId && !safeUrl(reference.url))
    row.append(el("p", "subtle", "此项尚无可打开的来源正文。"));
  if (!compact && reference.sha256)
    row.append(
      researchTechnical(
        "来源版本",
        el("p", "source-path", "引用版本 SHA-256：" + reference.sha256),
        reference.documentId ? el("p", "source-path", "文档：" + reference.documentId) : null,
      ),
    );
  return row;
}

function researchAcquisition(item) {
  const box = el("div", "research-acquisition");
  add(box, el("p", null, item.purpose || item.owner || "补充来源证据"));
  if (item.status)
    box.append(meta(status(item.status), item.error ? researchText(item.error) : null));
  const actions = el("div", "actions");
  if (item.documentId)
    actions.append(button("阅读已取得原文", () => openDocument(item.documentId)));
  if (safeUrl(item.url))
    add(
      actions,
      link("查看待补来源 ↗", item.url),
      button("获取此资料", () =>
        action(
          "/api/collect",
          { urls: [item.url], force: true },
          "已提交补证资料获取任务；取得原文后仍需核对相关主张。",
        ),
      ),
    );
  box.append(actions);
  return box;
}

function renderResearchAudit(parent) {
  const audit = researchData().audit;
  if (!audit) return;
  const card = el("details", "card research-module secondary-panel");
  add(card, el("summary", null, "研究证据复核"), el("h2", null, "研究结论的证据缺口"));
  const summary = el("div", "research-audit-counts");
  for (const [key, label] of [
    ["unresolvedClaims", "待补证的主张"],
    ["invalidReferences", "引用未匹配"],
    ["staleReferences", "来源有更新的引用"],
    ["notIndependentlyVerified", "未独立核验"],
  ]) {
    const value = audit[key];
    if (value !== undefined)
      summary.append(
        add(
          el("div"),
          el("strong", null, Array.isArray(value) ? value.length : value),
          el("span", null, label),
        ),
      );
  }
  card.append(summary);
  if (researchRows(audit.acquisitionGaps).length) {
    const gaps = el("details");
    gaps.append(el("summary", null, "查看补证队列（" + audit.acquisitionGaps.length + "）"));
    audit.acquisitionGaps.forEach((item) => gaps.append(researchAcquisition(item)));
    card.append(gaps);
  }
  if (researchRows(audit.invalidDetails).length) {
    const invalid = el("details");
    invalid.append(el("summary", null, "定位未匹配的引用"));
    audit.invalidDetails.forEach((item) => {
      const row = el("section", "research-acquisition");
      add(row, el("p", null, item.owner), el("p", "boundary", item.reason || "引用需要重新核对"));
      if (item.documentId)
        row.append(button("打开登记原文核对", () => openDocument(item.documentId)));
      invalid.append(row);
    });
    card.append(invalid);
  }
  if (researchRows(audit.staleDetails).length) {
    const stale = el("details");
    stale.append(el("summary", null, "比较已有新版本的引用"));
    audit.staleDetails.forEach((item) => {
      const row = el("section", "research-acquisition");
      row.append(el("p", null, item.owner));
      const actions = el("div", "actions");
      if (item.documentId)
        actions.append(button("引用的旧版本", () => openDocument(item.documentId)));
      if (item.latestDocumentId)
        actions.append(button("已取得的新版本", () => openDocument(item.latestDocumentId)));
      row.append(actions);
      stale.append(row);
    });
    card.append(stale);
  }
  if (researchRows(audit.configErrors).length)
    card.append(
      el(
        "p",
        "reading-error",
        "部分研究资料配置未能加载：" +
          audit.configErrors
            .map((item) => (item.file || "未记录文件") + " · " + (item.error || "读取失败"))
            .join("；"),
      ),
    );
  parent.append(card);
}
