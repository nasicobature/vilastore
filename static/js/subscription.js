function notify(message) {
    if (typeof showToast === "function") {
        showToast(message);
        return;
    }
    alert(message);
}

function startSubscriptionPayment() {
    const flutterwaveKey = (window.FLUTTERWAVE_PUBLIC_KEY || "").trim();
    if (!flutterwaveKey) {
        notify("Flutterwave public key is missing. Please configure FLUTTERWAVE_PUBLIC_KEY.");
        return;
    }
    if (!flutterwaveKey.startsWith("FLWPUBK")) {
        notify("Flutterwave public key is invalid. Use your FLWPUBK public key from Flutterwave.");
        return;
    }

    const email = (window.SUBSCRIPTION_EMAIL || "").trim();
    if (!email) {
        notify("Account email is missing.");
        return;
    }

    const amount = Number(window.SUBSCRIPTION_AMOUNT || 0);
    if (!amount || amount <= 0) {
        notify("Payment amount is missing.");
        return;
    }

    if (typeof FlutterwaveCheckout !== "function") {
        notify("Flutterwave checkout library not loaded.");
        return;
    }

    const txRef = `VILASTORE-${Date.now()}-${Math.floor(Math.random() * 1000000)}`;
    FlutterwaveCheckout({
        public_key: flutterwaveKey,
        tx_ref: txRef,
        amount: amount,
        currency: "NGN",
        payment_options: "card,banktransfer,ussd",
        customer: {
            email: email,
            name: window.SUBSCRIPTION_CUSTOMER_NAME || "VilaStore customer",
            phone_number: window.SUBSCRIPTION_PHONE || "",
        },
        customizations: {
            title: "VilaStore Subscription",
            description: window.SUBSCRIPTION_DESCRIPTION || "Subscription payment",
            logo: window.VILASTORE_LOGO_URL || "",
        },
        callback: function (response) {
            const refInput = document.getElementById("subscriptionPaymentReference");
            if (refInput) {
                refInput.value = response.transaction_id || response.id || response.tx_ref || txRef;
            }
            document.getElementById("subscriptionPaymentForm")?.submit();
        },
        onclose: function () {
            notify("Payment was cancelled.");
        }
    });
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
