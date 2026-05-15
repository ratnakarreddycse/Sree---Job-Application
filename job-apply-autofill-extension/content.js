const FIELD_HINTS = {
  full_name: ["full name", "name", "legal name", "first and last"],
  first_name: ["first name", "given name", "forename"],
  last_name: ["last name", "family name", "surname"],
  email: ["email", "e-mail"],
  phone: ["phone", "mobile", "contact number", "telephone"],
  linkedin: ["linkedin"],
  location: ["location", "city", "state", "country", "address"],
  work_authorization: ["work authorization", "authorized to work", "authorization", "legally authorized"],
  needs_sponsorship: ["sponsorship", "require sponsorship", "need sponsorship", "visa sponsorship"],
};

// EEO question text patterns → answer key in questions memory
const EEO_QUESTION_MAP = [
  { pattern: "how did you hear",                                    key: "How did you hear about this job?" },
  { pattern: "legally authorized to work in the country",           key: "Are you legally authorized to work in the country in which you are applying?" },
  { pattern: "legally authorized to work in the us",                key: "Are you legally authorized to work in the US?" },
  { pattern: "need sponsorship for employment visa",                key: "Do you now or will you in the future need sponsorship for employment visa status in the country in which you are applying?" },
  { pattern: "require sponsorship",                                 key: "Do you now or will you in the future need sponsorship for employment visa status in the country in which you are applying?" },
  { pattern: "willing to relocate",                                 key: "Are you willing to relocate?" },
  { pattern: "previously worked for",                               key: "Do you currently or have you previously worked for Databricks in the past?" },
  { pattern: "previously worked",                                   key: "Do you currently or have you previously worked for Databricks in the past?" },
  { pattern: "gender",                                              key: "Gender" },
  { pattern: "hispanic",                                            key: "Are you Hispanic/Latino?" },
  { pattern: "identify your race",                                  key: "Please identify your race" },
  { pattern: "race",                                                key: "Please identify your race" },
  { pattern: "veteran status",                                      key: "Veteran Status" },
  { pattern: "veteran",                                             key: "Veteran Status" },
  { pattern: "disability status",                                   key: "Disability Status" },
  { pattern: "disability",                                          key: "Disability Status" },
];

function normalize(text) {
  return (text || "").toLowerCase().replace(/\s+/g, " ").trim();
}

function splitName(fullName) {
  const parts = (fullName || "").trim().split(/\s+/).filter(Boolean);
  return {
    first: parts[0] || "",
    last: parts.length > 1 ? parts.slice(1).join(" ") : "",
  };
}

function getFieldContextText(el) {
  const parts = [];
  const attrs = ["name", "id", "placeholder", "aria-label", "autocomplete", "data-qa", "data-test"];
  for (const attr of attrs) {
    const value = el.getAttribute(attr);
    if (value) parts.push(value);
  }
  if (el.id) {
    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
    if (label) parts.push(label.textContent || "");
  }
  const closestLabel = el.closest("label");
  if (closestLabel) parts.push(closestLabel.textContent || "");

  const wrapper = el.closest("fieldset, [role='group'], .question, .application-question, .form-group, .field, li, div");
  if (wrapper) {
    const heading = wrapper.querySelector("legend, h1, h2, h3, h4, .question-title, .label");
    if (heading) parts.push(heading.textContent || "");
  }

  return normalize(parts.join(" | "));
}

function dispatchEvents(el) {
  el.dispatchEvent(new Event("input", { bubbles: true }));
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.dispatchEvent(new Event("blur", { bubbles: true }));
}

function setFieldValue(el, value) {
  if (!value) return false;
  const tag = el.tagName.toLowerCase();
  const type = (el.getAttribute("type") || "").toLowerCase();

  if (tag === "select") {
    const options = [...el.options];
    const target = normalize(value);
    const found = options.find((o) => normalize(o.textContent).includes(target) || normalize(o.value) === target);
    if (found) {
      el.value = found.value;
      dispatchEvents(el);
      return true;
    }
    return false;
  }

  if (type === "radio" || type === "checkbox") {
    const candidate = normalize(`${el.value} ${el.getAttribute("aria-label") || ""} ${(el.closest("label")?.textContent || "")}`);
    if (candidate.includes(normalize(value))) {
      el.checked = true;
      dispatchEvents(el);
      return true;
    }
    return false;
  }

  if (["input", "textarea"].includes(tag)) {
    if (el.value && normalize(el.value) === normalize(value)) return false;
    if (!el.value || el.value.length < 2) {
      el.focus();
      el.value = value;
      dispatchEvents(el);
      return true;
    }
  }
  return false;
}

