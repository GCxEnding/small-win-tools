// ==UserScript==
// @name         생각 검색기: Gemini 대화 수집
// @namespace    https://github.com/GCxEnding/small-win-tools
// @version      0.1.0
// @description  바뀐 Gemini 대화만 다운로드 폴더의 claude-sync/ 에 JSON으로 저장한다 (생각 검색기가 읽음)
// @match        https://gemini.google.com/*
// @run-at       document-idle
// @noframes
// @grant        GM_download
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_notification
// @grant        GM_registerMenuCommand
// ==/UserScript==

// chatgpt-sync.user.js와 같은 방식이다. Tampermonkey 설정도 같다 (thought-searcher/README.md 참고).
// 저장 폴더는 같은 claude-sync/ 이고, 파일 이름으로 구분한다:
//   gemini_<대화 id>.json, 상태는 _status_gemini.json
//
// Gemini 웹에는 JSON API가 없어 화면이 쓰는 내부 RPC(batchexecute)를 부른다. 응답은 이름 없는 중첩 배열이다.
// 2026-11-17 실제 응답으로 확인한 것:
//   대화 목록 MaZiqc  [쪽 크기, 다음 쪽 표] -> [null, 다음 쪽 표, [[대화 id, 제목, ., ., ., [초, 나노초], ...], ...]]
//                     최근에 바뀐 순서. 고정한 대화는 [쪽 크기, null, [1, null, 1]]로 따로 받는다
//   대화 본문 hNvQHb  [대화 id, 턴 수, 다음 쪽 표, 1, [0], [4], null, 1] -> [[턴, ...], 다음 쪽 표, ...]
//                     최신 턴부터 온다
// 턴을 글로 바꾸는 일은 앱(app/importers/gemini.py)이 한다. 여기서는 받은 턴을 그대로 저장한다.
// 구글이 RPC 이름이나 칸 위치를 바꾸면 수집이 멈추고 상태 파일에 오류가 남는다.

