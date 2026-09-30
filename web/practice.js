"use strict";

function researchLabRunning() {
  return researchUI.labSubmitting || Boolean(researchUI.lab?.running);
}

const labArmNames = {
  sql_rules: "规则基线",
  retrieval_dsh: "原文 + AI",
  ontology_dsh: "本体 + AI",
};

function labStatus(value) {
  return (
    {
      QUEUED: "已排队",
      RUNNING: "正在执行",
      COMPLETED: "本轮执行结束",
      COMPLETED_WITH_FAILURES: "执行结束 · 部分题次失败",
      SUCCEEDED: "输出完成",
      FAILED: "执行失败",
      INTERRUPTED: "执行中断",
    }[String(value || "").toUpperCase()] || status(value)
  );
}

function renderPracticeMetrics() {
  const state = researchUI.lab;
  const run = state?.latest;
  const metrics = [
    [state?.dataset?.questions ?? "—", "合成练习题目"],
    [researchRows(state?.arms).length || "—", "同题比较的方法"],
    [run?.completed ?? "—", "已执行题次（含失败）"],
    [
      run ? researchRows(run.results).filter((result) => result.status === "FAILED").length : "—",
      "执行失败题次",
    ],
  ];
  $("metrics").setAttribute("aria-label", "本地试验实际运行进度");
  $("metrics").replaceChildren(
    ...metrics.map(([value, label]) =>
      add(el("div", "metric"), el("strong", null, value), el("span", null, label)),
    ),
  );
}

async function loadResearchLab(redraw = true) {
  if (researchUI.labLoading) return;
  researchUI.labLoading = true;
  try {
    researchUI.lab = await api("/api/lab");
    researchUI.labError = "";
  } catch (error) {
    researchUI.labError = error.message;
  } finally {
    researchUI.labLoading = false;
    if (redraw && app.view === "practice") render();
  }
}

async function runResearchLab() {
  if (researchLabRunning()) return;
  researchUI.labSubmitting = true;
  render();
  try {
    await api("/api/lab/run", {});
    message("试验已提交。");
    await loadResearchLab(false);
  } catch (error) {
    message("试验未能启动：" + error.message, true);
  } finally {
    researchUI.labSubmitting = false;
    render();
    await refresh(false);
  }
}

function renderPractice(parent) {
  const state = researchUI.lab;
  if (!state) {
    parent.append(
      empty(researchUI.labError ? "暂时无法读取试验" : "正在读取试验…", researchUI.labError || ""),
    );
    if (researchUI.labError) parent.append(button("重试", () => loadResearchLab()));
    else if (!researchUI.labLoading) loadResearchLab();
    return;
  }
  const intro = el("section", "card research-module");
  add(
    intro,
    el("h2", null, state.dataset?.title || "对照试验"),
    add(
      el("div", "badges"),
      badge(state.dataset?.synthetic === true ? "合成数据练习" : "数据范围见运行记录", "warn"),
      ...researchRows(state.arms).map((arm) => badge(labArmNames[arm] || arm)),
    ),
    el("p", "subtle", "比较同一问题的三种解法。合成试验结果不代表企业实测或收益。"),
  );
  const method = researchTechnical(
    "试验方法与限制",
    el("p", "coverage-note", researchText(state.scope)),
    el(
      "p",
      "coverage-note",
      "文本臂接收全部授权记录，未测向量检索或检索召回率；本体臂的约束拦截与模型原始正确率分开统计。",
    ),
  );
  if (state.fairness) method.append(el("p", "coverage-note", researchText(state.fairness)));
  if (state.boundaryMeaning)
    method.append(el("p", "coverage-note", "程序控制边界：" + researchText(state.boundaryMeaning)));
  if (state.costMeaning)
    method.append(el("p", "coverage-note", "耗时与成本口径：" + researchText(state.costMeaning)));
  method.append(
    el(
      "p",
      "boundary",
      "自动判分只比较指定的结构化字段；引用 ID 存在不等于引用支持结论。这里不评估解释忠实性，也不检测自由文本泄露，不能把字段检查通过理解为全面安全。",
    ),
  );
  const start = button(
    researchLabRunning() ? "试验运行中…" : "运行试验",
    () => runResearchLab(),
    "",
  );
  start.id = "run-lab";
  start.disabled = researchLabRunning();
  add(
    intro,
    add(
      el("div", "actions"),
      start,
      button("刷新结果", () => loadResearchLab()),
    ),
  );
  parent.append(intro);
  if (researchUI.labError)
    add(
      parent,
      el("p", "boundary", "结果刷新失败，当前显示上次记录。"),
      researchTechnical("连接详情", el("p", "reading-error", researchUI.labError)),
    );
  if (state.latest) parent.append(labRunCard(state.latest));
  else parent.append(empty("尚无实际试验记录", ""));
  parent.append(method);
  if (state.dataset) {
    const dataset = el("details", "card research-module secondary-panel technical-details");
    dataset.append(
      el("summary", null, "练习题与数据（" + (state.dataset.questions ?? "已登记") + " 题）"),
    );
    add(
      dataset,
      meta("版本 " + (state.dataset.version || "未记录")),
      el("p", "source-path", "数据 SHA-256：" + (state.dataset.dataSha256 || "未记录")),
      el("p", "source-path", "题目 SHA-256：" + (state.dataset.questionSha256 || "未记录")),
    );
    researchRows(state.dataset.challenges).forEach((challenge) => {
      const item = el("section", "lab-step");
      add(
        item,
        el("h3", null, challenge.id + " · " + challenge.challenge),
        el("pre", "lab-pre", researchText(challenge.request)),
      );
      dataset.append(item);
    });
    parent.append(dataset);
  }
  const previous = researchRows(state.runs).filter(
    (run) => !state.latest || run.id !== state.latest.id,
  );
  if (previous.length) {
    const history = el("details");
    history.append(el("summary", null, "历史试验运行（" + previous.length + "）"));
    previous.forEach((run) => history.append(labRunCard(run)));
    parent.append(history);
  }
}

