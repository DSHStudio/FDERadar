"use strict";

function renderTasks(parent) {
  const pending = notes().filter((n) => n.status === "pending_review");
  parent.append(
    add(
      el("div", "section-header"),
      el("h2", null, "待审核笔记"),
      el("span", "subtle", pending.length + " 篇"),
    ),
  );
  const renderReview = (note) => {
    const card = el("article", "card");
    add(
      card,
      badge("AI 研究 · " + status(note.status)),
      el("h3", null, note.title),
      meta(views[note.track]?.[0], date(note.createdAt)),
    );
    if (note.payload.quote) card.append(el("blockquote", null, note.payload.quote));
    if (note.payload.documentId)
      card.append(button("核对原文", () => openDocument(note.payload.documentId)));
    card.append(noteAnalysis(note), reviewButtons(note));
    return card;
  };
  if (!pending.length) parent.append(empty("暂无待审核笔记", "新研究完成后会出现在这里。"));
  const reviews = el("div", "cards");
  pending.forEach((n) => reviews.append(renderReview(n)));
  parent.append(reviews);
  const reviewed = notes().filter((n) => ["accepted", "rejected"].includes(n.status));
  if (reviewed.length) {
    const history = el("details", "secondary-panel");
    history.append(el("summary", null, "已审核笔记 · " + reviewed.length));
    reviewed.forEach((n) => history.append(renderReview(n)));
    parent.append(history);
  }
  const work = el("details", "secondary-panel");
  add(work, el("summary", null, "发起新研究"), analyzeForm());
  parent.prepend(work);
  const jobs = [...(app.data.jobs || [])].sort((a, b) =>
    String(b.createdAt).localeCompare(String(a.createdAt)),
  );
  const runs = [...(app.data.runs || [])].sort((a, b) =>
    String(b.startedAt).localeCompare(String(a.startedAt)),
  );
  const active = [
    ...jobs.filter((j) => isActive(j.status)).map(jobCard),
    ...runs.filter((r) => isActive(r.status)).map(runCard),
  ];
  if (active.length)
    parent.prepend(add(el("section", "active-tasks"), el("h2", null, "正在进行"), ...active));
  const log = el("details", "secondary-panel");
  const failed = [...jobs, ...runs].filter((r) => isFailure(r.status)).length;
  log.append(
    el("summary", null, "运行记录" + (failed ? " · " + failed + " 项存在获取或执行问题" : "")),
  );
  add(
    log,
    el("h3", null, "采集记录"),
    ...jobs
      .filter((j) => !isActive(j.status))
      .slice(0, 30)
      .map(jobCard),
    el("h3", null, "研究记录"),
    ...runs
      .filter((r) => !isActive(r.status))
      .slice(0, 15)
      .map(runCard),
  );
  parent.append(log);
  if (app.data.capabilities)
    parent.append(detail("服务与调度详情", JSON.stringify(app.data.capabilities, null, 2)));
}

function analyzeForm() {
  const card = el("section", "card");
  add(
    card,
    el("h2", null, "研究问题"),
    el(
      "p",
      "subtle",
      "写明问题、时间和地区范围。已有来源可直接引用；新事实必须有可追溯的获取记录。",
    ),
  );
  const form = el("form");
  const task = el("textarea");
  task.required = true;
  task.minLength = 8;
  task.setAttribute("aria-label", "研究任务");
  task.placeholder =
    "例如：检查本周新增材料中的中国制造业项目。逐项区分本体、FDE 和 Agent 的证据，引用原文，注明无法验证的部分。";
  const submit = el("button", null, "开始研究");
  submit.type = "submit";
  add(form, task, add(el("div", "form-row"), submit));
  bindFormSubmission(form, submit, {
    draftKey: "analyze",
    path: "/api/analyze",
    prepare: () => ({ task: task.value.trim() }),
    successMessage: "DSH 研究任务已提交。请查看运行状态和待审核笔记。",
  });
  bindFormDraft(form, "analyze", [task]);
  card.append(form);
  return card;
}

function jobCard(job) {
  const card = el("article", "card job");
  add(
    card,
    add(el("div", "badges"), badge(status(job.status), isFailure(job.status) ? "warn" : "good")),
    el("h3", null, job.title || job.type || "来源采集"),
    meta(
      "开始 " + date(job.startedAt || job.createdAt),
      "结束 " + date(job.completedAt || job.endedAt),
    ),
  );
  if (job.counts)
    card.append(
      el(
        "div",
        "progress-counts",
        Object.entries(job.counts)
          .map(
            ([k, v]) =>
              (({
                total: "总计",
                succeeded: "已取得",
                failed: "失败",
                pending: "等待",
                running: "进行中",
                unchanged: "无变化",
                cancelled: "已取消",
                completed: "已完成",
              })[k] || status(k)) +
              " " +
              v,
          )
          .join(" · "),
      ),
    );
  if (job.error)
    card.append(
      detail("失败原因", typeof job.error === "object" ? JSON.stringify(job.error) : job.error),
    );
  if (job.items?.length) {
    const details = el("details");
    details.append(el("summary", null, "查看逐项结果（" + job.items.length + "）"));
    job.items.forEach((item) =>
      details.append(
        add(
          el("div", "meta"),
          link(item.title || item.url || item.id || "采集条目", item.url),
          badge(
            status(item.status || item.access),
            isFailure(item.status || item.access) ? "warn" : "",
          ),
          el(
            "span",
            null,
            item.error
              ? typeof item.error === "object"
                ? JSON.stringify(item.error)
                : item.error
              : "",
          ),
        ),
      ),
    );
    card.append(details);
  }
  if (isActive(job.status))
    card.append(
      button("取消此任务", () =>
        action("/api/cancel", { id: job.id }, "已请求取消；正在进行的网络请求可能在超时后结束。"),
      ),
    );
  return card;
}

function runCard(run) {
  const card = el("article", "card job");
  add(
    card,
    badge(status(run.status), isFailure(run.status) ? "warn" : ""),
    el("p", "task-text", run.task || "研究任务"),
    meta("开始 " + date(run.startedAt), "结束 " + date(run.endedAt)),
  );
  let result = run.result;
  if (typeof result === "string") {
    try {
      result = JSON.parse(result);
    } catch (_) {}
  }
  if (result)
    card.append(
      detail(
        "查看运行结果（AI 输出）",
        typeof result === "object" ? result.response || JSON.stringify(result, null, 2) : result,
      ),
    );
  if (isActive(run.status))
    card.append(el("p", "subtle", "研究执行中；此界面不提供研究进程的强制终止。"));
  return card;
}

function reviewButtons(note) {
  const row = el("div", "review-actions");
  [
    ["收入研究笔记", "accepted"],
    ["排除此笔记", "rejected"],
    ["退回待审核", "pending_review"],
  ].forEach(([label, next]) => {
    if (note.status !== next)
      row.append(
        button(label, () =>
          action(
            "/api/review",
            { id: note.id, status: next },
            "审核状态已保存。该操作不改变事实核验等级。",
          ),
        ),
      );
  });
  return row;
}
