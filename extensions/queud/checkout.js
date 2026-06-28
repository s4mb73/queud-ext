const params = new URLSearchParams(location.search);
const session = params.get("session");
const endUrl = params.get("endUrl");
const proxy = params.get("proxy");

if (!session || !endUrl) {
  document.body.textContent = "Missing session or endUrl.";
} else {
  chrome.runtime.sendMessage(
    { type: "QUEUD_CHECKOUT", session, endUrl, proxy: proxy || "" },
    () => {
      if (chrome.runtime.lastError) {
        document.body.textContent = "queud error: " + chrome.runtime.lastError.message;
      }
    }
  );
}