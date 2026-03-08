document.addEventListener('DOMContentLoaded', function() {
  lucide.createIcons();
});

let currentProductId = null;
let currentQuantity = 1;
let currentProductStock = 0;
let currentSellingPrice = 0;
let currentCostPrice = 0;

function openSellModal(id, name, sellingPrice, costPrice, stock) {
  if (stock === 0) return;

  currentProductId = id;
  currentQuantity = 1;
  currentProductStock = stock;
  currentSellingPrice = sellingPrice;
  currentCostPrice = costPrice;

  updateSellModalDisplay();

  document.getElementById('sellModal').classList.add('active');
}

function closeSellModal() {
  document.getElementById('sellModal').classList.remove('active');
}

function updateSellModalDisplay() {
  document.getElementById('sellProductName').textContent = currentProductId;
  document.getElementById('sellProductPrice').textContent = "₦" + currentSellingPrice + " per unit";
  document.getElementById('sellQuantity').textContent = currentQuantity;
  document.getElementById('sellTotal').textContent = "₦" + (currentSellingPrice * currentQuantity);
  document.getElementById('sellProfit').textContent = "+₦" + ((currentSellingPrice - currentCostPrice) * currentQuantity);
}

function updateQuantity(delta) {
  const newQty = currentQuantity + delta;

  if (newQty >= 1 && newQty <= currentProductStock) {
    currentQuantity = newQty;
    updateSellModalDisplay();
  }
}

function completeSale() {
  fetch('/api/create-sale/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCookie('csrftoken')
    },
    body: JSON.stringify({
      product_id: currentProductId,
      quantity: currentQuantity
    })
  })
  .then(res => res.json())
  .then(data => {
    if (data.success) {
      closeSellModal();
      location.reload();   // simple + clean
    } else {
      alert(data.error);
    }
  });
}