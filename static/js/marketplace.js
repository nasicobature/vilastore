// ===== MARKETPLACE JS (Server-backed) =====
document.addEventListener('DOMContentLoaded', function () {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  const form = document.getElementById('filterForm');
  const categoryInput = document.getElementById('categoryInput');
  const locationInput = document.getElementById('locationInput');
  const propertyTypeInput = document.getElementById('propertyTypeInput');
  const clearBtn = document.getElementById('clearFiltersBtn');

  document.querySelectorAll('[data-filter="category"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      categoryInput.value = btn.getAttribute('data-value') || '';
      form.submit();
    });
  });

  document.querySelectorAll('[data-filter="location"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      locationInput.value = btn.getAttribute('data-value') || '';
      form.submit();
    });
  });

  document.querySelectorAll('[data-filter="property_type"]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      propertyTypeInput.value = btn.getAttribute('data-value') || '';
      form.submit();
    });
  });

  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      document.getElementById('shopSearch').value = '';
      categoryInput.value = '';
      locationInput.value = '';
      propertyTypeInput.value = '';
      const minPrice = document.getElementById('minPriceField');
      const maxPrice = document.getElementById('maxPriceField');
      if (minPrice) minPrice.value = '';
      if (maxPrice) maxPrice.value = '';
      const verified = form.querySelector('input[name="verified"]');
      if (verified) verified.checked = false;
      const available = form.querySelector('input[name="available"]');
      if (available) available.checked = false;
      const sort = form.querySelector('select[name="sort"]');
      if (sort) sort.value = 'rating';
      form.submit();
    });
  }

  form.addEventListener('change', function (e) {
    if (e.target && (e.target.name === 'verified' || e.target.name === 'available' || e.target.name === 'sort' || e.target.name === 'min_price' || e.target.name === 'max_price')) {
      form.submit();
    }
  });
});
