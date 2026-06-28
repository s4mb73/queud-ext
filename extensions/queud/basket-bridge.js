/** Runs on API basket landing pages — wakes the service worker reliably. */
(function () {
  const match = location.pathname.match(/\/basket\/([0-9a-f-]{36})/i);
  if (!match) {
    return;
  }

  chrome.runtime.sendMessage(
    {
      type: "QUEUD_BASKET",
      apiBase: location.origin,
      basketId: match[1],
    },
    (resp) => {
      if (chrome.runtime.lastError) {
        console.warn("queud:", chrome.runtime.lastError.message);
        return;
      }
      if (resp && !resp.ok) {
        console.warn("queud checkout failed:", resp.error);
      }
    }
  );
})();