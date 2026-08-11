// ===== SHARED UTILITIES =====
function formatCurrency(amount) { return '₦' + amount.toLocaleString('en-NG'); }
function formatTime(date) { return new Date(date).toLocaleTimeString('en-NG', { hour: '2-digit', minute: '2-digit' }); }
function formatDate(date) { return new Date(date).toLocaleDateString('en-NG', { day: 'numeric', month: 'short', year: 'numeric' }); }
function generateId() { return Date.now().toString(36) + Math.random().toString(36).substr(2); }

function showToast(message) {
  const container = document.getElementById('toastContainer') || document.body;
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 3000);
}

function logout() { clearUser(); window.location.href = 'login.html'; }
