"use strict";

function renderScenarios(parent) {
  parent.append(el("h2", "section-title", "AI 研究笔记"));
  toolbar(parent);
  const rows = notes().filter(
    (n) =>
      n.track === "scenario" && matches(n) && (!app.host || host(n.payload.sourceUrl) === app.host),
  );
  if (!rows.length)
    parent.append(
      empty("尚无符合筛选的场景研究", "在「任务与审核」中启动有具体企业痛点与来源要求的研究任务。"),
    );
  pageList(parent, rows, (n) => {
    const card = el("article", "card");
    add(
      card,
      badge("研究建议 · 未实测", "warn"),
      el("h2", null, n.title),
      meta(status(n.status), date(n.createdAt)),
      el("p", "subtle", n.payload.summary),
    );
    if (n.payload.quote) card.append(el("blockquote", null, n.payload.quote));
    if (n.payload.documentId)
      card.append(button("查看依据文本", () => openDocument(n.payload.documentId)));
    card.append(noteAnalysis(n));
    return card;
  });
  renderHistorical(parent, "scenario");
}

function renderScenarioResearch(parent) {
  const scenarios = researchRows(researchData().scenarios);
  if (!scenarios.length) return;
  const section = el("section", "research-module");
  add(section, add(el("div", "section-header"), el("h2", null, "可探索的业务场景")));
  const cards = el("div", "cards");
  scenarios.filter(matches).forEach((scenario) => {
    const card = el("article", "card scenario-research");
    add(
      card,
      badge("研究方案 · 未经企业实测"),
      el("h2", null, scenario.title),
      researchSection("业务痛点", researchText(scenario.pain)),
      researchSection("数据前提", researchList(scenario.dataRequirements)),
    );
    if (scenario.nextExperiment)
      card.append(researchSection("先做什么", researchText(scenario.nextExperiment)));
    add(
      card,
      researchSection("通过条件", researchList(scenario.acceptance)),
      researchSection("何时停止", researchList(scenario.stop)),
    );
    const plan = researchDetails(
      "试点步骤与分工",
      researchSection("对象与关系", researchList(scenario.objects)),
    );
    const division = el("dl", "research-definition");
    for (const [key, label] of [
      ["ai", "AI"],
      ["rules", "确定性规则"],
      ["human", "人员责任"],
    ])
      if (scenario.division?.[key])
        add(division, el("dt", null, label), el("dd", null, researchText(scenario.division[key])));
    plan.append(researchSection("职责分工", division));
    add(
      plan,
      researchSection("FDE 现场步骤", researchList(scenario.fdeSteps, true)),
      researchSection("试验基线", researchList(scenario.baseline)),
    );
    card.append(plan);
    if (researchRows(scenario.evidence).length) {
      const evidence = researchDetails("依据原文");
      scenario.evidence.forEach((reference, index) =>
        evidence.append(researchEvidence(reference, { key: scenario.id + "-" + index })),
      );
      card.append(evidence);
    }
    cards.append(card);
  });
  section.append(cards);
  parent.append(section);
}