function fillBySelectorList(selectors, value) {
  if (!value) return 0;
  let updated = 0;
  for (const selector of selectors) {
    const elements = document.querySelectorAll(selector);
    for (const el of elements) {
      if (el.disabled || el.readOnly || el.type === "hidden") continue;
      if (setFieldValue(el, value)) updated += 1;
      if (updated > 0) return updated;
    }
  }
  return updated;
}

function fillBySelectorMap(map, profile) {
  let updated = 0;
  const name = splitName(profile.full_name || "");
  for (const [key, selectors] of Object.entries(map)) {
    let value = profile[key] || "";
    if (key === "first_name") value = name.first;
    if (key === "last_name") value = name.last;
    updated += fillBySelectorList(selectors, value);
  }
  return updated;
}

function fillLinkedIn(profile) {
  const selectorMap = {
    first_name: [
      "input[id*='firstName']",
      "input[name*='firstName']",
      "input[autocomplete='given-name']",
    ],
    last_name: [
      "input[id*='lastName']",
      "input[name*='lastName']",
      "input[autocomplete='family-name']",
    ],
    email: [
      "input[type='email']",
      "input[id*='email']",
      "input[name*='email']",
    ],
    phone: [
      "input[type='tel']",
      "input[id*='phone']",
      "input[name*='phone']",
    ],
    location: [
      "input[id*='location']",
      "input[name*='location']",
      "input[autocomplete='address-level2']",
    ],
    linkedin: [
      "input[id*='linkedin']",
      "input[name*='linkedin']",
    ],
  };
  return fillBySelectorMap(selectorMap, profile);
}

function fillGreenhouse(profile) {
  const selectorMap = {
    first_name: [
      "input[name='first_name']",
      "input[id*='first_name']",
    ],
    last_name: [
      "input[name='last_name']",
      "input[id*='last_name']",
    ],
    email: [
      "input[name='email']",
      "input[type='email']",
    ],
    phone: [
      "input[name='phone']",
      "input[type='tel']",
    ],
    location: [
      "input[name='location']",
      "input[id*='location']",
    ],
    linkedin: [
      "input[name='urls[LinkedIn]']",
      "input[id*='linkedin']",
      "input[name*='linkedin']",
    ],
  };
  return fillBySelectorMap(selectorMap, profile);
}

function fillLever(profile) {
  const selectorMap = {
    full_name: [
      "input[name='name']",
      "input[id*='name']",
    ],
    email: [
      "input[name='email']",
      "input[type='email']",
    ],
    phone: [
      "input[name='phone']",
      "input[type='tel']",
    ],
    location: [
      "input[name='location']",
      "input[id*='location']",
    ],
    linkedin: [
      "input[name='urls[LinkedIn]']",
      "input[name*='linkedin']",
      "input[id*='linkedin']",
    ],
  };
  return fillBySelectorMap(selectorMap, profile);
}

function fillWorkday(profile) {
  const selectorMap = {
    first_name: [
      "input[name*='firstName']",
      "input[id*='firstName']",
      "input[aria-label*='First Name']",
    ],
    last_name: [
      "input[name*='lastName']",
      "input[id*='lastName']",
      "input[aria-label*='Last Name']",
    ],
    email: [
      "input[type='email']",
      "input[name*='email']",
      "input[id*='email']",
    ],
    phone: [
      "input[type='tel']",
      "input[name*='phone']",
      "input[id*='phone']",
    ],
    location: [
      "input[name*='city']",
      "input[aria-label*='City']",
      "input[name*='location']",
    ],
    linkedin: [
      "input[name*='linkedin']",
      "input[aria-label*='LinkedIn']",
    ],
  };
  return fillBySelectorMap(selectorMap, profile);
}

function bestProfileKey(context) {
  for (const [key, hints] of Object.entries(FIELD_HINTS)) {
    if (hints.some((h) => context.includes(h))) return key;
  }
  return null;
}

