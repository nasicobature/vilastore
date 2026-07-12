(function () {
  if (window.__VilaStoreOfflineWebInitialized) return;
  window.__VilaStoreOfflineWebInitialized = true;

  const QUEUE_KEY = "vilastore_web_offline_queue_v1";
  const CART_KEY = "vilastore_web_offline_cart_v1";
  const PRODUCTS_KEY = "vilastore_web_products_v1";
  const CUSTOMERS_KEY = "vilastore_web_customers_v1";
  const EXPENSES_KEY = "vilastore_web_expenses_v1";
  const ACTIVITIES_KEY = "vilastore_web_activities_v1";
  const OFFLINE_AUTH_KEY = "vilastore_web_offline_auth_v1";
  const PENDING_LOGIN_KEY = "vilastore_web_pending_login_v1";
  const LAST_SYNC_KEY = "vilastore_web_last_sync_v1";
  const LAST_SYNC_ERROR_KEY = "vilastore_web_last_sync_error_v1";
  const OFFLINE_RECEIPTS_KEY = "vilastore_web_offline_receipts_v1";
  const OFFLINE_CONTROLS_KEY = "vilastore_web_offline_controls_v1";
  const MAX_ACTIVITY_ROWS = 80;
  const OFFLINE_PAGE_URLS = [
    "/index/",
    "/product/",
    "/inventory",
    "/sales-history",
    "/loans",
    "/expenses",
    "/reports",
    "/customer",
    "/settings",
    "/shopboy/dashboard/",
  ];

  function read(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (err) {
      return fallback;
    }
  }

  function write(key, value) {
    localStorage.setItem(key, JSON.stringify(value));
    return value;
  }

  function money(value) {
    const parsed = Number(value || 0);
    return Number.isFinite(parsed) ? parsed.toFixed(2) : "0.00";
  }

  function formatDateTime(value) {
    if (!value) return "Never";
    try {
      return new Date(value).toLocaleString();
    } catch (err) {
      return String(value);
    }
  }

  function nowId(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function simpleHash(value) {
    const text = String(value || "");
    let hash = 5381;
    for (let index = 0; index < text.length; index += 1) {
      hash = (hash * 33) ^ text.charCodeAt(index);
    }
    return (hash >>> 0).toString(16);
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function fieldValue(fields, name, fallback) {
    const found = (fields || []).find(([key]) => key === name);
    return found ? found[1] : fallback;
  }

  function metaValue(name, fallback) {
    const marker = document.querySelector(`meta[name="${name}"]`);
    const value = marker ? marker.getAttribute("content") : "";
    return value === null || value === "" ? fallback : value;
  }

  function numberOrNull(value) {
    if (value === null || value === undefined || value === "") return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  function cookieValue(name) {
    return document.cookie
      .split(";")
      .map((item) => item.trim())
      .filter(Boolean)
      .map((item) => item.split("="))
      .find(([key]) => key === name)?.[1] || "";
  }

  function actionPathFromUrl(action) {
    try {
      return new URL(action, window.location.href).pathname;
    } catch (err) {
      return window.location.pathname;
    }
  }

  function requiresOnline(actionPath) {
    return [
      "/subscription/payment",
      "/marketplace/",
      "marketplace",
      "/api/marketplace/",
      "/logout/",
      "/signup/",
      "/verify",
      "/send-code",
      "/forgot-password",
      "/admin-portal/login",
      "/investor/login",
      "/agent/login",
      "/agent/signup",
    ].some((path) => actionPath.includes(path));
  }

  function normalizeIdentity(value) {
    return String(value || "").trim().toLowerCase();
  }

  function loginIdentityFromFields(fields, actionPath) {
    if (actionPath.includes("/shopboy/login")) {
      return [
        "staff",
        normalizeIdentity(fieldValue(fields, "shop_code", "")),
        normalizeIdentity(fieldValue(fields, "username", "")),
      ].join(":");
    }
    return [
      "owner",
      normalizeIdentity(fieldValue(fields, "email", "")),
      normalizeIdentity(fieldValue(fields, "account_type", "")),
    ].join(":");
  }

  function loginCredentialHash(fields, actionPath) {
    return simpleHash(`${loginIdentityFromFields(fields, actionPath)}:${fieldValue(fields, "password", "")}`);
  }

  function rememberPendingLogin(form, fields) {
    const actionPath = actionPathFromUrl(form.action || window.location.href);
    if (!actionPath.includes("/login/")) return;
    write(PENDING_LOGIN_KEY, {
      login_identity: loginIdentityFromFields(fields, actionPath),
      credential_hash: loginCredentialHash(fields, actionPath),
      display_identity:
        fieldValue(fields, "email", "") ||
        fieldValue(fields, "username", "") ||
        fieldValue(fields, "shop_code", ""),
      created_at: new Date().toISOString(),
    });
  }

  function pendingLoginIsFresh(pending) {
    if (!pending?.created_at) return false;
    const createdAt = new Date(pending.created_at).getTime();
    return Number.isFinite(createdAt) && Date.now() - createdAt <= 15 * 60 * 1000;
  }

  function rememberOfflineSession() {
    const userMarker = document.querySelector('meta[name="vilastore-offline-user"]');
    const emailMarker = document.querySelector('meta[name="vilastore-offline-email"]');
    const identities = [
      userMarker ? userMarker.getAttribute("content") : "",
      emailMarker ? emailMarker.getAttribute("content") : "",
    ].filter(Boolean);
    if (!identities.length) return;
    const existing = getOfflineSession();
    const pending = read(PENDING_LOGIN_KEY, null);
    const pendingIsFresh = pendingLoginIsFresh(pending);
    const canPreserveCredential =
      existing &&
      (existing.identities || [existing.identity]).some((identity) =>
        identities.map(normalizeIdentity).includes(normalizeIdentity(identity))
      );
    const credential = pendingIsFresh
      ? {
          login_identity: pending.login_identity,
          credential_hash: pending.credential_hash,
        }
      : canPreserveCredential
      ? {
          login_identity: existing.login_identity,
          credential_hash: existing.credential_hash,
        }
      : {};
    write(OFFLINE_AUTH_KEY, {
      identity: identities[0],
      identities,
      ...credential,
      saved_at: new Date().toISOString(),
      last_path: window.location.pathname || "/index/",
    });
    localStorage.removeItem(PENDING_LOGIN_KEY);
  }

  function getOfflineSession() {
    return read(OFFLINE_AUTH_KEY, null);
  }

  function restoreOfflineRouteIfNeeded() {
    if (navigator.onLine) return;
    const session = getOfflineSession();
    const lastPath = session && session.last_path ? session.last_path : "";
    if (!lastPath || lastPath === window.location.pathname) return;
    const offlineEntryPaths = new Set(["/", "/home/", "/login/", "/shopboy/login/"]);
    if (!offlineEntryPaths.has(window.location.pathname)) return;
    notify("Offline mode: opening your saved VilaStore dashboard...", true);
    window.setTimeout(() => {
      window.location.replace(lastPath);
    }, 250);
  }

  function handleOfflineLogin(form, fields) {
    const session = getOfflineSession();
    if (!session || !session.identity) {
      notify("Offline login is available only after this browser has logged in successfully online once.", true);
      return true;
    }
    const actionPath = actionPathFromUrl(form.action || window.location.href);
    const enteredIdentity =
      fieldValue(fields, "email", "") ||
      fieldValue(fields, "username", "") ||
      fieldValue(fields, "shop_code", "");
    const savedIdentities = (session.identities || [session.identity]).map(normalizeIdentity).filter(Boolean);
    const normalizedEntered = normalizeIdentity(enteredIdentity);
    const enteredLooksSaved =
      savedIdentities.includes(normalizedEntered) ||
      savedIdentities.some((identity) => identity.includes(normalizedEntered) || normalizedEntered.includes(identity));
    if (normalizedEntered && !enteredLooksSaved) {
      notify(`Offline login is saved for ${session.identity}. Connect to internet to login with another account.`, true);
      return true;
    }
    if (!session.credential_hash || !session.login_identity) {
      notify("Connect once and login online again to activate stronger offline login on this browser.", true);
      return true;
    }
    if (
      session.login_identity !== loginIdentityFromFields(fields, actionPath) ||
      session.credential_hash !== loginCredentialHash(fields, actionPath)
    ) {
      notify("Offline login failed. Use the same username and password you used during your last successful online login.", true);
      return true;
    }
    notify("Offline login accepted on this trusted browser. Opening your saved dashboard...");
    window.setTimeout(() => {
      window.location.href = session.last_path || "/index/";
    }, 600);
    return true;
  }

  function rememberOfflineControls() {
    const hasControls = document.querySelector('meta[name="vilastore-offline-allow-staff-sales"]');
    if (!hasControls) return;
    write(OFFLINE_CONTROLS_KEY, {
      allowStaffOfflineSales: metaValue("vilastore-offline-allow-staff-sales", "true") !== "false",
      staffMaxSaleAmount: numberOrNull(metaValue("vilastore-offline-staff-max-sale", "")),
      staffPin: metaValue("vilastore-offline-staff-pin", ""),
      staffMaxPendingSales: Math.max(1, Number(metaValue("vilastore-offline-staff-max-pending", "20")) || 20),
      warningHours: Math.max(1, Number(metaValue("vilastore-offline-warning-hours", "24")) || 24),
      savedAt: new Date().toISOString(),
    });
  }

  function offlineControls() {
    return read(OFFLINE_CONTROLS_KEY, {
      allowStaffOfflineSales: true,
      staffMaxSaleAmount: null,
      staffPin: "",
      staffMaxPendingSales: 20,
      warningHours: 24,
    });
  }

  function isStaffSalePath(actionPath) {
    return actionPath.includes("/shopboy/cart/checkout/");
  }

  function pendingStaffSalesCount() {
    return getQueue().filter((entry) => isStaffSalePath(actionPathFromUrl(entry.action || ""))).length;
  }

  function oldestPendingAgeHours() {
    const queue = getQueue();
    if (!queue.length) return 0;
    const oldest = queue
      .map((entry) => new Date(entry.created_at || Date.now()).getTime())
      .filter(Number.isFinite)
      .sort((a, b) => a - b)[0];
    if (!oldest) return 0;
    return (Date.now() - oldest) / (1000 * 60 * 60);
  }

  function validateStaffOfflineCheckout(actionPath, saleTotal) {
    if (!isStaffSalePath(actionPath)) return true;
    const controls = offlineControls();
    if (!controls.allowStaffOfflineSales) {
      notify("Staff offline sales are disabled by the shop owner. Connect to internet or ask the owner to allow it.", true);
      return false;
    }
    if (controls.staffMaxSaleAmount !== null && Number(saleTotal || 0) > Number(controls.staffMaxSaleAmount || 0)) {
      notify(`This offline sale is above the staff limit of NGN ${money(controls.staffMaxSaleAmount)}. Connect to internet or ask the owner to raise the limit.`, true);
      return false;
    }
    if (pendingStaffSalesCount() >= Number(controls.staffMaxPendingSales || 20)) {
      notify(`Staff already has ${controls.staffMaxPendingSales} pending offline sale${Number(controls.staffMaxPendingSales) === 1 ? "" : "s"}. Sync before making another sale.`, true);
      return false;
    }
    if (controls.staffPin) {
      const entered = window.prompt("Enter staff offline PIN to complete this sale.");
      if (entered !== controls.staffPin) {
        notify("Incorrect staff offline PIN. Sale was not saved.", true);
        return false;
      }
    }
    return true;
  }

  function rememberActivity(entry) {
    const rows = read(ACTIVITIES_KEY, []);
    rows.unshift({
      id: nowId("activity"),
      created_at: new Date().toISOString(),
      ...entry,
    });
    write(ACTIVITIES_KEY, rows.slice(0, MAX_ACTIVITY_ROWS));
    renderLocalRecords();
    renderOfflineStatus();
  }

  function ensurePanel() {
    let panel = document.getElementById("offlineSyncPanel");
    if (panel) return panel;
    panel = document.createElement("div");
    panel.id = "offlineSyncPanel";
    panel.style.cssText = [
      "position:fixed",
      "left:1rem",
      "right:1rem",
      "bottom:1rem",
      "z-index:99999",
      "display:none",
      "padding:0.8rem 1rem",
      "border-radius:12px",
      "background:#111827",
      "color:#fff",
      "box-shadow:0 16px 40px rgba(15,23,42,.22)",
      "font:500 0.9rem system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
    ].join(";");
    document.body.appendChild(panel);
    return panel;
  }

  function notify(message, hold) {
    const panel = ensurePanel();
    panel.textContent = message;
    panel.style.display = "block";
    if (!hold) {
      clearTimeout(panel._timer);
      panel._timer = setTimeout(updateStatus, 3600);
    }
  }

  function getQueue() {
    return read(QUEUE_KEY, []);
  }

  function setQueue(queue) {
    return write(QUEUE_KEY, queue);
  }

  function enqueue(entry) {
    const queue = getQueue();
    queue.push({
      id: nowId("web-offline"),
      created_at: new Date().toISOString(),
      attempts: 0,
      ...entry,
    });
    setQueue(queue);
    updateStatus();
  }

  function updateStatus() {
    const panel = ensurePanel();
    const pending = getQueue().length;
    renderOfflineStatus();
    if (!navigator.onLine) {
      panel.textContent = pending
        ? `Offline mode: ${pending} pending action${pending === 1 ? "" : "s"} will sync when internet returns.`
        : "Offline mode: sales, inventory and customer records will be saved on this browser.";
      panel.style.display = "block";
      return;
    }
    if (pending) {
      panel.textContent = `${pending} pending action${pending === 1 ? "" : "s"} waiting to sync.`;
      panel.style.display = "block";
      return;
    }
    panel.style.display = "none";
  }

  function queueBreakdown() {
    const rows = getQueue();
    const summary = {
      total: rows.length,
      sales: 0,
      products: 0,
      customers: 0,
      inventory: 0,
      expenses: 0,
      other: 0,
    };
    rows.forEach((entry) => {
      const path = actionPathFromUrl(entry.action || "");
      if (path.includes("/checkout/")) summary.sales += 1;
      else if (path.includes("/add_product") || path.includes("/add-product") || path.includes("/edit-product/") || path.includes("/delete-product/")) summary.products += 1;
      else if (path.includes("/adjust-stock/")) summary.inventory += 1;
      else if (path.includes("/add-customer/") || path.includes("/edit-customer/") || path.includes("/delete-customer/")) summary.customers += 1;
      else if (path.replace(/\/$/, "").endsWith("/expenses")) summary.expenses += 1;
      else summary.other += 1;
    });
    return summary;
  }

  function localRecordCounts() {
    return {
      cart: getCart().items.length,
      customers: read(CUSTOMERS_KEY, []).length,
      expenses: read(EXPENSES_KEY, []).length,
      activities: read(ACTIVITIES_KEY, []).length,
      products: Object.values(read(PRODUCTS_KEY, {})).filter((item, index, rows) => {
        if (!item || !item.id) return false;
        return rows.findIndex((candidate) => candidate && String(candidate.id) === String(item.id)) === index;
      }).length,
    };
  }

  function receiptDateCode(date) {
    const d = date ? new Date(date) : new Date();
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
  }

  function nextOfflineReceiptNumber() {
    const todayCode = receiptDateCode();
    const receipts = read(OFFLINE_RECEIPTS_KEY, []);
    const todayCount = receipts.filter((receipt) => String(receipt.receipt_no || "").includes(`OFF-${todayCode}-`)).length + 1;
    return `OFF-${todayCode}-${String(todayCount).padStart(3, "0")}`;
  }

  function saveOfflineReceipt(fields) {
    const cart = getCart();
    const receipt = {
      id: nowId("offline-receipt"),
      receipt_no: nextOfflineReceiptNumber(),
      created_at: new Date().toISOString(),
      customer_name: fieldValue(fields, "customer_name", "Walk-in customer") || "Walk-in customer",
      payment_status: fieldValue(fields, "payment_status", "paid"),
      initial_payment: money(fieldValue(fields, "initial_payment", 0)),
      total: cart.total,
      items: cart.items || [],
      sync_status: "Pending sync",
    };
    const receipts = read(OFFLINE_RECEIPTS_KEY, []);
    receipts.unshift(receipt);
    write(OFFLINE_RECEIPTS_KEY, receipts.slice(0, 50));
    return receipt;
  }

  function markPendingReceiptsSynced() {
    const receipts = read(OFFLINE_RECEIPTS_KEY, []);
    write(
      OFFLINE_RECEIPTS_KEY,
      receipts.map((receipt) =>
        receipt.sync_status === "Pending sync"
          ? { ...receipt, sync_status: "Synced", synced_at: new Date().toISOString() }
          : receipt
      )
    );
  }

  function receiptHtml(receipt, printReady) {
    const rows = (receipt.items || [])
      .map(
        (item) => `
          <tr>
            <td>${escapeHtml(item.name)}</td>
            <td style="text-align:center;">${escapeHtml(item.quantity)}</td>
            <td style="text-align:right;">NGN ${escapeHtml(item.price)}</td>
            <td style="text-align:right;">NGN ${money(Number(item.price || 0) * Number(item.quantity || 0))}</td>
          </tr>
        `
      )
      .join("");
    return `
      <!doctype html>
      <html>
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>${escapeHtml(receipt.receipt_no)}</title>
        <style>
          body{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f8fafc;color:#111827;margin:0;padding:1rem}
          main{max-width:720px;margin:0 auto;background:#fff;border:1px solid #e5e7eb;border-radius:14px;padding:1.25rem}
          h1{margin:0;font-size:1.4rem}.muted{color:#64748b;font-size:.9rem}
          .top{display:flex;justify-content:space-between;gap:1rem;flex-wrap:wrap;border-bottom:1px solid #e5e7eb;padding-bottom:1rem;margin-bottom:1rem}
          table{width:100%;border-collapse:collapse;margin-top:1rem}th,td{border-bottom:1px solid #e5e7eb;padding:.7rem;text-align:left;font-size:.92rem}
          th{background:#f8fafc;color:#475569;font-size:.78rem;text-transform:uppercase}.total{display:flex;justify-content:flex-end;margin-top:1rem;font-size:1.2rem;font-weight:800}
          .badge{display:inline-block;border-radius:999px;background:#fef3c7;color:#92400e;padding:.25rem .55rem;font-size:.75rem;font-weight:800}
          .actions{margin-top:1rem;display:flex;gap:.5rem;justify-content:flex-end}button{border:0;border-radius:10px;background:#111827;color:#fff;padding:.75rem 1rem;font-weight:800;cursor:pointer}
          @media print{@page{size:80mm auto;margin:4mm}body{background:#fff;padding:0;width:80mm}.actions{display:none}main{border:0;border-radius:0;max-width:80mm;padding:0}th,td{font-size:.75rem;padding:.45rem .2rem}.muted{font-size:.75rem}}
        </style>
      </head>
      <body>
        <main>
          <div class="top">
            <div><h1>VilaStore Offline Receipt</h1><div class="muted">Temporary receipt. It will be confirmed after cloud sync.</div></div>
            <div style="text-align:right;"><strong>${escapeHtml(receipt.receipt_no)}</strong><br><span class="badge">${escapeHtml(receipt.sync_status)}</span></div>
          </div>
          <div class="muted">Date: ${escapeHtml(formatDateTime(receipt.created_at))}</div>
          <div class="muted">Customer: ${escapeHtml(receipt.customer_name)}</div>
          <div class="muted">Payment: ${escapeHtml(receipt.payment_status)}</div>
          <table>
            <thead><tr><th>Product</th><th style="text-align:center;">Qty</th><th style="text-align:right;">Price</th><th style="text-align:right;">Total</th></tr></thead>
            <tbody>${rows || `<tr><td colspan="4">No items recorded.</td></tr>`}</tbody>
          </table>
          <div class="total">Total: NGN ${escapeHtml(receipt.total)}</div>
          <div class="actions"><button onclick="window.print()">Print Receipt</button></div>
        </main>
        ${printReady ? "<script>window.addEventListener('load',function(){setTimeout(function(){window.focus();window.print()},300)})</script>" : ""}
      </body>
      </html>
    `;
  }

  function printReceiptInFrame(receipt) {
    let frame = document.getElementById("offlineReceiptPrintFrame");
    if (!frame) {
      frame = document.createElement("iframe");
      frame.id = "offlineReceiptPrintFrame";
      frame.title = "Offline receipt print";
      frame.style.cssText = "position:fixed;right:0;bottom:0;width:0;height:0;border:0;opacity:0;pointer-events:none;";
      document.body.appendChild(frame);
    }
    const doc = frame.contentWindow?.document;
    if (!doc) {
      notify("Unable to open printer. Use Offline Status > Receipts > Print.", true);
      return;
    }
    doc.open();
    doc.write(receiptHtml(receipt, false));
    doc.close();
    window.setTimeout(() => {
      try {
        frame.contentWindow.focus();
        frame.contentWindow.print();
      } catch (err) {
        notify("Unable to open printer. Use Offline Status > Receipts > Print.", true);
      }
    }, 350);
  }

  function openOfflineReceipt(receiptId, printReady) {
    const receipt = read(OFFLINE_RECEIPTS_KEY, []).find((item) => item.id === receiptId || item.receipt_no === receiptId);
    if (!receipt) {
      notify("Offline receipt not found.", true);
      return;
    }
    const popup = window.open("", "_blank", "noopener,noreferrer,width=780,height=900");
    if (!popup) {
      if (printReady) {
        printReceiptInFrame(receipt);
        return;
      }
      notify("Allow popups to view this offline receipt, or use the receipt Print button.", true);
      return;
    }
    popup.document.open();
    popup.document.write(receiptHtml(receipt, printReady));
    popup.document.close();
  }

  function ensureStatusWidget() {
    let button = document.getElementById("offlineStatusButton");
    if (!button) {
      button = document.createElement("button");
      button.id = "offlineStatusButton";
      button.type = "button";
      button.style.cssText = [
        "position:fixed",
        "right:1rem",
        "bottom:1rem",
        "z-index:99998",
        "border:0",
        "border-radius:999px",
        "padding:0.75rem 1rem",
        "background:#111827",
        "color:#fff",
        "box-shadow:0 16px 40px rgba(15,23,42,.2)",
        "font:700 0.85rem system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
        "cursor:pointer",
      ].join(";");
      button.addEventListener("click", function () {
        const drawer = ensureStatusDrawer();
        drawer.style.display = drawer.style.display === "block" ? "none" : "block";
        renderOfflineStatus();
      });
      document.body.appendChild(button);
    }
    return button;
  }

  function ensureStatusDrawer() {
    let drawer = document.getElementById("offlineStatusDrawer");
    if (drawer) return drawer;
    drawer = document.createElement("section");
    drawer.id = "offlineStatusDrawer";
    drawer.style.cssText = [
      "position:fixed",
      "right:1rem",
      "bottom:4.7rem",
      "z-index:99998",
      "display:none",
      "width:min(420px,calc(100vw - 2rem))",
      "max-height:min(680px,calc(100vh - 6rem))",
      "overflow:auto",
      "border:1px solid #e5e7eb",
      "border-radius:14px",
      "background:#fff",
      "box-shadow:0 24px 70px rgba(15,23,42,.24)",
      "color:#111827",
      "font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif",
    ].join(";");
    drawer.innerHTML = `
      <div style="padding:1rem;border-bottom:1px solid #e5e7eb;display:flex;align-items:center;justify-content:space-between;gap:1rem;">
        <div>
          <div style="font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;color:#64748b;font-weight:800;">VilaStore Sync</div>
          <h3 style="margin:.15rem 0 0;font-size:1.05rem;">Offline Status</h3>
        </div>
        <button type="button" data-offline-close style="border:0;background:#f1f5f9;border-radius:8px;padding:.45rem .65rem;cursor:pointer;">Close</button>
      </div>
      <div id="offlineStatusBody" style="padding:1rem;display:grid;gap:.75rem;"></div>
    `;
    drawer.querySelector("[data-offline-close]").addEventListener("click", function () {
      drawer.style.display = "none";
    });
    document.body.appendChild(drawer);
    return drawer;
  }

  function statusCard(label, value, detail) {
    return `
      <div style="border:1px solid #e5e7eb;border-radius:12px;padding:.8rem;background:#f8fafc;">
        <div style="font-size:.75rem;color:#64748b;font-weight:700;">${label}</div>
        <div style="font-size:1.05rem;font-weight:800;margin-top:.15rem;">${value}</div>
        ${detail ? `<div style="font-size:.78rem;color:#64748b;margin-top:.25rem;">${detail}</div>` : ""}
      </div>
    `;
  }

  function renderOfflineStatus() {
    const button = document.getElementById("offlineStatusButton");
    const drawer = document.getElementById("offlineStatusDrawer");
    if (!button && !drawer) return;

    const pending = queueBreakdown();
    const counts = localRecordCounts();
    const receipts = read(OFFLINE_RECEIPTS_KEY, []);
    const lastSync = read(LAST_SYNC_KEY, "");
    const lastError = read(LAST_SYNC_ERROR_KEY, "");
    const controls = offlineControls();
    const staleHours = oldestPendingAgeHours();
    const isStale = pending.total > 0 && staleHours >= Number(controls.warningHours || 24);
    const online = navigator.onLine;
    const buttonText = online
      ? pending.total
        ? `Sync Pending (${pending.total})`
        : "Online"
      : pending.total
      ? `Offline (${pending.total})`
      : "Offline";
    if (button) {
      button.textContent = buttonText;
      button.style.background = online ? (pending.total ? "#92400e" : "#166534") : "#991b1b";
    }

    const body = document.getElementById("offlineStatusBody");
    if (!body) return;
    body.innerHTML = `
      ${statusCard("Connection", online ? "Online" : "Offline", online ? "Pending data can sync now." : "New actions will be saved on this browser.")}
      ${statusCard("Pending Sync", String(pending.total), "Sales, products, customers, stock and expenses waiting for cloud sync.")}
      ${isStale ? statusCard("Sync Warning", `${Math.floor(staleHours)} hours old`, "Some offline data has stayed too long on this browser. Sync as soon as internet is available.") : ""}
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.6rem;">
        ${statusCard("Sales", String(pending.sales))}
        ${statusCard("Products", String(pending.products))}
        ${statusCard("Customers", String(pending.customers))}
        ${statusCard("Inventory", String(pending.inventory))}
        ${statusCard("Expenses", String(pending.expenses))}
        ${statusCard("Other", String(pending.other))}
      </div>
      ${statusCard("Local Records", `${counts.products} products cached`, `${counts.cart} cart items, ${counts.customers} local customers, ${counts.expenses} local expenses, ${counts.activities} recent activities.`)}
      ${statusCard(
        "Staff Offline Rules",
        controls.allowStaffOfflineSales ? "Allowed" : "Blocked",
        `Limit: ${controls.staffMaxSaleAmount === null ? "No amount limit" : `NGN ${money(controls.staffMaxSaleAmount)}`} - Pending sales max: ${controls.staffMaxPendingSales || 20} - PIN: ${controls.staffPin ? "Required" : "Not required"}`
      )}
      ${statusCard("Last Successful Sync", formatDateTime(lastSync))}
      ${lastError ? statusCard("Last Sync Error", lastError) : ""}
      ${
        receipts.length
          ? `<div style="border:1px solid #e5e7eb;border-radius:12px;padding:.8rem;background:#fff;">
              <div style="font-size:.75rem;color:#64748b;font-weight:800;margin-bottom:.5rem;">Offline Receipts</div>
              ${receipts
                .slice(0, 5)
                .map(
                  (receipt) => `
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:.6rem;padding:.5rem 0;border-top:1px solid #f1f5f9;">
                      <div>
                        <strong>${escapeHtml(receipt.receipt_no)}</strong>
                        <div style="font-size:.78rem;color:#64748b;">NGN ${escapeHtml(receipt.total)} - ${escapeHtml(receipt.sync_status)}</div>
                      </div>
                      <div style="display:flex;gap:.35rem;">
                        <button type="button" data-offline-view-receipt="${escapeHtml(receipt.id)}" style="border:1px solid #e5e7eb;border-radius:8px;background:#fff;color:#111827;padding:.45rem .6rem;font-weight:800;cursor:pointer;">View</button>
                        <button type="button" data-offline-print-receipt="${escapeHtml(receipt.id)}" style="border:0;border-radius:8px;background:#111827;color:#fff;padding:.45rem .6rem;font-weight:800;cursor:pointer;">Print</button>
                      </div>
                    </div>
                  `
                )
                .join("")}
            </div>`
          : ""
      }
      <div style="display:flex;gap:.5rem;flex-wrap:wrap;">
        <button type="button" data-offline-sync-now style="border:0;border-radius:10px;background:#111827;color:#fff;padding:.75rem 1rem;font-weight:800;cursor:pointer;">Sync Now</button>
        <button type="button" data-offline-refresh-status style="border:1px solid #e5e7eb;border-radius:10px;background:#fff;color:#111827;padding:.75rem 1rem;font-weight:800;cursor:pointer;">Refresh</button>
      </div>
      <div style="font-size:.78rem;color:#64748b;line-height:1.45;">
        Payment gateway, subscription verification, marketplace updates, cloud backup and multi-device sync still require internet.
      </div>
    `;
    body.querySelector("[data-offline-sync-now]")?.addEventListener("click", flushQueue);
    body.querySelector("[data-offline-refresh-status]")?.addEventListener("click", renderOfflineStatus);
    body.querySelectorAll("[data-offline-view-receipt]").forEach((button) => {
      button.addEventListener("click", () => openOfflineReceipt(button.dataset.offlineViewReceipt, false));
    });
    body.querySelectorAll("[data-offline-print-receipt]").forEach((button) => {
      button.addEventListener("click", () => openOfflineReceipt(button.dataset.offlinePrintReceipt, true));
    });
  }

  function formFields(form, submitter) {
    let formData;
    try {
      formData = submitter ? new FormData(form, submitter) : new FormData(form);
    } catch (err) {
      formData = new FormData(form);
      if (submitter && submitter.name) {
        formData.append(submitter.name, submitter.value || "");
      }
    }
    const fields = [];
    let hasFile = false;
    formData.forEach((value, key) => {
      if (value instanceof File) {
        if (value.name) hasFile = true;
        return;
      }
      fields.push([key, String(value)]);
    });
    return { fields, hasFile };
  }

  function postQueued(entry) {
    const formData = new FormData();
    (entry.fields || []).forEach(([key, value]) => formData.append(key, value));
    const csrfToken = fieldValue(entry.fields || [], "csrfmiddlewaretoken", "") || decodeURIComponent(cookieValue("csrftoken"));
    if (csrfToken && !fieldValue(entry.fields || [], "csrfmiddlewaretoken", "")) {
      formData.append("csrfmiddlewaretoken", csrfToken);
    }
    return fetch(entry.action, {
      method: entry.method || "POST",
      body: formData,
      credentials: "same-origin",
      headers: {
        "X-Offline-Sync": "1",
        ...(csrfToken ? { "X-CSRFToken": csrfToken } : {}),
      },
    });
  }

  async function flushQueue() {
    if (!navigator.onLine) {
      updateStatus();
      return;
    }
    const queue = getQueue();
    if (!queue.length) {
      updateStatus();
      return;
    }
    const remaining = [];
    let synced = 0;
    for (const entry of queue) {
      try {
        const response = await postQueued(entry);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        synced += 1;
      } catch (err) {
        remaining.push({ ...entry, attempts: Number(entry.attempts || 0) + 1, last_error: err.message });
      }
    }
    setQueue(remaining);
    if (synced) {
      write(LAST_SYNC_KEY, new Date().toISOString());
      write(LAST_SYNC_ERROR_KEY, "");
      if (!remaining.length) {
        markPendingReceiptsSynced();
        write(CUSTOMERS_KEY, []);
        write(EXPENSES_KEY, []);
        write(ACTIVITIES_KEY, []);
        renderLocalRecords();
      }
      notify(`${synced} offline action${synced === 1 ? "" : "s"} synced successfully.`);
    }
    if (remaining.length) {
      write(LAST_SYNC_ERROR_KEY, remaining[0].last_error || "Some items could not sync yet.");
    }
    updateStatus();
  }

  setInterval(flushQueue, 30000);

  function cacheProductsFromPage() {
    const current = read(PRODUCTS_KEY, {});
    document.querySelectorAll("[data-offline-product]").forEach((el) => {
      const product = {
        id: el.dataset.productId || "",
        name: el.dataset.productName || "Product",
        code: el.dataset.productCode || "",
        price: money(el.dataset.productPrice),
        stock: Number(el.dataset.productStock || 0),
      };
      if (product.id) current[`id:${product.id}`] = product;
      if (product.code) current[`code:${product.code.toLowerCase()}`] = product;
    });
    write(PRODUCTS_KEY, current);
  }

  function findProduct(ref, byCode) {
    const products = read(PRODUCTS_KEY, {});
    const key = byCode ? `code:${String(ref || "").toLowerCase()}` : `id:${ref}`;
    return products[key] || null;
  }

  function getCart() {
    return read(CART_KEY, { items: [], total: "0.00" });
  }

  function setCart(cart) {
    cart.total = money((cart.items || []).reduce((sum, item) => sum + Number(item.price || 0) * Number(item.quantity || 0), 0));
    return write(CART_KEY, cart);
  }

  function seedCartFromServer() {
    const existing = getCart();
    if (existing.items && existing.items.length) return;
    const items = [];
    document.querySelectorAll("[data-offline-cart-item]").forEach((el) => {
      items.push({
        product_id: el.dataset.productId,
        name: el.dataset.productName || "Product",
        price: money(el.dataset.productPrice),
        quantity: Number(el.dataset.productQuantity || 1),
      });
    });
    if (items.length) setCart({ items });
  }

  function renderCart() {
    const host = document.getElementById("offlineCartMirror");
    if (!host) return;
    const cart = getCart();
    if (!cart.items.length) {
      host.innerHTML = "";
      if (window.VilaStoreCart && typeof window.VilaStoreCart.sync === "function") {
        window.VilaStoreCart.sync(0);
      }
      return;
    }
    const checkoutPath = window.location.pathname.includes("/shopboy/") ? "/shopboy/cart/checkout/" : "/checkout/";
    const csrfToken = decodeURIComponent(cookieValue("csrftoken") || "");
    host.innerHTML = `
      <div class="card" style="padding:0.75rem 1rem;margin-bottom:0.75rem;border:1px dashed var(--border);">
        <strong>Offline cart</strong>
        <p style="margin:0.25rem 0;color:var(--muted-foreground);font-size:0.85rem;">This cart is saved on this browser and will sync when internet returns.</p>
        <ul style="padding-left:1.1rem;margin:0.5rem 0;">
          ${cart.items
            .map(
              (item) =>
                `<li data-offline-cart-row data-product-quantity="${escapeHtml(item.quantity)}">${item.name} - ${item.quantity} x NGN ${item.price}</li>`
            )
            .join("")}
        </ul>
        <strong>Total: NGN ${cart.total}</strong>
        <form method="POST" action="${checkoutPath}" data-offline-local-checkout="true" style="margin-top:0.75rem;display:flex;flex-direction:column;gap:0.5rem;">
          ${csrfToken ? `<input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">` : ""}
          <select name="payment_status" class="input">
            <option value="paid">Paid</option>
            <option value="loan">Credit</option>
          </select>
          <input type="text" name="customer_name" class="input" placeholder="Customer full name (optional)">
          <input type="number" name="initial_payment" min="0" step="0.01" class="input" placeholder="Initial payment for credit sale">
          <button type="submit" class="btn btn-primary">Complete Offline Sale</button>
        </form>
      </div>
    `;
    if (window.VilaStoreCart && typeof window.VilaStoreCart.sync === "function") {
      window.VilaStoreCart.sync(
        (cart.items || []).reduce((sum, item) => sum + Number(item.quantity || 0), 0)
      );
    }
  }

  function addToOfflineCart(product, quantity) {
    const cart = getCart();
    const qty = Math.max(0.01, Number(quantity || 1));
    const items = [...(cart.items || [])];
    const index = items.findIndex((item) => String(item.product_id) === String(product.id));
    if (index >= 0) {
      items[index].quantity = Number(items[index].quantity || 0) + qty;
    } else {
      items.push({
        product_id: product.id,
        name: product.name,
        price: money(product.price),
        quantity: qty,
      });
    }
    setCart({ items });
    updateLocalProductStock(product.id, -qty);
    renderCart();
  }

  function updateOfflineCart(productId, action, quantity) {
    const cart = getCart();
    let items = [...(cart.items || [])];
    if (action === "remove") {
      items = items.filter((item) => String(item.product_id) !== String(productId));
    } else {
      items = items
        .map((item) => {
          if (String(item.product_id) !== String(productId)) return item;
          const current = Number(item.quantity || 0);
          const next =
            action === "increase" ? current + 1 : action === "decrease" ? current - 1 : Number(quantity || current);
          return { ...item, quantity: next };
        })
        .filter((item) => Number(item.quantity || 0) > 0);
    }
    setCart({ items });
    renderCart();
  }

  function updateLocalProductStock(productId, adjustment) {
    if (!productId) return;
    const products = read(PRODUCTS_KEY, {});
    Object.keys(products).forEach((key) => {
      const product = products[key];
      if (String(product.id) === String(productId)) {
        product.stock = Math.max(0, Number(product.stock || 0) + Number(adjustment || 0));
      }
    });
    write(PRODUCTS_KEY, products);
  }

  function upsertLocalProduct(fields, actionPath) {
    const idMatch = actionPath.match(/edit-product\/(\d+)/);
    const id = idMatch ? idMatch[1] : nowId("local-product");
    const product = {
      id,
      name: fieldValue(fields, "name", "Product"),
      code: fieldValue(fields, "code", ""),
      price: money(fieldValue(fields, "selling_price", 0)),
      stock: Number(fieldValue(fields, "stock", 0)),
      cost_price: money(fieldValue(fields, "cost_price", 0)),
      category: fieldValue(fields, "category", ""),
      offline: true,
    };
    const products = read(PRODUCTS_KEY, {});
    products[`id:${id}`] = product;
    if (product.code) products[`code:${String(product.code).toLowerCase()}`] = product;
    write(PRODUCTS_KEY, products);
    rememberActivity({ kind: "Product", label: product.name, detail: `Saved locally. Stock: ${product.stock}` });
  }

  function removeLocalProduct(actionPath) {
    const id = (actionPath.match(/delete-product\/(\d+)/) || [])[1];
    if (!id) return;
    const products = read(PRODUCTS_KEY, {});
    Object.keys(products).forEach((key) => {
      if (String(products[key].id) === String(id)) delete products[key];
    });
    write(PRODUCTS_KEY, products);
    rememberActivity({ kind: "Product", label: `Product #${id}`, detail: "Deleted locally." });
  }

  function adjustLocalProduct(fields, actionPath) {
    const id = (actionPath.match(/adjust-stock\/(\d+)/) || [])[1];
    const adjustment = Number(fieldValue(fields, "adjustment", 0));
    updateLocalProductStock(id, adjustment);
    rememberActivity({ kind: "Inventory", label: `Product #${id}`, detail: `Stock adjusted by ${adjustment}.` });
  }

  function upsertLocalCustomer(fields, actionPath) {
    const id = (actionPath.match(/edit-customer\/(\d+)/) || [])[1] || nowId("local-customer");
    const customer = {
      id,
      first_name: fieldValue(fields, "first_name", ""),
      last_name: fieldValue(fields, "last_name", ""),
      phone: fieldValue(fields, "phone", ""),
      email: fieldValue(fields, "email", ""),
      birthday: fieldValue(fields, "birthday", ""),
      religion: fieldValue(fields, "religion", ""),
      tribe: fieldValue(fields, "tribe", ""),
      offline: true,
    };
    const customers = read(CUSTOMERS_KEY, []);
    const next = customers.filter((item) => String(item.id) !== String(id));
    next.unshift(customer);
    write(CUSTOMERS_KEY, next);
    rememberActivity({
      kind: "Customer",
      label: `${customer.first_name} ${customer.last_name}`.trim() || customer.phone || "Customer",
      detail: "Saved locally.",
    });
  }

  function removeLocalCustomer(actionPath) {
    const id = (actionPath.match(/delete-customer\/(\d+)/) || [])[1];
    if (!id) return;
    write(CUSTOMERS_KEY, read(CUSTOMERS_KEY, []).filter((item) => String(item.id) !== String(id)));
    rememberActivity({ kind: "Customer", label: `Customer #${id}`, detail: "Deleted locally." });
  }

  function addLocalExpense(fields) {
    const expense = {
      id: nowId("local-expense"),
      date: fieldValue(fields, "date", new Date().toISOString().slice(0, 10)),
      branch_id: fieldValue(fields, "branch_id", ""),
      category: fieldValue(fields, "category", "Other"),
      title: fieldValue(fields, "title", ""),
      amount: money(fieldValue(fields, "amount", 0)),
      offline: true,
    };
    const expenses = read(EXPENSES_KEY, []);
    expenses.unshift(expense);
    write(EXPENSES_KEY, expenses);
    rememberActivity({ kind: "Expense", label: expense.category, detail: `NGN ${expense.amount} saved locally.` });
  }

  function renderLocalRecords() {
    const customers = read(CUSTOMERS_KEY, []);
    const expenses = read(EXPENSES_KEY, []);
    const activities = read(ACTIVITIES_KEY, []);

    const customerTable = document.querySelector('form[action$="/add-customer/"], form[action*="/edit-customer/"]')?.closest("main")?.querySelector("tbody");
    if (customerTable && customers.length) {
      customers.slice().reverse().forEach((customer) => {
        if (document.querySelector(`[data-offline-customer-id="${customer.id}"]`)) return;
        const row = document.createElement("tr");
        row.dataset.offlineCustomerId = customer.id;
        row.innerHTML = `
          <td data-label="Name"><strong>${customer.first_name || ""} ${customer.last_name || ""}</strong> <span class="badge badge-warning">Offline</span></td>
          <td data-label="Phone">${customer.phone || "-"}</td>
          <td data-label="Email">${customer.email || "-"}</td>
          <td data-label="Birthday">${customer.birthday || "-"}</td>
          <td data-label="Religion">${customer.religion || "-"}</td>
          <td data-label="Tribe">${customer.tribe || "-"}</td>
          <td data-label="Actions">Pending sync</td>
        `;
        customerTable.prepend(row);
      });
    }

    const expenseForm = document.querySelector('form[action$="/expenses"], form[action$="/expenses/"]');
    const expenseTable = expenseForm?.closest("main")?.querySelector("tbody");
    if (expenseTable && expenses.length) {
      expenses.slice().reverse().forEach((expense) => {
        if (document.querySelector(`[data-offline-expense-id="${expense.id}"]`)) return;
        const row = document.createElement("tr");
        row.dataset.offlineExpenseId = expense.id;
        row.innerHTML = `
          <td>${expense.date}</td>
          <td>Pending sync</td>
          <td>${expense.category}</td>
          <td>${expense.title} <span class="badge badge-warning">Offline</span></td>
          <td>NGN ${expense.amount}</td>
        `;
        expenseTable.prepend(row);
      });
    }

    const host = document.getElementById("offlineActivityMirror") || document.querySelector("[data-offline-activity-host]");
    if (host && activities.length) {
      host.innerHTML = activities
        .slice(0, 12)
        .map(
          (item) => `
            <div class="card" style="padding:0.75rem 1rem;margin-bottom:0.5rem;border:1px dashed var(--border);">
              <strong>${item.kind}: ${item.label || "Pending action"}</strong>
              <div style="color:var(--muted-foreground);font-size:0.85rem;">${item.detail || "Saved locally."}</div>
            </div>
          `
        )
        .join("");
    }
  }

  function handleOfflineForm(form, submitter) {
    const method = (form.method || "GET").toUpperCase();
    if (method !== "POST") return false;
    const action = form.action || window.location.href;
    const { fields, hasFile } = formFields(form, submitter);
    const actionPath = actionPathFromUrl(action);

    if (requiresOnline(actionPath)) {
      notify("This action needs internet. Connect and try again.", true);
      return true;
    }

    if (actionPath.includes("/login/")) {
      return handleOfflineLogin(form, fields);
    }

    if (hasFile) {
      notify("Image upload needs internet. The text fields were saved offline; upload the image after sync.", true);
    }

    if (actionPath.includes("/add-to-cart/") || actionPath.includes("/cart/add/")) {
      const isCode = actionPath.includes("/by-code/") || actionPath.includes("/add-by-code/");
      const product = isCode
        ? findProduct(fields.find(([key]) => key === "code")?.[1], true)
        : findProduct((actionPath.match(/(?:add-to-cart|cart\/add)\/(\d+)/) || [])[1], false);
      if (!product) {
        notify("This product code is not saved offline yet. Open inventory/products online once, then scan again.");
        return true;
      }
      addToOfflineCart(product, fields.find(([key]) => key === "quantity")?.[1] || 1);
    } else if (actionPath.includes("/update-cart/") || actionPath.includes("/cart/update/")) {
      const productId = (actionPath.match(/(?:update-cart|cart\/update)\/([^/]+)/) || [])[1];
      updateOfflineCart(productId, fields.find(([key]) => key === "action")?.[1], fields.find(([key]) => key === "quantity")?.[1]);
    } else if (actionPath.includes("/remove-from-cart/") || actionPath.includes("/cart/remove/")) {
      const productId = (actionPath.match(/(?:remove-from-cart|cart\/remove)\/([^/]+)/) || [])[1];
      updateOfflineCart(productId, "remove");
    } else if (actionPath.includes("/checkout/")) {
      const currentTotal = getCart().total;
      if (!validateStaffOfflineCheckout(actionPath, currentTotal)) {
        return true;
      }
      const receipt = saveOfflineReceipt(fields);
      const saleTotal = receipt.total;
      write(CART_KEY, { items: [], total: "0.00" });
      renderCart();
      rememberActivity({ kind: "Sale", label: `${receipt.receipt_no} - NGN ${saleTotal}`, detail: "Offline receipt generated and waiting to sync." });
      notify(`Offline receipt ${receipt.receipt_no} generated. Printing now. It will sync when internet returns.`, true);
      openOfflineReceipt(receipt.id, true);
    } else if (actionPath.includes("/add_product") || actionPath.includes("/add-product") || actionPath.includes("/edit-product/")) {
      upsertLocalProduct(fields, actionPath);
      notify("Product saved offline. It will sync when internet returns.");
    } else if (actionPath.includes("/delete-product/")) {
      removeLocalProduct(actionPath);
      notify("Product deletion saved offline. It will sync when internet returns.");
    } else if (actionPath.includes("/adjust-stock/")) {
      adjustLocalProduct(fields, actionPath);
      notify("Stock change saved offline. It will sync when internet returns.");
    } else if (actionPath.includes("/add-customer/") || actionPath.includes("/edit-customer/")) {
      upsertLocalCustomer(fields, actionPath);
      notify("Customer saved offline. It will sync when internet returns.");
    } else if (actionPath.includes("/delete-customer/")) {
      removeLocalCustomer(actionPath);
      notify("Customer deletion saved offline. It will sync when internet returns.");
    } else if (actionPath.replace(/\/$/, "").endsWith("/expenses")) {
      addLocalExpense(fields);
      notify("Expense saved offline. It will sync when internet returns.");
    } else {
      rememberActivity({ kind: "Action", label: form.dataset.offlineLabel || document.title || "VilaStore", detail: "Saved offline and waiting to sync." });
      notify("Saved offline. VilaStore will sync this when internet returns.");
    }

    enqueue({ action, method, fields });
    renderOfflineStatus();
    return true;
  }

  function bindForms() {
    document.addEventListener("submit", function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (form.dataset.offlineIgnore === "true") return;
      if (form.dataset.offlineLocalCheckout === "true") {
        event.preventDefault();
        handleOfflineForm(form, event.submitter);
        return;
      }
      if (navigator.onLine) {
        const { fields } = formFields(form, event.submitter);
        rememberPendingLogin(form, fields);
        return;
      }
      if (handleOfflineForm(form, event.submitter)) {
        event.preventDefault();
      }
    });
  }

  function warmOfflinePages() {
    if (!navigator.onLine) return;
    if (!("serviceWorker" in navigator)) return;
    const currentPath = window.location.pathname;
    if (
      currentPath.includes("/login") ||
      currentPath.includes("/signup") ||
      currentPath.includes("/marketplace") ||
      currentPath.includes("/subscription/payment")
    ) {
      return;
    }
    OFFLINE_PAGE_URLS.forEach((url, index) => {
      window.setTimeout(() => {
        fetch(url, {
          credentials: "same-origin",
          cache: "reload",
          headers: { "X-Offline-Warmup": "1" },
        }).catch(() => {});
      }, 800 + index * 350);
    });
  }

  window.VilaStoreOffline = {
    findProductByCode(code) {
      return findProduct(code, true);
    },
    flushQueue,
    pendingCount() {
      return getQueue().length;
    },
  };

  document.addEventListener("DOMContentLoaded", function () {
    ensureStatusWidget();
    ensureStatusDrawer();
    rememberOfflineSession();
    rememberOfflineControls();
    restoreOfflineRouteIfNeeded();
    cacheProductsFromPage();
    seedCartFromServer();
    renderCart();
    renderLocalRecords();
    bindForms();
    updateStatus();
    renderOfflineStatus();
    flushQueue();
    warmOfflinePages();
  });
  window.addEventListener("online", flushQueue);
  window.addEventListener("online", warmOfflinePages);
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) flushQueue();
  });
  window.addEventListener("offline", updateStatus);
})();
