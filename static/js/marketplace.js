// ===== MARKETPLACE JS (Server-backed) =====
document.addEventListener('DOMContentLoaded', function () {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  const form = document.getElementById('filterForm');
  const clearBtn = document.getElementById('clearFiltersBtn');
  const controls = form ? Array.from(form.querySelectorAll('input, select, textarea')) : [];

  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      document.getElementById('shopSearch').value = '';
      const locationInput = form.querySelector('[name="location"]');
      const categoryInput = form.querySelector('[name="category"]');
      const propertyTypeInput = form.querySelector('[name="property_type"]');
      const listingModeInput = form.querySelector('[name="listing_mode"]');
      if (locationInput) locationInput.value = '';
      if (categoryInput) categoryInput.value = '';
      if (propertyTypeInput) propertyTypeInput.value = '';
      if (listingModeInput) listingModeInput.value = '';
      const roomsMin = form.querySelector('input[name="rooms_min"]');
      if (roomsMin) roomsMin.value = '';
      const minPrice = document.getElementById('minPriceField');
      const maxPrice = document.getElementById('maxPriceField');
      if (minPrice) minPrice.value = '';
      if (maxPrice) maxPrice.value = '';
      const verified = form.querySelector('input[name="verified"]');
      if (verified) verified.checked = false;
      const available = form.querySelector('input[name="available"]');
      if (available) available.checked = false;
      const sort = form.querySelector('select[name="sort"]');
      if (sort) sort.value = sort.dataset.defaultSort || 'rating';
      form.submit();
    });
  }

  controls.forEach(function (control) {
    control.addEventListener('change', function (e) {
      if (e.target && e.target.name !== 'q') {
        form.submit();
      }
    });
  });
});
