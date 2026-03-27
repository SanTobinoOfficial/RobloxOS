/**
 * RobloxOS Guard – background service worker
 * Zarządza dynamicznymi regułami whitelisty i synchronizuje je z chrome.storage.
 *
 * Statyczne reguły (rules.json) są ładowane automatycznie przez przeglądarkę.
 * Ten worker obsługuje DYNAMICZNE zmiany whitelisty przez admina
 * bez konieczności edycji pliku rules.json i reinstalacji extension.
 *
 * ID dynamicznych reguł: 1000–1999  (statyczne: 1–999)
 */

const DYNAMIC_RULE_ID_BASE = 1000;

// ── Domyślna whitelist (mirror z rules.json, używana jako fallback) ──────────
const DEFAULT_WHITELIST = [
  "roblox.com",
  "discord.com",
  "discordapp.com",
  "discordapp.net",
  "youtube.com",
  "youtu.be",
  "ytimg.com",
  "yt3.ggpht.com",
  "googlevideo.com",
  "googleapis.com",
  "gstatic.com",
];

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Buduje regułę ALLOW dla podanej domeny (i jej subdomen).
 * @param {number} id   - unikalny ID reguły
 * @param {string} domain
 * @returns {chrome.declarativeNetRequest.Rule}
 */
function buildAllowRule(id, domain) {
  return {
    id,
    priority: 10,
    action: { type: "allow" },
    condition: {
      requestDomains: [domain],
      resourceTypes: ["main_frame", "sub_frame"],
    },
  };
}

/**
 * Przelicza tablicę domen na zestaw reguł dynamicznych.
 * @param {string[]} domains
 * @returns {chrome.declarativeNetRequest.Rule[]}
 */
function buildRulesFromDomains(domains) {
  return domains.map((domain, index) =>
    buildAllowRule(DYNAMIC_RULE_ID_BASE + index, domain.toLowerCase().trim())
  );
}

// ── Główna logika sync reguł ──────────────────────────────────────────────────

/**
 * Pobiera aktualną whitelist z chrome.storage.local (lub zwraca default).
 * @returns {Promise<string[]>}
 */
async function getStoredWhitelist() {
  return new Promise((resolve) => {
    chrome.storage.local.get(["whitelist"], (result) => {
      if (chrome.runtime.lastError) {
        console.warn("[RobloxOS Guard] storage.get error:", chrome.runtime.lastError);
        resolve(DEFAULT_WHITELIST);
        return;
      }
      resolve(Array.isArray(result.whitelist) ? result.whitelist : DEFAULT_WHITELIST);
    });
  });
}

/**
 * Usuwa WSZYSTKIE dotychczasowe reguły dynamiczne i zastępuje je nowymi.
 * @param {string[]} domains
 */
async function applyDynamicRules(domains) {
  // Pobierz istniejące dynamiczne reguły żeby znać ich ID do usunięcia
  const existing = await chrome.declarativeNetRequest.getDynamicRules();
  const removeIds = existing.map((r) => r.id);

  const addRules = buildRulesFromDomains(domains);

  await chrome.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: removeIds,
    addRules,
  });

  console.log(
    `[RobloxOS Guard] Zaaplikowano ${addRules.length} dynamicznych reguł` +
    ` (usunięto ${removeIds.length} starych).`
  );
}

// ── Event: instalacja / aktualizacja extension ────────────────────────────────

chrome.runtime.onInstalled.addListener(async (details) => {
  console.log(`[RobloxOS Guard] onInstalled – reason: ${details.reason}`);

  if (details.reason === "install") {
    // Pierwsza instalacja: zapisz domyślną whitelist do storage
    await chrome.storage.local.set({ whitelist: DEFAULT_WHITELIST });
    console.log("[RobloxOS Guard] Zapisano domyślną whitelist do storage.");
  }

  // Przy install i update: zaaplikuj reguły
  const domains = await getStoredWhitelist();
  await applyDynamicRules(domains);
});

// ── Event: zmiana storage (admin edytuje whitelist) ───────────────────────────
//
// Jak admin dodaje domenę (z poziomu roota na systemie):
//   chrome.storage.local.set({ whitelist: [...dotychczasowe, "nowadomena.com"] })
// lub przez devtools extension w trybie deweloperskim.

chrome.storage.onChanged.addListener(async (changes, areaName) => {
  if (areaName !== "local" || !changes.whitelist) return;

  const newWhitelist = changes.whitelist.newValue;
  if (!Array.isArray(newWhitelist)) {
    console.warn("[RobloxOS Guard] storage.whitelist ma nieprawidłowy format – ignoruję.");
    return;
  }

  console.log("[RobloxOS Guard] Whitelist zmieniona przez admina:", newWhitelist);
  await applyDynamicRules(newWhitelist);
});

// ── Event: startup przeglądarki (service worker może być uśpiony) ─────────────

chrome.runtime.onStartup.addListener(async () => {
  console.log("[RobloxOS Guard] onStartup – przywracam reguły dynamiczne.");
  const domains = await getStoredWhitelist();
  await applyDynamicRules(domains);
});
