"use strict";

// Remembers the last /api/state validator so an unchanged library costs a 304
// instead of a full re-serialisation and re-parse on every poll.
let stateEtag = null;

async function api(path, body, retry = true) {
  const options = { cache: "no-store", headers: { "Accept": "application/json" } };
  // Only the state read is conditional; every mutation stays unconditional.
  const conditional = body === undefined && path === "/api/state" && Boolean(stateEtag);
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.headers["X-Radar-Token"] = app.token;
    options.body = JSON.stringify(body);
  } else if (conditional) {
    options.headers["If-None-Match"] = stateEtag;
  }
  const response = await fetch(path, options);
  // The server confirmed the snapshot is unchanged; keep the one already in memory.
  if (conditional && response.status === 304) return null;
  let data;
  try {
    data = await response.json();
  } catch (_) {
    throw new Error("服务未返回有效 JSON（HTTP " + response.status + "）");
  }
  // A rejected token means the server has not accepted this operation. Never retry ambiguous network failures.
  if (body !== undefined && retry && response.status === 403 && data?.error === "FORBIDDEN") {
    const session = await api("/api/session");
    if (typeof session?.token !== "string" || !session.token)
      throw new Error("本地会话未能恢复，请刷新界面后重试。");
    app.token = session.token;
    return api(path, body, false);
  }
  if (!response.ok || (data?.error && !(data.id && data.status)))
    throw new Error(
      typeof data?.error === "string"
        ? data.error
        : data?.message || "请求失败（HTTP " + response.status + "）",
    );
  if (body === undefined && path === "/api/state")
    stateEtag = response.headers?.get?.("ETag") ?? null;
  return data;
}

async function action(path, body, confirmation) {
  try {
    const result = await api(path, body);
    message(confirmation || "操作已提交。");
    await refresh(false);
    return result;
  } catch (error) {
    message(error.message, true);
  }
}

async function refresh(renderAll = true) {
  if (app.busy) return;
  app.busy = true;
  try {
    if (!app.token) app.token = (await api("/api/session")).token;
    const next = await api("/api/state");
    const stateText = (value) =>
      JSON.stringify(value, (key, item) => (key === "generatedAt" ? undefined : item));
    if (next === null) {
      app.lastSeen = new Date();
      $("connection-status").textContent = "本地服务已连接";
      $("connection-dot").className = "connected";
      renderRefreshTime();
      return;
    }
    let changed = stateText(next) !== stateText(app.data);
    app.data = next;
    app.lastSeen = new Date();
    $("connection-status").textContent = "本地服务已连接";
    $("connection-dot").className = "connected";
    if (location.hash === "#practice") {
      const beforeLab = stateText([researchUI.lab, researchUI.labError]);
      await loadResearchLab(false);
      changed = changed || beforeLab !== stateText([researchUI.lab, researchUI.labError]);
    }
    if (renderAll || changed) render();
    else renderRefreshTime();
  } catch (error) {
    $("connection-status").textContent = "连接中断";
    $("connection-dot").className = "failed";
    message(
      "无法读取本地工作台：" + error.message + "。请确认本地服务正在运行。已有结果不会被清空。",
      true,
    );
  } finally {
    app.busy = false;
    clearTimeout(app.timer);
    app.timer = setTimeout(() => refresh(false), anyTaskRunning() ? 5000 : 30000);
  }
}
