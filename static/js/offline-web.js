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

  function nowId(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function fieldValue(fields, name, fallback) {
    const found = (fields || []).find(([key]) => key === name);
    return found ? found[1] : fallback;
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

  function rememberOfflineSession() {
    const userMarker = document.querySelector('meta[name="vilastore-offline-user"]');
    const emailMarker = document.querySelector('meta[name="vilastore-offline-email"]');
    const identities = [
      userMarker ? userMarker.getAttribute("content") : "",
      emailMarker ? emailMarker.getAttribute("content") : "",
    ].filter(Boolean);
    if (!identities.length) return;
    write(OFFLINE_AUTH_KEY, {
      identity: identities[0],
      identities,
      saved_at: new Date().toISOString(),
      last_path: window.location.pathname || "/index/",
    });
  }

  function getOfflineSession() {
    return read(OFFLINE_AUTH_KEY, null);
  }

  function handleOfflineLogin(form, fields) {
    const session = getOfflineSession();
    if (!session || !session.identity) {
      notify("Offline login is available only after this browser has logged in successfully online once.", true);
      return true;
    }
    const enteredIdentity = normalizeIdentity(fieldValue(fields, "email", ""));
    const savedIdentities = (session.identities || [session.identity]).map(normalizeIdentity).filter(Boolean);
    if (enteredIdentity && !savedIdentities.includes(enteredIdentity)) {
      notify(`Offline login is saved for ${session.identity}. Connect to internet to login with another account.`, true);
      return true;
    }
    notify("Offline login accepted on this trusted browser. Opening your saved dashboard...");
    window.setTimeout(() => {
      window.location.href = session.last_path || "/index/";
    }, 600);
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
      if (!remaining.length) {
        write(CUSTOMERS_KEY, []);
        write(EXPENSES_KEY, []);
        write(ACTIVITIES_KEY, []);
        renderLocalRecords();
      }
      notify(`${synced} offline action${synced === 1 ? "" : "s"} synced successfully.`);
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
        <form method="POST" action="/checkout/" data-offline-local-checkout="true" style="margin-top:0.75rem;display:flex;flex-direction:column;gap:0.5rem;">
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
      const saleTotal = getCart().total;
      write(CART_KEY, { items: [], total: "0.00" });
      renderCart();
      rememberActivity({ kind: "Sale", label: `NGN ${saleTotal}`, detail: "Sale saved offline and waiting to sync." });
      notify("Sale saved offline. It will sync when internet returns.");
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
    return true;
  }

  function bindForms() {
    document.addEventListener("submit", function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (form.dataset.offlineIgnore === "true") return;
      if (navigator.onLine) return;
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
    rememberOfflineSession();
    cacheProductsFromPage();
    seedCartFromServer();
    renderCart();
    renderLocalRecords();
    bindForms();
    updateStatus();
    flushQueue();
    warmOfflinePages();
  });
  window.addEventListener("online", flushQueue);
  window.addEventListener("online", warmOfflinePages);
  window.addEventListener("offline", updateStatus);
})();
