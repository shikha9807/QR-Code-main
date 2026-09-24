# 📱 QR-Based Attendance System — Complete Technical Documentation

A full-stack, automated attendance tracking platform built with **Python (Flask)**, **SQLite**, dynamic **QR Code generation**, and a **modern Glassmorphic UI**.

---

## 📑 Table of Contents

1. [System Overview & Architecture](#-system-overview--architecture)
2. [Tech Stack & Dependencies](#-tech-stack--dependencies)
3. [Project Structure & File Breakdown](#-project-structure--file-breakdown)
4. [How Everything Works (Workflow & Logic)](#-how-everything-works-workflow--logic)
5. [Key Features & Implemented Capabilities](#-key-features--implemented-capabilities)
6. [Security & Anti-Fraud Mechanisms](#-security--anti-fraud-mechanisms)
7. [API Endpoints & Routing Reference](#-api-endpoints--routing-reference)
8. [Database Schema](#-database-schema)
9. [Step-by-Step Setup & Execution](#-step-by-step-setup--execution)
10. [Default Credentials & Testing Guide](#-default-credentials--testing-guide)

---

## 🏛️ System Overview & Architecture

The system enables teachers and instructors to launch short-lived (10-minute), cryptographically unique QR attendance sessions. Students scan the QR code with their mobile devices or browser to enter their details and record attendance instantly. The teacher's dashboard receives live updates in real-time without requiring a page reload.

```
+------------------+         Generates QR         +------------------------+
|                  | ---------------------------> |   Teacher Live Screen   |
|   Flask Server   |                              |  (Real-Time Attendee   |
| (Port 5001 / WSGI)                              |   Roster & Countdown)  |
|                  | <--------------------------- +------------------------+
+--------+---------+       Polls Stats (AJAX)
         |
         | Serves Mobile Form & Validates Check-In
         v
+------------------+         Database         +------------------------+
|  Student Device  | -----------------------> |       SQLite DB        |
| (Scans QR Code)  |    (INSERT Attendance)   |    (attendance.db)     |
+------------------+                          +------------------------+
```

---

## 🛠️ Tech Stack & Dependencies

### Backend
- **Python 3.14+**
- **Flask (v3.1.3+)**: Lightweight WSGI web framework handling routing, sessions, templates, and API responses.
- **SQLite3**: Serverless, zero-configuration relational database engine for storing users, sessions, and attendance logs.
- **qrcode (v8.2+)**: High-density QR code matrix generator.
- **Pillow / PIL (v12.3+)**: Python Imaging Library used for rasterizing QR code images into base64 PNG data streams.

### Frontend
- **HTML5 & Jinja2 Templates**: Semantic structure, dynamic data binding, and template inheritance (`base.html`).
- **Modern Vanilla CSS (Design System)**:
  - Custom dark theme with deep indigo palette (`#090d16` to `#1e1b4b`) and vibrant neon accents (`#6366f1`, `#06b6d4`, `#10b981`).
  - Glassmorphic translucent cards with `backdrop-filter: blur(12px)`.
  - Typography powered by Google Fonts (*Plus Jakarta Sans* & *JetBrains Mono*).
  - Responsive layouts optimized for desktop projectors and mobile smartphones.
- **Vanilla JavaScript (ES6+)**:
  - Asynchronous polling (`fetch()`) every 3 seconds for zero-refresh roster updates.
  - Active session countdown timer (10-minute client synchronization).
  - One-click clipboard copy utility with animated feedback.
- **Font Awesome 6.5**: Vector icons for dashboards, status badges, and interactive controls.

---

## 📂 Project Structure & File Breakdown

```text
QR-Code-main/
│
├── app.py                     # Main Flask application with all routes, API endpoints, and logic
├── models.py                  # SQLite database initialization, schemas, and connection helper
├── qr_handler.py              # QR Code generator producing Base64 PNG image streams
├── requirements.txt           # Python dependencies (flask, qrcode, pillow)
├── test_app.py                # Automated unit & integration test suite (7/7 passing tests)
├── attendance.db              # SQLite database file containing persistent data
├── README.md                  # Quick project overview
├── PROJECT_DOCUMENTATION.md   # Complete technical specifications & manual
│
├── static/
│   ├── css/
│   │   └── style.css          # Design system, glassmorphism, responsive grid, and animations
│   └── js/
│       └── app.js             # Client-side live polling, countdown timer, and clipboard logic
│
└── templates/
    ├── base.html              # Core layout (navbar, user badge, flash alerts, footer)
    ├── login.html             # Login & Teacher Registration with demo auto-fill
    ├── dashboard.html         # Teacher dashboard with metrics & session launcher
    ├── session.html           # Live QR projection room with real-time roster feed
    ├── student_form.html      # Mobile student attendance input form
    ├── feedback.html          # Success/error feedback cards after scanning
    └── reports.html           # Attendance log audit trail, CSV export, and deletion tools
```

---

## ⚙️ How Everything Works (Workflow & Logic)

### 1. Teacher Authentication & Session Start
1. The teacher logs in at `/login` (or registers a new instructor account at `/register`).
2. From `/dashboard`, clicking **"Launch Live QR Session"** triggers `POST /start-session`.
3. `app.py` generates a cryptographically secure `UUID4` token and sets an expiration timestamp (10 minutes from creation).
4. The teacher is redirected to `/session/<session_id>`.

### 2. QR Code Generation & Network Resolution
1. `qr_handler.py` encodes the scan URL into a base64 PNG image string.
2. `get_local_ip()` dynamically identifies the host machine's Wi-Fi / LAN IP (e.g. `http://10.12.85.202:5001/mark-attendance/<token>`), allowing any student connected to the same local network to scan the projected QR code.
3. The live session page also provides a local testing link (`http://127.0.0.1:5001/...`) and a **Copy Link** button.

### 3. Student Check-In & Validation
1. Student scans the QR code and is directed to `/mark-attendance/<token>`.
2. The server performs validation checks:
   - **Session existence**: Verifies token exists in `sessions` table.
   - **Time expiration**: Compares current time with `expiry_time`.
   - **Device duplicate check**: Verifies if the browser has the `attended_sess_<id>` cookie.
   - **Name duplicate check**: Checks the SQLite `UNIQUE(session_id, student_id)` constraint.
3. If valid, an attendance entry is inserted with the current timestamp.
4. A secure cookie is stored in the student's browser to prevent re-marking from the same phone.
5. The student receives an animated confirmation screen (`feedback.html`).

### 4. Real-Time Teacher Roster Updates
1. The teacher's browser on `/session/<id>` runs `initLiveSession()` in `static/js/app.js`.
2. Every 3 seconds, a background AJAX request hits `/api/session-stats/<session_id>`.
3. Newly marked students appear in the live roster list with instant badge notifications.
4. The remaining session countdown timer updates every second.

### 5. Archiving, Deletion & CSV Export
1. At `/reports`, all historical sessions and student logs are accessible.
2. Clicking **"Export CSV"** generates a formatted `.csv` file containing student name, timestamp, session ID, and session date.
3. Instructors can delete individual student records or entire sessions with cascade removal.

---

## 🌟 Key Features & Implemented Capabilities

| Feature | Description | Status |
| :--- | :--- | :---: |
| **Dynamic QR Generation** | High-contrast base64 QR codes generated on the fly without storing temporary files. | ✅ Working |
| **Real-time Live Sync** | Teacher screen updates automatically when students scan without refreshing. | ✅ Working |
| **Mobile-Friendly UI** | Student portal tailored for all iOS & Android camera scanners and mobile browsers. | ✅ Working |
| **Session Expiration** | Enforces 10-minute active window for each attendance QR session. | ✅ Working |
| **Device Anti-Fraud** | HTTP cookie binding prevents one device from submitting multiple attendances. | ✅ Working |
| **Duplicate Name Protection** | Database-level unique constraints reject duplicate student submissions. | ✅ Working |
| **CSV Data Export** | One-click spreadsheet export for Excel, Google Sheets, or grading records. | ✅ Working |
| **Role & Account System** | Teacher login, registration, and session isolation. | ✅ Working |
| **Live Countdown Timer** | Visual countdown showing remaining validity of active QR code. | ✅ Working |
| **Management & Deletion** | Delete erroneous entries or purge old sessions safely. | ✅ Working |

---

## 🔒 Security & Anti-Fraud Mechanisms

1. **UUIDv4 Tokenization**: Session URLs cannot be guessed; each session uses a 128-bit random unique token.
2. **Device Cookie Fingerprinting**: `attended_sess_<id>` cookie prevents a single student from proxy-marking friends on one phone.
3. **Database Unique Constraints**: `UNIQUE(session_id, student_id)` prevents repeated submissions with the same name.
4. **Time Expiration Verification**: Server rejects any `POST` request submitted after `expiry_time`.
5. **SQL Injection Protection**: All database queries use parameterized SQL bindings (`?`).

---

## 🛣️ API Endpoints & Routing Reference

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :---: |
| `GET` | `/` | Redirects to `/dashboard` if logged in, else `/login` | No |
| `GET`, `POST` | `/login` | User authentication | No |
| `GET`, `POST` | `/register` | Teacher account creation | No |
| `GET` | `/logout` | Clears session data | Yes |
| `GET` | `/dashboard` | Main metrics, recent sessions, and quick actions | Yes |
| `POST` | `/start-session` | Creates a new 10-minute session and generates QR | Yes |
| `GET` | `/session/<id>` | Live projection room with QR and real-time roster | Yes |
| `GET` | `/api/session-stats/<id>` | JSON endpoint for live attendee count & roster feed | Yes |
| `GET`, `POST` | `/mark-attendance/<token>`| Student scan portal and check-in submission | No |
| `GET` | `/reports` | Historical attendance logs and audit table | Yes |
| `GET` | `/export/<id>` | Downloads session records as a `.csv` file | Yes |
| `POST` | `/delete-attendance/<s_id>/<a_id>` | Deletes a single attendance entry | Yes |
| `POST` | `/delete-session/<id>` | Deletes an entire session and all associated attendees | Yes |

---

## 🗄️ Database Schema

### `users` Table
```sql
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT DEFAULT 'teacher'
);
```

### `sessions` Table
```sql
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expiry_time DATETIME NOT NULL,
    token TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'active',
    FOREIGN KEY (teacher_id) REFERENCES users (id)
);
```

### `attendance` Table
```sql
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    student_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, student_id),
    FOREIGN KEY (session_id) REFERENCES sessions (id)
);
```

---

## 🚀 Step-by-Step Setup & Execution

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Automated Tests
```bash

```
*(Expected output: `Ran 7 tests ... OK`)*

### 3. Launch the Server
```bash
python3 app.py
```

---

## 🔑 Default Credentials & Testing Guide

- **URL**: [http://127.0.0.1:5001](http://127.0.0.1:5001)
- **Admin Username**: `admin`
- **Admin Password**: `admin123`

### Quick Test Walkthrough:
1. Open [http://127.0.0.1:5001/login](http://127.0.0.1:5001/login) and click **"Auto Fill"** & **"Sign In"**.
2. Click **"Launch Live QR Session"**.
3. In the live session view, click **"Open Attendance Form in New Tab"** (or scan the QR code with your smartphone).
4. Enter a student name (e.g., `John Doe (Roll 101)`) and click **"Submit Attendance"**.
5. Switch back to the teacher tab — observe `John Doe` appearing instantly on the live roster without page reload!
6. Navigate to **"Reports"** to view records or click **"Export CSV"** to download the attendance sheet.