(function () {
  "use strict";

  // ---- 설정 ---------------------------------------------------------------
  const SYNC_MINUTES = 30;          // 주기
  const MAX_PER_RUN = 50;           // 한 번 돌 때 받는 대화 수 상한
  const REQUEST_GAP_MS = 1100;      // 요청 사이 간격
  const PAGE_SIZE = 20;             // 대화 목록 한 쪽 크기
  const TURN_PAGE = 50;             // 대화 본문 한 쪽의 턴 수
  const MAX_TURN_PAGES = 40;        // 대화 하나에서 받는 쪽 수 상한 (턴 2000개)
  const FOLDER = "claude-sync";     // 다운로드 폴더 아래 저장 폴더 (claude.ai 수집과 같은 곳)
  const LOCK_MS = 10 * 60 * 1000;   // 다른 탭이 돌고 있다고 보는 시간
  const NOTIFY_EVERY_MS = 6 * 60 * 60 * 1000;   // 같은 오류 알림 간격
  const FORMAT = "thought-searcher.capture/1";
  const STATUS_FORMAT = "thought-searcher.capture-status/1";
  const SITE = "gemini";
  const RPC_LIST = "MaZiqc";
  const RPC_READ = "hNvQHb";

  const TAB = Math.random().toString(36).slice(2);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const nowIso = () => new Date().toISOString();
  const log = (...a) => console.log("[gemini-sync]", ...a);

  class SyncError extends Error {
    constructor(kind, message) { super(message); this.kind = kind; }
  }

  // ---- 사이트 RPC (비공식) ---------------------------------------------------
  // 여러 계정으로 로그인했으면 주소가 /u/1/app 처럼 시작한다. 같은 계정의 주소로 부른다
  const ACCOUNT = (location.pathname.match(/^\/u\/\d+/) || [""])[0];
  let session = null;               // {at, bl, sid}
  let reqid = Math.floor(Math.random() * 9000) + 1000;

  async function login() {
    let res;
    try {
      res = await fetch(`${ACCOUNT}/app`, { credentials: "include" });
    } catch (e) {
      throw new SyncError("network", `요청 실패: ${e.message || e}`);
    }
    if (res.status === 429) throw new SyncError("rate", "요청이 너무 많아 다음 주기까지 쉽니다.");
    if (!res.ok) throw new SyncError("http", `HTTP ${res.status}: /app`);
    const html = await res.text();
    const pick = (key) => { const m = html.match(new RegExp(`"${key}":"([^"]*)"`)); return m ? m[1] : ""; };
    const at = pick("SNlM0e");
    if (!at) throw new SyncError("auth", "로그아웃 상태입니다. Gemini에 다시 로그인해 주세요.");
    session = { at, bl: pick("cfb2h"), sid: pick("FdrFJe") };
  }

  // 응답 틀: ")]}'" 다음에 [길이, JSON] 묶음이 이어진다. 원하는 RPC의 ["wrb.fr", id, "본문 JSON 문자열", ...]을 찾는다
  function unwrap(text, rpcid) {
    for (const line of text.split("\n")) {
      if (!line.startsWith("[")) continue;
      let rows;
      try { rows = JSON.parse(line); } catch (e) { continue; }
      for (const r of Array.isArray(rows) ? rows : []) {
        if (!Array.isArray(r) || r[0] !== "wrb.fr" || r[1] !== rpcid) continue;
        if (typeof r[2] !== "string") throw new SyncError("format", `${rpcid} 응답에 본문이 없습니다 (RPC가 바뀌었을 수 있음).`);
        try { return JSON.parse(r[2]); } catch (e) { throw new SyncError("format", `${rpcid} 본문이 JSON이 아닙니다.`); }
      }
    }
    throw new SyncError("format", `${rpcid} 응답을 찾지 못했습니다 (RPC가 바뀌었을 수 있음).`);
  }

  async function rpc(rpcid, payload, retried) {
    reqid += 100000;
    const q = new URLSearchParams({ rpcids: rpcid, "source-path": `${ACCOUNT}/app`, bl: session.bl,
                                    "f.sid": session.sid, hl: "ko", _reqid: String(reqid), rt: "c" });
    const body = new URLSearchParams({ "f.req": JSON.stringify([[[rpcid, JSON.stringify(payload), null, "generic"]]]),
                                       at: session.at });
    let res;
    try {
      res = await fetch(`${ACCOUNT}/_/BardChatUi/data/batchexecute?${q}`, {
        method: "POST", credentials: "include",
        headers: { "content-type": "application/x-www-form-urlencoded;charset=UTF-8" }, body,
      });
    } catch (e) {
      throw new SyncError("network", `요청 실패: ${e.message || e}`);
    }
    if ((res.status === 400 || res.status === 401) && !retried) {   // 표가 만료: 한 번 다시 받아 재시도
      await login();
      return rpc(rpcid, payload, true);
    }
    if (res.status === 401 || res.status === 403) throw new SyncError("auth", "로그아웃 상태입니다. Gemini에 다시 로그인해 주세요.");
    if (res.status === 429) throw new SyncError("rate", "요청이 너무 많아 다음 주기까지 쉽니다.");
    if (!res.ok) throw new SyncError("http", `HTTP ${res.status}: ${rpcid}`);
    return unwrap(await res.text(), rpcid);
  }

  const stamp = (c) => (Array.isArray(c[5]) ? `${c[5][0]}.${c[5][1]}` : "");

  function chatsOf(body) {
    if (!Array.isArray(body)) throw new SyncError("format", "대화 목록 형식이 다릅니다.");
    const list = Array.isArray(body[2]) ? body[2] : [];
    return { items: list.filter((c) => Array.isArray(c) && typeof c[0] === "string" && c[0].startsWith("c_")),
             next: typeof body[1] === "string" && body[1] ? body[1] : null };
  }

  // 대화 목록을 최근 수정 순으로 훑어 바뀐 것만 고른다. 고정한 대화는 따로 한 번 받는다
  async function changedConversations(seen, fullScan) {
    const changed = [];
    const listed = new Set();
    const consider = (items) => {
      let fresh = 0;
      for (const c of items) {
        if (listed.has(c[0])) continue;
        listed.add(c[0]);
        if (seen[c[0]] !== stamp(c)) { changed.push(c); fresh++; }
      }
      return fresh;
    };
    consider(chatsOf(await rpc(RPC_LIST, [PAGE_SIZE, null, [1, null, 1]])).items);
    let token = null;
    let complete = false;
    for (;;) {
      await sleep(REQUEST_GAP_MS);
      const page = chatsOf(await rpc(RPC_LIST, token ? [PAGE_SIZE, token] : [PAGE_SIZE]));
      const fresh = consider(page.items);
      if (!page.next || page.items.length === 0) { complete = true; break; }
      if (!fullScan && fresh === 0) break;   // 한 쪽이 통째로 본 것이면 그 뒤는 더 오래된 것
      if (changed.length >= MAX_PER_RUN * 4) break;
      token = page.next;
    }
    return { changed, complete };
  }

  async function conversation(cid) {
    const turns = [];
    let token = null;
    for (let i = 0; i < MAX_TURN_PAGES; i++) {
      if (i) await sleep(REQUEST_GAP_MS);
      const body = await rpc(RPC_READ, [cid, TURN_PAGE, token, 1, [0], [4], null, 1]);
      if (!Array.isArray(body) || !Array.isArray(body[0])) throw new SyncError("format", `대화 본문 형식이 다릅니다: ${cid}`);
      turns.push(...body[0]);
      token = typeof body[1] === "string" && body[1] ? body[1] : null;
      if (!token) break;
    }
    return turns;
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
    return save("_status_gemini.json", { format: STATUS_FORMAT, site: SITE, ...status })
      .catch((e) => log("상태 파일 저장 실패", e.message));
  }

  // ---- 알림 ---------------------------------------------------------------
  function notify(kind, text) {
    const sent = GM_getValue("notified", {});
    const now = Date.now();
    if (sent[kind] && now - sent[kind] < NOTIFY_EVERY_MS) return;
    sent[kind] = now;
    GM_setValue("notified", sent);
    GM_notification({ title: "생각 검색기 Gemini 수집", text, timeout: 15000 });
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
        const turns = await conversation(c[0]);
        await save(`gemini_${c[0].slice(2)}.json`, {
          format: FORMAT, site: SITE, captured_at: nowIso(), project: null,
          data: { id: c[0], title: typeof c[1] === "string" ? c[1] : "", updated: c[5] || null, turns },
        });
        seen[c[0]] = stamp(c);
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
