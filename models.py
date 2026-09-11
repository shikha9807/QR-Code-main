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

    # 1. Users table (Upgraded for RBAC)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT CHECK(role IN ('admin', 'teacher', 'student')) DEFAULT 'teacher'
    )
    ''')

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

    # Create indexes for performance
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_session ON attendance(session_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_teacher ON sessions(teacher_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_students_roll ON students(roll_number)')

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
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                       ('admin', hashed_pw, 'admin'))

    conn.commit()
    conn.close()

# Auto-initialize database when module is imported
init_db()

if __name__ == '__main__':
    init_db()
    print("Database initialized successfully with University Schema.")
