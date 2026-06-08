(function () {
  const BRIDGE_URLS = ["http://127.0.0.1:8787", "http://localhost:8787"];
  const SETTINGS_KEY = "vilastore_thermal_printer_settings_v2";
  const BRIDGE_OFFLINE_MESSAGE = "VilaPrintBridge is not running or the browser blocked it. Start start-vila-print-bridge.bat, keep its window open, then try again.";
  const LINE_WIDTH = 32;
  const BLE_SERVICES = [
    "0000ff00-0000-1000-8000-00805f9b34fb",
    "000018f0-0000-1000-8000-00805f9b34fb",
    "49535343-fe7d-4ae5-8fa9-9fafd205e455",
  ];
  const BLE_CHARACTERISTICS = [
    "0000ff01-0000-1000-8000-00805f9b34fb",
    "0000ff02-0000-1000-8000-00805f9b34fb",
    "00002af1-0000-1000-8000-00805f9b34fb",
    "49535343-8841-43f4-a8d4-ecbe34729bb3",
  ];
  let browserSerialPort = null;
  let browserBluetoothDevice = null;
  let browserBluetoothCharacteristic = null;

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

  function withTimeout(promise, ms, message) {
    let timer = null;
    const timeout = new Promise((_, reject) => {
      timer = window.setTimeout(() => reject(new Error(message)), ms);
    });
    return Promise.race([promise, timeout]).finally(() => {
      if (timer) window.clearTimeout(timer);
    });
  }

  function cleanText(value) {
    return String(value || "")
      .replace(/\r|\n/g, " ")
      .replace(/₦/g, "NGN ")
      .replace(/[–—]/g, "-")
      .replace(/•/g, "*")
      .trim();
  }

  function fit(text, width, align = "left") {
    let value = cleanText(text);
    if (value.length > width) value = `${value.slice(0, Math.max(0, width - 1))}.`;
    if (align === "right") return value.padStart(width, " ");
    if (align === "center") {
      const left = Math.floor((width - value.length) / 2);
      return `${" ".repeat(Math.max(0, left))}${value}`.padEnd(width, " ");
    }
    return value.padEnd(width, " ");
  }

  function wrap(text, width) {
    const words = cleanText(text).split(/\s+/).filter(Boolean);
    const lines = [];
    let current = "";
    words.forEach((word) => {
      const candidate = current ? `${current} ${word}` : word;
      if (candidate.length <= width) {
        current = candidate;
      } else {
        if (current) lines.push(current);
        while (word.length > width) {
          lines.push(word.slice(0, width));
          word = word.slice(width);
        }
        current = word;
      }
    });
    if (current) lines.push(current);
    return lines.length ? lines : [""];
  }

  function money(value, currency = "NGN") {
    const number = Number(value || 0);
    if (Number.isFinite(number)) return `${currency} ${number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    return `${currency} ${cleanText(value)}`;
  }

  function row(left, right, width = LINE_WIDTH) {
    const cleanLeft = cleanText(left);
    const cleanRight = cleanText(right);
    const spaces = Math.max(1, width - cleanLeft.length - cleanRight.length);
    return `${cleanLeft.slice(0, Math.max(0, width - cleanRight.length - 1))}${" ".repeat(spaces)}${cleanRight}`;
  }

  function asciiBytes(text) {
    return Array.from(cleanText(text), (char) => {
      const code = char.charCodeAt(0);
      return code > 127 ? 63 : code;
    });
  }

  function receiptToEscpos(receipt, test = false) {
    const currency = receipt.currency || "NGN";
    const bytes = [];
    const push = (...items) => bytes.push(...items);
    const text = (value) => push(...asciiBytes(value));
    push(0x1b, 0x40, 0x1b, 0x74, 0x00, 0x1b, 0x61, 0x01, 0x1b, 0x45, 0x01);
    text(`${fit(receipt.shop_name || "VilaStore", LINE_WIDTH, "center")}\n`);
    push(0x1b, 0x45, 0x00);
    ["address", "phone"].forEach((field) => {
      if (receipt[field]) wrap(receipt[field], LINE_WIDTH).forEach((line) => text(`${fit(line, LINE_WIDTH, "center")}\n`));
    });
    push(0x1b, 0x61, 0x00);
    text(`${"-".repeat(LINE_WIDTH)}\n`);
    text(`${row("Receipt:", receipt.receipt_no || "TEST")}\n`);
    text(`${row("Date:", receipt.date || "Test print")}\n`);
    if (receipt.handled_by) text(`${row("By:", receipt.handled_by)}\n`);
    if (receipt.customer) text(`${row("Customer:", receipt.customer)}\n`);
    text(`${"-".repeat(LINE_WIDTH)}\n`);
    text(`${fit("ITEM", 16)}${fit("QTY", 4, "right")}${fit("AMOUNT", 12, "right")}\n`);
    text(`${"-".repeat(LINE_WIDTH)}\n`);
    const items = receipt.items?.length ? receipt.items : test ? [{ name: "Printer test", quantity: "1", total: "0.00" }] : [];
    items.forEach((item) => {
      const lines = wrap(item.name || "Item", 16);
      text(`${fit(lines[0], 16)}${fit(item.quantity || "1", 4, "right")}${fit(money(item.total, currency), 12, "right")}\n`);
      lines.slice(1).forEach((line) => text(`${fit(line, LINE_WIDTH)}\n`));
    });
    text(`${"-".repeat(LINE_WIDTH)}\n`);
    push(0x1b, 0x45, 0x01);
    text(`${row("TOTAL", money(receipt.total, currency))}\n`);
    push(0x1b, 0x45, 0x00);
    if (receipt.amount_paid) text(`${row("Paid", money(receipt.amount_paid, currency))}\n`);
    if (receipt.balance) text(`${row("Balance", money(receipt.balance, currency))}\n`);
    text(`${"-".repeat(LINE_WIDTH)}\n`);
    push(0x1b, 0x61, 0x01);
    text("Thank you for shopping\nVilaStore\n\n\n");
    push(0x1d, 0x56, 0x42, 0x00);
    return new Uint8Array(bytes);
  }

  async function writeSerialBytes(bytes, baudRate = 9600) {
    if (!("serial" in navigator)) throw new Error("Browser Serial is not supported. Use Chrome or Edge on desktop.");
    if (!browserSerialPort) {
      const ports = await navigator.serial.getPorts();
      browserSerialPort = ports[0] || null;
    }
    if (!browserSerialPort) throw new Error("Connect Browser Serial/USB in Settings first.");
    if (!browserSerialPort.writable) {
      await browserSerialPort.open({ baudRate });
    }
    const writer = browserSerialPort.writable.getWriter();
    try {
      await writer.write(bytes);
    } finally {
      writer.releaseLock();
    }
  }

  async function findBluetoothCharacteristic(server) {
    for (const serviceUuid of BLE_SERVICES) {
      try {
        const service = await server.getPrimaryService(serviceUuid);
        for (const characteristicUuid of BLE_CHARACTERISTICS) {
          try {
            const characteristic = await service.getCharacteristic(characteristicUuid);
            if (characteristic.properties.write || characteristic.properties.writeWithoutResponse) return characteristic;
          } catch (error) {}
        }
        const characteristics = await service.getCharacteristics();
        const writable = characteristics.find((item) => item.properties.write || item.properties.writeWithoutResponse);
        if (writable) return writable;
      } catch (error) {}
    }
    throw new Error("Bluetooth printer connected, but no writable ESC/POS service was found.");
  }

  async function writeBluetoothBytes(bytes) {
    if (!("bluetooth" in navigator)) throw new Error("Browser Bluetooth is not supported. Use Chrome or Edge on desktop/Android.");
    if (!browserBluetoothDevice && navigator.bluetooth.getDevices) {
      const devices = await navigator.bluetooth.getDevices();
      browserBluetoothDevice = devices[0] || null;
    }
    if (!browserBluetoothDevice) throw new Error("Connect Browser Bluetooth in Settings first.");
    if (!browserBluetoothDevice.gatt.connected || !browserBluetoothCharacteristic) {
      const server = await browserBluetoothDevice.gatt.connect();
      browserBluetoothCharacteristic = await findBluetoothCharacteristic(server);
    }
    for (let index = 0; index < bytes.length; index += 20) {
      const chunk = bytes.slice(index, index + 20);
      if (browserBluetoothCharacteristic.writeValueWithoutResponse) {
        await browserBluetoothCharacteristic.writeValueWithoutResponse(chunk);
      } else {
        await browserBluetoothCharacteristic.writeValue(chunk);
      }
    }
  }

  async function printBrowserDirect(receipt) {
    const settings = readSettings();
    const bytes = receiptToEscpos(receipt);
    if (settings.browserMode === "serial") {
      await writeSerialBytes(bytes, Number(settings.serialBaud || 9600));
      return true;
    }
    if (settings.browserMode === "bluetooth") {
      await writeBluetoothBytes(bytes);
      return true;
    }
    return false;
  }

  async function bridgeFetch(path, options = {}) {
    let lastError = null;
    for (const bridgeUrl of BRIDGE_URLS) {
      try {
        const response = await fetch(`${bridgeUrl}${path}`, {
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
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError && lastError.message && lastError.message !== "Failed to fetch") {
      throw lastError;
    }
    throw new Error(BRIDGE_OFFLINE_MESSAGE);
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

  function showPrinterStatus(panel, message, alertUser = false) {
    setText(panel, "[data-printer-status]", message);
    if (alertUser) window.alert(message);
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

  function browserDirectHelp() {
    if (!window.isSecureContext) return "Open VilaStore using HTTPS, Chrome, or Edge before browser-direct printer connection can work.";
    if (!("serial" in navigator) && !("bluetooth" in navigator)) return "This browser cannot connect directly to printers. Use Chrome or Edge on desktop/Android.";
    return "Try Auto Connect Printer, then choose your thermal printer in the browser popup.";
  }

  function browserFeatureReport() {
    return `Secure: ${window.isSecureContext ? "yes" : "no"} | Serial: ${"serial" in navigator ? "yes" : "no"} | Bluetooth: ${"bluetooth" in navigator ? "yes" : "no"}`;
  }

  async function printReceipt(receipt) {
    if (await printBrowserDirect(receipt)) return { ok: true, direct: true };
    return bridgeFetch("/print", {
      method: "POST",
      body: JSON.stringify({ receipt, paper_width: "58mm" }),
    });
  }

  async function testPrint() {
    const receipt = {
      shop_name: document.body.dataset.shopName || "VilaStore",
      address: document.body.dataset.shopAddress || "",
      receipt_no: "TEST",
      date: "Test print",
      items: [{ name: "Printer test", quantity: "1", total: "0.00" }],
      total: "0.00",
      amount_paid: "0.00",
      balance: "0.00",
      currency: "NGN",
    };
    if (await printBrowserDirect(receipt)) return { ok: true, direct: true };
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
        if (status) status.textContent = error.message || BRIDGE_OFFLINE_MESSAGE;
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
    const connectIp = panel.querySelector("[data-printer-connect-ip]");
    const connectCom = panel.querySelector("[data-printer-connect-com]");
    const scan = panel.querySelector("[data-printer-scan]");
    const disconnect = panel.querySelector("[data-printer-disconnect]");
    const test = panel.querySelector("[data-printer-test]");
    const browserAutoConnect = panel.querySelector("[data-browser-auto-connect]");
    const browserSerialConnect = panel.querySelector("[data-browser-serial-connect]");
    const browserBluetoothConnect = panel.querySelector("[data-browser-bluetooth-connect]");
    const browserSerialBaud = panel.querySelector("[data-browser-serial-baud]");
    const ipInput = panel.querySelector("[data-printer-ip]");
    const comInput = panel.querySelector("[data-printer-com]");
    const settings = readSettings();
    updateConnectionUi(panel, settings.connection);
    showPrinterStatus(panel, `${browserDirectHelp()} (${browserFeatureReport()})`);

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
        showPrinterStatus(panel, error.message || BRIDGE_OFFLINE_MESSAGE);
      } finally {
        scan.disabled = false;
      }
    };

    const connectBrowserSerial = async () => {
      if (!("serial" in navigator)) {
        throw new Error("Browser Serial is not supported. Use Chrome or Edge on desktop.");
      }
      showPrinterStatus(panel, "Choose the USB/Bluetooth serial printer in the browser popup...");
      browserSerialPort = await navigator.serial.requestPort();
      const serialBaud = Number(browserSerialBaud?.value || 9600);
      showPrinterStatus(panel, `Opening serial printer at ${serialBaud} baud...`);
      await withTimeout(
        browserSerialPort.open({ baudRate: serialBaud }),
        12000,
        "Serial printer did not open. Try another baud rate, reconnect the printer, or choose a different device."
      );
      await browserSerialPort.close().catch(() => {});
      saveSettings({
        ...readSettings(),
        browserMode: "serial",
        serialBaud,
        connection: {
          connected: true,
          status: "Connected",
          target: { label: `Browser Serial/USB (${serialBaud})`, id: "browser:serial" },
        },
      });
      updateConnectionUi(panel, readSettings().connection);
      showPrinterStatus(panel, "Browser Serial/USB connected. Click Test Print.", true);
      return true;
    };

    const connectBrowserBluetooth = async () => {
      if (!("bluetooth" in navigator)) {
        throw new Error("Browser Bluetooth is not supported. Use Chrome or Edge on desktop/Android.");
      }
      showPrinterStatus(panel, "Choose the Bluetooth printer in the browser popup...");
      browserBluetoothDevice = await navigator.bluetooth.requestDevice({
        acceptAllDevices: true,
        optionalServices: BLE_SERVICES,
      });
      showPrinterStatus(panel, "Connecting to Bluetooth printer service...");
      const server = await withTimeout(
        browserBluetoothDevice.gatt.connect(),
        12000,
        "Bluetooth connection timed out. If this is a classic Bluetooth printer, use Connect Browser Serial/USB or Connect COM instead."
      );
      showPrinterStatus(panel, "Finding writable ESC/POS Bluetooth service...");
      browserBluetoothCharacteristic = await withTimeout(
        findBluetoothCharacteristic(server),
        12000,
        "No writable BLE ESC/POS service was found. This printer likely uses classic Bluetooth; try Connect Browser Serial/USB or Connect COM."
      );
      saveSettings({
        ...readSettings(),
        browserMode: "bluetooth",
        connection: {
          connected: true,
          status: "Connected",
          target: { label: `${browserBluetoothDevice.name || "Browser Bluetooth printer"}`, id: "browser:bluetooth" },
        },
      });
      updateConnectionUi(panel, readSettings().connection);
      showPrinterStatus(panel, "Browser Bluetooth connected. Click Test Print.", true);
      return true;
    };

    scan?.addEventListener("click", scanPrinters);
    browserAutoConnect?.addEventListener("click", async () => {
      browserAutoConnect.disabled = true;
      showPrinterStatus(panel, `Auto Connect clicked. ${browserDirectHelp()} (${browserFeatureReport()})`);
      try {
        if ("serial" in navigator) {
          await connectBrowserSerial();
          return;
        }
        if ("bluetooth" in navigator) {
          await connectBrowserBluetooth();
          return;
        }
        showPrinterStatus(panel, browserDirectHelp(), true);
      } catch (error) {
        showPrinterStatus(panel, `${error.message || browserDirectHelp()} If you need Bluetooth, click Connect Browser Bluetooth directly.`, true);
      } finally {
        browserAutoConnect.disabled = false;
      }
    });
    browserSerialConnect?.addEventListener("click", async () => {
      browserSerialConnect.disabled = true;
      try {
        await connectBrowserSerial();
      } catch (error) {
        showPrinterStatus(panel, error.message || "Serial connection was cancelled.", true);
      } finally {
        browserSerialConnect.disabled = false;
      }
    });
    browserBluetoothConnect?.addEventListener("click", async () => {
      browserBluetoothConnect.disabled = true;
      try {
        await connectBrowserBluetooth();
      } catch (error) {
        showPrinterStatus(panel, error.message || "Bluetooth connection was cancelled.", true);
      } finally {
        browserBluetoothConnect.disabled = false;
      }
    });
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
        saveSettings({ connection: payload.connection || null, browserMode: "" });
        setText(panel, "[data-printer-status]", "Printer connected and saved.");
      } catch (error) {
        setText(panel, "[data-printer-status]", error.message);
      } finally {
        connect.disabled = false;
      }
    });
    connectIp?.addEventListener("click", async () => {
      const host = (ipInput?.value || "").trim();
      if (!host) {
        setText(panel, "[data-printer-status]", "Enter the Wi-Fi printer IP address first.");
        return;
      }
      connectIp.disabled = true;
      setText(panel, "[data-printer-status]", "Connecting directly to Wi-Fi ESC/POS printer...");
      const label = `${host}:9100 (Wi-Fi ESC/POS)`;
      try {
        const payload = await bridgeFetch("/connect", {
          method: "POST",
          body: JSON.stringify({
            target: {
              id: `network:${host}:9100`,
              kind: "network",
              host,
              port: 9100,
              label,
              name: host,
            },
            label,
          }),
        });
        updateConnectionUi(panel, payload.connection);
        saveSettings({ connection: payload.connection || null, browserMode: "" });
        setText(panel, "[data-printer-status]", "Wi-Fi printer connected. Send a test print.");
      } catch (error) {
        setText(panel, "[data-printer-status]", error.message || "Could not connect to Wi-Fi printer.");
      } finally {
        connectIp.disabled = false;
      }
    });
    connectCom?.addEventListener("click", async () => {
      const port = (comInput?.value || "").trim().toUpperCase();
      if (!/^COM\d+$/.test(port)) {
        setText(panel, "[data-printer-status]", "Enter a Bluetooth COM port like COM3.");
        return;
      }
      connectCom.disabled = true;
      setText(panel, "[data-printer-status]", "Connecting directly to Bluetooth COM printer...");
      const label = `${port} (Bluetooth ESC/POS)`;
      try {
        const payload = await bridgeFetch("/connect", {
          method: "POST",
          body: JSON.stringify({
            target: {
              id: `serial:${port}`,
              kind: "serial",
              port,
              label,
              name: port,
            },
            label,
          }),
        });
        updateConnectionUi(panel, payload.connection);
        saveSettings({ connection: payload.connection || null, browserMode: "" });
        setText(panel, "[data-printer-status]", "Bluetooth COM printer connected. Send a test print.");
      } catch (error) {
        setText(panel, "[data-printer-status]", error.message || "Could not connect to Bluetooth COM printer.");
      } finally {
        connectCom.disabled = false;
      }
    });
    disconnect?.addEventListener("click", async () => {
      disconnect.disabled = true;
      setText(panel, "[data-printer-status]", "Disconnecting printer...");
      try {
        const settings = readSettings();
        if (settings.browserMode === "serial" && browserSerialPort?.readable) {
          await browserSerialPort.close().catch(() => {});
        }
        if (settings.browserMode === "bluetooth" && browserBluetoothDevice?.gatt?.connected) {
          browserBluetoothDevice.gatt.disconnect();
        }
        browserSerialPort = null;
        browserBluetoothDevice = null;
        browserBluetoothCharacteristic = null;
        const payload = await bridgeFetch("/disconnect", { method: "POST", body: "{}" });
        updateConnectionUi(panel, payload.connection);
        saveSettings({ connection: payload.connection || null, browserMode: "" });
        setText(panel, "[data-printer-status]", "Printer disconnected.");
      } catch (error) {
        browserSerialPort = null;
        browserBluetoothDevice = null;
        browserBluetoothCharacteristic = null;
        saveSettings({ connection: null, browserMode: "" });
        updateConnectionUi(panel, null);
        setText(panel, "[data-printer-status]", "Printer disconnected locally.");
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
      showPrinterStatus(panel, `${browserDirectHelp()} (${browserFeatureReport()})`);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initReceiptPage();
    initSettingsPage();
  });
})();
