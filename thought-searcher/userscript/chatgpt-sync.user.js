// ==UserScript==
// @name         생각 검색기: ChatGPT 대화 수집
// @namespace    https://github.com/GCxEnding/small-win-tools
// @version      0.1.0
// @description  바뀐 ChatGPT 대화만 다운로드 폴더의 claude-sync/ 에 JSON으로 저장한다 (생각 검색기가 읽음)
// @match        https://chatgpt.com/*
// @match        https://chat.openai.com/*
// @run-at       document-idle
// @noframes
// @grant        GM_download
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_notification
// @grant        GM_registerMenuCommand
// ==/UserScript==

// claude-sync.user.js와 같은 방식이다. Tampermonkey 설정도 같다 (thought-searcher/README.md 참고).
// 저장 폴더는 claude.ai 수집과 같은 claude-sync/ 이고, 파일 이름으로 구분한다:
//   chatgpt_<대화 id>.json, 상태는 _status_chatgpt.json
// 명세: thought-searcher/SPEC-queue.md 3-D

(function () {
  "use strict";

  // ---- 설정 ---------------------------------------------------------------
  const SYNC_MINUTES = 30;          // 주기
  const MAX_PER_RUN = 50;           // 한 번 돌 때 받는 대화 수 상한
  const REQUEST_GAP_MS = 1100;      // 요청 사이 간격
  const PAGE_SIZE = 28;             // 대화 목록 한 쪽 크기 (사이트 화면과 같은 값)
  const FOLDER = "claude-sync";     // 다운로드 폴더 아래 저장 폴더 (claude.ai 수집과 같은 곳)
  const LOCK_MS = 10 * 60 * 1000;   // 다른 탭이 돌고 있다고 보는 시간
  const NOTIFY_EVERY_MS = 6 * 60 * 60 * 1000;   // 같은 오류 알림 간격
  const FORMAT = "thought-searcher.capture/1";
  const STATUS_FORMAT = "thought-searcher.capture-status/1";
  const SITE = "chatgpt";

  const TAB = Math.random().toString(36).slice(2);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const nowIso = () => new Date().toISOString();
  const log = (...a) => console.log("[chatgpt-sync]", ...a);

  class SyncError extends Error {
    constructor(kind, message) { super(message); this.kind = kind; }
  }

  // ---- 사이트 API (비공식) ---------------------------------------------------
  let token = "";

  async function rawFetch(path, auth) {
    const headers = { accept: "application/json" };
    if (auth) headers.authorization = `Bearer ${token}`;
    try {
      return await fetch(path, { credentials: "include", headers });
    } catch (e) {
      throw new SyncError("network", `요청 실패: ${e.message || e}`);
    }
  }

  async function login() {
    const res = await rawFetch("/api/auth/session", false);
    if (!res.ok) throw new SyncError(res.status === 429 ? "rate" : "auth", `로그인 정보를 못 받음 (HTTP ${res.status})`);
    let s;
    try { s = await res.json(); } catch (e) { throw new SyncError("format", "로그인 정보가 JSON이 아닙니다."); }
    if (!s || !s.accessToken) throw new SyncError("auth", "로그아웃 상태입니다. ChatGPT에 다시 로그인해 주세요.");
    token = s.accessToken;
  }

  async function api(path) {
    let res = await rawFetch(path, true);
    if (res.status === 401) {               // 토큰 만료: 한 번 다시 받아 재시도
      await login();
      res = await rawFetch(path, true);
    }
    if (res.status === 401 || res.status === 403) throw new SyncError("auth", "로그아웃 상태입니다. ChatGPT에 다시 로그인해 주세요.");
    if (res.status === 429) throw new SyncError("rate", "요청이 너무 많아 다음 주기까지 쉽니다.");
    if (!res.ok) throw new SyncError("http", `HTTP ${res.status}: ${path}`);
    try {
      return await res.json();
    } catch (e) {
      throw new SyncError("format", `JSON이 아닌 응답: ${path}`);
    }
  }

  // 대화 목록을 최근 수정 순으로 훑어 바뀐 것만 고른다.
  async function changedConversations(seen, fullScan) {
    const changed = [];
    const listed = new Set();
    let offset = 0;
    let complete = false;
    for (;;) {
      const page = await api(`/backend-api/conversations?offset=${offset}&limit=${PAGE_SIZE}&order=updated`);
      const items = page && Array.isArray(page.items) ? page.items : null;
      if (!items) throw new SyncError("format", "대화 목록 형식이 다릅니다.");
      let fresh = 0;
      let unseenId = 0;
      for (const c of items) {
        if (!c || !c.id || listed.has(c.id)) continue;
        listed.add(c.id);
        unseenId++;
        if (seen[c.id] !== String(c.update_time)) { changed.push(c); fresh++; }
      }
      const total = typeof page.total === "number" ? page.total : null;
      if (items.length === 0 || unseenId === 0 || items.length < PAGE_SIZE ||
          (total !== null && offset + items.length >= total)) { complete = true; break; }
      if (!fullScan && fresh === 0) break;   // 한 쪽이 통째로 본 것이면 그 뒤는 더 오래된 것
      if (changed.length >= MAX_PER_RUN * 4) break;
      offset += items.length;
      await sleep(REQUEST_GAP_MS);
    }
    return { changed, complete };
  }

  async function conversation(id) {
    return api(`/backend-api/conversation/${id}`);
  }

  // ---- 저장 ---------------------------------------------------------------
  function save(name, obj) {
    return new Promise((resolve, reject) => {
      const blob = new Blob([JSON.stringify(obj)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const done = (fn, arg) => { setTimeout(() => URL.revokeObjectURL(url), 5000); fn(arg); };
      GM_download({
        url,
        name: `${FOLDER}/${name}`,
        saveAs: false,
        conflictAction: "overwrite",
        onload: () => done(resolve),
        onerror: (e) => done(reject, new SyncError("download", `다운로드 실패 (${(e && (e.error || e.details)) || "알 수 없음"}): ${name}`)),
        ontimeout: () => done(reject, new SyncError("download", `다운로드 시간 초과: ${name}`)),
      });
    });
  }

  function writeStatus(status) {
    return save("_status_chatgpt.json", { format: STATUS_FORMAT, site: SITE, ...status })
      .catch((e) => log("상태 파일 저장 실패", e.message));
  }

  // ---- 알림 ---------------------------------------------------------------
  function notify(kind, text) {
    const sent = GM_getValue("notified", {});
    const now = Date.now();
    if (sent[kind] && now - sent[kind] < NOTIFY_EVERY_MS) return;
    sent[kind] = now;
    GM_setValue("notified", sent);
    GM_notification({ title: "생각 검색기 ChatGPT 수집", text, timeout: 15000 });
  }

  // ---- 여러 탭 중 하나만 ------------------------------------------------------
  function takeLock() {
    const lock = GM_getValue("lock", null);
    if (lock && lock.tab !== TAB && Date.now() - lock.at < LOCK_MS) return false;
    GM_setValue("lock", { tab: TAB, at: Date.now() });
    const again = GM_getValue("lock", null);
    return !!again && again.tab === TAB;
  }
  function releaseLock() {
    const lock = GM_getValue("lock", null);
    if (lock && lock.tab === TAB) GM_setValue("lock", null);
  }

  // ---- 한 번 돌기 -------------------------------------------------------------
  let running = false;
  async function runOnce(reason) {
    if (running) return;
    if (!takeLock()) { log("다른 탭이 수집 중이라 건너뜀"); return; }
    running = true;
    const prev = GM_getValue("status", {});
    const status = { last_run: nowIso(), last_ok: prev.last_ok || null, saved: 0, error: null };
    log("수집 시작:", reason);
    try {
      await login();
      await sleep(REQUEST_GAP_MS);
      const seen = GM_getValue("seen", {});
      const backfilled = GM_getValue("backfilled", false);
      const { changed, complete } = await changedConversations(seen, !backfilled);
      const todo = changed.slice(0, MAX_PER_RUN);
      log(`바뀐 대화 ${changed.length}개, 이번에 ${todo.length}개 받음`);
      for (const c of todo) {
        await sleep(REQUEST_GAP_MS);
        const data = await conversation(c.id);
        if (!data || !data.mapping) throw new SyncError("format", `대화 본문 형식이 다릅니다: ${c.id}`);
        if (!data.conversation_id && !data.id) data.conversation_id = c.id;
        await save(`chatgpt_${c.id}.json`, {
          format: FORMAT, site: SITE, captured_at: nowIso(), project: null, data,
        });
        seen[c.id] = String(c.update_time);
        GM_setValue("seen", seen);        // 하나 받을 때마다 기록 (중간에 멈춰도 다시 받지 않음)
        status.saved++;
      }
      if (!backfilled && complete && changed.length <= MAX_PER_RUN) GM_setValue("backfilled", true);
      status.last_ok = nowIso();
      if (changed.length > todo.length) setTimeout(() => runOnce("이어 받기"), 3 * 60 * 1000);
    } catch (e) {
      const kind = e.kind || "error";
      status.error = `${kind}: ${e.message || e}`;
      log("수집 오류", status.error);
      notify(kind, e.message || String(e));
    } finally {
      GM_setValue("status", status);
      await writeStatus(status);
      running = false;
      releaseLock();
      log("수집 끝", status);
    }
  }

  // ---- 메뉴와 주기 ------------------------------------------------------------
  GM_registerMenuCommand("지금 수집", () => runOnce("메뉴"));
  GM_registerMenuCommand("상태 보기", () => {
    const s = GM_getValue("status", {});
    const n = Object.keys(GM_getValue("seen", {})).length;
    alert(`마지막 실행: ${s.last_run || "없음"}\n마지막 성공: ${s.last_ok || "없음"}\n이번에 저장: ${s.saved || 0}개\n받은 대화 누적: ${n}개\n첫 전체 받기: ${GM_getValue("backfilled", false) ? "끝" : "진행 중"}\n오류: ${s.error || "없음"}`);
  });
  GM_registerMenuCommand("받은 기록 지우기 (전부 다시 받기)", () => {
    if (!confirm("받은 대화 기록을 지우고 다음 수집 때 전부 다시 받을까요?")) return;
    GM_setValue("seen", {});
    GM_setValue("backfilled", false);
    alert("지웠습니다. 메뉴의 '지금 수집'으로 바로 시작할 수 있습니다.");
  });

  setTimeout(() => runOnce("페이지 열림"), 15 * 1000);
  setInterval(() => runOnce("주기"), SYNC_MINUTES * 60 * 1000);
})();
