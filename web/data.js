"use strict";

function payload(row) {
  if (!row) return {};
  if (typeof row.payload === "string") {
    try {
      return JSON.parse(row.payload);
    } catch (_) {
      return {};
    }
  }
  return row.payload || row;
}

function searchable(row) {
  return JSON.stringify(row).toLocaleLowerCase();
}

function matches(row) {
  return !app.query || searchable(row).includes(app.query.toLocaleLowerCase());
}

function notes() {
  return (app.data.notes || []).map((row) => ({ ...row, payload: payload(row) }));
}

function documents() {
  return app.data.documents || [];
}

function sources() {
  return (app.data.sources || []).map((row) => {
    const source = { ...payload(row), ...row };
    return {
      ...source,
      lastStatus: source.lastStatus || source.access,
      lastError: source.lastError || source.error,
      enabled: source.enabled !== false && source.enabled !== 0,
    };
  });
}

function recordTrack(row) {
  const p = payload(row);
  if (p.track) return p.track;
  const c = String(row.category || "");
  if (/项目|披露|case/i.test(c)) return "case";
  if (/场景|scenario/i.test(c)) return "scenario";
  if (/技术|方法|多媒体|学习|theory/i.test(c)) return "theory";
  return "";
}

function boundNotes(doc) {
  return notes().filter((n) => n.payload.documentId === doc.id && n.payload.sha256 === doc.sha256);
}

function documentTracks(doc) {
  const set = new Set([
    ...(Array.isArray(doc.tracks) ? doc.tracks : []),
    ...boundNotes(doc).map((n) => n.track),
  ]);
  (app.data.records || []).forEach((r) => {
    if (normalized(payload(r).url || payload(r).sourceUrl) === normalized(doc.url))
      set.add(recordTrack(r));
  });
  return set;
}

function githubData() {
  return app.data?.githubResources || { resources: [] };
}

function githubResources() {
  return Array.isArray(githubData().resources) ? githubData().resources : [];
}

function githubRunning() {
  const state = githubData();
  return (
    githubSubmitting ||
    (typeof state.running === "boolean" ? state.running : isActive(state.lastRun?.status))
  );
}

function anyTaskRunning() {
  return (
    githubRunning() ||
    researchLabRunning() ||
    [...(app.data?.jobs || []), ...(app.data?.runs || [])].some((j) => isActive(j.status))
  );
}
