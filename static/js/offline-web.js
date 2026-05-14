(function () {
  const QUEUE_KEY = "vilastore_web_offline_queue_v1";
  const CART_KEY = "vilastore_web_offline_cart_v1";
  const PRODUCTS_KEY = "vilastore_web_products_v1";

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
      id: `web-offline-${Date.now()}-${Math.random().toString(16).slice(2)}`,
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

  function formFields(form) {
    const formData = new FormData(form);
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
    return fetch(entry.action, {
      method: entry.method || "POST",
      body: formData,
      credentials: "same-origin",
      headers: { "X-Offline-Sync": "1" },
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
    if (synced) notify(`${synced} offline action${synced === 1 ? "" : "s"} synced successfully.`);
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
      return;
    }
    host.innerHTML = `
      <div class="card" style="padding:0.75rem 1rem;margin-bottom:0.75rem;border:1px dashed var(--border);">
        <strong>Offline cart</strong>
        <p style="margin:0.25rem 0;color:var(--muted-foreground);font-size:0.85rem;">This cart is saved on this browser and will sync when internet returns.</p>
        <ul style="padding-left:1.1rem;margin:0.5rem 0;">
          ${cart.items
            .map((item) => `<li>${item.name} - ${item.quantity} x NGN ${item.price}</li>`)
            .join("")}
        </ul>
        <strong>Total: NGN ${cart.total}</strong>
      </div>
    `;
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

  function handleOfflineForm(form) {
    const method = (form.method || "GET").toUpperCase();
    if (method !== "POST") return false;
    const action = form.action || window.location.href;
    const { fields, hasFile } = formFields(form);
    const actionPath = new URL(action, window.location.href).pathname;

    if (hasFile) {
      notify("Image upload needs internet. The text fields were saved offline; upload the image after sync.");
    }

    if (actionPath.includes("/add-to-cart/")) {
      const isCode = actionPath.includes("/by-code/");
      const product = isCode
        ? findProduct(fields.find(([key]) => key === "code")?.[1], true)
        : findProduct((actionPath.match(/add-to-cart\/(\d+)/) || [])[1], false);
      if (!product) {
        notify("This product code is not saved offline yet. Open inventory/products online once, then scan again.");
        return true;
      }
      addToOfflineCart(product, fields.find(([key]) => key === "quantity")?.[1] || 1);
    } else if (actionPath.includes("/update-cart/")) {
      const productId = (actionPath.match(/update-cart\/([^/]+)/) || [])[1];
      updateOfflineCart(productId, fields.find(([key]) => key === "action")?.[1], fields.find(([key]) => key === "quantity")?.[1]);
    } else if (actionPath.includes("/remove-from-cart/")) {
      const productId = (actionPath.match(/remove-from-cart\/([^/]+)/) || [])[1];
      updateOfflineCart(productId, "remove");
    } else if (actionPath.includes("/checkout/")) {
      write(CART_KEY, { items: [], total: "0.00" });
      renderCart();
      notify("Sale saved offline. It will sync when internet returns.");
    } else {
      notify("Saved offline. VilaStore will sync this when internet returns.");
    }

    enqueue({ action, method, fields });
    return true;
  }

  function bindForms() {
    document.addEventListener("submit", function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (form.dataset.offlineIgnore === "true") return;
      if (navigator.onLine) return;
      if (handleOfflineForm(form)) {
        event.preventDefault();
      }
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
    cacheProductsFromPage();
    seedCartFromServer();
    renderCart();
    bindForms();
    updateStatus();
    flushQueue();
  });
  window.addEventListener("online", flushQueue);
  window.addEventListener("offline", updateStatus);
})();
