function marketplaceMoney(value) {
  const amount = Number(value || 0);
  return `NGN ${amount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function marketplaceToast(message) {
  window.alert(message);
}

async function marketplaceApiRequest(path, { method = "GET", token = "", body, formData } = {}) {
  const headers = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (!formData) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(path, {
    method,
    headers,
    body: formData ? formData : body ? JSON.stringify(body) : undefined,
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) {
    throw new Error(payload.error || "Something went wrong.");
  }
  return payload;
}

function renderLucide() {
  if (window.lucide && typeof window.lucide.createIcons === "function") {
    window.lucide.createIcons();
  }
}

document.addEventListener("DOMContentLoaded", () => {
  renderLucide();

  const buyerHomeApp = document.getElementById("buyerDeliveryApp");
  if (buyerHomeApp) {
    initBuyerDeliveryApp(buyerHomeApp);
  }

  const riderWorkspaceApp = document.getElementById("riderWorkspaceApp");
  if (riderWorkspaceApp) {
    initRiderWorkspaceApp(riderWorkspaceApp);
  }
});

function initBuyerDeliveryApp(app) {
  const token = app.dataset.token || "";
  const state = {
    coords: null,
    availableRiders: [],
    activeRequest: null,
    estimate: null,
  };

  const els = {
    pickup: document.getElementById("deliveryPickupAddress"),
    dropoff: document.getElementById("deliveryDropoffAddress"),
    customerName: document.getElementById("deliveryCustomerName"),
    customerPhone: document.getElementById("deliveryCustomerPhone"),
    notes: document.getElementById("deliveryNotes"),
    distance: document.getElementById("deliveryDistanceKm"),
    locationStatus: document.getElementById("deliveryLocationStatus"),
    ridersList: document.getElementById("deliveryRidersList"),
    price: document.getElementById("deliveryPrice"),
    routeDistance: document.getElementById("deliveryRouteDistance"),
    suggestedRider: document.getElementById("deliverySuggestedRider"),
    breakdown: document.getElementById("deliveryPricingBreakdown"),
    activeDeliveryCard: document.getElementById("activeDeliveryCard"),
    useCurrentLocation: document.getElementById("deliveryUseCurrentLocation"),
    estimateButton: document.getElementById("deliveryEstimateButton"),
    submitButton: document.getElementById("deliverySubmitButton"),
    refreshButton: app.querySelector('[data-action="refresh-delivery-home"]'),
  };

  function getDistanceKm() {
    return Number(els.distance.value || 3);
  }

  function requestBody(extra = {}) {
    const body = {
      pickup_address: els.pickup.value.trim(),
      dropoff_address: els.dropoff.value.trim(),
      customer_name: els.customerName.value.trim(),
      customer_phone: els.customerPhone.value.trim(),
      notes: els.notes.value.trim(),
      distance_km: getDistanceKm(),
      ...extra,
    };
    if (state.coords) {
      body.pickup_lat = state.coords.latitude;
      body.pickup_lng = state.coords.longitude;
    }
    return body;
  }

  function renderEstimate(estimate) {
    state.estimate = estimate;
    els.price.textContent = marketplaceMoney(estimate?.price || 0);
    els.routeDistance.textContent = `${Number(estimate?.distance_km || getDistanceKm()).toFixed(2)} km`;
    const rider = state.availableRiders[0];
    els.suggestedRider.textContent = rider ? rider.full_name : "Unassigned";
    if (!estimate?.pricing) {
      els.breakdown.innerHTML = "";
      return;
    }
    els.breakdown.innerHTML = `
      <div class="delivery-breakdown-row"><span>Base fare</span><strong>${marketplaceMoney(estimate.pricing.base_fare)}</strong></div>
      <div class="delivery-breakdown-row"><span>Distance fee</span><strong>${marketplaceMoney(estimate.pricing.distance_fee)}</strong></div>
      <div class="delivery-breakdown-row"><span>Fuel surcharge</span><strong>${marketplaceMoney(estimate.pricing.fuel_surcharge)}</strong></div>
      <div class="delivery-breakdown-row"><span>Surge multiplier</span><strong>${estimate.pricing.surge_multiplier}x</strong></div>
    `;
  }

  function renderRiders() {
    if (!state.availableRiders.length) {
      els.ridersList.innerHTML = '<div class="delivery-empty"><p>No riders found yet. Turn on location or request without assigning one.</p></div>';
      return;
    }
    els.ridersList.innerHTML = state.availableRiders
      .map((rider, index) => `
        <article class="delivery-list-item ${index === 0 ? "is-selected" : ""}" data-rider-id="${rider.id}">
          <div>
            <strong>${rider.full_name}</strong>
            <p>${rider.vehicle_type || "Vehicle pending"}${rider.vehicle_model ? ` - ${rider.vehicle_model}` : ""}</p>
            <p>${rider.phone || "Direct calling disabled"}</p>
          </div>
          <div class="delivery-list-meta">
            <strong>${rider.distance_km != null ? `${Number(rider.distance_km).toFixed(2)} km` : "Nearby"}</strong>
            <span>${rider.rider_type || "personal"}</span>
          </div>
        </article>
      `)
      .join("");
  }

  function renderActiveRequest() {
    if (!state.activeRequest) {
      els.activeDeliveryCard.innerHTML = '<p>No active delivery yet.</p>';
      return;
    }
    const riderName = state.activeRequest.rider?.full_name || "Waiting for rider";
    const riderPhone = state.activeRequest.rider?.phone || "Phone hidden";
    els.activeDeliveryCard.innerHTML = `
      <strong>${state.activeRequest.pickup_address}</strong>
      <p>To ${state.activeRequest.dropoff_address}</p>
      <p>Status: ${state.activeRequest.status_label}</p>
      <p>Rider: ${riderName}</p>
      <p>Contact: ${riderPhone}</p>
      <p>Price: ${marketplaceMoney(state.activeRequest.price)}</p>
    `;
  }

  async function loadRiders() {
    const params = new URLSearchParams();
    params.set("max_distance_km", String(getDistanceKm()));
    if (state.coords) {
      params.set("pickup_lat", String(state.coords.latitude));
      params.set("pickup_lng", String(state.coords.longitude));
    }
    const response = await marketplaceApiRequest(`/api/marketplace/delivery/riders/?${params.toString()}`, { token });
    state.availableRiders = response.riders || [];
    renderRiders();
  }

  async function estimateDelivery() {
    const response = await marketplaceApiRequest("/api/marketplace/delivery/estimate/", {
      method: "POST",
      token,
      body: requestBody(),
    });
    renderEstimate(response);
  }

  async function loadActiveRequest() {
    if (!state.activeRequest?.public_id) {
      renderActiveRequest();
      return;
    }
    const response = await marketplaceApiRequest(`/api/marketplace/delivery/requests/${state.activeRequest.public_id}/`, { token });
    state.activeRequest = response.request;
    renderActiveRequest();
  }

  async function submitDeliveryRequest() {
    const chosenRider = state.availableRiders[0];
    const response = await marketplaceApiRequest("/api/marketplace/delivery/requests/", {
      method: "POST",
      token,
      body: requestBody({
        rider_id: chosenRider ? chosenRider.id : "",
      }),
    });
    state.activeRequest = response.request;
    renderActiveRequest();
    marketplaceToast("Delivery request created successfully.");
  }

  function initLocation() {
    if (!(navigator && navigator.geolocation)) {
      els.locationStatus.textContent = "Browser location unavailable";
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        state.coords = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
        els.locationStatus.textContent = "Location detected";
      },
      () => {
        els.locationStatus.textContent = "Location permission denied";
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 }
    );
  }

  els.useCurrentLocation?.addEventListener("click", async () => {
    initLocation();
    try {
      await loadRiders();
      await estimateDelivery();
    } catch (error) {
      marketplaceToast(error.message);
    }
  });

  els.estimateButton?.addEventListener("click", async () => {
    try {
      await loadRiders();
      await estimateDelivery();
    } catch (error) {
      marketplaceToast(error.message);
    }
  });

  els.submitButton?.addEventListener("click", async () => {
    try {
      if (!state.estimate) {
        await estimateDelivery();
      }
      if (!state.availableRiders.length) {
        await loadRiders();
      }
      await submitDeliveryRequest();
    } catch (error) {
      marketplaceToast(error.message);
    }
  });

  els.refreshButton?.addEventListener("click", async () => {
    try {
      await loadRiders();
      await estimateDelivery();
      await loadActiveRequest();
    } catch (error) {
      marketplaceToast(error.message);
    }
  });

  initLocation();
  loadRiders().catch(() => {});
  estimateDelivery().catch(() => {});
}

function initRiderWorkspaceApp(app) {
  const token = app.dataset.token || "";
  const state = {
    requests: [],
    companyRiders: [],
  };

  const els = {
    locationStatus: document.getElementById("riderWorkspaceLocationStatus"),
    personalPanel: document.getElementById("riderPersonalPanel"),
    companyPanel: document.getElementById("riderCompanyPanel"),
    tabs: Array.from(document.querySelectorAll("[data-rider-tab]")),
    requestsList: document.getElementById("riderRequestsList"),
    companyRidersList: document.getElementById("companyRidersList"),
    riderRegisterButton: document.getElementById("riderRegisterButton"),
    riderRefreshRequestsButton: document.getElementById("riderRefreshRequestsButton"),
    companySaveButton: document.getElementById("companySaveButton"),
    companyAddRiderButton: document.getElementById("companyAddRiderButton"),
  };

  function switchTab(tabId) {
    els.tabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.riderTab === tabId);
    });
    els.personalPanel.classList.toggle("is-hidden", tabId !== "personal");
    els.companyPanel.classList.toggle("is-hidden", tabId !== "company");
  }

  function renderRequests() {
    if (!state.requests.length) {
      els.requestsList.innerHTML = '<div class="delivery-empty"><p>No rider requests available yet.</p></div>';
      return;
    }
    els.requestsList.innerHTML = state.requests
      .map((request) => `
        <article class="delivery-list-item">
          <div>
            <strong>${request.pickup_address}</strong>
            <p>To ${request.dropoff_address}</p>
            <p>Status: ${request.status_label}</p>
          </div>
          <div class="delivery-list-meta">
            <strong>${marketplaceMoney(request.price)}</strong>
            <div class="delivery-inline-actions">
              ${renderStatusButton(request, "accepted", "Accept")}
              ${renderStatusButton(request, "picked_up", "Picked Up")}
              ${renderStatusButton(request, "delivered", "Delivered")}
              ${renderStatusButton(request, "cancelled", "Cancel")}
            </div>
          </div>
        </article>
      `)
      .join("");

    els.requestsList.querySelectorAll("[data-request-status]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await marketplaceApiRequest(`/api/marketplace/delivery/rider/requests/${button.dataset.publicId}/status/`, {
            method: "POST",
            token,
            body: { status: button.dataset.requestStatus },
          });
          await loadRequests();
        } catch (error) {
          marketplaceToast(error.message);
        }
      });
    });
  }

  function renderStatusButton(request, status, label) {
    if (request.status === status) {
      return `<span class="delivery-mini-pill">${label}</span>`;
    }
    return `<button type="button" class="btn btn-outline btn-sm" data-public-id="${request.public_id}" data-request-status="${status}">${label}</button>`;
  }

  function renderCompanyRiders() {
    if (!state.companyRiders.length) {
      els.companyRidersList.innerHTML = '<div class="delivery-empty"><p>No company riders yet.</p></div>';
      return;
    }
    els.companyRidersList.innerHTML = state.companyRiders
      .map((rider) => `
        <article class="delivery-list-item">
          <div>
            <strong>${rider.full_name || rider.email}</strong>
            <p>${rider.phone || "-"}</p>
            <p>${rider.email}</p>
          </div>
          <div class="delivery-list-meta">
            <strong>${rider.is_approved ? "Approved" : "Pending"}</strong>
            <div class="delivery-inline-actions">
              ${rider.is_approved ? "" : `<button type="button" class="btn btn-secondary btn-sm" data-company-approve="${rider.id}">Approve</button>`}
              <button type="button" class="btn btn-outline btn-sm" data-company-remove="${rider.id}">Remove</button>
            </div>
          </div>
        </article>
      `)
      .join("");

    els.companyRidersList.querySelectorAll("[data-company-approve]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await marketplaceApiRequest(`/api/marketplace/delivery/company/riders/${button.dataset.companyApprove}/approve/`, {
            method: "POST",
            token,
          });
          await loadCompanyRiders();
        } catch (error) {
          marketplaceToast(error.message);
        }
      });
    });

    els.companyRidersList.querySelectorAll("[data-company-remove]").forEach((button) => {
      button.addEventListener("click", async () => {
        try {
          await marketplaceApiRequest(`/api/marketplace/delivery/company/riders/${button.dataset.companyRemove}/remove/`, {
            method: "POST",
            token,
          });
          await loadCompanyRiders();
        } catch (error) {
          marketplaceToast(error.message);
        }
      });
    });
  }

  async function loadRequests() {
    const response = await marketplaceApiRequest("/api/marketplace/delivery/rider/requests/", { token });
    state.requests = response.requests || [];
    renderRequests();
  }

  async function loadCompanyRiders() {
    const response = await marketplaceApiRequest("/api/marketplace/delivery/company/riders/", { token });
    state.companyRiders = response.riders || [];
    renderCompanyRiders();
  }

  function riderFormData() {
    const formData = new FormData();
    formData.append("full_name", document.getElementById("riderFullName").value.trim());
    formData.append("phone", document.getElementById("riderPhone").value.trim());
    formData.append("email", document.getElementById("riderEmail").value.trim());
    formData.append("home_address", document.getElementById("riderHomeAddress").value.trim());
    formData.append("id_type", document.getElementById("riderIdType").value);
    formData.append("id_number", document.getElementById("riderIdNumber").value.trim());
    formData.append("vehicle_type", document.getElementById("riderVehicleType").value);
    formData.append("plate_number", document.getElementById("riderPlateNumber").value.trim());
    formData.append("vehicle_color", document.getElementById("riderVehicleColor").value.trim());
    formData.append("vehicle_model", document.getElementById("riderVehicleModel").value.trim());
    formData.append("city", document.getElementById("riderCity").value.trim());
    formData.append("operating_areas", document.getElementById("riderOperatingAreas").value.trim());
    formData.append("bank_name", document.getElementById("riderBankName").value.trim());
    formData.append("account_number", document.getElementById("riderAccountNumber").value.trim());
    formData.append("account_name", document.getElementById("riderAccountName").value.trim());
    formData.append("allow_direct_call", document.getElementById("riderAllowDirectCall").checked ? "true" : "false");
    formData.append("terms_accepted", document.getElementById("riderTermsAccepted").checked ? "true" : "false");

    const fileFields = [
      ["profile_photo", "riderProfilePhoto"],
      ["vehicle_photo", "riderVehiclePhoto"],
      ["plate_photo", "riderPlatePhoto"],
      ["id_document", "riderIdDocument"],
    ];

    fileFields.forEach(([fieldName, inputId]) => {
      const file = document.getElementById(inputId).files[0];
      if (file) {
        formData.append(fieldName, file);
      }
    });

    return formData;
  }

  async function saveRiderProfile() {
    await marketplaceApiRequest("/api/marketplace/delivery/rider/register/", {
      method: "POST",
      token,
      formData: riderFormData(),
    });
    marketplaceToast("Rider profile saved.");
    await loadRequests();
  }

  async function saveCompanyProfile() {
    await marketplaceApiRequest("/api/marketplace/delivery/company/profile/", {
      method: "POST",
      token,
      body: {
        company_name: document.getElementById("companyName").value.trim(),
        phone: document.getElementById("companyPhone").value.trim(),
        email: document.getElementById("companyEmail").value.trim(),
        address: document.getElementById("companyAddress").value.trim(),
        city: document.getElementById("companyCity").value.trim(),
        operating_areas: document.getElementById("companyAreas").value.trim(),
        bank_name: document.getElementById("companyBankName").value.trim(),
        account_number: document.getElementById("companyAccountNumber").value.trim(),
        account_name: document.getElementById("companyAccountName").value.trim(),
        terms_accepted: document.getElementById("companyTermsAccepted").checked,
      },
    });
    marketplaceToast("Company profile saved.");
    await loadCompanyRiders();
  }

  async function addCompanyRider() {
    await marketplaceApiRequest("/api/marketplace/delivery/company/riders/", {
      method: "POST",
      token,
      body: {
        full_name: document.getElementById("companyRiderName").value.trim(),
        phone: document.getElementById("companyRiderPhone").value.trim(),
        email: document.getElementById("companyRiderEmail").value.trim(),
        password: document.getElementById("companyRiderPassword").value,
        allow_direct_call: true,
      },
    });
    marketplaceToast("Company rider added.");
    document.getElementById("companyRiderName").value = "";
    document.getElementById("companyRiderPhone").value = "";
    document.getElementById("companyRiderEmail").value = "";
    document.getElementById("companyRiderPassword").value = "";
    await loadCompanyRiders();
  }

  function initLocationUpdates() {
    if (!(navigator && navigator.geolocation)) {
      els.locationStatus.textContent = "Browser location unavailable";
      return;
    }

    navigator.geolocation.watchPosition(
      async (position) => {
        els.locationStatus.textContent = "Location updating";
        try {
          await marketplaceApiRequest("/api/marketplace/delivery/rider/location/", {
            method: "POST",
            token,
            body: {
              lat: position.coords.latitude,
              lng: position.coords.longitude,
              is_available: true,
            },
          });
          els.locationStatus.textContent = "Live rider location active";
        } catch (error) {
          els.locationStatus.textContent = error.message;
        }
      },
      () => {
        els.locationStatus.textContent = "Location permission denied";
      },
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 }
    );
  }

  els.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      switchTab(tab.dataset.riderTab);
      if (tab.dataset.riderTab === "company") {
        loadCompanyRiders().catch(() => {});
      }
    });
  });

  els.riderRegisterButton?.addEventListener("click", () => {
    saveRiderProfile().catch((error) => marketplaceToast(error.message));
  });

  els.riderRefreshRequestsButton?.addEventListener("click", () => {
    loadRequests().catch((error) => marketplaceToast(error.message));
  });

  els.companySaveButton?.addEventListener("click", () => {
    saveCompanyProfile().catch((error) => marketplaceToast(error.message));
  });

  els.companyAddRiderButton?.addEventListener("click", () => {
    addCompanyRider().catch((error) => marketplaceToast(error.message));
  });

  initLocationUpdates();
  loadRequests().catch((error) => {
    els.requestsList.innerHTML = `<div class="delivery-empty"><p>${error.message}</p></div>`;
  });
  loadCompanyRiders().catch((error) => {
    els.companyRidersList.innerHTML = `<div class="delivery-empty"><p>${error.message}</p></div>`;
  });
}
