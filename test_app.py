import unittest
from app import app
from models import get_db_connection, init_db
import uuid
import sqlite3
from werkzeug.security import generate_password_hash

class TestQRAttendanceUpgrade(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Clean DB for every test
        init_db()
        conn = get_db_connection()
        tables = ['attendance', 'sessions', 'teacher_assignments', 'enrollments', 'students', 'sections', 'courses', 'departments', 'users', 'student_imports', 'import_errors']
        for table in tables:
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        conn.commit()
        # Re-add default admin
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                     ('admin', generate_password_hash('admin123'), 'admin'))
        conn.commit()
        conn.close()

    def login(self, username, password):
        # Always logout first to ensure we are testing the login process, not just the session
        self.client.get('/logout')
        resp = self.client.post('/login', data={
            'username': username,
            'password': password
        }, follow_redirects=True)
        if b'Welcome back' not in resp.data and b'Dashboard' not in resp.data:
            self.fail(f"Login failed for user {username}")
        return resp

    def test_01_secure_auth_and_migration(self):
        # Test hashed password login
        self.login('admin', 'admin123')
        resp = self.client.get('/dashboard')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Dashboard', resp.data)

        # Test plaintext migration
        conn = get_db_connection()
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ('legacy_user', 'legacy123', 'teacher'))
        conn.commit()
        conn.close()

        self.login('legacy_user', 'legacy123')

        # Verify password was hashed in DB
        conn = get_db_connection()
        user = conn.execute("SELECT password FROM users WHERE username = 'legacy_user'").fetchone()
        conn.close()
        self.assertNotEqual(user['password'], 'legacy123')
        self.assertTrue(len(user['password']) > 20) # Hashes are typically long

    def test_02_rbac_permissions(self):
        # Create a student
        conn = get_db_connection()
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                     ('student1', generate_password_hash('pass123'), 'student'))
        conn.commit()
        conn.close()

        self.login('student1', 'pass123')

        # Try to access admin dashboard
        resp_admin = self.client.get('/admin', follow_redirects=True)
        self.assertIn(b'You do not have permission', resp_admin.data)

        # Try to start a session
        resp_session = self.client.post('/start-session', follow_redirects=True)
        self.assertIn(b'You do not have permission', resp_session.data)

    def test_03_teacher_ownership_restrictions(self):
        # Create two teachers
        conn = get_db_connection()
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ('teacher_a', generate_password_hash('p1'), 'teacher'))
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ('teacher_b', generate_password_hash('p2'), 'teacher'))
        conn.commit()
        conn.close()

        # Teacher A creates a session
        self.login('teacher_a', 'p1')
        self.client.post('/start-session')

        conn = get_db_connection()
        sess = conn.execute('SELECT id FROM sessions ORDER BY id DESC LIMIT 1').fetchone()
        sess_id = sess['id']
        conn.close()

        # Teacher B tries to view Teacher A's session
        self.login('teacher_b', 'p2')
        resp_view = self.client.get(f'/session/{sess_id}', follow_redirects=True)
        self.assertIn(b'You do not have permission', resp_view.data)

        # Teacher B tries to export Teacher A's session
        resp_export = self.client.get(f'/export/{sess_id}', follow_redirects=True)
        self.assertIn(b'You do not have permission', resp_export.data)

    def test_04_university_data_management(self):
        self.login('admin', 'admin123')

        # Add Department
        resp = self.client.post('/admin/departments', data={'name': 'Computer Science', 'code': 'CSE'}, follow_redirects=True)
        self.assertIn(b'Department added successfully', resp.data)

        # Add Course
        conn = get_db_connection()
        dept = conn.execute('SELECT id FROM departments WHERE code = "CSE"').fetchone()
        dept_id = dept['id']

        resp_course = self.client.post('/admin/courses', data={
            'course_code': 'CS101',
            'course_name': 'Intro to CS',
            'dept_id': dept_id,
            'semester': 1
        }, follow_redirects=True)
        self.assertIn(b'Course added successfully', resp_course.data)
        conn.close()

    def test_05_student_roll_number_uniqueness(self):
        self.login('admin', 'admin123')

        # Setup dept and section
        conn = get_db_connection()
        conn.execute("INSERT INTO departments (name, code) VALUES ('CS', 'CSE')")
        conn.execute("INSERT INTO courses (course_code, course_name, dept_id, semester) VALUES ('C1', 'Name', 1, 1)")
        conn.execute("INSERT INTO sections (section_name, course_id) VALUES ('A', 1)")
        conn.commit()
        conn.close()

        # Register student 1
        self.client.post('/admin/students', data={
            'roll_number': 'ROLL001',
            'full_name': 'Student One',
            'email': 's1@uni.edu',
            'dept_id': 1,
            'program': 'BTech',
            'semester': 1,
            'section_id': 1
        })

        # Register student 2 with SAME roll number
        resp = self.client.post('/admin/students', data={
            'roll_number': 'ROLL001',
            'full_name': 'Student Two',
            'email': 's2@uni.edu',
            'dept_id': 1,
            'program': 'BTech',
            'semester': 1,
            'section_id': 1
        }, follow_redirects=True)
        self.assertIn(b'Roll number or Email already exists', resp.data)

    def test_06_bulk_import_valid_csv(self):
        self.login('admin', 'admin123')

        # Setup dependencies
        conn = get_db_connection()
        conn.execute("INSERT INTO departments (name, code) VALUES ('Computer Science', 'CSE')")
        conn.execute("INSERT INTO courses (course_code, course_name, dept_id, semester) VALUES ('CS101', 'CS', 1, 1)")
        conn.execute("INSERT INTO sections (section_name, course_id) VALUES ('Section A', 1)")
        conn.commit()
        conn.close()

        # Create a valid CSV file
        csv_path = '/tmp/test_valid.csv'
        with open(csv_path, 'w') as f:
            f.write("roll_number,full_name,email,department,program,semester,section\n")
            f.write("V001,Valid One,v1@uni.edu,Computer Science,BTech,1,Section A\n")
            f.write("V002,Valid Two,v2@uni.edu,Computer Science,BTech,1,Section A\n")

        with open(csv_path, 'rb') as f:
            resp = self.client.post('/admin/import-students', data={
                'file': (f, 'test_valid.csv', 'text/csv'),
                'mode': 'skip_invalid',
                'update': 'on'
            }, follow_redirects=True)

        self.assertIn(b'Import Summary', resp.data)
        self.assertIn(b'Successfully Imported', resp.data)

    def test_07_bulk_import_invalid_data(self):
        self.login('admin', 'admin123')

        # Setup dependencies
        conn = get_db_connection()
        conn.execute("INSERT INTO departments (name, code) VALUES ('Computer Science', 'CSE')")
        conn.execute("INSERT INTO courses (course_code, course_name, dept_id, semester) VALUES ('CS101', 'CS', 1, 1)")
        conn.execute("INSERT INTO sections (section_name, course_id) VALUES ('Section A', 1)")
        conn.commit()
        conn.close()

        # Create an invalid CSV file
        csv_path = '/tmp/test_invalid.csv'
        with open(csv_path, 'w') as f:
            f.write("roll_number,full_name,email,department,program,semester,section\n")
            f.write("B001,Bad One,bad-email,Computer Science,BTech,-1,Section A\n") # Bad email, bad sem
            f.write("B002,Bad Two,v2@uni.edu,WrongDept,BTech,1,Section A\n") # Bad dept
            f.write(",Bad Three,v3@uni.edu,Computer Science,BTech,1,Section A\n") # Missing roll

        with open(csv_path, 'rb') as f:
            resp = self.client.post('/admin/import-students', data={
                'file': (f, 'test_invalid.csv', 'text/csv'),
                'mode': 'all_or_nothing',
                'update': 'off'
            }, follow_redirects=True)

        # Should fail in "All or Nothing" mode
        self.assertIn(b'Import failed', resp.data)
        self.assertIn(b'Invalid email format', resp.data)

    def test_08_bulk_import_auth_restriction(self):
        # Login as teacher
        conn = get_db_connection()
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ('teacher1', generate_password_hash('p1'), 'teacher'))
        conn.commit()
        conn.close()

        self.login('teacher1', 'p1')
        resp = self.client.get('/admin/import-students', follow_redirects=True)
        self.assertIn(b'You do not have permission', resp.data)

    def test_09_ai_predictor_engine_metrics(self):
        from ai_predictor import AIAttendancePredictor
        
        student = {
            'id': 1,
            'roll_number': 'CS101',
            'full_name': 'Test Student',
            'email': 'student@uni.edu',
            'dept_name': 'Computer Science',
            'section_name': 'Section A',
            'semester': 1
        }
        
        # Scenario 1: Low attendance with streak (Critical)
        sessions = [{'id': i, 'created_at': f'2026-09-0{i+1} 10:00:00'} for i in range(10)]
        attended = {0, 1, 2, 3} # 4 out of 10 attended = 40% (missed last 6)
        
        metrics = AIAttendancePredictor.calculate_student_metrics(student, sessions, attended)
        self.assertEqual(metrics['current_pct'], 40.0)
        self.assertEqual(metrics['risk_level'], 'CRITICAL')
        self.assertTrue(metrics['consecutive_needed'] > 0)
        self.assertEqual(metrics['current_absence_streak'], 6)

        # Scenario 2: High attendance (Safe)
        attended_good = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9}
        metrics_good = AIAttendancePredictor.calculate_student_metrics(student, sessions, attended_good)
        self.assertEqual(metrics_good['current_pct'], 100.0)
        self.assertEqual(metrics_good['risk_level'], 'SAFE')
        self.assertTrue(metrics_good['buffer_missable'] > 0)

        # Scenario 3: Notice Generation
        notice = AIAttendancePredictor.generate_notice_text(metrics)
        self.assertIn('OFFICIAL ATTENDANCE DEFAULTER WARNING', notice)
        self.assertIn('CS101', notice)

    def test_10_ai_risk_analytics_views(self):
        self.login('admin', 'admin123')
        
        # Setup sample department, section, student, session, attendance
        conn = get_db_connection()
        conn.execute("INSERT INTO departments (name, code) VALUES ('Computer Science', 'CSE')")
        conn.execute("INSERT INTO courses (course_code, course_name, dept_id, semester) VALUES ('CS101', 'CS', 1, 1)")
        conn.execute("INSERT INTO sections (section_name, course_id) VALUES ('Section A', 1)")
        conn.execute("INSERT INTO students (roll_number, full_name, email, dept_id, program, semester, section_id) VALUES ('AI_STU_1', 'AI Student', 'ai@uni.edu', 1, 'BTech', 1, 1)")
        conn.execute("INSERT INTO sessions (teacher_id, created_at, expiry_time, token, status) VALUES (1, '2026-09-01 10:00:00', '2026-09-01 10:10:00', 'tok1', 'expired')")
        conn.commit()
        conn.close()

        # Check AI Risk Analytics page
        resp = self.client.get('/ai-risk-analytics')
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'AI-Powered Retention Engine', resp.data)
        self.assertIn(b'AI_STU_1', resp.data)

        # Check Dashboard alert banner integration
        resp_dash = self.client.get('/dashboard')
        self.assertEqual(resp_dash.status_code, 200)
        self.assertIn(b'AI Early Warning Alert', resp_dash.data)

    def test_11_ai_api_endpoints_and_notices(self):
        self.login('admin', 'admin123')
        
        conn = get_db_connection()
        conn.execute("INSERT INTO departments (name, code) VALUES ('Electrical', 'EE')")
        conn.execute("INSERT INTO courses (course_code, course_name, dept_id, semester) VALUES ('EE101', 'EE', 1, 1)")
        conn.execute("INSERT INTO sections (section_name, course_id) VALUES ('Section B', 1)")
        conn.execute("INSERT INTO students (roll_number, full_name, email, dept_id, program, semester, section_id) VALUES ('EE001', 'Electric Student', 'ee@uni.edu', 1, 'BTech', 1, 1)")
        conn.commit()
        conn.close()

        # API summary
        resp_summary = self.client.get('/api/ai-risk-summary')
        self.assertEqual(resp_summary.status_code, 200)
        data = resp_summary.get_json()
        self.assertIn('total_analyzed', data)

        # API student analysis
        resp_student = self.client.get('/api/ai-student-analysis/EE001')
        self.assertEqual(resp_student.status_code, 200)
        st_data = resp_student.get_json()
        self.assertEqual(st_data['roll_number'], 'EE001')

        # API notice generation
        resp_notice = self.client.post('/api/ai-generate-notice', json={'roll_number': 'EE001'})
        self.assertEqual(resp_notice.status_code, 200)
        notice_data = resp_notice.get_json()
        self.assertIn('notice', notice_data)
        self.assertIn('EE001', notice_data['notice'])

    def test_12_export_risk_report_csv(self):
        self.login('admin', 'admin123')
        resp = self.client.get('/export-risk-report')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Content-Type'], 'text/csv; charset=utf-8')
        self.assertIn(b'Roll Number,Full Name,Department', resp.data)

if __name__ == '__main__':
    unittest.main()

