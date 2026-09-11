# 📱 QR-Based Attendance System

A modern, full-stack automated attendance tracking application built with **Flask**, **SQLite**, dynamic **QR Code generation**, and a **Glassmorphic UI**.

For full in-depth technical documentation, database schemas, security flows, and architecture details, see [PROJECT_DOCUMENTATION.md](file:///Users/shikha/Downloads/QR-Code-main/PROJECT_DOCUMENTATION.md).

---

## 🚀 Key Highlights

* 📱 **Dynamic QR Generation**: Creates temporary, secure QR codes for 10-minute sessions.
* ⚡ **Live Real-Time Sync**: Teacher dashboard auto-updates attendee lists in real-time as students scan.
* 🛡️ **Anti-Proxy Protection**: Cookie-based single device restriction + database unique constraints.
* 📊 **Reports & CSV Export**: Downloadable attendance records for grading and analytics.
* 👤 **Multi-Teacher Management**: Account registration and login authentication.
* 🎨 **Glassmorphism Design**: Dark theme with responsive styling for desktop projectors and mobile devices.

---

## 🛠️ Tech Stack

* **Backend**: Python 3.14+, Flask 3.1.3+, SQLite3
* **QR Engine**: `qrcode`, `Pillow` (PIL)
* **Frontend**: HTML5, Vanilla CSS3 (Glassmorphic Design System), JavaScript (ES6+ AJAX Polling), Font Awesome 6.5

---

## ⚙️ Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Test Suite
```bash
python3 test_app.py
```

### 3. Start the Server
```bash
python3 app.py
```

Open [http://127.0.0.1:5001](http://127.0.0.1:5001) in your browser.

---

## 🔑 Default Credentials

* **Username**: `admin`
* **Password**: `admin123`
*(Or use the Registration tab on `/login` to create new teacher accounts).*

---

## 📂 Project Structure

```text
├── app.py                     # Main Flask routes, endpoints & logic
├── models.py                  # Database schema & SQLite helpers
├── qr_handler.py              # QR Code generator
├── requirements.txt           # Python dependencies
├── test_app.py                # Automated test suite
├── attendance.db              # SQLite Database
├── PROJECT_DOCUMENTATION.md   # Complete technical specifications
├── templates/                 # Jinja2 HTML templates
└── static/                    # CSS design system & client JavaScript
```

---

## 📄 License
This project is licensed under the MIT License.
