/*
 * Phone-camera barcode scanner for the POS (shop owner) and the shopboy dashboard.
 *
 * Markup:
 *   <form data-camera-scan-form action="...add-by-code..."> with an input[name=code]
 *   <button data-camera-scan-open> inside that form, or
 *   <button data-camera-scan-open="#formId"> anywhere on the page
 *
 * The camera stays open so several products can be scanned in a row. Each scan
 * posts the code to the form's action (JSON reply) and adds 1 unit to the cart.
 * Offline, the form is submitted instead so offline-web.js puts it in the offline cart.
 * Uses html5-qrcode (works on iPhone/Safari/Firefox) and falls back to the
 * browser's own BarcodeDetector when the library cannot load.
 */
(function () {
  "use strict";

  var LIB_URL = "https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js";
  var NATIVE_FORMATS = ["ean_13", "ean_8", "code_128", "code_39", "upc_a", "upc_e", "qr_code"];
  var REPEAT_DELAY_MS = 2500;
  var libPromise = null;

  function lib() {
    var bundle = window.__Html5QrcodeLibrary__ || {};
    return {
      Html5Qrcode: window.Html5Qrcode || bundle.Html5Qrcode,
      formats: window.Html5QrcodeSupportedFormats || bundle.Html5QrcodeSupportedFormats
    };
  }

  function loadLibrary() {
    if (lib().Html5Qrcode) return Promise.resolve(true);
    if (!libPromise) {
      libPromise = new Promise(function (resolve) {
        var script = document.createElement("script");
        script.src = LIB_URL;
        script.async = true;
        script.onload = function () { resolve(!!lib().Html5Qrcode); };
        script.onerror = function () { libPromise = null; resolve(false); };
        document.head.appendChild(script);
      });
    }
    return libPromise;
  }

  function injectStyles() {
    if (document.getElementById("vila-scan-styles")) return;
    var style = document.createElement("style");
    style.id = "vila-scan-styles";
    style.textContent = [
      ".vila-scan-overlay{position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;padding:12px}",
      ".vila-scan-card{background:#fff;color:#111;border-radius:14px;width:100%;max-width:420px;max-height:100%;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 20px 50px rgba(0,0,0,.35)}",
      ".vila-scan-head{display:flex;align-items:center;justify-content:space-between;padding:12px 14px;border-bottom:1px solid #eee}",
      ".vila-scan-head strong{font-size:1rem}",
      ".vila-scan-count{font-size:.8rem;background:#111;color:#fff;border-radius:999px;padding:2px 10px;margin-left:8px}",
      ".vila-scan-view{position:relative;background:#000;min-height:240px}",
      ".vila-scan-view video{width:100%;display:block}",
      ".vila-scan-status{padding:8px 14px;font-size:.85rem;color:#555}",
      ".vila-scan-list{list-style:none;margin:0;padding:0 14px;max-height:30vh;overflow-y:auto}",
      ".vila-scan-list li{font-size:.85rem;padding:6px 0;border-bottom:1px dashed #eee}",
      ".vila-scan-list .ok{color:#15803d}.vila-scan-list .warn{color:#b45309}.vila-scan-list .err{color:#b91c1c}",
      ".vila-scan-foot{display:flex;gap:8px;padding:12px 14px}",
      ".vila-scan-foot button{flex:1;border:0;border-radius:10px;padding:12px;font-weight:600;font-size:.95rem;cursor:pointer}",
      ".vila-scan-done{background:#111;color:#fff}",
      ".vila-scan-cancel{background:#f1f1f1;color:#111}",
      ".vila-scan-flash{position:absolute;inset:0;background:rgba(34,197,94,.35);opacity:0;transition:opacity .25s;pointer-events:none}",
      ".vila-scan-flash.on{opacity:1}",
      "@media (max-width:520px){.vila-scan-overlay{padding:0;align-items:flex-end}.vila-scan-card{max-width:none;border-radius:14px 14px 0 0}}"
    ].join("");
    document.head.appendChild(style);
  }

  function buildModal() {
    injectStyles();
    var overlay = document.createElement("div");
    overlay.className = "vila-scan-overlay";
    overlay.innerHTML =
      '<div class="vila-scan-card" role="dialog" aria-modal="true" aria-label="Scan products">' +
      '  <div class="vila-scan-head"><div><strong>Scan products</strong><span class="vila-scan-count">0 in cart</span></div></div>' +
      '  <div class="vila-scan-view"><div id="vilaScanReader"></div><div class="vila-scan-flash"></div></div>' +
      '  <div class="vila-scan-status">Starting camera…</div>' +
      '  <ul class="vila-scan-list"></ul>' +
      '  <div class="vila-scan-foot">' +
      '    <button type="button" class="vila-scan-cancel">Close</button>' +
      '    <button type="button" class="vila-scan-done">Done – view cart</button>' +
      "  </div>" +
      "</div>";
    document.body.appendChild(overlay);
    return {
      overlay: overlay,
      view: overlay.querySelector(".vila-scan-view"),
      reader: overlay.querySelector("#vilaScanReader"),
      flash: overlay.querySelector(".vila-scan-flash"),
      status: overlay.querySelector(".vila-scan-status"),
      list: overlay.querySelector(".vila-scan-list"),
      count: overlay.querySelector(".vila-scan-count"),
      cancel: overlay.querySelector(".vila-scan-cancel"),
      done: overlay.querySelector(".vila-scan-done")
    };
  }

  function cameraErrorMessage(err) {
    var name = (err && err.name) || "";
    var text = String((err && err.message) || err || "");
    if (name === "NotAllowedError" || /permission|denied|notallowed/i.test(text)) {
      return "Camera permission was blocked. Allow camera access for this site in your browser settings, then try again.";
    }
    if (name === "NotFoundError" || /not ?found|no camera/i.test(text)) {
      return "No camera was found on this device.";
    }
    if (name === "NotReadableError" || /in use|could not start/i.test(text)) {
      return "The camera is being used by another app. Close it and try again.";
    }
    return "Could not start the camera. " + text;
  }

  // Engine using the html5-qrcode library.
  function libraryEngine(ui, onCode) {
    var formats = lib().formats;
    var scanner = new (lib().Html5Qrcode)(ui.reader.id, {
      verbose: false,
      formatsToSupport: [
        formats.EAN_13, formats.EAN_8, formats.CODE_128, formats.CODE_39,
        formats.UPC_A, formats.UPC_E, formats.QR_CODE
      ],
      experimentalFeatures: { useBarCodeDetectorIfSupported: true }
    });
    return {
      start: function () {
        return scanner.start(
          { facingMode: "environment" },
          {
            fps: 12,
            qrbox: function (width, height) {
              return { width: Math.max(160, Math.floor(width * 0.85)), height: Math.max(100, Math.floor(height * 0.5)) };
            }
          },
          function (text) { onCode(text); },
          function () {}
        );
      },
      stop: function () {
        return Promise.resolve()
          .then(function () { return scanner.isScanning ? scanner.stop() : null; })
          .then(function () { scanner.clear(); })
          .catch(function () {});
      }
    };
  }

  // Engine using the browser's built-in BarcodeDetector (Chrome / Android).
  function nativeEngine(ui, onCode) {
    var stream = null;
    var running = false;
    var video = document.createElement("video");
    video.setAttribute("playsinline", "");
    video.muted = true;
    video.autoplay = true;
    ui.reader.appendChild(video);
    var detector = new window.BarcodeDetector({ formats: NATIVE_FORMATS });

    function loop() {
      if (!running) return;
      detector.detect(video)
        .then(function (codes) {
          if (codes && codes.length && codes[0].rawValue) onCode(codes[0].rawValue);
        })
        .catch(function () {})
        .then(function () { if (running) setTimeout(loop, 150); });
    }

    return {
      start: function () {
        return navigator.mediaDevices
          .getUserMedia({ video: { facingMode: "environment" }, audio: false })
          .then(function (s) {
            stream = s;
            video.srcObject = s;
            running = true;
            loop();
          });
      },
      stop: function () {
        running = false;
        if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
        stream = null;
        return Promise.resolve();
      }
    };
  }

  function openScanner(form) {
    var codeInput = form.querySelector('input[name="code"]');
    var qtyInput = form.querySelector('input[name="quantity"]');
    var ui = buildModal();
    var engine = null;
    var busy = false;
    var lastCode = "";
    var lastAt = 0;
    var cartChanged = false;
    var closed = false;

    function setStatus(text) { ui.status.textContent = text; }

    function addLine(text, kind) {
      var li = document.createElement("li");
      li.className = kind;
      li.textContent = text;
      ui.list.insertBefore(li, ui.list.firstChild);
    }

    function signalHit() {
      ui.flash.classList.add("on");
      setTimeout(function () { ui.flash.classList.remove("on"); }, 250);
      if (navigator.vibrate) navigator.vibrate(80);
    }

    function addOffline(code) {
      if (!codeInput) return;
      var oldQty = qtyInput ? qtyInput.value : "";
      codeInput.value = code;
      if (qtyInput) qtyInput.value = "1";
      if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
      if (qtyInput) qtyInput.value = oldQty;
      codeInput.value = "";
      addLine(code + " – sent to offline cart", "ok");
    }

    function addOnline(code) {
      var data = new FormData(form);
      data.set("code", code);
      data.set("quantity", "1");
      return fetch(form.action, {
        method: "POST",
        body: data,
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" }
      })
        .then(function (res) {
          return res.json().catch(function () {
            return { success: false, message: res.status === 403 ? "Your session expired. Log in again." : "Unexpected server response." };
          });
        })
        .then(function (result) {
          if (result.success) {
            cartChanged = true;
            ui.count.textContent = (result.cart_count || 0) + " in cart";
            addLine(result.product + " – qty " + result.quantity + (result.message ? " (" + result.message + ")" : ""), result.message ? "warn" : "ok");
          } else {
            addLine(code + " – " + (result.message || "Could not add product."), "err");
          }
        })
        .catch(function () {
          addLine(code + " – network error, scan again.", "err");
        });
    }

    function handleCode(raw) {
      var code = String(raw || "").trim();
      if (!code || busy || closed) return;
      var now = Date.now();
      if (code === lastCode && now - lastAt < REPEAT_DELAY_MS) return;
      lastCode = code;
      lastAt = now;
      busy = true;
      signalHit();
      setStatus("Adding " + code + "…");
      var work = navigator.onLine ? addOnline(code) : Promise.resolve(addOffline(code));
      work.then(function () {
        setStatus("Scan the next product, or tap Done.");
        setTimeout(function () { busy = false; }, 500);
      });
    }

    function close(showCart) {
      if (closed) return;
      closed = true;
      var stopping = engine ? engine.stop() : Promise.resolve();
      stopping.then(function () {
        ui.overlay.remove();
        if (cartChanged && navigator.onLine) {
          if (showCart) sessionStorage.setItem("vilaScanOpenCart", "1");
          window.location.reload();
        }
      });
    }

    ui.cancel.addEventListener("click", function () { close(false); });
    ui.done.addEventListener("click", function () { close(true); });

    if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus("Camera needs a secure (https) connection and a browser with camera support.");
      return;
    }

    loadLibrary().then(function (hasLibrary) {
      if (closed) return;
      if (hasLibrary) {
        engine = libraryEngine(ui, handleCode);
      } else if ("BarcodeDetector" in window) {
        engine = nativeEngine(ui, handleCode);
      } else {
        setStatus("The scanner could not load. Check your internet connection and try again.");
        return;
      }
      engine.start()
        .then(function () { setStatus("Point the camera at a product barcode."); })
        .catch(function (err) { setStatus(cameraErrorMessage(err)); });
    });
  }

  function reopenCartAfterScan() {
    try {
      if (sessionStorage.getItem("vilaScanOpenCart") !== "1") return;
      sessionStorage.removeItem("vilaScanOpenCart");
    } catch (e) {
      return;
    }
    setTimeout(function () {
      var toggle = document.querySelector("[data-floating-cart-open]");
      if (toggle && !toggle.hidden) toggle.click();
    }, 0);
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest && event.target.closest("[data-camera-scan-open]");
    if (!button) return;
    var target = button.getAttribute("data-camera-scan-open");
    var form = target ? document.querySelector(target) : button.closest("form[data-camera-scan-form]");
    if (!form) return;
    event.preventDefault();
    openScanner(form);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", reopenCartAfterScan);
  } else {
    reopenCartAfterScan();
  }
})();
