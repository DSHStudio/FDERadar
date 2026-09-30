"use strict";

function evidenceMatches(doc, reference) {
  if (!doc || !reference) return { positions: [], error: "" };
  if (reference.documentId !== doc.id || !reference.sha256 || reference.sha256 !== doc.sha256)
    return { positions: [], error: "引用与当前原文版本不一致，未定位。" };
  if (reference.valid !== true)
    return { positions: [], error: "这条引用尚未匹配，请结合完整原文核对。" };
  const quote = typeof reference.quote === "string" ? reference.quote : "";
  if (!quote) return { positions: [], error: "该资料未指定引文，可直接阅读原文。" };
  const content = typeof doc.content === "string" ? doc.content : "";
  const positions = [];
  let offset = 0;
  while (positions.length < 200) {
    const next = content.indexOf(quote, offset);
    if (next < 0) break;
    positions.push(next);
    offset = next + quote.length;
  }
  return {
    positions,
    error: positions.length ? "" : "在此版本中未找到完全一致的原句，未定位。",
    limited: positions.length === 200,
  };
}

function renderEvidenceLocation() {
  const locator = $("evidence-locator");
  if (!locator) return;
  locator.replaceChildren();
  locator.hidden = reader.mode !== "original" || !reader.evidence || !reader.document;
  if (locator.hidden) return;
  const match = evidenceMatches(reader.document, reader.evidence);
  if (match.error) {
    locator.append(el("p", "reading-error", match.error));
    return;
  }
  reader.occurrence = Math.min(Math.max(reader.occurrence, 0), match.positions.length - 1);
  const index = match.positions[reader.occurrence];
  const quote = reader.evidence.quote;
  const content = reader.document.content;
  const output = $("document-content");
  const mark = el("mark", "evidence-highlight", quote);
  mark.id = "evidence-highlight";
  output.replaceChildren(
    el("span", null, content.slice(0, index)),
    mark,
    el("span", null, content.slice(index + quote.length)),
  );
  locator.append(
    el(
      "span",
      null,
      match.positions.length > 1
        ? "原句定位 " +
            (reader.occurrence + 1) +
            " / " +
            match.positions.length +
            (match.limited ? "（前 200 处）" : "")
        : "已定位引用原句",
    ),
  );
  if (match.positions.length > 1) {
    const prev = button("上一处", () => {
      reader.occurrence--;
      renderReading();
    });
    prev.disabled = reader.occurrence === 0;
    const next = button("下一处", () => {
      reader.occurrence++;
      renderReading();
    });
    next.disabled = reader.occurrence === match.positions.length - 1;
    locator.append(prev, next);
  }
  if (mark.scrollIntoView) mark.scrollIntoView({ block: "center", behavior: "instant" });
}

async function openEvidence(reference) {
  if (!reference?.documentId) return;
  await openDocument(reference.documentId, "original", false, {
    documentId: reference.documentId,
    sha256: reference.sha256,
    quote: reference.quote,
    valid: reference.valid,
  });
}

function readingUnavailable(doc) {
  if (!doc) return "尚未取得原文文档。";
  if (["metadata_only", "shell", "listing"].includes(doc.quality))
    return "此版本只有目录、元数据或页面框架，需要先取得实际资料文本。";
  if (
    [
      "metadata_only",
      "http_error",
      "insufficient_body",
      "access_restricted",
      "robots_disallowed",
      "robots_unavailable",
    ].includes(doc.access)
  )
    return "此版本没有取得足以加工的正文。";
  if (
    (Object.prototype.hasOwnProperty.call(doc, "content") && !String(doc.content || "").trim()) ||
    doc.chars === 0
  )
    return "未保存可读原文，不能以生成内容替代。";
  if (!doc.sha256) return "原文版本校验信息缺失，请先重新采集。";
  return "";
}

function readingKey(doc, mode) {
  return doc.id + ":" + doc.sha256 + ":" + mode;
}

function stopReadingPoll() {
  clearTimeout(reader.timer);
  reader.timer = null;
}

