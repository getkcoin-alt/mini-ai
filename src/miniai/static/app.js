const $ = (selector) => document.querySelector(selector);
const slug = location.pathname.match(/^\/u\/([^/]+)/)?.[1];
const root = `/v1/mini/t/${encodeURIComponent(slug || "")}`;
let pin = sessionStorage.getItem(`mini-pin:${slug}`) || "";
let prefs;
let sending = false;

function notice(text) { $("#notice").textContent = text; }
function addMessage(role, text) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.textContent = text;
  $("#messages").append(item);
  $("#messages").scrollTop = $("#messages").scrollHeight;
  return item;
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${pin}`, ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "Please check the fields and try again.";
    throw new Error(detail);
  }
  return body;
}
function bindForm(selector, action) {
  $(selector).addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector('button[type="submit"]');
    button.disabled = true;
    try { await action(); } catch (error) { notice(error.message); }
    finally { button.disabled = false; }
  });
}
function applyPreferences() {
  $("#focus").value = prefs.focus;
  $("#tone").value = prefs.tone;
  $("#preferred-mode").value = prefs.mode;
  $("#mode").value = prefs.mode;
  $("#memory-enabled").checked = prefs.memory_enabled;
  $("#remember-private").disabled = !prefs.memory_enabled;
  $("#add-memory").disabled = !prefs.memory_enabled;
  $("#memory-status").textContent = prefs.memory_enabled ? "Personal memory is on. Save only what you want Mini to recall." : "Personal memory is off. Enable it in your preferences to save and recall notes.";
  if (!prefs.memory_enabled) $("#remember-private").checked = false;
  $("#space").open = !prefs.onboarded;
  $("#space-title").textContent = prefs.onboarded ? "Your preferences" : "Make Mini yours";
}
async function refreshMemories() {
  const { memories } = await api(`${root}/memories`);
  const list = $("#memory-list");
  list.replaceChildren();
  if (!memories.length) { list.textContent = "No personal memories saved yet."; return; }
  for (const memory of memories) {
    const form = document.createElement("form");
    form.className = "stack note";
    const label = document.createElement("label");
    label.textContent = "Saved memory";
    const text = document.createElement("textarea");
    text.value = memory.content; text.required = true; text.maxLength = 2000;
    label.append(text);
    const save = document.createElement("button");
    save.type = "submit"; save.textContent = "Save changes"; save.disabled = !prefs.memory_enabled;
    const remove = document.createElement("button");
    remove.type = "button"; remove.textContent = "Delete memory";
    form.append(label, save, remove); list.append(form);
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); save.disabled = true;
      try {
        await api(`${root}/memories/${memory.id}`, { method: "PUT", body: JSON.stringify({ content: text.value }) });
        notice("Memory updated."); await refreshMemories();
      } catch (error) { notice(error.message); save.disabled = false; }
    });
    remove.addEventListener("click", async () => {
      remove.disabled = true;
      try { await api(`${root}/memories/${memory.id}`, { method: "DELETE" }); notice("Memory deleted."); await refreshMemories(); }
      catch (error) { notice(error.message); remove.disabled = false; }
    });
  }
}
async function refreshGoals() {
  const { goals } = await api(`${root}/goals`);
  const list = $("#goal-list"); list.replaceChildren();
  const active = goals.find((g) => g.status === "active");
  $("#goal-form").hidden = Boolean(active);
  for (const goal of goals) {
    const card = document.createElement("div"); card.className = "note stack";
    const title = document.createElement("h3"); title.textContent = `${goal.status === "complete" ? "Completed: " : ""}${goal.title}`;
    const step = document.createElement("p"); step.textContent = `Next step: ${goal.next_step}`;
    card.append(title, step);
    for (const entry of goal.checkins.slice(0, 5)) {
      const row = document.createElement("p"); row.textContent = `${new Date(entry.created_at).toLocaleDateString()}: ${entry.note}`; card.append(row);
    }
    if (goal.status === "active") {
      const form = document.createElement("form"); form.className = "stack";
      const noteLabel = document.createElement("label"); noteLabel.textContent = "What happened since your last visit?";
      const note = document.createElement("textarea"); note.required = true; note.maxLength = 1000; noteLabel.append(note);
      const nextLabel = document.createElement("label"); nextLabel.textContent = "My next small step";
      const next = document.createElement("input"); next.required = true; next.maxLength = 500; next.value = goal.next_step; nextLabel.append(next);
      const completeLabel = document.createElement("label"); completeLabel.className = "toggle";
      const complete = document.createElement("input"); complete.type = "checkbox"; completeLabel.append(complete, " I completed this goal");
      const save = document.createElement("button"); save.type = "submit"; save.textContent = "Save check-in";
      form.append(noteLabel, nextLabel, completeLabel, save); card.append(form);
      form.addEventListener("submit", async (event) => {
        event.preventDefault(); save.disabled = true;
        try {
          await api(`${root}/goals/${goal.id}/checkins`, { method: "POST", body: JSON.stringify({ note: note.value, next_step: next.value, complete: complete.checked }) });
          notice(complete.checked ? "Goal completed. Take a moment to recognise your progress." : "Progress saved. Your next step is ready."); await refreshGoals();
        } catch (error) { notice(error.message); save.disabled = false; }
      });
    }
    list.append(card);
  }
}
async function unlock() {
  if (!slug) { $("#presence").textContent = "Open the personal /u/<name> link shared with you."; $("#pin-form").hidden = true; return; }
  const profile = await api(`${root}/profile`);
  prefs = profile.preferences;
  $("#presence").textContent = `${profile.owner_name}'s Mini is here.`;
  $("#remember-wrap").hidden = !profile.vault_enabled;
  const history = await api(`${root}/history?limit=30`);
  $("#messages").replaceChildren();
  for (const row of history.messages) addMessage(row.role, row.content);
  if (!history.count) addMessage("system", `Hello ${profile.owner_name}. Tell Mini what's on your mind, or start with one small goal.`);
  applyPreferences();
  await Promise.all([refreshMemories(), refreshGoals()]);
  $("#welcome").hidden = true;
  for (const id of ["#space", "#chat", "#tools"]) $(id).hidden = false;
  if (!prefs.onboarded) $("#focus").focus();
}
$("#pin-form").addEventListener("submit", async (event) => {
  event.preventDefault(); pin = $("#pin").value.trim(); $("#pin-error").textContent = "";
  const button = event.currentTarget.querySelector("button"); button.disabled = true;
  try { await unlock(); sessionStorage.setItem(`mini-pin:${slug}`, pin); $("#pin").value = ""; }
  catch (error) { $("#pin-error").textContent = error.message; }
  finally { button.disabled = false; }
});
bindForm("#preferences-form", async () => {
  prefs = await api(`${root}/preferences`, { method: "PUT", body: JSON.stringify({ focus: $("#focus").value, tone: $("#tone").value, mode: $("#preferred-mode").value, memory_enabled: $("#memory-enabled").checked }) });
  applyPreferences(); await refreshMemories(); notice("Preferences saved. Mini is ready.");
});
bindForm("#memory-form", async () => {
  await api(`${root}/memories`, { method: "POST", body: JSON.stringify({ content: $("#memory-content").value }) });
  $("#memory-content").value = ""; await refreshMemories(); notice("Saved to your personal memories.");
});
bindForm("#goal-form", async () => {
  await api(`${root}/goals`, { method: "POST", body: JSON.stringify({ title: $("#goal-title").value, next_step: $("#goal-step").value }) });
  $("#mode").value = "mentor"; $("#goal-form").reset(); await refreshGoals(); notice("Goal saved. Mentor can help you with your next step.");
});
async function sendMessage(text, payload, retry = false) {
  if (sending) return;
  sending = true; $("#send").disabled = true;
  if (!retry) addMessage("user", text);
  const pending = addMessage("system", "Mini is thinking…");
  try {
    const result = await api(`${root}/chat`, { method: "POST", body: JSON.stringify(payload) });
    pending.remove(); addMessage("assistant", result.reply);
    $("#remember").checked = false; $("#remember-private").checked = false;
    notice(`${result.personal_memories_used} personal ${result.personal_memories_used === 1 ? "memory" : "memories"} used.${result.private_memory ? " Your message was saved as a personal memory." : ""}${result.vault_memory ? " Your message was shared with Vault Zeta." : ""}`);
    if (result.private_memory) await refreshMemories();
  } catch (error) {
    pending.textContent = error.message;
    // Keep the draft available; don't silently repeat writes to an external Vault.
    $("#message").value = text;
    notice("Your message could not be completed. Your draft is restored; review it before sending again.");
  } finally { sending = false; $("#send").disabled = false; $("#message").focus(); }
}
$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault(); const text = $("#message").value.trim(); if (!text || sending) return;
  const payload = { message: text, mode: $("#mode").value, remember: $("#remember").checked, remember_private: $("#remember-private").checked };
  $("#message").value = ""; await sendMessage(text, payload);
});
bindForm("#pin-change-form", async () => {
  const next = $("#new-pin").value;
  await api(`${root}/pin`, { method: "PUT", body: JSON.stringify({ pin: next }) });
  pin = next; sessionStorage.setItem(`mini-pin:${slug}`, pin); $("#new-pin").value = ""; notice("PIN changed. Use your new PIN next time.");
});
$("#export").addEventListener("click", async () => {
  try {
    const data = await api(`${root}/export`);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "mini-data.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice("Your data download is ready.");
  } catch (error) { notice(error.message); }
});
$("#lock").addEventListener("click", () => { sessionStorage.removeItem(`mini-pin:${slug}`); location.reload(); });
bindForm("#erase-form", async () => {
  const result = await api(`${root}/erase`, { method: "POST", body: JSON.stringify({ confirmation: $("#erase-confirm").value }) });
  sessionStorage.removeItem(`mini-pin:${slug}`); pin = "";
  for (const id of ["#space", "#chat", "#tools"]) $(id).hidden = true;
  $("#messages").replaceChildren(); notice(result.scope); $("#presence").textContent = "Your Mini data has been erased and this link is disabled.";
});
if (slug && pin) unlock().catch((error) => { sessionStorage.removeItem(`mini-pin:${slug}`); notice(error.message); });
else if (!slug) unlock();
