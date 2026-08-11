# WhatsApp Data Subscription Bot

This app adds a WhatsApp bot for selling mobile data and wallet-funded reseller transactions.

## URLs

- WhatsApp webhook: `/whatsapp-bot/webhook/whatsapp/`
- Payment webhook: `/whatsapp-bot/webhook/payment/`
- Data plans API: `/whatsapp-bot/api/data-plans/`
- Transaction history API: `/whatsapp-bot/api/transactions/?phone=2348012345678`

## Environment Variables

Put these in Render environment variables and in local `.env` for development:

```env
WHATSAPP_VERIFY_TOKEN=your_webhook_verify_token
WHATSAPP_ACCESS_TOKEN=your_whatsapp_cloud_api_access_token
WHATSAPP_PHONE_NUMBER_ID=your_whatsapp_phone_number_id

PAYMENT_WEBHOOK_SECRET=your_payment_webhook_secret
PAYMENT_CHECKOUT_URL=https://your-payment-page.example/checkout

VTU_API_URL=https://your-vtu-provider.example/api/data
VTU_API_KEY=your_vtu_api_key
```

## Admin Setup

Use Django Admin to add data plans:

- Network: MTN, Airtel, Glo, or 9mobile
- Plan name, size, validity
- VTU plan code
- Cost price
- Normal user price
- Reseller price

Reseller applications appear under `Reseller profiles`; approve them from admin.

## MVP Flow

User sends `Hi`, the bot sends the menu. The first complete flow is:

`Buy Data -> Network -> Plan -> Recipient -> Confirm -> Wallet deduction -> VTU API -> Transaction saved`

If the VTU API fails, the wallet is refunded automatically and the failed transaction is saved for admin retry.
