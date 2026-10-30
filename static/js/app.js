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
  const metricPresent = document.getElementById('metric-present');
  const metricAbsent = document.getElementById('metric-absent');
  const metricRate = document.getElementById('metric-rate');
  const liveAbsentCount = document.getElementById('live-absent-count');
  const attendeeListElement = document.getElementById('attendee-list');
  const absenteeListElement = document.getElementById('absentee-list');
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
        if (data.count !== undefined) {
          if (countElement) countElement.textContent = data.count;
          if (metricPresent) metricPresent.textContent = data.count;
        }

        if (data.absent_count !== undefined) {
          if (liveAbsentCount) liveAbsentCount.textContent = data.absent_count;
          if (metricAbsent) metricAbsent.textContent = data.absent_count;
        }

        if (data.attendance_rate !== undefined && metricRate) {
          metricRate.textContent = `${data.attendance_rate}%`;
        }

        // Render Present Students Feed
        if (data.students && attendeeListElement) {
          if (data.students.length > 0 && emptyStateElement) {
            emptyStateElement.style.display = 'none';
          }
          
          attendeeListElement.innerHTML = data.students.map((student) => {
            const avatarHtml = student.photo_path
              ? `<img src="${escapeHtml(student.photo_path)}" alt="Photo" onclick="openPhotoModal('${escapeHtml(student.photo_path)}', '${escapeHtml(student.student_id)}')" style="width: 36px; height: 36px; border-radius: 50%; object-fit: cover; border: 2px solid var(--primary); cursor: pointer;" title="Click to view photo">`
              : `<div class="attendee-avatar">${escapeHtml(student.student_id.charAt(0).toUpperCase())}</div>`;

            const gpsInfo = (student.distance_meters !== null && student.distance_meters !== undefined)
              ? `&bull; <span style="color: #38bdf8;"><i class="fa-solid fa-location-dot"></i> ${Math.round(student.distance_meters)}m</span>`
              : '';

            const faceBadge = (student.photo_path && student.face_verified)
              ? `<span class="badge badge-active" title="Face verified"><i class="fa-solid fa-camera"></i> Face OK</span>`
              : '';

            return `
              <li class="attendee-item">
                <div style="display: flex; align-items: center; gap: 0.75rem;">
                  ${avatarHtml}
                  <div>
                    <div style="font-weight: 600; color: #ffffff;">${escapeHtml(student.student_id)}</div>
                    <div style="font-size: 0.75rem; color: #64748b;">
                      ${escapeHtml(student.timestamp)} ${gpsInfo}
                    </div>
                  </div>
                </div>
                <div style="display: flex; gap: 0.35rem; align-items: center;">
                  ${faceBadge}
                  <span class="badge badge-active">Verified</span>
                </div>
              </li>
            `;
          }).join('');
        }

        // Render Absent Students Roster
        if (data.absentees && absenteeListElement) {
          absenteeListElement.innerHTML = data.absentees.map((student) => `
            <li class="attendee-item" style="border-left: 3px solid #ef4444;">
              <div style="display: flex; align-items: center; gap: 0.75rem;">
                <div class="attendee-avatar" style="background: rgba(239, 68, 68, 0.2); color: #f87171;">
                  ${escapeHtml((student.roll_number || 'A').charAt(0).toUpperCase())}
                </div>
                <div>
                  <div style="font-weight: 600; color: #ffffff;">${escapeHtml(student.full_name || student.roll_number)}</div>
                  <div style="font-size: 0.75rem; color: #64748b; font-family: var(--font-mono);">
                    ${escapeHtml(student.roll_number)} &bull; ${escapeHtml(student.email || 'No email')}
                  </div>
                </div>
              </div>
              <span class="badge badge-expired" style="color: #f87171; border-color: rgba(239, 68, 68, 0.3); background: rgba(239, 68, 68, 0.1);">
                Absent
              </span>
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
  if (!text) return '';
  const map = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}
