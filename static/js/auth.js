let currentStep = 1;
let emailVerified = false;
let paymentReady = false;

function notify(message) {
    if (typeof showToast === "function") {
        showToast(message);
        return;
    }
    alert(message);
}

function showStep(step) {
    const safeStep = Math.max(1, Math.min(3, Number(step) || 1));
    currentStep = safeStep;

    document.querySelectorAll(".form-step").forEach((el) => {
        el.classList.toggle("active", Number(el.dataset.step) === safeStep);
    });

    document.querySelectorAll(".step").forEach((el) => {
        const stepNumber = Number(el.dataset.step);
        el.classList.toggle("active", stepNumber === safeStep);
        el.classList.toggle("completed", stepNumber < safeStep);
    });
}

function goToStep(step) {
    showStep(step);
}

function getSelectedPlan() {
    return document.querySelector('input[name="plan"]:checked')?.value || "starter";
}

function getPlanAmount(plan) {
    const prices = {
        starter: 1000,
        growth: 5000,
        business: 15000,
        pro: 50000,
    };
    return prices[plan] || prices.starter;
}

function startFlutterwavePayment() {
    const flutterwaveKey = (window.FLUTTERWAVE_PUBLIC_KEY || "").trim();
    if (!flutterwaveKey) {
        notify("Flutterwave public key is missing. Please configure FLUTTERWAVE_PUBLIC_KEY.");
        return;
    }

    const emailInput = document.getElementById("signupEmail");
    const email = ((emailInput && emailInput.value) || window.SIGNUP_EMAIL || "").trim();
    if (!email) {
        notify("Signup email is missing.");
        return;
    }

    const plan = getSelectedPlan();
    const amount = getPlanAmount(plan);

    if (typeof FlutterwaveCheckout !== "function") {
        notify("Flutterwave checkout library not loaded.");
        return;
    }

    const txRef = `VILASTORE-SIGNUP-${Date.now()}-${Math.floor(Math.random() * 1000000)}`;
    FlutterwaveCheckout({
        public_key: flutterwaveKey,
        tx_ref: txRef,
        amount: amount,
        currency: "NGN",
        payment_options: "card,banktransfer,ussd",
        customer: {
            email: email,
            name: "VilaStore customer",
        },
        customizations: {
            title: "VilaStore Subscription",
            description: `${plan} plan subscription`,
            logo: window.VILASTORE_LOGO_URL || "",
        },
        callback: function (response) {
            const refInput = document.getElementById("paymentReferenceInput");
            if (refInput) {
                refInput.value = response.transaction_id || response.id || "";
            }
            paymentReady = true;
            document.getElementById("shopSetupForm")?.submit();
        },
        onclose: function () {
            notify("Payment was cancelled.");
        }
    });
}

function validateAccountForm(event) {
    const username = (document.getElementById("signupUsername")?.value || "").trim();
    const password = document.getElementById("signupPassword")?.value || "";
    const confirmPassword = document.getElementById("signupConfirmPassword")?.value || "";

    const usernameOk = /^[A-Za-z0-9._-]{3,30}$/.test(username);
    if (!usernameOk) {
        event.preventDefault();
        notify("Username must be 3-30 characters and use only letters, numbers, dot, dash, or underscore.");
        return;
    }

    if (password !== confirmPassword) {
        event.preventDefault();
        notify("Passwords do not match.");
        return;
    }

    const hasUpper = /[A-Z]/.test(password);
    const hasNumber = /[0-9]/.test(password);
    const hasSpecial = /[^A-Za-z0-9]/.test(password);
    if (!(hasUpper && hasNumber && hasSpecial)) {
        event.preventDefault();
        notify("Password must include uppercase, number, and special character.");
    }
}

function validateVerifyForm(event) {
    const code = (document.getElementById("emailCodeInput")?.value || "").trim();
    if (!code) {
        event.preventDefault();
        notify("Enter the verification code.");
        return;
    }

    if (!/^\d{6}$/.test(code)) {
        event.preventDefault();
        notify("Verification code must be 6 digits.");
    }
}

function validateShopForm(event) {
    if (!emailVerified) {
        event.preventDefault();
        notify("Please verify your email before completing signup.");
        return;
    }
}

document.addEventListener("DOMContentLoaded", function () {
    currentStep = Number(window.CURRENT_STEP || 1);
    emailVerified = Boolean(window.EMAIL_VERIFIED);

    showStep(currentStep);

    document.getElementById("accountStepForm")?.addEventListener("submit", validateAccountForm);
    document.getElementById("verifyCodeForm")?.addEventListener("submit", validateVerifyForm);
    document.getElementById("shopSetupForm")?.addEventListener("submit", validateShopForm);

    if (window.lucide && typeof window.lucide.createIcons === "function") {
        window.lucide.createIcons();
    }
});

window.goToStep = goToStep;
window.startFlutterwavePayment = startFlutterwavePayment;