function fillProfileFallback(profile) {
  const fields = document.querySelectorAll("input, textarea, select");
  const name = splitName(profile.full_name || "");
  let updated = 0;
  for (const el of fields) {
    if (el.disabled || el.readOnly || el.type === "hidden") continue;
    const context = getFieldContextText(el);
    const key = bestProfileKey(context);
    if (!key) continue;
    let value = profile[key] || "";
    if (key === "first_name") value = name.first;
    if (key === "last_name") value = name.last;
    if (setFieldValue(el, value)) updated += 1;
  }
  return updated;
}

function findQuestionContainers() {
  const selectors = [
    "fieldset",
    "[role='group']",
    ".question",
    ".application-question",
    ".form-group",
    ".field",
    "li",
    "div",
  ];
  return [...document.querySelectorAll(selectors.join(","))];
}

function fillEeoFields(questions) {
  // Fill EEO/standard dropdowns by scanning every select + nearby label text.
  if (!questions) return 0;
  let updated = 0;
  const selects = document.querySelectorAll("select");
  for (const sel of selects) {
    if (sel.disabled || sel.readOnly) continue;
    // Build context text from the select's surrounding DOM
    const context = getFieldContextText(sel);
    const wrapper = sel.closest("fieldset, [role='group'], .question, .application-question, .form-group, .field, li, div");
    const wrapperText = wrapper ? normalize(wrapper.innerText || "") : "";
    const fullContext = context + " " + wrapperText;

    for (const { pattern, key } of EEO_QUESTION_MAP) {
      if (!fullContext.includes(pattern)) continue;
      const answer = questions[key];
      if (!answer) continue;
      if (setFieldValue(sel, answer)) { updated += 1; break; }
    }
  }
  return updated;
}

function fillKnownQuestions(questions) {
  let updated = 0;
  const containers = findQuestionContainers();
  const entries = Object.entries(questions || {});
  for (const [question, answer] of entries) {
    const qNorm = normalize(question);
    const aNorm = normalize(answer);
    const match = containers.find((c) => normalize(c.innerText).includes(qNorm));
    if (!match) continue;

    const fields = match.querySelectorAll("input, textarea, select");
    for (const el of fields) {
      const before = el.type === "checkbox" || el.type === "radio" ? el.checked : el.value;
      const changed = setFieldValue(el, answer);
      const after = el.type === "checkbox" || el.type === "radio" ? el.checked : el.value;
      if (changed || before !== after) {
        updated += 1;
        break;
      }
      if (el.tagName.toLowerCase() === "select") {
        const options = [...el.options];
        const found = options.find((o) => normalize(o.textContent).includes(aNorm));
        if (found) {
          el.value = found.value;
          dispatchEvents(el);
          updated += 1;
          break;
        }
      }
    }
  }
  return updated;
}

function detectPortal() {
  const host = window.location.hostname;
  if (host.includes("linkedin.com")) return "linkedin";
  if (host.includes("greenhouse.io")) return "greenhouse";
  if (host.includes("lever.co")) return "lever";
  if (host.includes("myworkdayjobs.com") || host.includes("workday.com")) return "workday";
  if (host.includes("indeed.com")) return "indeed";
  if (host.includes("dice.com")) return "dice";
  return "generic";
}

function fillPortalSpecific(portal, profile) {
  if (portal === "linkedin") return fillLinkedIn(profile);
  if (portal === "greenhouse") return fillGreenhouse(profile);
  if (portal === "lever") return fillLever(profile);
  if (portal === "workday") return fillWorkday(profile);
  return 0;
}

async function runAutofill() {
  const data = await chrome.storage.local.get("memory");
  const memory = data.memory || { profile: {}, questions: {} };
  const portal = detectPortal();
  const filledSpecific = fillPortalSpecific(portal, memory.profile || {});
  const filledFallback = fillProfileFallback(memory.profile || {});
  const filledQuestions = fillKnownQuestions(memory.questions || {});
  console.log("[job-autofill] filled fields", {
    portal,
    filledSpecific,
    filledFallback,
    filledQuestions,
  });
}

