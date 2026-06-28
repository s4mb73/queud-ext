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

function handleCheckoutMessage(message, sender, sendResponse) {
  if (message.type !== "QUEUD_CHECKOUT") {
    return false;
  }
  runCheckout(message, sender.tab?.id)
    .then(() => sendResponse({ ok: true }))
    .catch((err) => sendResponse({ ok: false, error: String(err) }));
  return true;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  return handleCheckoutMessage(message, sender, sendResponse);
});

chrome.runtime.onMessageExternal.addListener((message, sender, sendResponse) => {
  return handleCheckoutMessage(message, sender, sendResponse);
});

function decodeSession(session) {
  const raw = decodeURIComponent(session);
  return JSON.parse(decodeURIComponent(escape(atob(raw))));
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
    if (/\/basket\/[0-9a-f-]{36}/i.test(url)) {
      checkout = await checkoutFromBasketApi(url);
    } else if (url.includes("/checkout.html?")) {
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
  for (const cookie of cookieList) {
    await setCookie(cookie);
  }
}

function setCookie(cookie) {
  const path = cookie.path || "/";
  const host = (cookie.domain || "").replace(/^\./, "").replace(/\.$/, "");
  const details = {
    name: cookie.name,
    value: cookie.value,
    path,
    httpOnly: Boolean(cookie.httponly),
    secure: Boolean(cookie.secure),
  };

  if (cookie.domain && cookie.domain.startsWith(".")) {
    details.url = "https://" + host;
    details.domain = host;
  } else {
    details.url = "https://" + (cookie.domain || host);
  }

  return new Promise((resolve, reject) => {
    chrome.cookies.set(details, (result) => {
      if (chrome.runtime.lastError) {
        reject(chrome.runtime.lastError);
      } else {
        resolve(result);
      }
    });
  });
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