const $ = (id) => document.getElementById(id);

const STEPS = ["content", "cast", "script", "voicing", "done"];
const COUNT_HINT = {
  1: "One person explains the topic as a talk.",
  2: "Host and expert in conversation.",
  3: "Plus someone who asks questions.",
  4: "A round of four voices, including disagreement.",
};
const ROLE_NAMES = {
  host: "Host",
  expert: "Expert",
  student: "Student",
  critic: "Critical voice",
};
const LANGUAGE_NAMES = { de: "German", en: "English" };
const DEFAULT_NAMES = ["Ana", "Ben", "Cleo", "Dan"];
const DEFAULT_ROLES = ["host", "expert", "student", "critic"];

let info = {};
let chosenFiles = [];
let lines = [];
let persons = [];
let step = "content";
let polling = null;

function show(next) {
  step = next;
  STEPS.forEach((name) => {
    $("pane-" + name).hidden = name !== next;
  });
  const at = STEPS.indexOf(next);
  document.querySelectorAll(".stepper .step").forEach((node, index) => {
    node.classList.toggle("active", index === at);
    node.classList.toggle("past", index < at);
  });
}

function fail(id, message) {
  const node = $(id);
  node.textContent = message || "";
  node.hidden = !message;
}

async function ask(url, options) {
  const response = await fetch(url, options);
  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    body = null;
  }
  if (!response.ok) {
    throw new Error((body && body.detail) || response.statusText);
  }
  return body;
}

function renderFiles() {
  const list = $("file-list");
  list.textContent = "";
  chosenFiles.forEach((file, index) => {
    const row = document.createElement("li");
    const name = document.createElement("span");
    name.textContent = file.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", "Remove " + file.name);
    remove.addEventListener("click", () => {
      chosenFiles.splice(index, 1);
      renderFiles();
    });
    row.append(name, remove);
    list.append(row);
  });
  $("file-count").textContent = chosenFiles.length
    ? chosenFiles.length + " of " + info.max_sources + " files"
    : "";
}

function addFiles(files) {
  for (const file of files) {
    if (chosenFiles.length >= info.max_sources) {
      fail("content-error", "That is too many files. Remove some to continue.");
      break;
    }
    chosenFiles.push(file);
  }
  renderFiles();
}

function renderPersons() {
  const count = Number($("speakers").value);
  $("count-hint").textContent = COUNT_HINT[count] || "";
  const box = $("persons");
  const before = persons.slice();
  persons = [];
  box.textContent = "";
  for (let index = 0; index < count; index += 1) {
    const person = before[index] || {
      name: (info.names && info.names[index]) || DEFAULT_NAMES[index],
      role: (info.roles && info.roles[index]) || DEFAULT_ROLES[index],
      voice: (info.voices && info.voices[index]) || "",
    };
    persons.push(person);
    box.append(personRow(person, index));
  }
}

function personRow(person, index) {
  const row = document.createElement("div");
  row.className = "person";
  const title = document.createElement("strong");
  title.textContent = "Person " + (index + 1);
  row.append(title, field("Name", person, "name", "text"),
             roleField(person), field("Voice", person, "voice", "text"));
  return row;
}

function field(text, person, key, type) {
  const label = document.createElement("label");
  label.append(document.createTextNode(text));
  const input = document.createElement("input");
  input.type = type;
  input.value = person[key] || "";
  input.addEventListener("input", () => {
    person[key] = input.value;
  });
  label.append(input);
  return label;
}

function roleField(person) {
  const label = document.createElement("label");
  label.append(document.createTextNode("Role"));
  const select = document.createElement("select");
  (info.role_names || Object.keys(ROLE_NAMES)).forEach((role) => {
    const option = document.createElement("option");
    option.value = role;
    option.textContent = ROLE_NAMES[role] || role;
    select.append(option);
  });
  select.value = person.role;
  select.addEventListener("change", () => {
    person.role = select.value;
  });
  label.append(select);
  return label;
}