function readerIsCurrent(generation, id, mode) {
  return (
    $("document-dialog").open &&
    reader.generation === generation &&
    app.selectedDocument === id &&
    reader.mode === mode
  );
}

function validateReadingTask(task, doc, mode) {
  if (!task) return null;
  if (task.documentId !== doc.id || task.sha256 !== doc.sha256 || task.mode !== mode)
    throw new Error("阅读结果与当前原文版本不一致，已阻止展示。请重新取得本版本的结果。");
  return task;
}

function readingStatusLabel(value) {
  return (
    {
      QUEUED: "等待处理",
      RUNNING: "正在处理",
      SUCCEEDED: "已完成",
      FAILED: "处理失败",
      CANCELLED: "已取消",
      INTERRUPTED: "处理已中断",
    }[String(value || "").toUpperCase()] || status(value)
  );
}

function readingError(value) {
  const raw = typeof value === "string" ? value : value ? JSON.stringify(value) : "";
  const labels = {
    DOCUMENT_NOT_FOUND: "原文文档不存在，请重新采集。",
    INVALID_READING_MODE: "阅读模式无效，请重新选择中文译文或通俗解读。",
    MODEL_CREDENTIAL_UNAVAILABLE: "模型凭据暂不可用，请检查本地 DSH 服务配置。",
    SOURCE_BODY_NOT_AVAILABLE: "当前来源没有可加工的正文，请先补齐原文。",
  };
  for (const [code, label] of Object.entries(labels))
    if (raw.includes(code)) return label + "（诊断：" + raw + "）";
  return raw;
}

function renderReading() {
  const doc = reader.document;
  const limit = readingUnavailable(doc);
  const original = reader.mode === "original";
  for (const mode of ["original", "translate", "explain"]) {
    const tab = $("reader-tab-" + mode);
    tab.classList.toggle("active", reader.mode === mode);
    tab.setAttribute("aria-selected", String(reader.mode === mode));
    tab.disabled = mode !== "original" && Boolean(limit);
  }
  const output = $("document-content");
  output.setAttribute("aria-labelledby", "reader-tab-" + reader.mode);
  output.classList.toggle("ai-reading", !original);
  const panel = $("reading-status");
  panel.replaceChildren();
  panel.hidden = original;
  if ($("evidence-locator")) $("evidence-locator").hidden = !original;
  if (original) {
    renderOriginalReading(doc, limit, output);
    return;
  }
  const label = reader.mode === "translate" ? "AI 中文译文" : "AI 通俗解读";
  $("document-boundary").textContent =
    label +
    " · 可能有误，请结合原文阅读。" +
    (doc?.quality === "partial" ? " 来源本身不完整，不代表整篇文章已处理。" : "");
  add(
    panel,
    add(
      el("div", "badges"),
      badge(label),
      reader.task
        ? badge(readingStatusLabel(reader.task.status), isFailure(reader.task.status) ? "warn" : "")
        : null,
    ),
  );
  if (limit) {
    panel.append(el("p", "boundary", limit));
    output.textContent = "此文档暂不可加工。请先补齐来源正文。";
    return;
  }
  if (reader.error) panel.append(el("p", "reading-error", readingError(reader.error)));
  const task = reader.task;
  if (!task) {
    renderUnstartedReading(panel, output);
    return;
  }
  renderReadingTask(panel, output, task);
}

function scheduleReadingPoll(generation, id, mode) {
  stopReadingPoll();
  if (!readerIsCurrent(generation, id, mode) || !reader.task || !isActive(reader.task.status))
    return;
  reader.timer = setTimeout(() => loadReading(false), 2000);
}

