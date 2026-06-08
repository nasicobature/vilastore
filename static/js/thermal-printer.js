(function () {
  const BRIDGE_URL = "http://127.0.0.1:8787";
  const SETTINGS_KEY = "vilastore_thermal_printer_settings_v2";

  function readSettings() {
    try {
      return JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}");
    } catch (error) {
      return {};
    }
  }

  function saveSettings(settings) {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings || {}));
  }

  async function bridgeFetch(path, options = {}) {
    const response = await fetch(`${BRIDGE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || "Printer bridge request failed.");
    }
    return payload;
  }

  function getReceiptPayload() {
    const element = document.getElementById("receipt-payload");
    if (!element) return null;
    try {
      return JSON.parse(element.textContent || "{}");
    } catch (error) {
      return null;
    }
  }

  function setText(root, selector, text) {
    const element = root.querySelector(selector);
    if (element) element.textContent = text;
  }

  function connectionLabel(connection) {
    if (!connection || !connection.target) return "No printer connected";
    return connection.target.label || connection.target.id || "Selected printer";
  }

  function updateConnectionUi(panel, connection) {
    const connected = Boolean(connection && connection.connected);
    setText(panel, "[data-printer-current]", connectionLabel(connection));
    setText(panel, "[data-printer-connection]", connected ? "Connected" : "Disconnected");
    const indicator = panel.querySelector("[data-printer-connection]");
    if (indicator) {
      indicator.classList.toggle("badge-success", connected);
      indicator.classList.toggle("badge-warning", !connected);
      indicator.classList.toggle("badge-primary", false);
    }
  }

  async function printReceipt(receipt) {
    return bridgeFetch("/print", {
      method: "POST",
      body: JSON.stringify({ receipt, paper_width: "58mm" }),
    });
  }

  async function testPrint() {
    return bridgeFetch("/test-print", {
      method: "POST",
      body: JSON.stringify({
        paper_width: "58mm",
        shop_name: document.body.dataset.shopName || "VilaStore",
        address: document.body.dataset.shopAddress || "",
      }),
    });
  }

  function optionLabel(printer) {
    const selected = printer.selected ? " - connected" : "";
    const defaultText = printer.is_default ? " - default" : "";
    return `${printer.label || printer.name}${defaultText}${selected}`;
  }

  function fillPrinterSelect(select, printers) {
    select.innerHTML = "";
    (printers || []).forEach((printer) => {
      const option = document.createElement("option");
      option.value = printer.id;
      option.textContent = optionLabel(printer);
      option.dataset.printer = JSON.stringify(printer);
      select.appendChild(option);
      if (printer.selected) select.value = printer.id;
    });
    if (!select.options.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No printers found";
      select.appendChild(option);
    }
  }

  async function loadStatus(panel) {
    const payload = await bridgeFetch("/status");
    updateConnectionUi(panel, payload.connection);
    saveSettings({ connection: payload.connection || null });
    return payload.connection;
  }

  function initReceiptPage() {
    const button = document.querySelector("[data-thermal-print]");
    if (!button) return;
    const fallbackButton = document.querySelector("[data-browser-print]");
    const status = document.querySelector("[data-print-status]");
    button.addEventListener("click", async () => {
      const receipt = getReceiptPayload();
      if (!receipt) {
        window.print();
        return;
      }
      button.disabled = true;
      if (status) status.textContent = "Sending receipt to connected printer...";
      try {
        await printReceipt(receipt);
        if (status) status.textContent = "Receipt sent to connected printer.";
      } catch (error) {
        if (status) status.textContent = `${error.message} Use Browser Print or reconnect the printer.`;
      } finally {
        button.disabled = false;
      }
    });
    if (fallbackButton) {
      fallbackButton.addEventListener("click", () => window.print());
    }
  }

  function initSettingsPage() {
    const panel = document.querySelector("[data-printer-settings]");
    if (!panel) return;
    const select = panel.querySelector("[data-printer-select]");
    const connect = panel.querySelector("[data-printer-connect]");
    const scan = panel.querySelector("[data-printer-scan]");
    const disconnect = panel.querySelector("[data-printer-disconnect]");
    const test = panel.querySelector("[data-printer-test]");
    const settings = readSettings();
    updateConnectionUi(panel, settings.connection);

    const scanPrinters = async () => {
      if (!select) return;
      setText(panel, "[data-printer-status]", "Scanning Windows, paired Bluetooth/COM, and Wi-Fi printers...");
      scan.disabled = true;
      try {
        const payload = await bridgeFetch("/discover");
        fillPrinterSelect(select, payload.printers || []);
        updateConnectionUi(panel, payload.connection);
        saveSettings({ connection: payload.connection || null });
        setText(panel, "[data-printer-status]", payload.printers?.length ? "Select a printer, then connect." : "No available printers found.");
      } catch (error) {
        setText(panel, "[data-printer-status]", "Start VilaPrintBridge, then scan again.");
      } finally {
        scan.disabled = false;
      }
    };

    scan?.addEventListener("click", scanPrinters);
    connect?.addEventListener("click", async () => {
      if (!select?.value) {
        setText(panel, "[data-printer-status]", "Select a printer first.");
        return;
      }
      const selectedOption = select.options[select.selectedIndex];
      const printer = JSON.parse(selectedOption.dataset.printer || "{}");
      connect.disabled = true;
      setText(panel, "[data-printer-status]", "Connecting printer...");
      try {
        const payload = await bridgeFetch("/connect", {
          method: "POST",
          body: JSON.stringify({
            target_id: printer.id,
            target: printer,
            label: printer.label,
          }),
        });
        updateConnectionUi(panel, payload.connection);
        saveSettings({ connection: payload.connection || null });
        setText(panel, "[data-printer-status]", "Printer connected and saved.");
      } catch (error) {
        setText(panel, "[data-printer-status]", error.message);
      } finally {
        connect.disabled = false;
      }
    });
    disconnect?.addEventListener("click", async () => {
      disconnect.disabled = true;
      setText(panel, "[data-printer-status]", "Disconnecting printer...");
      try {
        const payload = await bridgeFetch("/disconnect", { method: "POST", body: "{}" });
        updateConnectionUi(panel, payload.connection);
        saveSettings({ connection: payload.connection || null });
        setText(panel, "[data-printer-status]", "Printer disconnected.");
      } catch (error) {
        setText(panel, "[data-printer-status]", error.message);
      } finally {
        disconnect.disabled = false;
      }
    });
    test?.addEventListener("click", async () => {
      test.disabled = true;
      setText(panel, "[data-printer-status]", "Sending test receipt...");
      try {
        const payload = await testPrint();
        updateConnectionUi(panel, payload.connection);
        setText(panel, "[data-printer-status]", "Test receipt sent.");
      } catch (error) {
        setText(panel, "[data-printer-status]", error.message);
      } finally {
        test.disabled = false;
      }
    });

    loadStatus(panel).catch(() => {
      setText(panel, "[data-printer-status]", "Start VilaPrintBridge to connect printers.");
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initReceiptPage();
    initSettingsPage();
  });
})();