function labRunCard(run) {
  const card = el("article", "card lab-run");
  add(
    card,
    add(
      el("div", "badges"),
      badge(labStatus(run.status), isFailure(run.status) ? "warn" : ""),
      run.synthetic ? badge("合成试验", "warn") : null,
    ),
    el("h2", null, run.title || "试验结果"),
    meta(date(run.endedAt || run.completedAt || run.startedAt || run.createdAt)),
  );
  const technical = researchTechnical(
    "数据与运行详情",
    meta(
      "开始 " + date(run.startedAt || run.createdAt),
      "结束 " + date(run.endedAt || run.completedAt),
      run.model ? "模型 " + run.model : null,
      run.id,
    ),
  );
  if (Number.isFinite(Number(run.total)) && Number(run.total) > 0) {
    const progress = el("progress", "reading-progress");
    progress.max = Number(run.total);
    progress.value = Math.min(Number(run.completed) || 0, Number(run.total));
    progress.setAttribute("aria-label", "本地试验执行进度");
    add(
      card,
      el(
        "p",
        "reading-progress-text",
        "已执行 " + (run.completed || 0) + " / " + run.total + " 题次",
      ),
      progress,
    );
    technical.append(
      el(
        "p",
        "subtle",
        "已执行 " +
          (run.completed || 0) +
          " / " +
          run.total +
          " 题次（包含执行失败；不是通过题数）",
      ),
    );
  }
  if (run.error) {
    card.append(el("p", "boundary", "本轮未完整完成，已取得的结果仍保留。"));
    technical.append(el("p", "reading-error", researchText(run.error)));
  }
  const metrics = run.metrics || {};
  if (Object.keys(metrics).length) {
    const currentScoring = Boolean(
      run.scoringVersion ||
        Object.values(metrics).some((value) => value.scoringVersion) ||
        researchRows(run.results).some((result) => result.grading?.scoringVersion),
    );
    renderLabComparison(card, metrics);
    renderLabScoringDetails(technical, metrics, currentScoring);
  }
  renderLabQuestions(card, run);
  const artifacts = el("div", "actions");
  if (run.id) {
    add(
      artifacts,
      button("查看合成数据快照", () => openLabArtifact(run.id, "data")),
      button("查看题目与标准答案", () => openLabArtifact(run.id, "questions")),
    );
    if (run.startedAt || Number(run.completed) > 0)
      card.append(
        add(
          el("div", "actions"),
          button("阅读试点准备包", () => openLabArtifact(run.id, "pilotPack")),
        ),
      );
    artifacts.append(button("阅读完整运行回执", () => openLabArtifact(run.id, "receipt")));
  }
  technical.append(artifacts, detail("完整记录", researchText(run)));
  card.append(technical);
  return card;
}

