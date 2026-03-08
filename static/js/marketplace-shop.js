function formatCurrency(value) {
  const num = Number(value || 0);
  return `₦${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function showToast(message) {
  const container = document.getElementById('toastContainer');
  if (!container) {
    alert(message);
    return;
  }

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 2600);
}

function clampQty(input) {
  const max = Number(input.max || 0);
  let val = Number(input.value || 0);
  if (Number.isNaN(val) || val < 0) val = 0;
  if (max >= 0 && val > max) val = max;
  input.value = String(val);
  return val;
}

document.addEventListener('DOMContentLoaded', function () {
  if (window.lucide) {
    window.lucide.createIcons();
  }

  const form = document.getElementById('marketplaceOrderForm');
  if (!form) return;

  const selectedItemsEl = document.getElementById('selectedItems');
  const selectedTotalEl = document.getElementById('selectedTotal');
  const cards = Array.from(document.querySelectorAll('.marketplace-product-card'));

  function updateAddButtonState(productId, qty) {
    const btn = document.querySelector(`.add-to-cart-btn[data-product-id="${productId}"]`);
    if (!btn) return;

    if (qty > 0) {
      btn.classList.remove('btn-outline');
      btn.classList.add('btn-secondary');
      btn.innerHTML = '<i data-lucide="check"></i> Added';
    } else {
      btn.classList.remove('btn-secondary');
      btn.classList.add('btn-outline');
      btn.innerHTML = '<i data-lucide="shopping-cart"></i> Add to Cart';
    }

    if (window.lucide) {
      window.lucide.createIcons();
    }
  }

  function updateSummary() {
    const selectedRows = [];
    let total = 0;

    cards.forEach((card) => {
      const productId = card.getAttribute('data-product-id');
      const productName = card.getAttribute('data-product-name') || 'Item';
      const price = Number(card.getAttribute('data-product-price') || 0);
      const qtyInput = document.getElementById(`qty_${productId}`);
      if (!qtyInput) return;

      const qty = clampQty(qtyInput);
      updateAddButtonState(productId, qty);
      if (qty <= 0) return;

      const lineTotal = price * qty;
      total += lineTotal;
      selectedRows.push({ name: productName, qty, lineTotal });
    });

    if (!selectedRows.length) {
      selectedItemsEl.innerHTML = '<p class="marketplace-empty-selection">No items selected yet.</p>';
    } else {
      selectedItemsEl.innerHTML = selectedRows
        .map((row) => `
          <div class="marketplace-selected-row">
            <span>${row.name} x ${row.qty}</span>
            <strong>${formatCurrency(row.lineTotal)}</strong>
          </div>
        `)
        .join('');
    }

    selectedTotalEl.textContent = formatCurrency(total);
  }

  document.querySelectorAll('.qty-btn').forEach((btn) => {
    btn.addEventListener('click', function () {
      const productId = btn.getAttribute('data-product-id');
      const action = btn.getAttribute('data-action');
      const input = document.getElementById(`qty_${productId}`);
      if (!input || input.disabled) return;

      const max = Number(input.max || 0);
      let val = Number(input.value || 0);
      if (Number.isNaN(val)) val = 0;

      if (action === 'increase') {
        val = Math.min(val + 1, max);
      } else {
        val = Math.max(val - 1, 0);
      }

      input.value = String(val);
      updateSummary();
    });
  });

  document.querySelectorAll('.qty-input').forEach((input) => {
    input.addEventListener('input', updateSummary);
    input.addEventListener('change', updateSummary);
  });

  document.querySelectorAll('.add-to-cart-btn').forEach((btn) => {
    btn.addEventListener('click', function () {
      const productId = btn.getAttribute('data-product-id');
      const input = document.getElementById(`qty_${productId}`);
      if (!input || input.disabled) return;

      const max = Number(input.max || 0);
      let val = Number(input.value || 0);
      if (Number.isNaN(val)) val = 0;

      if (val > 0) {
        input.value = '0';
      } else if (max > 0) {
        input.value = '1';
      }

      updateSummary();
    });
  });

  form.addEventListener('submit', function (e) {
    let hasSelectedItem = false;
    document.querySelectorAll('.qty-input').forEach((input) => {
      if (input.disabled) return;
      if (clampQty(input) > 0) hasSelectedItem = true;
    });

    if (!hasSelectedItem) {
      e.preventDefault();
      showToast('Select at least one product before sending order.');
    }
  });

  updateSummary();
});
