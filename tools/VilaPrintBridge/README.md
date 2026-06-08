# VilaPrintBridge

Local ESC/POS bridge for VilaStore web receipt printing.

Browsers cannot silently print raw ESC/POS commands to USB or Windows thermal printers. Run this bridge on the same computer as the printer, then choose the printer in VilaStore Settings.

## Start

Double-click:

```text
start-vila-print-bridge.bat
```

The bridge listens on:

```text
http://127.0.0.1:8787
```

## Notes

- Supports 58mm ESC/POS receipts.
- Use the Windows printer name shown in Settings.
- If the bridge is not running, VilaStore falls back to the browser print dialog with 58mm formatting.
