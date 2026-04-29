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
}

init();