async function loadReading(start = false) {
  const doc = reader.document;
  const mode = reader.mode;
  const generation = reader.generation;
  if (!doc || mode === "original" || readingUnavailable(doc) || reader.loading) return;
  stopReadingPoll();
  reader.loading = true;
  reader.error = "";
  renderReading();
  try {
    let task = validateReadingTask(
      await api("/api/reading?documentId=" + encodeURIComponent(doc.id) + "&mode=" + mode),
      doc,
      mode,
    );
    if (!readerIsCurrent(generation, doc.id, mode)) return;
    if (
      start &&
      (!task || ["FAILED", "CANCELLED", "INTERRUPTED"].includes(String(task.status).toUpperCase()))
    )
      task = validateReadingTask(
        await api("/api/reading", { documentId: doc.id, mode }),
        doc,
        mode,
      );
    if (!readerIsCurrent(generation, doc.id, mode)) return;
    reader.task = task;
    if (task) reader.cache.set(readingKey(doc, mode), task);
    else reader.cache.delete(readingKey(doc, mode));
  } catch (error) {
    if (readerIsCurrent(generation, doc.id, mode)) reader.error = error.message;
  } finally {
    if (readerIsCurrent(generation, doc.id, mode)) {
      reader.loading = false;
      renderReading();
      scheduleReadingPoll(generation, doc.id, mode);
    }
  }
}

async function setReadingMode(mode, start = false) {
  if (!["original", "translate", "explain"].includes(mode) || !reader.document) return;
  stopReadingPoll();
  reader.generation++;
  reader.mode = mode;
  reader.loading = false;
  reader.cancelling = false;
  reader.error = "";
  reader.task =
    mode === "original" ? null : reader.cache.get(readingKey(reader.document, mode)) || null;
  renderReading();
  if (mode !== "original") await loadReading(start);
}

async function cancelReading() {
  const doc = reader.document;
  const mode = reader.mode;
  const generation = reader.generation;
  const task = reader.task;
  if (!doc || !task || !isActive(task.status) || reader.cancelling) return;
  stopReadingPoll();
  reader.cancelling = true;
  reader.error = "";
  renderReading();
  try {
    const next = validateReadingTask(await api("/api/reading/cancel", { id: task.id }), doc, mode);
    if (!readerIsCurrent(generation, doc.id, mode)) return;
    reader.task = next;
    if (next) reader.cache.set(readingKey(doc, mode), next);
  } catch (error) {
    if (readerIsCurrent(generation, doc.id, mode)) reader.error = error.message;
  } finally {
    if (readerIsCurrent(generation, doc.id, mode)) {
      reader.cancelling = false;
      renderReading();
      scheduleReadingPoll(generation, doc.id, mode);
    }
  }
}

async function openDocument(id, mode = "original", start = false, evidence = null) {
  reader.returnFocusId = document.activeElement?.id || reader.returnFocusId;
  reader.evidence = evidence;
  reader.occurrence = 0;
  stopReadingPoll();
  const generation = ++reader.generation;
  app.selectedDocument = id;
  reader.document = null;
  reader.mode = "original";
  reader.task = null;
  reader.loading = true;
  reader.cancelling = false;
  reader.error = "";
  $("document-title").textContent = "正在读取保存文本…";
  $("document-meta").replaceChildren();
  if (!$("document-dialog").open) $("document-dialog").showModal();
  renderReading();
  try {
    const fetched = await api("/api/document?id=" + encodeURIComponent(id));
    if (!readerIsCurrent(generation, id, "original")) return;
    const doc = { ...(app.data ? documents().find((item) => item.id === id) : {}), ...fetched };
    reader.document = doc;
    reader.loading = false;
    $("document-title").textContent = doc.title || "来源未提供标题";
    add(
      $("document-meta"),
      meta(
        link("打开原始来源 ↗", doc.url),
        doc.quality === "evidence_text" ? "原文 · 未独立核验" : status(doc.quality || doc.access),
      ),
      detail(
        "来源与版本详情",
        "取得时间：" +
          date(doc.retrievedAt) +
          "\n" +
          status(doc.access) +
          "\n" +
          (doc.contentScope || "") +
          "\nSHA-256：" +
          (doc.sha256 || "未记录"),
      ),
    );
    const locator = el("div", "evidence-locator");
    locator.id = "evidence-locator";
    locator.hidden = true;
    locator.setAttribute("role", "status");
    $("document-meta").append(locator);
    renderReading();
    if (mode !== "original") await setReadingMode(mode, start);
  } catch (error) {
    if (reader.generation !== generation || app.selectedDocument !== id) return;
    reader.loading = false;
    reader.error = error.message + "。不以 AI 摘要替代缺失原文。";
    $("document-title").textContent = "无法读取该文档";
    renderReading();
  }
}