let scheduled = null;
function scheduleAutofill(delayMs = 400) {
  if (scheduled) clearTimeout(scheduled);
  scheduled = setTimeout(() => {
    runAutofill().catch(() => {});
  }, delayMs);
}

// ── Adaptive learning ─────────────────────────────────────────────────────
// After autofill runs, watch for fields the user manually fills in.
// When a question field is answered, capture question→answer and persist it.

const _autofillTouched = new WeakSet();  // fields we filled — skip these

function _extractQuestionText(el) {
  // Walk up the DOM to find the question label for this field.
  const parts = [];
  const labelEl = el.id ? document.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
  if (labelEl) parts.push(labelEl.textContent.trim());
  const wrapper = el.closest(
    "fieldset, [role='group'], .question, .application-question, .form-group, .field, li"
  );
  if (wrapper) {
    const heading = wrapper.querySelector("legend, h2, h3, h4, .question-title, .label, label");
    if (heading && !parts.includes(heading.textContent.trim())) {
      parts.push(heading.textContent.trim());
    }
  }
  const text = parts.join(" ").replace(/\s+/g, " ").trim();
  // Only return if it looks like a real question (at least 10 chars, not just whitespace)
  return text.length >= 10 ? text : null;
}

async function _persistLearnedAnswer(question, answer) {
  // Save to chrome.storage.local immediately
  const data = await chrome.storage.local.get("memory");
  const memory = data.memory || { profile: {}, questions: {} };
  memory.questions[question] = answer;
  await chrome.storage.local.set({ memory });

  // Also POST to local dashboard so answers_memory.json is updated
  try {
    await fetch("http://127.0.0.1:8765/api/learn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, answer }),
    });
  } catch (_) {
    // Dashboard not running — local storage save is enough
  }
}

function _showLearnedBadge(el) {
  const badge = document.createElement("span");
  badge.textContent = "✓ Saved";
  badge.style.cssText =
    "position:absolute;background:#34d399;color:#052e2b;font-size:10px;font-weight:700;" +
    "padding:2px 6px;border-radius:4px;pointer-events:none;z-index:99999;";
  const rect = el.getBoundingClientRect();
  badge.style.top = `${window.scrollY + rect.top - 20}px`;
  badge.style.left = `${window.scrollX + rect.right + 4}px`;
  document.body.appendChild(badge);
  setTimeout(() => badge.remove(), 2000);
}

function setupAdaptiveLearning() {
  const fields = document.querySelectorAll("input:not([type=hidden]):not([type=file]):not([type=submit]):not([type=button]), textarea, select");
  for (const el of fields) {
    if (el.disabled || el.readOnly) continue;
    if (_autofillTouched.has(el)) continue;  // we filled this, skip

    el.addEventListener("blur", async () => {
      const value = (el.type === "checkbox" || el.type === "radio")
        ? (el.checked ? el.value || "Yes" : "")
        : el.value.trim();
      if (!value || value.length < 2) return;
      if (_autofillTouched.has(el)) return;  // autofill set it after listener registered

      const question = _extractQuestionText(el);
      if (!question) return;

      // Don't save obvious profile fields or EEO fields — already handled directly
      const profilePatterns = ["email", "phone", "first name", "last name", "full name", "linkedin", "address", "zip", "postal", "gender", "race", "hispanic", "veteran", "disability"];
      if (profilePatterns.some((p) => question.toLowerCase().includes(p))) return;

      await _persistLearnedAnswer(question, value);
      _showLearnedBadge(el);
    }, { once: true });
  }
}

// Patch setFieldValue to mark autofill-touched fields
const _origSetFieldValue = setFieldValue;
function setFieldValue(el, value) {
  const result = _origSetFieldValue(el, value);
  if (result) _autofillTouched.add(el);
  return result;
}

async function runAutofill() {
  const data = await chrome.storage.local.get("memory");
  const memory = data.memory || { profile: {}, questions: {} };
  const portal = detectPortal();
  const filledSpecific = fillPortalSpecific(portal, memory.profile || {});
  const filledFallback = fillProfileFallback(memory.profile || {});
  const filledQuestions = fillKnownQuestions(memory.questions || {});
  const filledEeo = fillEeoFields(memory.questions || {});
  console.log("[job-autofill] filled fields", {
    portal,
    filledSpecific,
    filledFallback,
    filledQuestions,
    filledEeo,
  });
  // After autofill completes, watch remaining unfilled fields for learning
  setTimeout(setupAdaptiveLearning, 600);
  // Silently prepare the tailored PDF resume and drop it in ~/Downloads/
  _prepResumeForPage().catch(() => {});
}

