"use strict";

function renderLearning(parent) {
  const lessons = researchRows(researchData().learning);
  if (!lessons.length) return;
  const section = el("section", "research-module");
  const completed = lessons.filter((lesson) => lesson.progress?.status === "completed").length;
  const workspace = el(
    "div",
    "researcher-workspace learning-workspace" + (researchUI.lessonDetail ? " mobile-detail" : ""),
  );
  const index = el("aside", "research-index");
  index.setAttribute("aria-label", "学习目录");
  add(
    index,
    add(el("div", "section-header"), el("h2", null, "学习路径")),
    el("p", "subtle", "自记完成 " + completed + " / " + lessons.length),
  );
  const selected = lessons.filter(matches);
  const retained = selected.find((lesson) => lesson.id === researchUI.lessonId);
  const current = retained || selected[0];
  if (!retained) researchUI.lessonDetail = false;
  if (current) researchUI.lessonId = current.id;
  workspace.className =
    "researcher-workspace learning-workspace" + (researchUI.lessonDetail ? " mobile-detail" : "");
  const list = el("div", "research-index-list");
  const labels = { not_started: "未开始", in_progress: "学习中", completed: "自记完成" };
  selected.forEach((lesson) => {
    const choice = button(
      "",
      () => {
        researchUI.lessonId = lesson.id;
        researchUI.lessonDetail = true;
        render();
        researchFocus("lesson-detail-title");
      },
      "research-index-item" + (lesson.id === current?.id ? " active" : ""),
    );
    choice.id = "lesson-choice-" + lesson.id;
    choice.setAttribute("aria-pressed", String(lesson.id === current?.id));
    const progress = el(
      "span",
      "index-meta",
      labels[researchUI.drafts.get(lesson.id)?.status || lesson.progress?.status || "not_started"],
    );
    progress.id = "lesson-status-" + lesson.id;
    add(
      choice,
      el("span", "index-title", lesson.title),
      el("span", "index-summary", lesson.goal),
      progress,
    );
    list.append(choice);
  });
  index.append(list);
  if (!selected.length)
    index.append(empty("没有符合关键词的单元", "可清除关键词后查看全部学习路径。"));
  const detailPane = el("section", "research-detail");
  add(
    detailPane,
    researchBack("lesson"),
    current ? learningCard(current) : empty("没有符合条件的学习单元", "可返回目录调整筛选。"),
  );
  add(workspace, index, detailPane);
  section.append(workspace);
  parent.append(section);
}

function learningCard(lesson) {
  const card = el("article", "card learning-card");
  const heading = el("h2", null, lesson.title);
  heading.id = "lesson-detail-title";
  heading.tabIndex = -1;
  add(card, heading, el("p", "research-goal", lesson.goal));
  if (researchRows(lesson.concepts).length)
    card.append(add(el("div", "badges"), ...lesson.concepts.map((concept) => badge(concept))));
  const references = researchRows(lesson.sourceRefs);
  if (references.length) {
    card.append(researchSection("学习资料", sourceMaterialList(references)));
    const evidence = researchDetails("原文引文（" + references.length + "）");
    references.forEach((reference, index) =>
      evidence.append(researchEvidence(reference, { key: lesson.id + "-" + index })),
    );
    card.append(evidence);
  }
  add(
    card,
    researchSection("练习", researchText(lesson.exercise)),
    researchSection("完成产出", researchText(lesson.deliverable)),
  );
  const criteria = researchDetails(
    "自查与常见误区",
    researchSection("自查条件", researchList(lesson.passCriteria)),
  );
  if (lesson.pitfall) criteria.append(el("p", "boundary", researchText(lesson.pitfall)));
  card.append(criteria);
  const record = learningProgressRecord(lesson);
  card.append(record);
  return card;
}

function learningProgressRecord(lesson) {
  const draft = researchUI.drafts.get(lesson.id) || {
    status: lesson.progress?.status || "not_started",
    notes: lesson.progress?.notes || "",
  };
  const form = el("form", "learning-progress");
  const progress = el("select");
  progress.id = "learning-progress-" + lesson.id;
  progress.setAttribute("aria-label", lesson.title + "学习进度");
  [
    ["尚未开始", "not_started"],
    ["学习中", "in_progress"],
    ["自行标记完成", "completed"],
  ].forEach(([label, value]) => progress.add(new Option(label, value)));
  progress.value = draft.status;
  const notes = el("textarea");
  notes.id = "learning-notes-" + lesson.id;
  notes.setAttribute("aria-label", lesson.title + "练习记录");
  notes.placeholder = "记录练习产出、原文位置和仍不理解的问题…";
  notes.value = draft.notes;
  notes.maxLength = 6000;
  const keepDraft = () =>
    researchUI.drafts.set(lesson.id, { status: progress.value, notes: notes.value });
  progress.addEventListener("change", keepDraft);
  notes.addEventListener("input", keepDraft);
  const submit = el("button", null, "保存学习记录");
  submit.type = "submit";
  const saved = el("span", "subtle");
  saved.setAttribute("role", "status");
  add(
    form,
    el("label", null, "练习记录"),
    notes,
    add(el("div", "form-row"), progress, submit, saved),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    submit.disabled = true;
    saved.textContent = "正在保存…";
    const values = { id: lesson.id, status: progress.value, notes: notes.value };
    try {
      await api("/api/research/progress", values);
      const latestDraft = researchUI.drafts.get(lesson.id);
      const hasNewerDraft =
        latestDraft && (latestDraft.status !== values.status || latestDraft.notes !== values.notes);
      if (!hasNewerDraft) researchUI.drafts.delete(lesson.id);
      lesson.progress = { status: values.status, notes: values.notes };
      const current = researchRows(researchData().learning).find((item) => item.id === lesson.id);
      if (current) current.progress = lesson.progress;
      const indexStatus = $("lesson-status-" + lesson.id);
      if (indexStatus)
        indexStatus.textContent =
          progressLabels[hasNewerDraft ? latestDraft.status : values.status];
      record.children[0].textContent = "我的进度 · " + progressLabels[values.status];
      saved.textContent = hasNewerDraft ? "已保存提交内容；新修改尚未保存" : "已保存";
      message("学习记录已保存。");
    } catch (error) {
      saved.textContent = "保存失败，输入已保留。";
      message(error.message, true);
    } finally {
      submit.disabled = false;
    }
  });
  const progressLabels = {
    not_started: "未开始",
    in_progress: "学习中",
    completed: "已自行标记完成",
  };
  const record = researchDetails(
    "我的进度 · " + (progressLabels[draft.status] || "未开始"),
    el("p", "subtle", "进度由你自记，保存在本地。"),
    form,
  );
  record.open = researchUI.drafts.has(lesson.id);
  return record;
}
