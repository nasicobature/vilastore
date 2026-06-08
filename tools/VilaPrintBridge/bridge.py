import ctypes
import json
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = "127.0.0.1"
PORT = 8787
CHARS_PER_LINE_58MM = 32
PRINTER_ENUM_LOCAL = 0x00000002
PRINTER_ENUM_CONNECTIONS = 0x00000004


class DOC_INFO_1(ctypes.Structure):
    _fields_ = [
        ("pDocName", wintypes.LPWSTR),
        ("pOutputFile", wintypes.LPWSTR),
        ("pDatatype", wintypes.LPWSTR),
    ]


class PRINTER_INFO_4(ctypes.Structure):
    _fields_ = [
        ("pPrinterName", wintypes.LPWSTR),
        ("pServerName", wintypes.LPWSTR),
        ("Attributes", wintypes.DWORD),
    ]


winspool = ctypes.WinDLL("winspool.drv")
OpenPrinter = winspool.OpenPrinterW
OpenPrinter.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE), wintypes.LPVOID]
OpenPrinter.restype = wintypes.BOOL
ClosePrinter = winspool.ClosePrinter
ClosePrinter.argtypes = [wintypes.HANDLE]
ClosePrinter.restype = wintypes.BOOL
StartDocPrinter = winspool.StartDocPrinterW
StartDocPrinter.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(DOC_INFO_1)]
StartDocPrinter.restype = wintypes.DWORD
EndDocPrinter = winspool.EndDocPrinter
EndDocPrinter.argtypes = [wintypes.HANDLE]
EndDocPrinter.restype = wintypes.BOOL
StartPagePrinter = winspool.StartPagePrinter
StartPagePrinter.argtypes = [wintypes.HANDLE]
StartPagePrinter.restype = wintypes.BOOL
EndPagePrinter = winspool.EndPagePrinter
EndPagePrinter.argtypes = [wintypes.HANDLE]
EndPagePrinter.restype = wintypes.BOOL
WritePrinter = winspool.WritePrinter
WritePrinter.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
WritePrinter.restype = wintypes.BOOL
EnumPrinters = winspool.EnumPrintersW
EnumPrinters.argtypes = [
    wintypes.DWORD,
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.LPBYTE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.POINTER(wintypes.DWORD),
]
EnumPrinters.restype = wintypes.BOOL
GetDefaultPrinter = winspool.GetDefaultPrinterW
GetDefaultPrinter.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
GetDefaultPrinter.restype = wintypes.BOOL


def as_text(value):
    return str(value or "").replace("\r", " ").replace("\n", " ").strip()


def money(value, currency="NGN"):
    try:
        number = float(value or 0)
        return f"{currency} {number:,.2f}"
    except (TypeError, ValueError):
        return f"{currency} {value}"


def clean_escpos_text(value):
    replacements = {
        "\u20a6": "NGN ",
        "\u2013": "-",
        "\u2014": "-",
        "\u2022": "*",
    }
    text = as_text(value)
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.encode("cp437", errors="replace").decode("cp437")


def fit(text, width, align="left"):
    text = clean_escpos_text(text)
    if len(text) > width:
        text = text[: max(0, width - 1)] + "."
    if align == "right":
        return text.rjust(width)
    if align == "center":
        return text.center(width)
    return text.ljust(width)


def wrap(text, width):
    text = clean_escpos_text(text)
    lines = []
    current = ""
    for word in text.split():
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            while len(word) > width:
                lines.append(word[:width])
                word = word[width:]
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def line(left="", right="", width=CHARS_PER_LINE_58MM):
    left = clean_escpos_text(left)
    right = clean_escpos_text(right)
    space = width - len(left) - len(right)
    if space < 1:
        left = left[: max(0, width - len(right) - 1)]
        space = width - len(left) - len(right)
    return f"{left}{' ' * max(1, space)}{right}"


def receipt_to_escpos(receipt, *, test=False):
    width = CHARS_PER_LINE_58MM
    currency = receipt.get("currency") or "NGN"
    parts = [
        b"\x1b@",  # initialize
        b"\x1b\x74\x00",  # CP437
        b"\x1b\x61\x01",  # center
        b"\x1b\x45\x01",
        (fit(receipt.get("shop_name") or "VilaStore", width, "center") + "\n").encode("cp437", "replace"),
        b"\x1b\x45\x00",
    ]

    for field in ("address", "phone"):
        value = receipt.get(field)
        if value:
            for wrapped in wrap(value, width):
                parts.append((fit(wrapped, width, "center") + "\n").encode("cp437", "replace"))

    parts.extend([b"\x1b\x61\x00", (("-" * width) + "\n").encode("ascii")])
    parts.append((line("Receipt:", receipt.get("receipt_no") or "TEST", width) + "\n").encode("cp437", "replace"))
    parts.append((line("Date:", receipt.get("date") or "", width) + "\n").encode("cp437", "replace"))
    if receipt.get("handled_by"):
        parts.append((line("By:", receipt.get("handled_by"), width) + "\n").encode("cp437", "replace"))
    if receipt.get("customer"):
        parts.append((line("Customer:", receipt.get("customer"), width) + "\n").encode("cp437", "replace"))
    parts.append((("-" * width) + "\n").encode("ascii"))
    parts.append((f"{fit('ITEM', 16)}{fit('QTY', 4, 'right')}{fit('AMOUNT', 12, 'right')}\n").encode("cp437", "replace"))
    parts.append((("-" * width) + "\n").encode("ascii"))

    items = receipt.get("items") or []
    if not items and test:
        items = [{"name": "Test item", "quantity": "1", "total": "0.00"}]
    for item in items:
        name_lines = wrap(item.get("name") or "Item", 16)
        qty = as_text(item.get("quantity") or "1")
        total = money(item.get("total"), currency)
        parts.append((f"{fit(name_lines[0], 16)}{fit(qty, 4, 'right')}{fit(total, 12, 'right')}\n").encode("cp437", "replace"))
        for extra in name_lines[1:]:
            parts.append((fit(extra, width) + "\n").encode("cp437", "replace"))

    parts.append((("-" * width) + "\n").encode("ascii"))
    parts.append(b"\x1b\x45\x01")
    parts.append((line("TOTAL", money(receipt.get("total"), currency), width) + "\n").encode("cp437", "replace"))
    parts.append(b"\x1b\x45\x00")
    if receipt.get("amount_paid"):
        parts.append((line("Paid", money(receipt.get("amount_paid"), currency), width) + "\n").encode("cp437", "replace"))
    if receipt.get("balance"):
        parts.append((line("Balance", money(receipt.get("balance"), currency), width) + "\n").encode("cp437", "replace"))
    parts.extend([
        (("-" * width) + "\n").encode("ascii"),
        b"\x1b\x61\x01",
        b"Thank you for shopping\n",
        b"VilaStore\n\n\n",
        b"\x1d\x56\x42\x00",  # partial cut, ignored by printers without cutter
    ])
    return b"".join(parts)


