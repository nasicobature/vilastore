function notify(message) {
    if (typeof showToast === "function") {
        showToast(message);
        return;
    }
    alert(message);
}

function startSubscriptionPayment() {
    const paystackKey = (window.PAYSTACK_PUBLIC_KEY || "").trim();
    if (!paystackKey) {
        notify("Paystack public key is missing. Please configure PAYSTACK_PUBLIC_KEY.");
        return;
    }

    const email = (window.SUBSCRIPTION_EMAIL || "").trim();
    if (!email) {
        notify("Account email is missing.");
        return;
    }

    const amount = Number(window.SUBSCRIPTION_AMOUNT_KOBO || 0);
    if (!amount || amount <= 0) {
        notify("Payment amount is missing.");
        return;
    }

    if (typeof PaystackPop === "undefined" || typeof PaystackPop.setup !== "function") {
        notify("Paystack library not loaded.");
        return;
    }

    const handler = PaystackPop.setup({
        key: paystackKey,
        email: email,
        amount: amount,
        currency: "NGN",
        callback: function (response) {
            const refInput = document.getElementById("subscriptionPaymentReference");
            if (refInput) {
                refInput.value = response.reference || "";
            }
            document.getElementById("subscriptionPaymentForm")?.submit();
        },
        onClose: function () {
            notify("Payment was cancelled.");
        }
    });

    handler.openIframe();
}

document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("startSubscriptionPayment")?.addEventListener("click", function (event) {
        event.preventDefault();
        startSubscriptionPayment();
    });

    if (window.lucide && typeof window.lucide.createIcons === "function") {
        window.lucide.createIcons();
    }
});
