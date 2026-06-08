(function () {
  const BRIDGE_URL = "http://127.0.0.1:8787";
  const SETTINGS_KEY = "vilastore_thermal_printer_settings_v1";

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

  async function bridgeFetch(path, options) {
    const response = await fetch(`${BRIDGE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options && options.headers ? options.headers : {}),
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

  function setText(selector, text) {
    const element = document.querySelector(selector);
    if (element) element.textContent = text;
  }

  async function printReceipt(receipt) {
    const settings = readSettings();
    if (!settings.printerName) {
      throw new Error("Choose a thermal printer in Settings first.");
    }
    return bridgeFetch("/print", {
      method: "POST",
      body: JSON.stringify({
        printer_name: settings.printerName,
        paper_width: settings.paperWidth || "58mm",
        receipt,
      }),
    });
  }

  async function testPrint() {
    const settings = readSettings();
    if (!settings.printerName) {
      throw new Error("Select a printer before test printing.");
    }
    return bridgeFetch("/test-print", {
      method: "POST",
      body: JSON.stringify({
        printer_name: settings.printerName,
        paper_width: settings.paperWidth || "58mm",
        shop_name: document.body.dataset.shopName || "VilaStore",
        address: document.body.dataset.shopAddress || "",
      }),
    });
  }

  async function loadPrinters(select) {
    const payload = await bridgeFetch("/printers", { method: "GET" });
    select.innerHTML = "";
    (payload.printers || []).forEach((printer) => {
      const option = document.createElement("option");
      option.value = printer.name;
      option.textContent = printer.is_default ? `${printer.name} (default)` : printer.name;
      select.appendChild(option);
    });
    if (!select.options.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No printers found";
      select.appendChild(option);
    }
    const settings = readSettings();
    if (settings.printerName) select.value = settings.printerName;
    if (!select.value && select.options.length) select.selectedIndex = 0;
    return payload;
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
      if (status) status.textContent = "Sending receipt to thermal printer...";
      try {
        await printReceipt(receipt);
        if (status) status.textContent = "Receipt sent to thermal printer.";
      } catch (error) {
        if (status) status.textContent = `${error.message} Using browser print instead.`;
        window.print();
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
    const refresh = panel.querySelector("[data-printer-refresh]");
    const save = panel.querySelector("[data-printer-save]");
    const test = panel.querySelector("[data-printer-test]");
    const width = panel.querySelector("[data-paper-width]");
    const settings = readSettings();
    if (width) width.value = settings.paperWidth || "58mm";
    setText("[data-printer-current]", settings.printerName || "Not selected");

    const refreshPrinters = async () => {
      if (!select) return;
      setText("[data-printer-status]", "Looking for local printer bridge...");
      try {
        await loadPrinters(select);
        setText("[data-printer-status]", "Printer bridge connected.");
      } catch (error) {
        setText("[data-printer-status]", "Start VilaPrintBridge, then refresh printers.");
      }
    };

    refresh?.addEventListener("click", refreshPrinters);
    save?.addEventListener("click", () => {
      saveSettings({
        printerName: select?.value || "",
        paperWidth: width?.value || "58mm",
      });
      setText("[data-printer-current]", select?.value || "Not selected");
      setText("[data-printer-status]", "Printer settings saved in this browser.");
    });
    test?.addEventListener("click", async () => {
      test.disabled = true;
      setText("[data-printer-status]", "Sending test receipt...");
      try {
        await testPrint();
        setText("[data-printer-status]", "Test receipt sent.");
      } catch (error) {
        setText("[data-printer-status]", error.message);
      } finally {
        test.disabled = false;
      }
    });
    refreshPrinters();
  }

  document.addEventListener("DOMContentLoaded", () => {
    initReceiptPage();
    initSettingsPage();
  });
})();
