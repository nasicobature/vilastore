// ===== ORDER CHAT JS (Server-backed) =====
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
  return '';
}

function showToast(message) {
  const container = document.getElementById('toastContainer') || document.body;
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.classList.add('show'), 10);
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, 3000);
}

function appendMessage(message, isOwn, senderType) {
  const container = document.getElementById('chatMessages');
  const time = new Date(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const avatarIcon = senderType === 'seller' ? 'store' : (senderType === 'system' ? 'info' : 'user');

  const row = document.createElement('div');
  row.className = `chat-bubble-row ${isOwn ? 'own' : ''}`;
  row.innerHTML = `
    <div class="chat-avatar"><i data-lucide="${avatarIcon}"></i></div>
    <div class="chat-bubble ${isOwn ? 'chat-bubble-own' : 'chat-bubble-other'}">
      <p></p>
      <span class="chat-time">${time}</span>
    </div>`;
  row.querySelector('p').textContent = message.message;
  container.appendChild(row);
  if (window.lucide) window.lucide.createIcons();
  container.scrollTop = container.scrollHeight;
}

document.addEventListener('DOMContentLoaded', function () {
  if (window.lucide) window.lucide.createIcons();

  const layout = document.querySelector('.order-chat-layout');
  if (!layout) return;
  const publicId = layout.getAttribute('data-order');
  const accessToken = layout.getAttribute('data-access') || '';
  const isSeller = layout.getAttribute('data-is-seller') === '1';

  const sendBtn = document.getElementById('sendBtn');
  const input = document.getElementById('messageInput');
  const nextBtn = document.getElementById('nextStatusBtn');
  const cancelBtn = document.getElementById('cancelOrderBtn');

  function sendMessage() {
    const text = (input.value || '').trim();
    if (!text) return;
    const formData = new FormData();
    formData.append('message', text);
    if (accessToken) formData.append('access', accessToken);

    fetch(`/marketplace/order/${publicId}/message/`, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCookie('csrftoken') },
      body: formData
    })
      .then(r => r.json())
      .then(data => {
        if (!data.success) {
          showToast(data.error || 'Failed to send message');
          return;
        }
        input.value = '';
        appendMessage(data.message, true, data.message.sender_type);
      })
      .catch(() => showToast('Failed to send message'));
  }

  if (sendBtn) {
    sendBtn.addEventListener('click', sendMessage);
  }
  if (input) {
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
  }

  function updateStatus(status) {
    const formData = new FormData();
    formData.append('status', status);
    if (accessToken) formData.append('access', accessToken);
    fetch(`/marketplace/order/${publicId}/status/`, {
      method: 'POST',
      headers: { 'X-CSRFToken': getCookie('csrftoken') },
      body: formData
    })
      .then(r => r.json())
      .then(data => {
        if (!data.success) {
          showToast(data.error || 'Failed to update status');
          return;
        }
        window.location.reload();
      })
      .catch(() => showToast('Failed to update status'));
  }

  if (nextBtn) {
    nextBtn.addEventListener('click', function () {
      const next = nextBtn.getAttribute('data-next-status');
      if (next) updateStatus(next);
    });
  }

  if (cancelBtn) {
    cancelBtn.addEventListener('click', function () {
      if (confirm('Cancel this order?')) {
        updateStatus('cancelled');
      }
    });
  }
});