function labResultCard(result, runId) {
  const card = el("section", "lab-step");
  add(
    card,
    el("h3", null, labArmNames[result.arm] || result.arm),
    add(
      el("div", "badges"),
      badge(labStatus(result.status), result.status === "FAILED" ? "warn" : ""),
      result.grading
        ? badge(
            result.grading.correct ? "自动判分：正确" : "自动判分：不正确",
            result.grading.correct ? "good" : "warn",
          )
        : badge("尚无完整判分", "warn"),
    ),
  );
  const execution = researchTechnical(
    "执行与输入详情",
    meta(
      result.execution === "actual_dsh"
        ? "真实 DSH 调用"
        : result.execution === "deterministic_sql_rules"
          ? "确定性程序运行"
          : result.execution,
      result.elapsedSeconds === undefined ? null : "耗时 " + result.elapsedSeconds + " 秒",
      result.dsh?.finishReason ? "运行结束原因 " + result.dsh.finishReason : null,
    ),
  );
  if (result.error) execution.append(el("p", "reading-error", result.error));
  if (result.constraintCheck)
    add(
      card,
      el(
        "p",
        result.constraintCheck.accepted ? "subtle" : "boundary",
        result.constraintCheck.accepted
          ? "本体约束：输出通过已实现的约束检查。"
          : "本体约束：输出被拦截；拦截不会改写模型答案，也不将错误计为正确。",
      ),
      researchList(result.constraintCheck.violations),
    );
  if (result.answer) card.append(detail("结构化输出 · 系统解析结果", researchText(result.answer)));
  if (result.rawOutput !== undefined)
    card.append(detail("原始输出 · 未改写", researchText(result.rawOutput)));
  if (result.grading) {
    renderLabGrading(card, result);
  }
  const inputItem = result.arm + "-" + result.questionId;
  if (runId && /^(sql_rules|retrieval_dsh|ontology_dsh)-Q[1-8]$/.test(inputItem))
    execution.append(button("读取此题实际输入", () => openLabArtifact(runId, "input", inputItem)));
  add(
    execution,
    el(
      "p",
      "source-path",
      "输入 SHA-256：" +
        (result.inputSha256 || "未记录") +
        " · 授权事实哈希：" +
        (result.sourceFactHash || "未记录"),
    ),
    el("p", "source-path", "输出 SHA-256：" + (result.outputSha256 || "未记录")),
  );
  card.append(execution);
  return card;
}

async function openLabArtifact(runId, name, item) {
  const generation = (researchUI.artifactGeneration = (researchUI.artifactGeneration || 0) + 1);
  const dialog = $("lab-artifact-dialog");
  const titles = {
    pilotPack: "试点准备包",
    receipt: "完整运行回执",
    data: "合成数据快照",
    questions: "题目与标准答案",
    input: "逐题实际输入",
  };
  $("lab-artifact-title").textContent = titles[name] || "试验产出";
  $("lab-artifact-meta").textContent = "合成试验资料，不是企业生产数据";
  $("lab-artifact-content").textContent = "正在读取…";
  if (!dialog.open) dialog.showModal();
  try {
    const result = await api(
      "/api/lab/artifact?runId=" +
        encodeURIComponent(runId) +
        "&name=" +
        encodeURIComponent(name) +
        (item === undefined ? "" : "&item=" + encodeURIComponent(item)),
    );
    if (researchUI.artifactGeneration !== generation || !dialog.open) return;
    $("lab-artifact-content").textContent = result.text || "文件没有可读文本。";
  } catch (error) {
    if (researchUI.artifactGeneration === generation && dialog.open)
      $("lab-artifact-content").textContent =
        "未能读取已保存产出：" + error.message + "。不以生成文字替代缺失文件。";
  }
}

function renderLabComparison(card, metrics) {
  card.append(el("p", "subtle", "正确率仅评结构化答案，失败计错；未评价解释是否可靠。"));
  const comparison = el("table", "lab-table");
  const columns = el("tr");
  ["方法", "结构化正确率", "执行失败", "约束拦截"].forEach((label) =>
    columns.append(el("th", null, label)),
  );
  comparison.append(columns);
  for (const [arm, value] of Object.entries(metrics)) {
    const accuracy = labAccuracy(value);
    comparison.append(
      add(
        el("tr"),
        el("td", null, labArmNames[arm] || arm),
        el("td", null, accuracy),
        el(
          "td",
          null,
          Number.isFinite(Number(value.attempted)) && Number.isFinite(Number(value.completed))
            ? Math.max(0, Number(value.attempted) - Number(value.completed))
            : "—",
        ),
        el("td", null, arm === "ontology_dsh" ? (value.constraintBlocked ?? "—") : "—"),
      ),
    );
  }
  card.append(add(el("div", "table-wrap lab-result-metrics"), comparison));
}

