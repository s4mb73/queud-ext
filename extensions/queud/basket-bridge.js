/** Checkout trigger on Railway basket pages (v1.3.1 HTML fallback). */
(async function () {
  if (window.__queudBasketInit) {
    return;
  }

  const match = location.pathname.match(/\/basket\/([0-9a-f-]{36})/i);
  if (!match) {
    return;
  }

  const basketId = match[1];
  const status =
    document.getElementById("queud-status") ||
    document.querySelector("p") ||
    document.body;

  function show(msg, isError) {
    if (status) {
      status.textContent = msg;
      if (isError) {
        status.style.color = "#f87171";
      }
    }
  }

  try {
    const resp = await fetch(`/basket/${basketId}/session`);
    if (!resp.ok) {
      show(`Session ${resp.status} — link used or expired. Get a new Discord link.`, true);
      return;
    }
    const data = await resp.json();

    chrome.runtime.sendMessage(
      {
        type: "QUEUD_CHECKOUT",
        session: data.session,
        endUrl: data.endUrl,
        proxy: data.proxy || "",
      },
      (reply) => {
        if (chrome.runtime.lastError) {
          show(`Extension error: ${chrome.runtime.lastError.message}`, true);
          addFallbackButton(data);
          return;
        }
        if (!reply || !reply.ok) {
          show(`Checkout failed: ${reply?.error || "unknown"}`, true);
          addFallbackButton(data);
        }
      }
    );
  } catch (err) {
    show(String(err.message || err), true);
  }

  function addFallbackButton(data) {
    if (document.getElementById("queud-fallback")) {
      return;
    }
    const extId = "cinkmcgingnfflllnhdfckdfcfcnocjk";
    const href =
      `chrome-extension://${extId}/checkout.html` +
      `?session=${encodeURIComponent(data.session)}` +
      `&endUrl=${encodeURIComponent(data.endUrl)}` +
      (data.proxy ? `&proxy=${encodeURIComponent(data.proxy)}` : "");
    const a = document.createElement("a");
    a.id = "queud-fallback";
    a.href = href;
    a.textContent = "Click here to open checkout (queud)";
    a.style.cssText =
      "display:inline-block;margin-top:1.5rem;padding:12px 20px;background:#3498db;color:#fff;border-radius:8px;text-decoration:none;font-weight:600";
    document.body.appendChild(a);
  }
})();