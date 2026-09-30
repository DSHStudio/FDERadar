"use strict";

function renderSources(parent) {
  const coverage = app.data.coverage || {};
  const metrics = coverage.metrics || {};
  const intro = el("details", "secondary-panel");
  add(
    intro,
    el("summary", null, "覆盖范围与统计口径"),
    el("p", "coverage-note", coverage.assessment || "仍在持续扩充，尚不能证明覆盖充分。"),
    el("p", "subtle", "未穷尽开放网络。登录、付费、动态网页及无字幕音视频仍可能存在缺口。"),
  );
  if (coverage.scopeMatrix?.length) {
    const table = el("table");
    const head = el("tr");
    ["范围", "登记组", "DSH 获取过的组"].forEach((t) => head.append(el("th", null, t)));
    table.append(head);
    coverage.scopeMatrix.forEach((row) =>
      add(
        table,
        add(
          el("tr"),
          el("td", null, row.label),
          el("td", null, row.registeredGroups),
          el("td", null, row.groupsWithAnyDshFetch),
        ),
      ),
    );
    intro.append(add(el("div", "table-wrap"), table));
  }
  if (Object.keys(metrics).length)
    intro.append(detail("查看覆盖统计与口径", JSON.stringify(coverage, null, 2)));
  parent.append(intro);
  const forms = el("details", "secondary-panel");
  forms.append(
    el("summary", null, "添加信源或指定资料"),
    add(el("div", "grid-two"), sourceForm(), collectForm()),
  );
  parent.append(forms);
  parent.append(
    add(
      el("div", "section-header"),
      el("h2", null, "自动采集信源"),
      el("span", "subtle", sources().length + " 个登记入口"),
    ),
  );
  toolbar(parent);
  const ss = sources().filter((s) => matches(s) && (!app.host || host(s.url) === app.host));
  if (!ss.length)
    parent.append(empty("此筛选范围没有信源", "可添加具体页面、公开 RSS、PDF 或公开字幕地址。"));
  pageList(parent, ss, sourceCard);
}

function sourceForm() {
  const card = el("section", "card");
  add(
    card,
    el("h2", null, "登记持续追踪的来源"),
    el("p", "subtle", "添加实际可访问的入口；登记后仍须通过采集验证。"),
  );
  const form = el("form");
  const url = el("input");
  url.type = "url";
  url.required = true;
  url.placeholder = "https://…";
  url.style.width = "100%";
  url.setAttribute("aria-label", "信源 URL");
  const title = el("input");
  title.placeholder = "来源名称（可选）";
  title.setAttribute("aria-label", "来源名称");
  const channel = el("select");
  channel.setAttribute("aria-label", "来源渠道");
  [
    ["企业网站", "enterprise"],
    ["新闻", "news"],
    ["大学 / 研究", "research"],
    ["视频 / 字幕", "video"],
    ["播客", "podcast"],
    ["著作", "book"],
    ["纪录片", "documentary"],
    ["RSS / Atom", "feed"],
  ].forEach(([name, value]) => channel.add(new Option(name, value)));
  const cadence = el("input");
  cadence.type = "number";
  cadence.min = "1";
  cadence.max = "8760";
  cadence.value = "24";
  cadence.style.maxWidth = "90px";
  cadence.setAttribute("aria-label", "刷新周期（小时）");
  const submit = el("button", null, "登记信源");
  submit.type = "submit";
  add(
    form,
    el("label", null, "来源地址"),
    url,
    add(el("div", "form-row"), title, channel),
    add(el("div", "form-row"), el("label", null, "采集周期（小时）"), cadence, submit),
  );
  bindFormSubmission(form, submit, {
    draftKey: "source",
    path: "/api/source",
    prepare: () => {
      if (!safeUrl(url.value)) {
        message("请输入有效的公开 HTTP(S) 地址。", true);
        return null;
      }
      return {
        url: url.value.trim(),
        title: title.value.trim(),
        channel: channel.value,
        enabled: true,
        cadenceHours: Number(cadence.value),
      };
    },
    onSuccess: () => form.reset(),
    successMessage: "信源已登记；实际可用性将在采集后记录。",
  });
  bindFormDraft(form, "source", [url, title, channel, cadence]);
  card.append(form);
  return card;
}

function collectForm() {
  const card = el("section", "card");
  add(
    card,
    el("h2", null, "获取指定材料"),
    el("p", "subtle", "每行一个公开 URL。正文、PDF、RSS 与字幕以各自的提取结果为准。"),
  );
  const form = el("form");
  const urls = el("textarea");
  urls.required = true;
  urls.placeholder = "https://example.org/article\nhttps://example.org/paper.pdf";
  urls.setAttribute("aria-label", "待获取的 URL，每行一个");
  const submit = el("button", null, "开始获取");
  submit.type = "submit";
  add(form, urls, add(el("div", "form-row"), submit));
  bindFormSubmission(form, submit, {
    draftKey: "collect",
    path: "/api/collect",
    prepare: () => {
      const values = urls.value
        .split(/\r?\n/)
        .map((x) => x.trim())
        .filter(Boolean);
      if (values.some((x) => !safeUrl(x))) {
        message("存在无效 URL，只接受 HTTP(S) 公开地址。", true);
        return null;
      }
      return { urls: values, force: true };
    },
    successMessage: "采集任务已提交，请在「任务与审核」查看逐项结果。",
  });
  bindFormDraft(form, "collect", [urls]);
  card.append(form);
  return card;
}

function sourceCard(source) {
  const card = el("article", "card source-card");
  add(
    card,
    add(
      el("div", "badges"),
      badge(source.channel || "渠道未分类"),
      source.candidate ? badge("候选来源") : null,
      badge(source.enabled === false ? "已暂停" : "追踪中", source.enabled === false ? "" : "good"),
      badge(status(source.lastStatus || "pending"), isFailure(source.lastStatus) ? "warn" : ""),
    ),
    add(el("h3"), link(source.title || source.name || source.url || source.id, source.url)),
    el("p", "source-path", source.url),
  );
  add(
    card,
    meta(
      "周期 " + (source.cadenceHours ?? "未记录") + " 小时",
      "最近成功 " + date(source.lastSuccess),
      "下次到期 " + date(source.nextDue),
    ),
  );
  if (source.lastError)
    card.append(
      detail(
        "获取失败 · 查看原因",
        typeof source.lastError === "object" ? JSON.stringify(source.lastError) : source.lastError,
      ),
    );
  if (source.url)
    add(
      card,
      add(
        el("div", "actions"),
        button("立即获取", () =>
          action("/api/collect", { urls: [source.url], force: true }, "已提交该来源的采集任务。"),
        ),
        button(source.enabled === false ? "恢复追踪" : "暂停追踪", () =>
          action(
            "/api/source",
            {
              url: source.url,
              title: source.title || source.name,
              channel: source.channel,
              cadenceHours: source.cadenceHours,
              enabled: source.enabled === false,
            },
            "信源追踪设置已更新。",
          ),
        ),
      ),
    );
  return card;
}