function closeDocument() {
  stopReadingPoll();
  reader.generation++;
  app.selectedDocument = null;
  reader.document = null;
  reader.task = null;
  reader.loading = false;
  reader.cancelling = false;
  reader.evidence = null;
  reader.occurrence = 0;
}

function renderOriginalReading(doc, limit, output) {
  $("document-boundary").textContent =
    "原文提取文本；图表与附件请查看来源。" +
    (doc?.quality === "partial" ? " 当前仅取得部分文本。" : "") +
    (limit ? " AI 阅读暂不可用：" + limit : "");
  output.textContent = doc
    ? doc.content || "未保存可读正文。此状态不能当作已经读过全文。"
    : reader.loading
      ? "正在读取保存文本…"
      : reader.error || "尚未取得原文。";
  renderEvidenceLocation();
}

function renderUnstartedReading(panel, output) {
  add(
    panel,
    el(
      "p",
      "subtle",
      reader.loading
        ? "正在读取任务与缓存…"
        : "尚未生成" + (reader.mode === "translate" ? "中文译文。" : "通俗解读。"),
    ),
  );
  if (!reader.loading)
    panel.append(
      button(
        reader.error
          ? "重新连接并读取缓存"
          : reader.mode === "translate"
            ? "英文转中文"
            : "通俗解读",
        () => loadReading(!reader.error),
      ),
    );
  output.textContent = "";
}

function renderReadingTask(panel, output, task) {
  const completed = Math.max(0, Number(task.completedChunks) || 0);
  const total = Math.max(0, Number(task.totalChunks) || 0);
  const processed = Math.max(0, Number(task.processedChars) || 0);
  const chars = Math.max(0, Number(task.totalChars) || 0);
  const remaining = Math.max(0, chars - processed);
  const progress = el("progress", "reading-progress");
  progress.max = total || chars || 1;
  progress.value = total ? Math.min(completed, total) : Math.min(processed, chars);
  progress.setAttribute("aria-label", "AI 阅读处理进度");
  add(
    panel,
    el("p", "reading-progress-text", "已完成 " + completed + " / " + (total || "待计算") + " 段"),
    progress,
  );
  if (remaining || (total && completed < total))
    panel.append(
      el(
        "p",
        "reading-remaining",
        "尚有 " +
          (remaining ? remaining.toLocaleString() + " 字符" : total - completed + " 段") +
          "未处理。下方仅为已完成片段，不是完整" +
          (reader.mode === "translate" ? "译文" : "解读") +
          "。",
      ),
    );
  if (!total && !chars)
    panel.append(el("p", "subtle", "任务尚未报告完整处理范围，暂不能认定覆盖全文。"));
  if (task.error) panel.append(el("p", "reading-error", readingError(task.error)));
  if (isActive(task.status))
    add(
      panel,
      add(
        el("div", "actions"),
        button(reader.cancelling ? "正在请求取消…" : "取消此阅读任务", () => cancelReading()),
      ),
      el("p", "subtle", "可关闭窗口，处理会继续。"),
    );
  else if (["FAILED", "CANCELLED", "INTERRUPTED"].includes(String(task.status).toUpperCase()))
    panel.append(button("重试此阅读任务", () => loadReading(true)));
  if (reader.error) panel.append(button("重新同步任务", () => loadReading(false)));
  if (reader.loading) panel.append(el("p", "subtle", "正在提交或同步任务…"));
  panel.append(
    detail(
      "处理详情",
      "任务：" +
        task.id +
        "\n已处理 " +
        processed +
        " / " +
        chars +
        " 字符\n开始：" +
        date(task.startedAt || task.createdAt) +
        "\n结束：" +
        date(task.endedAt),
    ),
  );
  output.textContent =
    typeof task.content === "string" && task.content
      ? task.content
      : "尚无已完成的处理片段。已取得的原文仍可在「原文」视图阅读。";
  panel.querySelectorAll("button").forEach((node) => {
    node.disabled = reader.loading || reader.cancelling;
  });
}
