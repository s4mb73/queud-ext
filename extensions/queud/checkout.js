const params = new URLSearchParams(location.search);
const session = params.get("session");
const endUrl = params.get("endUrl");
const proxy = params.get("proxy");

function show(msg, isError) {
  document.body.textContent = msg;
  if (isError) {
    document.body.style.color = "#f87171";
  }
}

if (!session || !endUrl) {
  show("Missing session or endUrl.", true);
} else {
  let settled = false;
  const timer = setTimeout(() => {
    if (settled) {
      return;
    }
    settled = true;
    show(
      "queud timed out — reload extension at chrome://extensions and retry",
      true
    );
  }, 20000);

  chrome.runtime.sendMessage(
    { type: "QUEUD_CHECKOUT", session, endUrl, proxy: proxy || "" },
    (resp) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      if (chrome.runtime.lastError) {
        show("queud error: " + chrome.runtime.lastError.message, true);
        return;
      }
      if (!resp || !resp.ok) {
        show("queud error: " + (resp?.error || "checkout failed"), true);
        return;
      }
      show("Redirecting to checkout…");
    }
  );
}