function renderLabScoringDetails(technical, metrics, currentScoring) {
  technical.append(
    el(
      "p",
      "boundary",
      "自动判分基于固定合成题。正确率以已尝试题次为分母，执行失败计为不正确；小样本结果不能证明某种方法普遍更优。调用耗时也不是人工工时节省。",
    ),
  );
  technical.append(
    el(
      "p",
      "subtle",
      currentScoring
        ? "权限与动作评分仅检查结构化工单、引用 ID、动作标志和越权拒绝；不包含自由文本安全性或解释忠实性。"
        : "历史 v1 记录：边界项仅检查请求权限 / 无写入字段，不能证明输出未越权或系统全面安全；保留当时判分，不按新版重新计分。",
    ),
  );
  const table = el("table", "lab-table");
  const head = el("tr");
  [
    "方法",
    "执行成功 / 已尝试",
    "结构化字段正确率",
    currentScoring ? "输出权限 / 动作字段检查" : "历史 v1：请求权限 / 无写入字段",
    "约束拦截",
    "调用总耗时",
  ].forEach((label) => head.append(el("th", null, label)));
  table.append(head);
  for (const [arm, value] of Object.entries(metrics)) {
    const accuracy = labAccuracy(value);
    table.append(
      add(
        el("tr"),
        el("td", null, labArmNames[arm] || arm),
        el("td", null, (value.completed ?? "—") + " / " + (value.attempted ?? "—")),
        el("td", null, accuracy),
        el("td", null, (value.safetyPassed ?? "—") + " / " + (value.attempted ?? "—")),
        el("td", null, arm === "ontology_dsh" ? (value.constraintBlocked ?? "—") : "不设此检查"),
        el(
          "td",
          null,
          value.elapsedSeconds === undefined ? "未记录" : value.elapsedSeconds + " 秒",
        ),
      ),
    );
  }
  technical.append(add(el("div", "table-wrap lab-result-metrics"), table));
}

function renderLabQuestions(card, run) {
  const results = researchRows(run.results);
  if (results.length) {
    const details = researchDetails("逐题结果（" + results.length + " 题次）");
    const byQuestion = new Map();
    results.forEach((result) => {
      if (!byQuestion.has(result.questionId)) byQuestion.set(result.questionId, []);
      byQuestion.get(result.questionId).push(result);
    });
    for (const [id, rows] of byQuestion) {
      const question = el("details", "lab-question");
      question.append(el("summary", null, id + " · " + (rows[0].challenge || "试验题目")));
      rows.forEach((result) => question.append(labResultCard(result, run.id)));
      details.append(question);
    }
    card.append(details);
  }
}

function renderLabGrading(card, result) {
  const scoring = el("details");
  scoring.append(el("summary", null, "核对自动判分依据与标准答案"));
  const labels = {
    decision: "决策",
    delayDays: "延迟天数",
    writeRequested: "是否请求写入",
    impactedWorkOrders: "受影响工单",
    referencesExist: "引用 ID 存在",
  };
  scoring.append(
    researchList(
      Object.entries(result.grading.fieldChecks || {}).map(
        ([key, passed]) => (labels[key] || key) + "：" + (passed ? "通过" : "未通过"),
      ),
    ),
  );
  add(
    scoring,
    el(
      "p",
      "subtle",
      (result.grading.scoringVersion
        ? "输出权限与动作字段检查："
        : "历史v1：请求权限/无写入字段检查：") +
        (result.grading.safetyBoundaryPassed ? "通过" : "未通过"),
    ),
    el("pre", "lab-pre", researchText(result.grading.expected)),
    el("p", "subtle", result.grading.meaning || "固定合成题自动判分，不是企业生产验收。"),
    el(
      "p",
      "boundary",
      "准确率仅比较结构化字段；引用只检查ID存在，不评判解释是否忠实或引文是否支持结论。",
    ),
  );
  card.append(scoring);
}

function labAccuracy(value) {
  return value.accuracy === null || value.accuracy === undefined
    ? "尚无结果"
    : (Number(value.accuracy) * 100).toFixed(1) +
        "%（" +
        value.correct +
        " / " +
        value.attempted +
        "）";
}
