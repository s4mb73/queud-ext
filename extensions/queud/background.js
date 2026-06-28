let proxyUserName = "";
let proxyPassword = "";
const processedTabs = new Set();

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "queud-clear-proxy",
    title: "Clear Proxy",
    contexts: ["all"],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "queud-clear-proxy") {
    chrome.proxy.settings.clear({ scope: "regular" });
  }
});

chrome.webRequest.onAuthRequired.addListener(
  (details, callback) => {
    callback({
      authCredentials: { username: proxyUserName, password: proxyPassword },
    });
  },
  { urls: ["<all_urls>"] },
  ["asyncBlocking"]
);

async function resolveTabId(sender) {
  if (sender.tab?.id) {
    return sender.tab.id;
  }
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.id;
}

function handleCheckoutMessage(message, sender, sendResponse) {
  if (message.type === "QUEUD_BASKET") {
    checkoutFromBasketApi(
      `${message.apiBase}/basket/${message.basketId}`
    )
      .then((checkout) => resolveTabId(sender).then((tabId) => runCheckout(checkout, tabId)))
      .then(() => sendResponse({ ok: true }))
      .catch((err) => {
        resolveTabId(sender).then((tabId) => showTabError(tabId, String(err)));
        sendResponse({ ok: false, error: String(err) });
      });
    return true;
  }
  if (message.type !== "QUEUD_CHECKOUT") {
    return false;
  }
  resolveTabId(sender)
    .then((tabId) => runCheckout(message, tabId))
    .then(() => sendResponse({ ok: true }))
    .catch((err) => {
      resolveTabId(sender).then((tabId) => showTabError(tabId, String(err)));
      sendResponse({ ok: false, error: String(err) });
    });
  return true;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  return handleCheckoutMessage(message, sender, sendResponse);
});

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  return handleCheckoutMessage(message, sender, sendResponse);
});

function decodeSession(session) {
  let raw = session;
  try {
    raw = decodeURIComponent(session);
  } catch (_) {
    raw = session;
  }
  const binary = atob(raw);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return JSON.parse(new TextDecoder().decode(bytes));
}

function checkoutFromUrl(url) {
  const parsed = new URL(url);
  const session = parsed.searchParams.get("session");
  const endUrl = parsed.searchParams.get("endUrl");
  if (!session || !endUrl) {
    return null;
  }
  return {
    session,
    endUrl,
    proxy: parsed.searchParams.get("proxy") || "",
  };
}

async function checkoutFromDiscordCarrier(tabId) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const el = document.getElementById("queud-data");
      return el ? el.textContent : null;
    },
  });
  if (!result) {
    return null;
  }
  return JSON.parse(result);
}

async function checkoutFromBasketApi(url) {
  const match = url.match(/^(https?:\/\/[^/?#]+)\/basket\/([0-9a-f-]{36})/i);
  if (!match) {
    return null;
  }
  const apiBase = match[1];
  const basketId = match[2];
  const resp = await fetch(`${apiBase}/basket/${basketId}/session`);
  if (!resp.ok) {
    throw new Error(`basket API ${resp.status}`);
  }
  return resp.json();
}

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete" || !tab.url || processedTabs.has(tabId)) {
    return;
  }

  let checkout = null;
  const url = tab.url;

  try {
    // Basket pages: content script (v1.3.1 HTML) or inline script (v1.3.2+).
    // Do not fetch /session here — it is one-time and failures were silent on old HTML.
    if (url.includes("/checkout.html?")) {
      checkout = checkoutFromUrl(url);
    } else if (url.includes("session=") && url.includes("endUrl=")) {
      checkout = checkoutFromUrl(url);
    } else if (
      (url.includes("cdn.discordapp.com") || url.includes("media.discordapp.net")) &&
      url.includes("queud-")
    ) {
      checkout = await checkoutFromDiscordCarrier(tabId);
    }
  } catch (err) {
    console.error("queud checkout parse failed", err);
    return;
  }

  if (!checkout) {
    return;
  }

  processedTabs.add(tabId);
  try {
    await runCheckout(checkout, tabId);
  } catch (err) {
    processedTabs.delete(tabId);
    console.error("queud checkout failed", err);
    await showTabError(tabId, String(err.message || err));
  }
});

