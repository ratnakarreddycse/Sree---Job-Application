const PROFILE_KEYS = [
  "full_name",
  "email",
  "phone",
  "linkedin",
  "location",
  "work_authorization",
  "needs_sponsorship",
];

function status(msg, ok = true) {
  const el = document.getElementById("status");
  el.textContent = msg;
  el.style.color = ok ? "#a7f3d0" : "#fca5a5";
}

function defaultMemory() {
  return {
    profile: {
      full_name: "",
      email: "",
      phone: "",
      linkedin: "",
      location: "",
      work_authorization: "",
      needs_sponsorship: "",
    },
    questions: {},
  };
}

async function getMemory() {
  const data = await chrome.storage.local.get("memory");
  return data.memory || defaultMemory();
}

async function setMemory(memory) {
  await chrome.storage.local.set({ memory });
}

function profileFromForm() {
  const profile = {};
  for (const key of PROFILE_KEYS) {
    profile[key] = document.getElementById(key).value.trim();
  }
  return profile;
}

function loadForm(memory) {
  const profile = memory.profile || {};
  for (const key of PROFILE_KEYS) {
    document.getElementById(key).value = profile[key] || "";
  }
}

function mergeMemory(base, updates) {
  const merged = defaultMemory();
  merged.profile = { ...(base.profile || {}), ...(updates.profile || {}) };
  merged.questions = { ...(base.questions || {}), ...(updates.questions || {}) };
  return merged;
}

async function saveMemoryFromUI() {
  const memory = await getMemory();
  memory.profile = profileFromForm();
  const q = document.getElementById("question").value.trim();
  const a = document.getElementById("answer").value.trim();
  if (q && a) {
    memory.questions[q] = a;
    document.getElementById("question").value = "";
    document.getElementById("answer").value = "";
  }
  await setMemory(memory);
  status("Memory saved");
}

async function syncFromDashboard() {
  try {
    const resp = await fetch("http://127.0.0.1:8765/api/answers");
    const payload = await resp.json();
    if (!payload.ok || !payload.memory) {
      status("Dashboard memory not available", false);
      return;
    }
    const current = await getMemory();
    const merged = mergeMemory(current, payload.memory);
    await setMemory(merged);
    loadForm(merged);
    status("Synced from dashboard");
  } catch (error) {
    status("Could not reach dashboard API", false);
  }
}

async function runAutofillOnActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    status("No active tab", false);
    return;
  }
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "RUN_AUTOFILL" });
    status("Autofill triggered on active tab");
  } catch (error) {
    status("Open a supported job portal tab first", false);
  }
}

async function importJson() {
  const raw = document.getElementById("memory-json").value.trim();
  if (!raw) {
    status("Paste JSON first", false);
    return;
  }
  try {
    const payload = JSON.parse(raw);
    const current = await getMemory();
    const merged = mergeMemory(current, payload);
    await setMemory(merged);
    loadForm(merged);
    status("JSON imported");
  } catch (error) {
    status("Invalid JSON", false);
  }
}

async function exportJson() {
  const memory = await getMemory();
  document.getElementById("memory-json").value = JSON.stringify(memory, null, 2);
  status("Memory exported to text area");
}

async function init() {
  const memory = await getMemory();
  loadForm(memory);

  document.getElementById("save-memory").addEventListener("click", saveMemoryFromUI);
  document.getElementById("sync-dashboard").addEventListener("click", syncFromDashboard);
  document.getElementById("run-autofill").addEventListener("click", runAutofillOnActiveTab);
  document.getElementById("import-json").addEventListener("click", importJson);
  document.getElementById("export-json").addEventListener("click", exportJson);

  // Resume pointer: find the resume that matches the current active tab URL
  loadResumePointer();
}

async function loadResumePointer() {
  const panel = document.getElementById("resume-panel");
  const info = document.getElementById("resume-info");
  const pdfStatus = document.getElementById("resume-pdf-status");

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const tabUrl = (tab && tab.url) || "";

    const resp = await fetch("http://127.0.0.1:8765/api/resume-index");
    const payload = await resp.json();
    const resumes = (payload.index && payload.index.resumes) || {};

    // Match tab URL against stored apply_url for each resume entry
    let match = null;
    for (const [slug, entry] of Object.entries(resumes)) {
      const applyUrl = entry.apply_url || "";
      if (!applyUrl || !tabUrl) continue;
      const extractId = (url) => {
        const m = url.match(/[?&/](?:gh_jid|jobId|id)[=\/](\d+)/i) || url.match(/\/(\d{6,})/);
        return m ? m[1] : null;
      };
      const tabId = extractId(tabUrl);
      const applyId = extractId(applyUrl);
      if (tabId && applyId && tabId === applyId) { match = { slug, ...entry }; break; }
      if (applyUrl && tabUrl && !match) {
        try {
          const tabHost = new URL(tabUrl).hostname.replace(/^www\./, "");
          const applyHost = new URL(applyUrl).hostname.replace(/^www\./, "");
          if (tabHost === applyHost && entry.company) match = { slug, ...entry };
        } catch (_) {}
      }
    }

    if (match) {
      panel.style.display = "block";
      info.innerHTML =
        `<strong>${match.company}</strong> — ${match.role}<br>` +
        `<span style="color:#94a3b8;font-size:10px;">Score: ${match.score} | JD match: ${match.keyword_match_score}%</span><br>` +
        `<span id="resume-path" style="word-break:break-all;color:#7dd3fc;font-size:10px;">${match.resume_path}</span>`;
      document.getElementById("copy-resume-path").onclick = () => {
        navigator.clipboard.writeText(match.resume_path);
        status("Resume path copied!");
      };
      document.getElementById("open-downloads").onclick = async () => {
        try { await fetch("http://127.0.0.1:8765/api/open-downloads"); } catch (_) {}
        status("Downloads folder opened");
      };

      // Auto-prepare the PDF in background — show live status
      if (pdfStatus) {
        pdfStatus.style.display = "block";
        pdfStatus.textContent = "⏳ Preparing PDF resume…";
        pdfStatus.style.color = "#94a3b8";
      }
      try {
        const pdfResp = await fetch(
          `http://127.0.0.1:8765/api/prep-resume?url=${encodeURIComponent(tabUrl)}`,
        );
        const pdfData = await pdfResp.json();
        if (pdfData.ok && pdfData.filename && pdfStatus) {
          pdfStatus.innerHTML =
            `✅ <strong style="color:#34d399">PDF ready:</strong> ` +
            `<span style="color:#7dd3fc;word-break:break-all">${pdfData.filename}</span><br>` +
            `<span style="color:#94a3b8;font-size:10px">In your Downloads folder — click "Open Downloads" to attach</span>`;
          pdfStatus.style.color = "#a7f3d0";
        } else if (pdfStatus) {
          pdfStatus.textContent = pdfData.message || "PDF prep failed";
          pdfStatus.style.color = "#fca5a5";
        }
      } catch (_) {
        if (pdfStatus) { pdfStatus.textContent = "Dashboard not running — PDF prep skipped"; pdfStatus.style.color = "#94a3b8"; }
      }
    } else if (tabUrl && Object.keys(resumes).length > 0) {
      panel.style.display = "block";
      info.textContent = "No matching resume found for this page.";
    }
  } catch (_) {
    // Dashboard not running or no index yet — hide panel silently
  }
}

init();
