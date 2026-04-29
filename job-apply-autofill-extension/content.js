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

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type === "RUN_AUTOFILL") {
    runAutofill().catch(() => {});
  }
});

scheduleAutofill(500);
window.addEventListener("load", () => scheduleAutofill(300));

const observer = new MutationObserver(() => scheduleAutofill(500));
observer.observe(document.documentElement, { childList: true, subtree: true });