async function runCheckout({ session, endUrl, proxy }, tabId) {
  const payload = decodeSession(session);
  const cookies = payload.cookies || [];
  const targetUrl = decodeURIComponent(endUrl);

  if (proxy) {
    await applyProxy(proxy, targetUrl);
  }

  await setCookies(cookies);

  if (tabId) {
    chrome.tabs.update(tabId, { url: targetUrl });
  } else {
    chrome.tabs.create({ url: targetUrl });
  }
}

async function applyProxy(proxyUrl, targetUrl) {
  const redirect = new URL(targetUrl);
  const domainParts = redirect.hostname.split(".");
  let domain = redirect.hostname;
  if (domainParts.length >= 3) {
    domain = domainParts.slice(-3).join(".");
  }

  const parsed = new URL(proxyUrl);
  proxyUserName = parsed.username;
  proxyPassword = parsed.password;
  const proxyHost = parsed.host;

  const pacScript = `
    function FindProxyForURL(url, host) {
      if (dnsDomainIs(host, "${domain}") || dnsDomainIs(host, ".${domain}")) {
        return "PROXY ${proxyHost}";
      }
      return "DIRECT";
    }
  `;

  await new Promise((resolve, reject) => {
    chrome.proxy.settings.set(
      {
        value: { mode: "pac_script", pacScript: { data: pacScript } },
        scope: "regular",
      },
      () => {
        if (chrome.runtime.lastError) {
          reject(chrome.runtime.lastError);
        } else {
          resolve();
        }
      }
    );
  });
}

async function setCookies(cookieList) {
  const domains = [...new Set(cookieList.map((c) => c.domain).filter(Boolean))];
  for (const domain of domains) {
    await clearDomain(domain);
  }
  let set = 0;
  for (const cookie of cookieList) {
    try {
      const ok = await setCookie(cookie);
      if (ok) {
        set += 1;
      }
    } catch (err) {
      console.warn("queud skip cookie", cookie.name, cookie.domain, err);
    }
  }
  if (set === 0) {
    throw new Error("no cookies could be set — reload extension and retry");
  }
}

function normalizeSameSite(value) {
  if (!value) {
    return undefined;
  }
  const normalized = String(value).toLowerCase();
  if (normalized === "lax" || normalized === "strict" || normalized === "none") {
    return normalized;
  }
  if (normalized === "no_restriction") {
    return "no_restriction";
  }
  return undefined;
}

function setCookie(cookie) {
  const path = cookie.path || "/";
  const rawDomain = String(cookie.domain || "").replace(/\.$/, "");
  const host = rawDomain.replace(/^\./, "");
  if (!host) {
    return Promise.resolve(false);
  }

  const httpOnly = Boolean(cookie.httpOnly ?? cookie.httponly);
  const secure = Boolean(cookie.secure ?? true);
  const sameSite = normalizeSameSite(cookie.sameSite ?? cookie.same_site);
  const details = {
    name: cookie.name,
    value: cookie.value,
    path,
    url: `https://${host}${path.startsWith("/") ? path : `/${path}`}`,
    httpOnly,
    secure,
  };

  if (rawDomain.startsWith(".")) {
    details.domain = rawDomain.startsWith(".") ? rawDomain : `.${host}`;
  }
  if (sameSite) {
    details.sameSite = sameSite;
  }

  return new Promise((resolve) => {
    chrome.cookies.set(details, () => {
      if (chrome.runtime.lastError) {
        console.warn(
          "queud cookie set failed",
          cookie.name,
          details.domain || host,
          chrome.runtime.lastError.message
        );
        resolve(false);
      } else {
        resolve(true);
      }
    });
  });
}

async function showTabError(tabId, message) {
  if (!tabId) {
    return;
  }
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: (msg) => {
        const status =
          document.getElementById("queud-status") ||
          document.querySelector("p") ||
          document.body;
        if (status) {
          status.textContent = msg;
          status.style.color = "#f87171";
        }
      },
      args: [message],
    });
  } catch (err) {
    console.warn("queud could not show tab error", err);
  }
}

function clearDomain(domain) {
  const host = domain.replace(/^\./, "");
  return new Promise((resolve) => {
    chrome.cookies.getAll({ domain: host }, async (existing) => {
      for (const cookie of existing) {
        await new Promise((res) => {
          chrome.cookies.remove(
            {
              url:
                "https://" +
                (cookie.domain || host).replace(/^\./, "") +
                (cookie.path || "/"),
              name: cookie.name,
            },
            () => res()
          );
        });
      }
      resolve();
    });
  });
}