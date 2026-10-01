const slug = location.pathname.match(/^\/u\/([^/]+)/)?.[1];
const welcome = document.querySelector("#welcome");
const chat = document.querySelector("#chat");
const presence = document.querySelector("#presence");
const messages = document.querySelector("#messages");
const pinForm = document.querySelector("#pin-form");
const chatForm = document.querySelector("#chat-form");
const rememberWrap = document.querySelector("#remember-wrap");
let pin = sessionStorage.getItem(`mini-pin:${slug}`) || "";

function addMessage(role, text) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.textContent = text;
  messages.append(item);
  messages.scrollTop = messages.scrollHeight;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${pin}`, ...(options.headers || {}) },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

async function unlock() {
  if (!slug) {
    presence.textContent = "Open the personal /u/<name> link shared with you.";
    pinForm.hidden = true;
    return;
  }
  const profile = await api(`/v1/mini/t/${slug}/profile`);
  presence.textContent = `${profile.owner_name}'s Mini is here.`;
  rememberWrap.hidden = !profile.vault_enabled;
  const history = await api(`/v1/mini/t/${slug}/history?limit=30`);
  messages.replaceChildren();
  for (const row of history.messages) addMessage(row.role, row.content);
  if (!history.count) addMessage("system", `Hello ${profile.owner_name}. This is your private space with Mini.`);
  welcome.hidden = true;
  chat.hidden = false;
}

pinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  pin = document.querySelector("#pin").value.trim();
  document.querySelector("#pin-error").textContent = "";
  try {
    await unlock();
    sessionStorage.setItem(`mini-pin:${slug}`, pin);
  } catch (error) {
    document.querySelector("#pin-error").textContent = error.message;
  }
});

chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.querySelector("#message");
  const send = document.querySelector("#send");
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", text);
  input.value = "";
  send.disabled = true;
  try {
    const result = await api(`/v1/mini/t/${slug}/chat`, {
      method: "POST",
      body: JSON.stringify({ message: text, mode: document.querySelector("#mode").value, remember: document.querySelector("#remember").checked }),
    });
    addMessage("assistant", result.reply);
    document.querySelector("#remember").checked = false;
  } catch (error) {
    addMessage("system", error.message);
  } finally {
    send.disabled = false;
    input.focus();
  }
});

if (pin && slug) unlock().catch(() => sessionStorage.removeItem(`mini-pin:${slug}`));

