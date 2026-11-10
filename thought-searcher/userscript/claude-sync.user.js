// ==UserScript==
// @name         생각 검색기: claude.ai 대화 수집
// @namespace    https://github.com/GCxEnding/small-win-tools
// @version      0.2.0
// @description  바뀐 claude.ai 대화만 다운로드 폴더의 claude-sync/ 에 JSON으로 저장한다 (생각 검색기가 읽음)
// @match        https://claude.ai/*
// @run-at       document-idle
// @noframes
// @grant        GM_download
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_notification
// @grant        GM_registerMenuCommand
// ==/UserScript==

// 설치 전 Tampermonkey 설정 (thought-searcher/README.md 참고)
// - 설정 > 일반 > 설정 모드: 고급
// - 설정 > 다운로드 BETA > 다운로드 모드: 브라우저 API, 허용 확장자에 .json 추가
// - 크롬 설정 > 다운로드 > "다운로드 전에 각 파일의 저장 위치 확인" 끄기
// 명세: thought-searcher/SPEC-queue.md 3-D

(function () {
  "use strict";

  // ---- 설정 ---------------------------------------------------------------
  const SYNC_MINUTES = 30;          // 주기
  const MAX_PER_RUN = 50;           // 한 번 돌 때 받는 대화 수 상한
  const REQUEST_GAP_MS = 1100;      // 요청 사이 간격
  const PAGE_SIZE = 50;             // 대화 목록 한 쪽 크기
  const FOLDER = "claude-sync";     // 다운로드 폴더 아래 저장 폴더
  const LOCK_MS = 10 * 60 * 1000;   // 다른 탭이 돌고 있다고 보는 시간
  const NOTIFY_EVERY_MS = 6 * 60 * 60 * 1000;   // 같은 오류 알림 간격
  const FORMAT = "thought-searcher.capture/1";
  const STATUS_FORMAT = "thought-searcher.capture-status/1";

  const TAB = Math.random().toString(36).slice(2);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const nowIso = () => new Date().toISOString();
  const log = (...a) => console.log("[claude-sync]", ...a);

  class SyncError extends Error {
    constructor(kind, message) { super(message); this.kind = kind; }
  }

  // ---- 사이트 API (비공식) ---------------------------------------------------
  async function api(path) {
    let res;
    try {
      res = await fetch(path, { credentials: "include", headers: { accept: "application/json" } });
    } catch (e) {
      throw new SyncError("network", `요청 실패: ${e.message || e}`);
    }
    if (res.status === 401 || res.status === 403) throw new SyncError("auth", "로그아웃 상태입니다. claude.ai에 다시 로그인해 주세요.");
    if (res.status === 429) throw new SyncError("rate", "요청이 너무 많아 다음 주기까지 쉽니다.");
    if (!res.ok) throw new SyncError("http", `HTTP ${res.status}: ${path}`);
    try {
      return await res.json();
    } catch (e) {
      throw new SyncError("format", `JSON이 아닌 응답: ${path}`);
    }
  }

  async function orgId() {
    const orgs = await api("/api/organizations");
    if (!Array.isArray(orgs) || !orgs.length) throw new SyncError("format", "조직 목록이 비었습니다.");
    const chat = orgs.find((o) => (o.capabilities || []).includes("chat")) || orgs[0];
    if (!chat.uuid) throw new SyncError("format", "조직 uuid가 없습니다.");
    return chat.uuid;
  }

  async function projectNames(org) {
    try {
      const list = await api(`/api/organizations/${org}/projects`);
      const map = {};
      for (const p of Array.isArray(list) ? list : []) if (p && p.uuid) map[p.uuid] = p.name || null;
      return map;
    } catch (e) {
      if (e.kind === "auth" || e.kind === "rate") throw e;
      log("프로젝트 목록 실패, 이름 없이 진행", e.message);
      return {};
    }
  }

  // 대화 목록을 최근 수정 순으로 훑어 바뀐 것만 고른다.
  async function changedConversations(org, seen, fullScan, ex) {
    const changed = [];
    const listed = new Set();
    let offset = 0;
    let complete = false;
    for (;;) {
      const page = await api(`/api/organizations/${org}/chat_conversations?limit=${PAGE_SIZE}&offset=${offset}`);
      if (!Array.isArray(page)) throw new SyncError("format", "대화 목록 형식이 다릅니다.");
      page.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
      let fresh = 0;
      let unseenUuid = 0;
      for (const c of page) {
        if (!c || !c.uuid || listed.has(c.uuid)) continue;
        listed.add(c.uuid);
        unseenUuid++;
        if (excluded(ex, c.uuid, c.project_uuid || (c.project && c.project.uuid), c.name)) {
          seen[c.uuid] = c.updated_at;    // 뺀 대화는 받지 않는다
          continue;
        }
        if (seen[c.uuid] !== c.updated_at) { changed.push(c); fresh++; }
      }
      if (unseenUuid === 0) { complete = true; break; }   // 서버가 offset을 무시: 같은 쪽만 옴
      // 서버가 limit을 무시하고 전부 주거나, 마지막 쪽이면 끝
      if (page.length < PAGE_SIZE || page.length > PAGE_SIZE) { complete = true; break; }
      // 첫 전체 받기가 끝난 뒤에는, 한 쪽이 통째로 본 것이면 그 뒤는 더 오래된 것이라 멈춘다
      if (!fullScan && fresh === 0) break;
      if (changed.length >= MAX_PER_RUN * 4) break;   // 한 번에 너무 많이 훑지 않음
      offset += PAGE_SIZE;
      await sleep(REQUEST_GAP_MS);
    }
    changed.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    return { changed, complete };
  }

  // ---- 수집 제외 (메뉴에서 뺀 대화, 프로젝트) -------------------------------------------
  // GM 저장소 "exclude": { conversations: {uuid: {title, project}}, projects: {uuid: name} }
  //   conversations.project: 뺀 프로젝트 때문에 들어간 대화면 그 프로젝트 uuid, 직접 뺐으면 null
  // 상태 파일(_status.json)의 "exclude"로 앱에 알린다. 앱은 그 대화의 기존 md도 지우고 zip에서도 뺀다.
  function getExclude() {
    const ex = GM_getValue("exclude", null) || {};
    return { conversations: ex.conversations || {}, projects: ex.projects || {} };
  }
  function setExclude(ex) { GM_setValue("exclude", ex); }
  function excludeForStatus() {
    const ex = getExclude();
    return {
      conversations: Object.entries(ex.conversations).map(([uuid, v]) => ({ uuid, title: v.title || "", project: v.project || null })),
      projects: Object.entries(ex.projects).map(([uuid, name]) => ({ uuid, name: name || "" })),
    };
  }
  // 대화가 뺀 대상이면 true (뺀 프로젝트의 대화는 목록에 더해 둔다)
  function excluded(ex, uuid, projectUuid, title) {
    if (ex.conversations[uuid]) return true;
    if (projectUuid && ex.projects[projectUuid] !== undefined) {
      ex.conversations[uuid] = { title: title || "", project: projectUuid };
      return true;
    }
    return false;
  }

  async function conversation(org, uuid) {
    return api(`/api/organizations/${org}/chat_conversations/${uuid}?tree=True&rendering_mode=messages&render_all_tools=true`);
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
    return save("_status.json", { format: STATUS_FORMAT, ...status, exclude: excludeForStatus() })
      .catch((e) => log("상태 파일 저장 실패", e.message));
  }

  // ---- 알림 ---------------------------------------------------------------
  function notify(kind, text) {
    const sent = GM_getValue("notified", {});
    const now = Date.now();
    if (sent[kind] && now - sent[kind] < NOTIFY_EVERY_MS) return;
    sent[kind] = now;
    GM_setValue("notified", sent);
    GM_notification({ title: "생각 검색기 수집", text, timeout: 15000 });
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
      const org = await orgId();
      await sleep(REQUEST_GAP_MS);
      const projects = await projectNames(org);
      await sleep(REQUEST_GAP_MS);
      const seen = GM_getValue("seen", {});
      const backfilled = GM_getValue("backfilled", false);
      const ex = getExclude();
      const exCount = Object.keys(ex.conversations).length;
      const { changed, complete } = await changedConversations(org, seen, !backfilled, ex);
      GM_setValue("seen", seen);
      if (Object.keys(ex.conversations).length !== exCount) setExclude(ex);   // 뺀 프로젝트에서 새로 찾은 대화
      const todo = changed.slice(0, MAX_PER_RUN);
      log(`바뀐 대화 ${changed.length}개, 이번에 ${todo.length}개 받음`);
      for (const c of todo) {
        await sleep(REQUEST_GAP_MS);
        const data = await conversation(org, c.uuid);
        if (!data || !data.uuid) throw new SyncError("format", `대화 본문 형식이 다릅니다: ${c.uuid}`);
        const puid = data.project_uuid || (data.project && data.project.uuid) || c.project_uuid || null;
        if (excluded(ex, data.uuid, puid, data.name)) {   // 목록에 프로젝트가 안 온 경우 본문에서 다시 확인
          setExclude(ex);
          seen[c.uuid] = c.updated_at;
          GM_setValue("seen", seen);
          continue;
        }
        const project = (data.project && data.project.name) || (puid && projects[puid]) || null;
        await save(`claude-ai_${data.uuid}.json`, {
          format: FORMAT, site: "claude-ai", captured_at: nowIso(), project, data,
        });
        seen[c.uuid] = c.updated_at;
        GM_setValue("seen", seen);        // 하나 받을 때마다 기록 (중간에 멈춰도 다시 받지 않음)
        status.saved++;
      }
      if (!backfilled && complete && changed.length <= MAX_PER_RUN) GM_setValue("backfilled", true);
      status.last_ok = nowIso();
      if (changed.length > todo.length) {
        // 첫 전체 받기 중: 남은 것은 다음 주기에. 다음 주기를 기다리지 않게 몇 분 뒤 한 번 더
        setTimeout(() => runOnce("이어 받기"), 3 * 60 * 1000);
      }
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

  // ---- 수집 제외 메뉴 ------------------------------------------------------------
  function pageIds() {
    const m = location.pathname.match(/^\/(chat|project)\/([0-9a-fA-F-]{8,64})/);
    return m ? { kind: m[1], uuid: m[2] } : null;
  }

  async function excludeThisConversation() {
    const page = pageIds();
    if (!page || page.kind !== "chat") { alert("뺄 대화를 연 화면에서 누르세요."); return; }
    try {
      const org = await orgId();
      const data = await api(`/api/organizations/${org}/chat_conversations/${page.uuid}`);
      const title = (data && data.name) || "(제목 없음)";
      if (!confirm(`'${title}' 대화를 수집에서 뺄까요?\n\n앞으로 받지 않고, 이미 모은 md는 생각 검색기가 지웁니다.\n되돌리려면 메뉴의 '수집에서 뺀 목록'을 쓰세요.`)) return;
      const ex = getExclude();
      ex.conversations[page.uuid] = { title, project: null };
      setExclude(ex);
      await writeStatus(GM_getValue("status", {}));
      alert("뺐습니다.");
    } catch (e) {
      alert(`빼지 못했습니다: ${e.message || e}`);
    }
  }

  async function excludeThisProject() {
    const page = pageIds();
    if (!page) { alert("프로젝트 화면이나 프로젝트 안의 대화를 연 화면에서 누르세요."); return; }
    try {
      const org = await orgId();
      let puid = page.kind === "project" ? page.uuid : null;
      if (!puid) {
        const data = await api(`/api/organizations/${org}/chat_conversations/${page.uuid}`);
        puid = data && (data.project_uuid || (data.project && data.project.uuid));
      }
      if (!puid) { alert("이 대화는 프로젝트에 속하지 않습니다. '이 대화 수집에서 빼기'를 쓰세요."); return; }
      const names = await projectNames(org);
      const name = names[puid] || "(이름 모름)";
      if (!confirm(`'${name}' 프로젝트를 수집에서 뺄까요?\n\n이 프로젝트의 대화와 프로젝트 문서를 앞으로 받지 않고, 이미 모은 md는 생각 검색기가 지웁니다.\n프로젝트 대화를 찾느라 곧 전체 대화 목록을 한 번 훑습니다.`)) return;
      const ex = getExclude();
      ex.projects[puid] = name;
      setExclude(ex);
      GM_setValue("backfilled", false);     // 전체 목록을 훑어 이 프로젝트의 대화를 찾는다
      await writeStatus(GM_getValue("status", {}));
      setTimeout(() => runOnce("프로젝트 빼기"), 2000);
      alert("뺐습니다. 이 프로젝트의 대화를 찾아 목록에 더하는 중입니다.");
    } catch (e) {
      alert(`빼지 못했습니다: ${e.message || e}`);
    }
  }

  function showExcluded() {
    const ex = getExclude();
    const items = [];
    for (const [uuid, name] of Object.entries(ex.projects)) {
      const n = Object.values(ex.conversations).filter((v) => v.project === uuid).length;
      items.push({ kind: "project", uuid, label: `[프로젝트] ${name || uuid} (대화 ${n}개)` });
    }
    for (const [uuid, v] of Object.entries(ex.conversations)) {
      if (!v.project) items.push({ kind: "chat", uuid, label: `[대화] ${v.title || uuid}` });
    }
    if (!items.length) { alert("수집에서 뺀 대화나 프로젝트가 없습니다."); return; }
    const list = items.map((it, i) => `${i + 1}. ${it.label}`).join("\n");
    const ans = prompt(`수집에서 뺀 목록\n\n${list}\n\n다시 수집할 번호를 넣으세요 (비우면 닫기).`, "");
    const i = parseInt(ans, 10) - 1;
    if (!(i >= 0 && i < items.length)) return;
    const it = items[i];
    const seen = GM_getValue("seen", {});
    if (it.kind === "project") {
      delete ex.projects[it.uuid];
      for (const [u, v] of Object.entries(ex.conversations)) {
        if (v.project === it.uuid) { delete ex.conversations[u]; delete seen[u]; }
      }
    } else {
      delete ex.conversations[it.uuid];
      delete seen[it.uuid];
    }
    setExclude(ex);
    GM_setValue("seen", seen);
    GM_setValue("backfilled", false);       // 되돌린 대화를 다시 받도록 전체 목록을 한 번 훑는다
    writeStatus(GM_getValue("status", {}));
    setTimeout(() => runOnce("되돌리기"), 2000);
    alert(`되돌렸습니다: ${it.label}\n곧 다시 받습니다. 프로젝트 문서는 다음 내보내기 zip을 가져올 때 돌아옵니다.`);
  }

  GM_registerMenuCommand("이 대화 수집에서 빼기", excludeThisConversation);
  GM_registerMenuCommand("이 프로젝트 수집에서 빼기", excludeThisProject);
  GM_registerMenuCommand("수집에서 뺀 목록 (되돌리기)", showExcluded);

  setTimeout(() => runOnce("페이지 열림"), 15 * 1000);
  setInterval(() => runOnce("주기"), SYNC_MINUTES * 60 * 1000);
})();
