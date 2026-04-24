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
    browserCoords: null,
    pickupCoords: null,
    dropoffCoords: null,
    availableRiders: [],
    activeRequest: null,
    estimate: null,
    lookupTimers: {},
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
    routeSummary: document.getElementById("deliveryRouteSummary"),
    mapFrame: document.getElementById("deliveryMapFrame"),
    mapPlaceholder: document.getElementById("deliveryMapPlaceholder"),
    mapLink: document.getElementById("deliveryMapLink"),
    pickupHint: document.getElementById("deliveryPickupHint"),
    dropoffHint: document.getElementById("deliveryDropoffHint"),
  };

  function getDistanceKm() {
    return Number(els.distance.value || 3);
  }

  function getPickupText() {
    return els.pickup.value.trim();
  }

  function getDropoffText() {
    return els.dropoff.value.trim();
  }

  function getPreviewPickupCoords() {
    return state.pickupCoords || state.browserCoords;
  }

  function getRequestPickupCoords() {
    return getPickupText() ? state.pickupCoords : state.browserCoords;
  }

  function requestBody(extra = {}) {
    const body = {
      pickup_address: getPickupText(),
      dropoff_address: getDropoffText(),
      customer_name: els.customerName.value.trim(),
      customer_phone: els.customerPhone.value.trim(),
      notes: els.notes.value.trim(),
      distance_km: getDistanceKm(),
      ...extra,
    };
    const pickupCoords = getRequestPickupCoords();
    if (pickupCoords) {
      body.pickup_lat = pickupCoords.latitude;
      body.pickup_lng = pickupCoords.longitude;
    }
    if (state.dropoffCoords) {
      body.dropoff_lat = state.dropoffCoords.latitude;
      body.dropoff_lng = state.dropoffCoords.longitude;
    }
    return body;
  }

  function buildMapState() {
    const pickup = getPickupText();
    const dropoff = getDropoffText();
    const focusCoords = state.dropoffCoords || getPreviewPickupCoords();

    if (pickup && dropoff) {
      return {
        embed: `https://maps.google.com/maps?saddr=${encodeURIComponent(pickup)}&daddr=${encodeURIComponent(dropoff)}&output=embed`,
        link: `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(pickup)}&destination=${encodeURIComponent(dropoff)}&travelmode=driving`,
        summary: `Previewing the route from ${pickup} to ${dropoff}.`,
      };
    }

    if (focusCoords) {
      return {
        embed: `https://maps.google.com/maps?q=${focusCoords.latitude},${focusCoords.longitude}&z=15&output=embed`,
        link: `https://www.google.com/maps?q=${focusCoords.latitude},${focusCoords.longitude}`,
        summary: pickup ? `Previewing pickup near ${pickup}.` : "Previewing your detected location.",
      };
    }

    if (pickup) {
      return {
        embed: `https://maps.google.com/maps?q=${encodeURIComponent(pickup)}&z=15&output=embed`,
        link: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(pickup)}`,
        summary: `Previewing pickup around ${pickup}.`,
      };
    }

    return {
      embed: "https://maps.google.com/maps?q=Nigeria&z=6&output=embed",
      link: "https://maps.google.com",
      summary: "Add a pickup and destination to preview the trip.",
    };
  }

  function updateRouteHints() {
    const pickup = getPickupText();
    const dropoff = getDropoffText();

    if (!pickup) {
      els.pickupHint.textContent = "Waiting for pickup details.";
    } else if (getRequestPickupCoords()) {
      els.pickupHint.textContent = "Pickup location is ready for rider matching.";
    } else {
      els.pickupHint.textContent = "Pickup address added. Use estimate to confirm the route.";
    }

    if (!dropoff) {
      els.dropoffHint.textContent = "Waiting for destination details.";
    } else if (state.dropoffCoords) {
      els.dropoffHint.textContent = "Destination is mapped and ready for pricing.";
    } else {
      els.dropoffHint.textContent = "Destination added. The map preview is using the typed address.";
    }
  }

  function updateMapPreview() {
    const mapState = buildMapState();
    if (els.routeSummary) {
      els.routeSummary.textContent = mapState.summary;
    }
    if (els.mapFrame) {
      els.mapFrame.src = mapState.embed;
    }
    if (els.mapLink) {
      els.mapLink.href = mapState.link;
    }
    if (els.mapPlaceholder) {
      const showPlaceholder = !getPickupText() && !getDropoffText() && !getPreviewPickupCoords();
      els.mapPlaceholder.classList.toggle("is-hidden", !showPlaceholder);
    }
  }

  async function geocodeAddress(query) {
    const response = await fetch(`https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=${encodeURIComponent(query)}`);
    if (!response.ok) {
      throw new Error("Address lookup is unavailable right now.");
    }
    const payload = await response.json();
    const match = payload && payload[0];
    if (!match) {
      return null;
    }
    return {
      latitude: Number(match.lat),
      longitude: Number(match.lon),
    };
  }

  async function reverseGeocode(latitude, longitude) {
    const response = await fetch(`https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${encodeURIComponent(latitude)}&lon=${encodeURIComponent(longitude)}`);
    if (!response.ok) {
      return null;
    }
    const payload = await response.json();
    return payload?.display_name || null;
  }

  async function resolveAddress(kind) {
    const value = kind === "pickup" ? getPickupText() : getDropoffText();
    if (!value || value.length < 5) {
      updateRouteHints();
      updateMapPreview();
      return;
    }

    try {
      const result = await geocodeAddress(value);
      if (kind === "pickup") {
        state.pickupCoords = result;
      } else {
        state.dropoffCoords = result;
      }
    } catch (error) {
      if (kind === "pickup") {
        state.pickupCoords = null;
      } else {
        state.dropoffCoords = null;
      }
    }

    updateRouteHints();
    updateMapPreview();
  }

  function queueAddressLookup(kind) {
    if (state.lookupTimers[kind]) {
      window.clearTimeout(state.lookupTimers[kind]);
    }
    state.lookupTimers[kind] = window.setTimeout(() => {
      resolveAddress(kind);
    }, 500);
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
      els.ridersList.innerHTML = '<div class="delivery-empty"><p>No riders found yet. Add a clearer pickup point or use current location for stronger matches.</p></div>';
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
    const pickupCoords = getRequestPickupCoords();
    if (pickupCoords) {
      params.set("pickup_lat", String(pickupCoords.latitude));
      params.set("pickup_lng", String(pickupCoords.longitude));
    }
    const response = await marketplaceApiRequest(`/api/marketplace/delivery/riders/?${params.toString()}`, { token });
    state.availableRiders = response.riders || [];
    renderRiders();
  }

  async function estimateDelivery() {
    if (!getPickupText() || !getDropoffText()) {
      throw new Error("Enter both pickup and destination before estimating.");
    }
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
    if (!getPickupText()) {
      throw new Error("Add a pickup address before requesting a rider.");
    }
    if (!getDropoffText()) {
      throw new Error("Add a dropoff address before requesting a rider.");
    }
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

  async function initLocation(applyToPickup = false) {
    if (!(navigator && navigator.geolocation)) {
      els.locationStatus.textContent = "Browser location unavailable";
      return false;
    }

    return new Promise((resolve) => {
      navigator.geolocation.getCurrentPosition(
        async (position) => {
          state.browserCoords = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          };
          els.locationStatus.textContent = "Location detected";

          if (applyToPickup) {
            state.pickupCoords = {
              latitude: position.coords.latitude,
              longitude: position.coords.longitude,
            };
            if (!getPickupText()) {
              els.pickup.value = "Current location";
            }
            const address = await reverseGeocode(position.coords.latitude, position.coords.longitude).catch(() => null);
            if (address) {
              els.pickup.value = address;
            }
          }

          updateRouteHints();
          updateMapPreview();
          resolve(true);
        },
        () => {
          els.locationStatus.textContent = "Location permission denied";
          resolve(false);
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 10000 }
      );
    });
  }

  els.useCurrentLocation?.addEventListener("click", async () => {
    try {
      await initLocation(true);
      await loadRiders();
      if (getDropoffText()) {
        await estimateDelivery();
      }
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
      if (getPickupText() && getDropoffText()) {
        await estimateDelivery();
      }
      await loadActiveRequest();
    } catch (error) {
      marketplaceToast(error.message);
    }
  });

  els.pickup?.addEventListener("input", () => {
    state.pickupCoords = null;
    updateRouteHints();
    updateMapPreview();
    queueAddressLookup("pickup");
  });

  els.dropoff?.addEventListener("input", () => {
    state.dropoffCoords = null;
    updateRouteHints();
    updateMapPreview();
    queueAddressLookup("dropoff");
  });

  els.distance?.addEventListener("change", async () => {
    if (!getPickupText()) {
      return;
    }
    try {
      await loadRiders();
      if (getDropoffText()) {
        await estimateDelivery();
      }
    } catch (error) {
      marketplaceToast(error.message);
    }
  });

  updateRouteHints();
  updateMapPreview();
  renderRiders();
  renderActiveRequest();
  initLocation();
}

function initRiderWorkspaceApp(app) {
  const token = app.dataset.token || "";
  const state = {
    requests: [],
    companyRiders: [],
    liveCoords: null,
    selectedRequestId: "",
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
    mapFrame: document.getElementById("riderMapFrame"),
    mapLink: document.getElementById("riderMapLink"),
    mapSummary: document.getElementById("riderMapSummary"),
    mapPlaceholder: document.getElementById("riderMapPlaceholder"),
    mapHint: document.getElementById("riderMapHint"),
  };

  function switchTab(tabId) {
    els.tabs.forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.riderTab === tabId);
    });
    if (els.personalPanel) {
      els.personalPanel.classList.toggle("is-hidden", tabId !== "personal");
    }
    if (els.companyPanel) {
      els.companyPanel.classList.toggle("is-hidden", tabId !== "company");
    }
  }

  function getSelectedRequest() {
    return state.requests.find((request) => request.public_id === state.selectedRequestId) || null;
  }

  function buildRiderMapState() {
    const selectedRequest = getSelectedRequest();
    if (selectedRequest) {
      return {
        embed: `https://maps.google.com/maps?saddr=${encodeURIComponent(selectedRequest.pickup_address)}&daddr=${encodeURIComponent(selectedRequest.dropoff_address)}&output=embed`,
        link: `https://www.google.com/maps/dir/?api=1&origin=${encodeURIComponent(selectedRequest.pickup_address)}&destination=${encodeURIComponent(selectedRequest.dropoff_address)}&travelmode=driving`,
        summary: `Previewing route from ${selectedRequest.pickup_address} to ${selectedRequest.dropoff_address}.`,
        hint: `Selected request is ${selectedRequest.status_label}.`,
      };
    }

    if (state.liveCoords) {
      return {
        embed: `https://maps.google.com/maps?q=${state.liveCoords.latitude},${state.liveCoords.longitude}&z=15&output=embed`,
        link: `https://www.google.com/maps?q=${state.liveCoords.latitude},${state.liveCoords.longitude}`,
        summary: "Previewing your current rider area.",
        hint: "Live rider location is active.",
      };
    }

    return {
      embed: "https://maps.google.com/maps?q=Nigeria&z=6&output=embed",
      link: "https://maps.google.com",
      summary: "Your live rider area will appear here, then you can click a request to inspect its route.",
      hint: "Waiting for live rider location.",
    };
  }

  function updateRiderMap() {
    const mapState = buildRiderMapState();
    if (els.mapFrame) {
      els.mapFrame.src = mapState.embed;
    }
    if (els.mapLink) {
      els.mapLink.href = mapState.link;
    }
    if (els.mapSummary) {
      els.mapSummary.textContent = mapState.summary;
    }
    if (els.mapHint) {
      els.mapHint.textContent = mapState.hint;
    }
    if (els.mapPlaceholder) {
      els.mapPlaceholder.classList.toggle("is-hidden", Boolean(state.liveCoords || getSelectedRequest()));
    }
  }

  function renderRequests() {
    if (!state.requests.length) {
      els.requestsList.innerHTML = '<div class="delivery-empty"><p>No rider requests available yet.</p></div>';
      state.selectedRequestId = "";
      updateRiderMap();
      return;
    }
    if (!getSelectedRequest()) {
      state.selectedRequestId = state.requests[0].public_id;
    }
    els.requestsList.innerHTML = state.requests
      .map((request) => `
        <article class="delivery-list-item rider-request-card ${state.selectedRequestId === request.public_id ? "is-selected" : ""}" data-request-focus="${request.public_id}">
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

    els.requestsList.querySelectorAll("[data-request-focus]").forEach((row) => {
      row.addEventListener("click", (event) => {
        if (event.target.closest("button")) {
          return;
        }
        state.selectedRequestId = row.dataset.requestFocus;
        renderRequests();
      });
    });

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

    updateRiderMap();
  }

  function renderStatusButton(request, status, label) {
    if (request.status === status) {
      return `<span class="delivery-mini-pill">${label}</span>`;
    }
    return `<button type="button" class="btn btn-outline btn-sm" data-public-id="${request.public_id}" data-request-status="${status}">${label}</button>`;
  }

  function renderCompanyRiders() {
    if (!els.companyRidersList) {
      return;
    }
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
    if (!els.companyRidersList) {
      return;
    }
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
        state.liveCoords = {
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
        };
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
          updateRiderMap();
        } catch (error) {
          els.locationStatus.textContent = error.message;
        }
      },
      () => {
        els.locationStatus.textContent = "Location permission denied";
        updateRiderMap();
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
  updateRiderMap();
  loadRequests().catch((error) => {
    els.requestsList.innerHTML = `<div class="delivery-empty"><p>${error.message}</p></div>`;
  });
  if (els.companyRidersList) {
    loadCompanyRiders().catch((error) => {
      els.companyRidersList.innerHTML = `<div class="delivery-empty"><p>${error.message}</p></div>`;
    });
  }
}
