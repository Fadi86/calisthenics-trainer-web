(function () {
  const script = document.currentScript;
  const myProfileId = parseInt(script.dataset.myProfileId, 10);
  const chatBox = document.getElementById("chat-box");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");

  function lastMessageId() {
    const msgs = chatBox.querySelectorAll(".chat-msg");
    if (!msgs.length) return 0;
    return parseInt(msgs[msgs.length - 1].dataset.id, 10) || 0;
  }

  function appendMessage(m) {
    const div = document.createElement("div");
    div.className = "chat-msg" + (m.profile_id === myProfileId ? " chat-msg-me" : "");
    div.dataset.id = m.id;
    const time = (m.created_at && m.created_at.length > 10) ? m.created_at.slice(11, 16) : (m.created_at || "");
    div.innerHTML =
      `<div class="chat-msg-meta">${escapeHtml(m.sender_name || "Someone")} · ${escapeHtml(time)}</div>` +
      `<div class="chat-msg-bubble">${escapeHtml(m.message)}</div>`;
    chatBox.appendChild(div);
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  async function poll() {
    try {
      const res = await fetch(`/api/chat/messages?since=${lastMessageId()}`);
      const messages = await res.json();
      if (messages.length) {
        messages.forEach(appendMessage);
        chatBox.scrollTop = chatBox.scrollHeight;
      }
    } catch (e) {
      // network hiccup - just try again next interval
    }
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    await fetch("/api/chat/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    await poll();
  });

  chatBox.scrollTop = chatBox.scrollHeight;
  setInterval(poll, 4000);
})();
