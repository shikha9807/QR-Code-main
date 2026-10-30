import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'attendance.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Users table (Upgraded for RBAC: admin, teacher, hod, student)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'teacher',
        email TEXT,
        full_name TEXT,
        dept_id INTEGER,
        FOREIGN KEY (dept_id) REFERENCES departments (id)
    )
    ''')

    # Safe column migration for existing databases
    cursor.execute("PRAGMA table_info(users)")
    existing_user_cols = {col['name'] for col in cursor.fetchall()}
    if 'email' not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
    if 'full_name' not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN full_name TEXT")
    if 'dept_id' not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN dept_id INTEGER")

    # 2. University Structure Tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS departments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        code TEXT UNIQUE NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_code TEXT UNIQUE NOT NULL,
        course_name TEXT NOT NULL,
        dept_id INTEGER,
        semester INTEGER,
        FOREIGN KEY (dept_id) REFERENCES departments (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_name TEXT NOT NULL,
        course_id INTEGER,
        FOREIGN KEY (course_id) REFERENCES courses (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        roll_number TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        dept_id INTEGER,
        program TEXT,
        semester INTEGER,
        section_id INTEGER,
        FOREIGN KEY (dept_id) REFERENCES departments (id),
        FOREIGN KEY (section_id) REFERENCES sections (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS teacher_assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER,
        course_id INTEGER,
        section_id INTEGER,
        FOREIGN KEY (teacher_id) REFERENCES users (id),
        FOREIGN KEY (course_id) REFERENCES courses (id),
        FOREIGN KEY (section_id) REFERENCES sections (id),
        UNIQUE(teacher_id, course_id, section_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        course_id INTEGER,
        section_id INTEGER,
        FOREIGN KEY (student_id) REFERENCES students (id),
        FOREIGN KEY (course_id) REFERENCES courses (id),
        FOREIGN KEY (section_id) REFERENCES sections (id),
        UNIQUE(student_id, course_id, section_id)
    )
    ''')

    # 3. Core Attendance Tables
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        expiry_time DATETIME NOT NULL,
        token TEXT UNIQUE NOT NULL,
        status TEXT DEFAULT 'active',
        FOREIGN KEY (teacher_id) REFERENCES users (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER,
        student_id TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id, student_id),
        FOREIGN KEY (session_id) REFERENCES sessions (id)
    )
    ''')

    # 4. System Settings Table (Configurable Attendance threshold, HOD rules, etc.)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        description TEXT
    )
    ''')

    # 5. Leave Types Table (Admin Configurable)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS leave_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        code TEXT UNIQUE NOT NULL,
        description TEXT,
        max_days INTEGER DEFAULT 10,
        requires_document INTEGER DEFAULT 0,
        requires_hod_approval INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    )
    ''')

    # 6. Academic Calendar & Holidays Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS academic_calendar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_date DATE UNIQUE NOT NULL,
        title TEXT NOT NULL,
        is_holiday INTEGER DEFAULT 1
    )
    ''')

    # 7. Timetable / Schedule Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS timetable (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        section_id INTEGER NOT NULL,
        day_of_week TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        room TEXT,
        teacher_id INTEGER,
        FOREIGN KEY (course_id) REFERENCES courses (id),
        FOREIGN KEY (section_id) REFERENCES sections (id),
        FOREIGN KEY (teacher_id) REFERENCES users (id)
    )
    ''')

    # 8. Leave Requests Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        roll_number TEXT NOT NULL,
        leave_type_id INTEGER NOT NULL,
        start_date DATE NOT NULL,
        end_date DATE NOT NULL,
        total_days INTEGER NOT NULL,
        reason TEXT NOT NULL,
        description TEXT,
        applied_via TEXT DEFAULT 'form',
        current_attendance_pct REAL NOT NULL,
        projected_attendance_pct REAL NOT NULL,
        conducted_classes INTEGER NOT NULL,
        attended_classes INTEGER NOT NULL,
        affected_classes INTEGER NOT NULL,
        risk_level TEXT NOT NULL,
        status TEXT DEFAULT 'PENDING_FACULTY',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES students (id),
        FOREIGN KEY (leave_type_id) REFERENCES leave_types (id)
    )
    ''')

    # 9. Leave Documents Table (with OCR assist fields)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS leave_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leave_request_id INTEGER NOT NULL,
        filename TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER,
        file_type TEXT,
        ocr_extracted_text TEXT,
        ocr_status TEXT DEFAULT 'PROCESSED',
        uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (leave_request_id) REFERENCES leave_requests (id)
    )
    ''')

    # 10. Leave Approval / Workflow History Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS leave_approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        leave_request_id INTEGER NOT NULL,
        approver_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        role TEXT NOT NULL,
        remarks TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (leave_request_id) REFERENCES leave_requests (id),
        FOREIGN KEY (approver_id) REFERENCES users (id)
    )
    ''')

    # 11. In-App Notifications Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        type TEXT DEFAULT 'INFO',
        link TEXT,
        is_read INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (id)
    )
    ''')

    # 12. University Audit Logs Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        action TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT,
        details TEXT,
        ip_address TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    # Create indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance(session_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_teacher ON sessions(teacher_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_students_roll ON students(roll_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_leave_student ON leave_requests(student_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_leave_roll ON leave_requests(roll_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_leave_status ON leave_requests(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_timetable_sec_course ON timetable(section_id, course_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)')

    # Student Import History Table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS student_imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        admin_id INTEGER,
        import_date DATETIME DEFAULT CURRENT_TIMESTAMP,
        total_rows INTEGER NOT NULL,
        success_count INTEGER NOT NULL,
        failure_count INTEGER NOT NULL,
        status TEXT NOT NULL,
        FOREIGN KEY (admin_id) REFERENCES users (id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS import_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id INTEGER,
        row_num INTEGER,
        roll_number TEXT,
        reasons TEXT,
        FOREIGN KEY (import_id) REFERENCES student_imports (id)
    )
    ''')

    # Default admin with hashed password
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        hashed_pw = generate_password_hash('admin123')
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
                       ('admin', hashed_pw, 'admin', 'System Administrator'))

    # Default HOD user
    cursor.execute("SELECT * FROM users WHERE username = 'hod'")
    if not cursor.fetchone():
        hashed_pw = generate_password_hash('hod123')
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)",
                       ('hod', hashed_pw, 'hod', 'Head of Department'))

    # Default system settings
    default_settings = [
        ('attendance_threshold', '75.0', 'Mandatory university minimum attendance percentage requirement'),
        ('hod_approval_days_threshold', '3', 'Leave requests with duration strictly greater than this require HOD approval'),
        ('semester_total_classes', '40', 'Standard total semester classes benchmark for projections'),
        ('allow_student_ai_apply', '1', 'Allow students to use Natural Language AI Leave Application'),
        ('duty_leave_counts_as_present', '1', 'If 1, approved duty/academic leave is compensated as attended in projected attendance')
    ]
    for key, val, desc in default_settings:
        cursor.execute("INSERT OR IGNORE INTO system_settings (key, value, description) VALUES (?, ?, ?)", (key, val, desc))

    # Default Leave Types
    default_leave_types = [
        ('Medical Leave', 'MED', 'Absence due to illness, injury, or medical hospitalization', 15, 1, 0),
        ('Casual Leave', 'CAS', 'Short-term personal, family, or social obligations', 5, 0, 0),
        ('Personal Leave', 'PER', 'Individual unavoidable personal engagements', 5, 0, 0),
        ('Emergency Leave', 'EMG', 'Urgent, unexpected crises or family emergencies', 7, 0, 0),
        ('Academic / Duty Leave', 'DUTY', 'Authorized university representation, conferences, sports, or hackathons', 14, 1, 1),
        ('Other Leave', 'OTH', 'Special discretionary leave requests', 5, 0, 0)
    ]
    for name, code, desc, max_d, req_doc, req_hod in default_leave_types:
        cursor.execute('''
            INSERT OR IGNORE INTO leave_types (name, code, description, max_days, requires_document, requires_hod_approval)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (name, code, desc, max_d, req_doc, req_hod))

    conn.commit()
    conn.close()

# Auto-initialize database when module is imported
init_db()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully with University Schema.")
