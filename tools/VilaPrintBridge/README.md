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
- Finds installed Windows printers, paired Bluetooth/serial COM printers, and Wi-Fi/LAN ESC/POS printers with raw port `9100` on the same local network.
- Bluetooth thermal printers must be paired in Windows first so they appear as a printer or COM port.
- If the Windows printer driver says unavailable, use the direct connection fields in VilaStore Settings: enter the Wi-Fi printer IP address or Bluetooth COM port. This sends raw ESC/POS without the Windows printer driver.
- Chrome/Edge users can also try browser-direct printing from Settings: `Connect Browser Serial/USB` for USB or Bluetooth serial printers, or `Connect Browser Bluetooth` for BLE thermal printers.
- Use VilaStore Settings > Connect printer to scan, connect, test print, disconnect, and reconnect.
- If the bridge is not running, VilaStore falls back to the browser print dialog with 58mm formatting.
