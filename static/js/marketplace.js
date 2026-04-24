// ===== MARKETPLACE JS (Server-backed) =====
document.addEventListener('DOMContentLoaded', function () {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  const form = document.getElementById('filterForm');
  const clearBtn = document.getElementById('clearFiltersBtn');

  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      document.getElementById('shopSearch').value = '';
      const locationInput = document.querySelector('[name="location"][form="filterForm"]');
      const propertyTypeInput = document.querySelector('[name="property_type"][form="filterForm"]');
      const listingModeInput = document.querySelector('[name="listing_mode"][form="filterForm"]');
      if (locationInput) locationInput.value = '';
      if (propertyTypeInput) propertyTypeInput.value = '';
      if (listingModeInput) listingModeInput.value = '';
      const roomsMin = document.querySelector('input[name="rooms_min"][form="filterForm"]');
      if (roomsMin) roomsMin.value = '';
      const minPrice = document.getElementById('minPriceField');
      const maxPrice = document.getElementById('maxPriceField');
      if (minPrice) minPrice.value = '';
      if (maxPrice) maxPrice.value = '';
      const verified = document.querySelector('input[name="verified"][form="filterForm"]');
      if (verified) verified.checked = false;
      const available = document.querySelector('input[name="available"][form="filterForm"]');
      if (available) available.checked = false;
      const sort = document.querySelector('select[name="sort"][form="filterForm"]');
      if (sort) sort.value = 'rating';
      form.submit();
    });
  }

  document.querySelectorAll('[form="filterForm"]').forEach(function (control) {
    control.addEventListener('change', function (e) {
      if (e.target && e.target.name !== 'q') {
        form.submit();
      }
    });
  });
});
