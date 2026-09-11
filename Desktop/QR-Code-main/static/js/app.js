// QR Code Attendance System Client Script

// Clipboard copy helper
function copyToClipboard(text, btnElement) {
  navigator.clipboard.writeText(text).then(() => {
    if (btnElement) {
      const originalHtml = btnElement.innerHTML;
      btnElement.innerHTML = '<span>✅ Copied!</span>';
      btnElement.classList.add('btn-success');
      setTimeout(() => {
        btnElement.innerHTML = originalHtml;
        btnElement.classList.remove('btn-success');
      }, 2000);
    }
  }).catch(err => {
    console.error('Failed to copy: ', err);
  });
}

// Live Session Polling & Countdown Timer
function initLiveSession(sessionId, initialSeconds) {
  let remainingSeconds = initialSeconds;
  const timerElement = document.getElementById('session-timer');
  const countElement = document.getElementById('live-count');
  const attendeeListElement = document.getElementById('attendee-list');
  const emptyStateElement = document.getElementById('empty-attendees');

  // Countdown timer interval
  const timerInterval = setInterval(() => {
    if (remainingSeconds <= 0) {
      clearInterval(timerInterval);
      if (timerElement) {
        timerElement.textContent = 'EXPIRED';
        timerElement.classList.remove('badge-active');
        timerElement.classList.add('badge-expired');
      }
      return;
    }
    remainingSeconds--;
    const mins = Math.floor(remainingSeconds / 60);
    const secs = remainingSeconds % 60;
    if (timerElement) {
      timerElement.textContent = `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    }
  }, 1000);

  // Poll server for new attendees every 3 seconds
  const pollInterval = setInterval(() => {
    fetch(`/api/session-stats/${sessionId}`)
      .then(res => res.json())
      .then(data => {
        if (data.count !== undefined && countElement) {
          countElement.textContent = data.count;
        }

        if (data.students && attendeeListElement) {
          if (data.students.length > 0 && emptyStateElement) {
            emptyStateElement.style.display = 'none';
          }
          
          attendeeListElement.innerHTML = data.students.map((student, idx) => `
            <li class="attendee-item">
              <div style="display: flex; align-items: center; gap: 0.75rem;">
                <div class="attendee-avatar">${student.student_id.charAt(0).toUpperCase()}</div>
                <div>
                  <div style="font-weight: 600; color: #ffffff;">${escapeHtml(student.student_id)}</div>
                  <div style="font-size: 0.75rem; color: #64748b;">${escapeHtml(student.timestamp)}</div>
                </div>
              </div>
              <span class="badge badge-active">Verified</span>
            </li>
          `).join('');
        }

        if (data.is_expired) {
          clearInterval(pollInterval);
        }
      })
      .catch(err => console.error('Poll error:', err));
  }, 3000);
}

function escapeHtml(text) {
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return text.replace(/[&<>"']/g, m => map[m]);
}
