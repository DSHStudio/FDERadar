"use strict";

const $ = (id) => document.getElementById(id);

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function add(parent, ...children) {
  children
    .flat()
    .filter(Boolean)
    .forEach((child) => parent.append(child));
  return parent;
}

function safeUrl(value) {
  try {
    const url = new URL(String(value));
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : null;
  } catch (_) {
    return null;
  }
}

function normalized(value) {
  const u = safeUrl(value);
  if (!u) return "";
  const url = new URL(u);
  url.hash = "";
  return url.href.replace(/\/$/, "");
}

function host(value) {
  const url = safeUrl(value);
  return url ? new URL(url).hostname : "来源未记录";
}

function link(text, url) {
  const node = el("a", null, text);
  const href = safeUrl(url);
  if (href) {
    node.href = href;
    node.target = "_blank";
    node.rel = "noopener noreferrer";
  } else {
    node.className = "muted";
    node.title = "来源网址无效或未记录";
  }
  return node;
}

function button(text, callback, style = "quiet small") {
  const node = el("button", style, text);
  node.type = "button";
  node.addEventListener("click", callback);
  return node;
}

function date(value) {
  if (!value) return "未记录";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? String(value)
    : parsed.toLocaleString("zh-CN", { hour12: false });
}

function status(value) {
  return (
    accessLabels[value] || accessLabels[String(value || "").toLowerCase()] || value || "未记录"
  );
}

function badge(text, kind = "") {
  return el("span", "badge " + kind, text);
}

function isActive(value) {
  return /^(running|queued|pending|collecting|analyzing)$/i.test(value || "");
}

function isFailure(value) {
  return /(fail|error|blocked|partial|insufficient|denied|timeout|robots|access_restricted|metadata_only|warnings|gaps|interrupted)/i.test(
    value || "",
  );
}

function empty(title, detail) {
  return add(el("div", "empty"), el("strong", null, title), el("div", null, detail));
}

function meta(...parts) {
  const node = el("div", "meta");
  parts.filter(Boolean).forEach((part, index) => {
    if (index) node.append(el("span", "separator", "·"));
    node.append(typeof part === "string" ? el("span", null, part) : part);
  });
  return node;
}

function detail(title, text) {
  const node = el("details");
  add(node, el("summary", null, title), el("div", "analysis", text));
  return node;
}

function message(text, error = false) {
  $("notice").hidden = false;
  $("notice").className = error ? "error" : "";
  $("notice").textContent = text;
}