def raw_print(printer_name, data):
    if not printer_name:
        raise ValueError("Printer name is required.")
    handle = wintypes.HANDLE()
    if not OpenPrinter(printer_name, ctypes.byref(handle), None):
        raise OSError(f"Could not open printer: {printer_name}")
    try:
        info = DOC_INFO_1("VilaStore Receipt", None, "RAW")
        if not StartDocPrinter(handle, 1, ctypes.byref(info)):
            raise OSError("Could not start print job.")
        try:
            if not StartPagePrinter(handle):
                raise OSError("Could not start printer page.")
            written = wintypes.DWORD(0)
            buffer = ctypes.create_string_buffer(data)
            if not WritePrinter(handle, buffer, len(data), ctypes.byref(written)):
                raise OSError("Could not write receipt to printer.")
            EndPagePrinter(handle)
        finally:
            EndDocPrinter(handle)
    finally:
        ClosePrinter(handle)


def default_printer_name():
    needed = wintypes.DWORD(0)
    GetDefaultPrinter(None, ctypes.byref(needed))
    if needed.value <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(needed.value)
    if not GetDefaultPrinter(buffer, ctypes.byref(needed)):
        return ""
    return buffer.value


def list_printers():
    flags = PRINTER_ENUM_LOCAL | PRINTER_ENUM_CONNECTIONS
    needed = wintypes.DWORD(0)
    returned = wintypes.DWORD(0)
    EnumPrinters(flags, None, 4, None, 0, ctypes.byref(needed), ctypes.byref(returned))
    if needed.value <= 0:
        return []

    buffer = ctypes.create_string_buffer(needed.value)
    if not EnumPrinters(
        flags,
        None,
        4,
        ctypes.cast(buffer, wintypes.LPBYTE),
        needed,
        ctypes.byref(needed),
        ctypes.byref(returned),
    ):
        raise OSError("Unable to list Windows printers.")

    default_name = default_printer_name()
    printers = ctypes.cast(buffer, ctypes.POINTER(PRINTER_INFO_4))
    return [
        {
            "name": printers[index].pPrinterName,
            "is_default": printers[index].pPrinterName == default_name,
        }
        for index in range(returned.value)
        if printers[index].pPrinterName
    ]


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"{self.address_string()} - {format % args}")

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_json({"ok": True})

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        try:
            if self.path == "/health":
                self.send_json({"ok": True, "service": "VilaPrintBridge"})
            elif self.path == "/printers":
                self.send_json({"ok": True, "printers": list_printers()})
            else:
                self.send_json({"ok": False, "error": "Not found."}, 404)
        except Exception as error:
            self.send_json({"ok": False, "error": str(error)}, 500)

    def do_POST(self):
        try:
            payload = self.read_body()
            printer_name = payload.get("printer_name")
            if self.path == "/print":
                receipt = payload.get("receipt") or {}
                raw_print(printer_name, receipt_to_escpos(receipt))
                self.send_json({"ok": True})
            elif self.path == "/test-print":
                receipt = {
                    "shop_name": payload.get("shop_name") or "VilaStore",
                    "address": payload.get("address") or "",
                    "receipt_no": "TEST",
                    "date": "Test print",
                    "items": [{"name": "Printer test", "quantity": "1", "total": "0.00"}],
                    "total": "0.00",
                    "amount_paid": "0.00",
                    "balance": "0.00",
                    "currency": "NGN",
                }
                raw_print(printer_name, receipt_to_escpos(receipt, test=True))
                self.send_json({"ok": True})
            else:
                self.send_json({"ok": False, "error": "Not found."}, 404)
        except Exception as error:
            self.send_json({"ok": False, "error": str(error)}, 500)


def main():
    server = ThreadingHTTPServer((HOST, PORT), BridgeHandler)
    print(f"VilaPrintBridge running at http://{HOST}:{PORT}")
    print("Open VilaStore Settings, choose your 58mm printer, then send a test print.")
    server.serve_forever()


if __name__ == "__main__":
    main()