function renderLines() {
  const box = $("lines");
  box.textContent = "";
  lines.forEach((line, index) => {
    const row = document.createElement("div");
    row.className = "line";
    const who = document.createElement("select");
    who.setAttribute("aria-label", "Person for contribution " + (index + 1));
    persons.forEach((person, number) => {
      const option = document.createElement("option");
      option.value = String(number);
      option.textContent = person.name || "Person " + (number + 1);
      who.append(option);
    });
    who.value = String(Math.min(line.speaker, persons.length - 1));
    who.addEventListener("change", () => {
      line.speaker = Number(who.value);
    });
    const text = document.createElement("textarea");
    text.rows = 2;
    text.value = line.text;
    text.setAttribute("aria-label", "Text of line " + (index + 1));
    text.addEventListener("input", () => {
      line.text = text.value;
      summarize();
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "Delete";
    remove.setAttribute("aria-label", "Delete line " + (index + 1));
    remove.addEventListener("click", () => {
      lines.splice(index, 1);
      renderLines();
    });
    row.append(who, text, remove);
    box.append(row);
  });
  summarize();
}

function summarize() {
  const words = lines.reduce((sum, line) => sum + line.text.split(/\s+/).filter(Boolean).length, 0);
  const minutes = Math.max(1, Math.round(words / 145));
  $("script-summary").textContent = lines.length
    ? lines.length + (lines.length === 1 ? " line" : " lines") + ", " + words
      + " words, about " + minutes + (minutes === 1 ? " minute" : " minutes")
    : "";
}

function serverFields() {
  return {
    base_url: $("base-url").value,
    model: $("model").value,
    api_key: $("api-key").value,
    tts_base_url: $("tts-base-url").value,
    tts_model: $("tts-model").value,
    tts_api_key: $("tts-api-key").value,
  };
}

async function startScript() {
  fail("cast-error", "");
  const body = new FormData();
  chosenFiles.forEach((file) => body.append("files", file));
  body.append("language", $("language").value);
  body.append("style", $("style").value);
  body.append("minutes", $("length").value);
  body.append("speakers", String(persons.length));
  body.append("names", persons.map((p) => p.name).join(","));
  body.append("roles", persons.map((p) => p.role).join(","));
  body.append("voices", persons.map((p) => p.voice).join(","));
  body.append("speed", $("speed").value);
  body.append("instructions", $("instructions").value);
  const fields = serverFields();
  body.append("base_url", fields.base_url);
  body.append("model", fields.model);
  body.append("api_key", fields.api_key);
  try {
    await ask("/api/script", { method: "POST", body });
  } catch (error) {
    fail("cast-error", error.message);
    return;
  }
  $("script-heading").textContent = "The script is being written";
  $("script-intro").hidden = true;
  $("script-actions").hidden = true;
  $("lines").textContent = "";
  fail("script-error", "");
  show("script");
  poll();
}

async function startVoicing() {
  fail("script-error", "");
  const payload = {
    lines: lines.map((line) => ({ speaker: line.speaker, text: line.text })),
    persons: persons.map((p) => ({ name: p.name, role: p.role, voice: p.voice })),
    language: $("language").value,
    speed: Number($("speed").value),
    intro_note: $("intro-note").value,
    ...serverFields(),
  };
  try {
    await ask("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    fail("script-error", error.message);
    return;
  }
  fail("voicing-error", "");
  $("voicing-actions").hidden = true;
  $("voicing-progress").textContent = "0 of " + lines.length + " lines voiced";
  show("voicing");
  poll();
}

function poll() {
  if (polling) {
    clearInterval(polling);
  }
  polling = setInterval(refresh, 700);
  refresh();
}

async function refresh() {
  let job;
  try {
    job = await ask("/api/job");
  } catch (error) {
    return;
  }
  if (job.step === "script") {
    $("script-progress").textContent = job.total
      ? job.done + " of " + job.total + " parts written"
      : "";
  }
  if (job.step === "tts" && job.state === "running") {
    $("voicing-progress").textContent = job.total
      ? job.done + " of " + job.total + " lines voiced"
      : "The contributions are being put together";
  }
  if (job.state === "running") {
    return;
  }
  clearInterval(polling);
  polling = null;
  if (job.state === "error") {
    if (job.step === "script") {
      $("script-heading").textContent = "The script could not be written";
      fail("script-error", job.error);
    } else {
      fail("voicing-error", job.error);
      $("voicing-actions").hidden = false;
    }
    return;
  }
  if (job.step === "script") {
    lines = job.lines.map((line) => ({ speaker: line.speaker, text: line.text }));
    persons = job.persons.map((person, index) => ({
      name: person.name,
      role: person.role,
      voice: person.voice || persons[index] && persons[index].voice || "",
    }));
    $("script-heading").textContent = "Check the script";
    $("script-progress").textContent = "";
    $("script-intro").hidden = false;
    $("script-unmatched").hidden = !job.instruction_unmatched;
    $("script-actions").hidden = false;
    renderLines();
    show("script");
    return;
  }
  const minutes = job.minutes || 0;
  const voices = new Set(lines.map((line) => line.speaker)).size;
  $("done-summary").textContent = "About " + minutes
    + (minutes === 1 ? " minute" : " minutes") + ", " + lines.length + " lines, "
    + voices + (voices === 1 ? " voice" : " voices");
  $("audio").src = "/api/audio?t=" + Date.now();
  show("done");
}

function reset() {
  chosenFiles = [];
  lines = [];
  renderFiles();
  fail("content-error", "");
  fail("cast-error", "");
  fail("script-error", "");
  fail("voicing-error", "");
  show("content");
}

async function load() {
  info = await ask("/api/info");
  $("extensions").textContent = "PDF, Word, PowerPoint or text files, at most "
    + info.max_sources + " at a time.";
  const language = $("language");
  (info.languages || ["en"]).forEach((code) => {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = LANGUAGE_NAMES[code] || code;
    language.append(option);
  });
  language.value = info.language || "en";
  $("style").value = info.style || "teaching";
  $("speakers").value = String(info.speakers || 2);
  $("speed").value = String(info.speed || 0.9);
  $("speed-label").firstChild.textContent = "Speed: " + $("speed").value + "x ";
  if (info.minutes) {
    const choice = [5, 10, 20].reduce((best, value) =>
      Math.abs(value - info.minutes) < Math.abs(best - info.minutes) ? value : best, 10);
    $("length").value = String(choice);
  }
  $("base-url").value = info.base_url || "";
  $("model").value = info.model || "";
  $("tts-base-url").value = info.tts_base_url || "";
  $("tts-model").value = info.tts_model || "";
  renderPersons();
  show("content");
}

$("files").addEventListener("change", (event) => {
  fail("content-error", "");
  addFiles(event.target.files);
  event.target.value = "";
});

["dragenter", "dragover"].forEach((name) => {
  $("drop").addEventListener(name, (event) => {
    event.preventDefault();
    $("drop").classList.add("over");
  });
});

["dragleave", "drop"].forEach((name) => {
  $("drop").addEventListener(name, () => $("drop").classList.remove("over"));
});

$("drop").addEventListener("drop", (event) => {
  event.preventDefault();
  fail("content-error", "");
  addFiles(event.dataTransfer.files);
});

$("to-cast").addEventListener("click", () => {
  if (!chosenFiles.length) {
    fail("content-error", "Please add at least one file.");
    return;
  }
  fail("content-error", "");
  renderPersons();
  show("cast");
});

$("speakers").addEventListener("change", renderPersons);
$("speed").addEventListener("input", () => {
  $("speed-label").firstChild.textContent = "Speed: " + $("speed").value + "x ";
});
$("back-content").addEventListener("click", () => show("content"));
$("to-script").addEventListener("click", startScript);
$("back-cast").addEventListener("click", () => show("cast"));
$("to-voicing").addEventListener("click", startVoicing);
$("back-script").addEventListener("click", () => show("script"));
$("edit-script").addEventListener("click", () => show("script"));
$("restart").addEventListener("click", reset);
$("add-line").addEventListener("click", () => {
  lines.push({ speaker: 0, text: "" });
  renderLines();
});

load();