// ── Auto PDF resume preparation ───────────────────────────────────────────
// On page load, ask the dashboard to convert the matching resume .md → PDF
// and save it to ~/Downloads/. This ensures the PDF is at the top of the
// Downloads list (newest timestamp) before the user ever clicks "Attach".

let _preparedPdfFilename = null;

async function _prepResumeForPage() {
  if (_preparedPdfFilename) return;  // already done for this page load
  try {
    const resp = await fetch(
      `http://127.0.0.1:8765/api/prep-resume?url=${encodeURIComponent(window.location.href)}`,
    );
    const data = await resp.json();
    if (data.ok && data.filename) {
      _preparedPdfFilename = data.filename;
      _showResumeBanner(data.filename);
      _annotateFileInputs(data.filename);
    }
  } catch (_) {
    // Dashboard not running — silent fail
  }
}

function _showResumeBanner(filename) {
  document.getElementById("_job_resume_banner")?.remove();
  const banner = document.createElement("div");
  banner.id = "_job_resume_banner";
  banner.style.cssText =
    "position:fixed;bottom:18px;right:18px;z-index:2147483647;" +
    "background:#052e2b;border:1.5px solid #34d399;border-radius:10px;" +
    "padding:10px 14px;font-size:12px;color:#a7f3d0;max-width:300px;" +
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;" +
    "box-shadow:0 4px 16px rgba(0,0,0,0.5);";
  banner.innerHTML =
    `<strong style="color:#34d399">✓ Resume PDF ready</strong><br>` +
    `<span style="color:#7dd3fc;font-size:10px;word-break:break-all">${filename}</span><br>` +
    `<span style="color:#94a3b8;font-size:10px">Open <strong>Downloads</strong> folder to attach ↑</span>` +
    `<span id="_resume_banner_x" style="position:absolute;top:5px;right:10px;cursor:pointer;color:#94a3b8;font-size:15px">×</span>`;
  document.body.appendChild(banner);
  document.getElementById("_resume_banner_x").onclick = () => banner.remove();
  setTimeout(() => { try { banner.remove(); } catch (_) {} }, 9000);
}

function _showFileInputBadge(input, filename) {
  if (input.parentElement?.querySelector("._resume_file_badge")) return;
  const badge = document.createElement("div");
  badge.className = "_resume_file_badge";
  badge.style.cssText =
    "display:block;margin-top:5px;padding:6px 10px;" +
    "background:#052e2b;border:1px solid #34d399;border-radius:5px;" +
    "font-size:10px;color:#a7f3d0;" +
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;";
  badge.innerHTML =
    `📎 <strong>Resume ready in Downloads:</strong><br>` +
    `<code style="color:#7dd3fc;word-break:break-all">${filename}</code>`;
  if (input.parentElement) {
    input.parentElement.insertBefore(badge, input.nextSibling);
  }
}

function _annotateFileInputs(filename) {
  const fileInputs = document.querySelectorAll('input[type="file"]');
  for (const input of fileInputs) {
    if (input._resumeAnnotated) continue;
    input._resumeAnnotated = true;
    // Show badge when user hovers or when input becomes visible
    const obs = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) { _showFileInputBadge(input, filename); obs.disconnect(); }
    }, { threshold: 0.1 });
    obs.observe(input);
    input.addEventListener("mouseenter", () => _showFileInputBadge(input, filename), { once: true });
  }
}

// Watch for file inputs added dynamically after page load
const _fileInputObserver = new MutationObserver(() => {
  if (_preparedPdfFilename) _annotateFileInputs(_preparedPdfFilename);
});
_fileInputObserver.observe(document.documentElement, { childList: true, subtree: true });

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "RUN_AUTOFILL") {
    runAutofill().catch(() => {});
  }
});

scheduleAutofill(500);
window.addEventListener("load", () => scheduleAutofill(300));

const observer = new MutationObserver(() => scheduleAutofill(500));
observer.observe(document.documentElement, { childList: true, subtree: true });
