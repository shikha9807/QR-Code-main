"""
AI-Based Leave Management & Attendance Impact Engine
Handles timetable-aware attendance impact calculations, what-if simulations,
subject-wise breakdown, approval workflows, audit logging, and notification dispatch.
"""

from datetime import datetime, date, timedelta
import math
import os
import sqlite3

class SystemSettingsManager:
    """Helper to fetch and manage configurable system settings."""
    @staticmethod
    def get_setting(conn, key, default=None):
        row = conn.execute("SELECT value FROM system_settings WHERE key = ?", (key,)).fetchone()
        if row:
            return row['value']
        return default

    @staticmethod
    def get_float(conn, key, default=75.0):
        val = SystemSettingsManager.get_setting(conn, key, None)
        try:
            return float(val) if val is not None else float(default)
        except (ValueError, TypeError):
            return float(default)

    @staticmethod
    def get_int(conn, key, default=3):
        val = SystemSettingsManager.get_setting(conn, key, None)
        try:
            return int(val) if val is not None else int(default)
        except (ValueError, TypeError):
            return int(default)

    @staticmethod
    def set_setting(conn, key, value, description=None):
        if description:
            conn.execute("""
                INSERT INTO system_settings (key, value, description) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, description = excluded.description
            """, (key, str(value), description))
        else:
            conn.execute("""
                INSERT INTO system_settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """, (key, str(value)))


class AuditLogger:
    """Centralized Audit Trail Logger for university compliance."""
    @staticmethod
    def log(conn, user_id, username, action, target_type, target_id, details=None, ip_address=None):
        conn.execute("""
            INSERT INTO audit_logs (user_id, username, action, target_type, target_id, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, action, target_type, str(target_id) if target_id is not None else None, details, ip_address))


class NotificationManager:
    """In-app and dispatch notification engine."""
    @staticmethod
    def create_notification(conn, user_id, title, message, notif_type='INFO', link=None):
        if not user_id:
            return None
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO notifications (user_id, title, message, type, link, is_read)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (user_id, title, message, notif_type, link))
        return cursor.lastrowid

    @staticmethod
    def notify_role(conn, role, title, message, notif_type='INFO', link=None, dept_id=None):
        query = "SELECT id FROM users WHERE role = ?"
        params = [role]
        if dept_id is not None and role != 'admin':
            query += " AND (dept_id = ? OR dept_id IS NULL)"
            params.append(dept_id)
        users = conn.execute(query, params).fetchall()
        for u in users:
            NotificationManager.create_notification(conn, u['id'], title, message, notif_type, link)

    @staticmethod
    def get_user_notifications(conn, user_id, limit=20):
        return conn.execute("""
            SELECT * FROM notifications 
            WHERE user_id = ? 
            ORDER BY created_at DESC LIMIT ?
        """, (user_id, limit)).fetchall()

    @staticmethod
    def get_unread_count(conn, user_id):
        row = conn.execute("SELECT COUNT(*) as count FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,)).fetchone()
        return row['count'] if row else 0

    @staticmethod
    def mark_as_read(conn, notif_id, user_id):
        conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (notif_id, user_id))

    @staticmethod
    def mark_all_as_read(conn, user_id):
        conn.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))


class LeaveCalculator:
    """
    Core computation engine for timetable-aware attendance calculations,
    impact assessments, what-if projections, and subject-wise breakdowns.
    """

    @staticmethod
    def get_student(conn, identifier):
        """Retrieves student record by id, roll_number, or email."""
        if isinstance(identifier, int) or (isinstance(identifier, str) and identifier.isdigit()):
            row = conn.execute("""
                SELECT s.*, d.name as dept_name, sec.section_name 
                FROM students s
                LEFT JOIN departments d ON s.dept_id = d.id
                LEFT JOIN sections sec ON s.section_id = sec.id
                WHERE s.id = ?
            """, (int(identifier),)).fetchone()
            if row:
                return dict(row)

        row = conn.execute("""
            SELECT s.*, d.name as dept_name, sec.section_name 
            FROM students s
            LEFT JOIN departments d ON s.dept_id = d.id
            LEFT JOIN sections sec ON s.section_id = sec.id
            WHERE s.roll_number = ? OR s.email = ?
        """, (str(identifier), str(identifier))).fetchone()
        if row:
            return dict(row)

        # Fallback for dynamic attendee without formal registration
        return {
            'id': None,
            'roll_number': str(identifier),
            'full_name': str(identifier),
            'email': f"{str(identifier).lower()}@university.edu",
            'dept_id': None,
            'dept_name': 'General Academic',
            'section_id': None,
            'section_name': 'Section A',
            'semester': 1
        }

    @staticmethod
    def get_student_attendance_summary(conn, roll_number):
        """Returns attended and conducted session counts for a student."""
        total_sessions_row = conn.execute("SELECT COUNT(*) as count FROM sessions").fetchone()
        total_conducted = total_sessions_row['count'] if total_sessions_row else 0

        attended_row = conn.execute("SELECT COUNT(DISTINCT session_id) as count FROM attendance WHERE student_id = ?", (roll_number,)).fetchone()
        attended_count = attended_row['count'] if attended_row else 0

        if total_conducted == 0:
            current_pct = 100.0
        else:
            current_pct = round((attended_count / total_conducted) * 100.0, 1)

        missed_count = max(0, total_conducted - attended_count)
        return {
            'conducted': total_conducted,
            'attended': attended_count,
            'missed': missed_count,
            'current_pct': current_pct
        }

    @staticmethod
    def get_scheduled_classes_in_range(conn, student, start_date_str, end_date_str):
        """
        Integrates with the Timetable & Academic Calendar to calculate exactly which
        classes are scheduled during the specified leave window.
        """
        try:
            start_d = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_d = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except Exception:
            return []

        if start_d > end_d:
            return []

        # Fetch academic calendar holidays in range
        holidays_rows = conn.execute("""
            SELECT event_date, title, is_holiday FROM academic_calendar 
            WHERE event_date BETWEEN ? AND ?
        """, (start_date_str, end_date_str)).fetchall()
        holiday_map = {row['event_date']: row for row in holidays_rows}

        # Fetch student section timetable
        section_id = student.get('section_id')
        timetable_entries = []
        if section_id:
            timetable_entries = conn.execute("""
                SELECT t.*, c.course_name, c.course_code 
                FROM timetable t
                JOIN courses c ON t.course_id = c.id
                WHERE t.section_id = ?
            """, (section_id,)).fetchall()

        # If no timetable entries configured for section, check if general timetable exists
        if not timetable_entries:
            timetable_entries = conn.execute("""
                SELECT t.*, c.course_name, c.course_code 
                FROM timetable t
                JOIN courses c ON t.course_id = c.id
            """).fetchall()

        scheduled_classes = []
        cur = start_d
        days_of_week = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

        while cur <= end_d:
            cur_str = cur.strftime('%Y-%m-%d')
            day_name = days_of_week[cur.weekday()]

            # Check if this date is an official holiday
            if cur_str in holiday_map and holiday_map[cur_str]['is_holiday'] == 1:
                cur += timedelta(days=1)
                continue

            # Sunday default skip unless configured as special working day
            if cur.weekday() == 6:
                if cur_str not in holiday_map or holiday_map[cur_str]['is_holiday'] == 1:
                    cur += timedelta(days=1)
                    continue

            # Find timetable slots for this day
            day_slots = [t for t in timetable_entries if t['day_of_week'].lower() == day_name.lower()]
            if day_slots:
                for slot in day_slots:
                    scheduled_classes.append({
                        'date': cur_str,
                        'day_of_week': day_name,
                        'course_id': slot['course_id'],
                        'course_code': slot['course_code'],
                        'course_name': slot['course_name'],
                        'start_time': slot['start_time'],
                        'end_time': slot['end_time'],
                        'room': slot['room'] or 'Lecture Hall'
                    })
            else:
                # If no timetable entry for this weekday, add 1 standard lecture slot as fallback
                scheduled_classes.append({
                    'date': cur_str,
                    'day_of_week': day_name,
                    'course_id': None,
                    'course_code': 'GEN101',
                    'course_name': 'Scheduled Core Lecture',
                    'start_time': '09:00',
                    'end_time': '10:00',
                    'room': 'Main Block'
                })

            cur += timedelta(days=1)

        return scheduled_classes

    @classmethod
    def calculate_leave_impact(cls, conn, student_identifier, start_date_str, end_date_str, leave_type_id=None, leave_type_code=None):
        """
        Calculates the exact before and after attendance figures for a proposed leave.
        Formula:
            Current Attendance = Attended / Conducted
            Projected Attendance = Attended / (Conducted + Affected_During_Leave)
            (Or if duty leave and compensated: (Attended + Affected) / (Conducted + Affected))
        """
        student = cls.get_student(conn, student_identifier)
        roll_number = student['roll_number']

        att_summary = cls.get_student_attendance_summary(conn, roll_number)
        conducted = att_summary['conducted']
        attended = att_summary['attended']
        missed = att_summary['missed']
        current_pct = att_summary['current_pct']

        # Determine leave type properties
        is_duty_leave = False
        if leave_type_code and 'DUTY' in leave_type_code.upper():
            is_duty_leave = True
        elif leave_type_id:
            lt_row = conn.execute("SELECT code FROM leave_types WHERE id = ?", (leave_type_id,)).fetchone()
            if lt_row and 'DUTY' in lt_row['code'].upper():
                is_duty_leave = True

        duty_compensated = SystemSettingsManager.get_setting(conn, 'duty_leave_counts_as_present', '1') == '1'
        threshold = SystemSettingsManager.get_float(conn, 'attendance_threshold', 75.0)

        scheduled = cls.get_scheduled_classes_in_range(conn, student, start_date_str, end_date_str)
        affected_count = len(scheduled)

        # Projected Calculations
        if conducted == 0 and affected_count == 0:
            projected_conducted = 0
            projected_attended = 0
            projected_pct = 100.0
        elif conducted == 0:
            projected_conducted = affected_count
            projected_attended = affected_count if (is_duty_leave and duty_compensated) else 0
            projected_pct = round((projected_attended / projected_conducted) * 100.0, 1)
        else:
            projected_conducted = conducted + affected_count
            if is_duty_leave and duty_compensated:
                projected_attended = attended + affected_count
            else:
                projected_attended = attended
            projected_pct = round((projected_attended / projected_conducted) * 100.0, 1)
            projected_pct = max(0.0, min(100.0, projected_pct))

        pct_drop = round(current_pct - projected_pct, 1)

        # Risk Classification
        if projected_pct < threshold:
            risk_level = "HIGH_RISK"
            risk_badge = "badge-ai-critical"
            risk_label = "High Risk (Exam Debarment Threat)"
            risk_message = f"Projected attendance ({projected_pct}%) will fall BELOW the mandatory {threshold}% threshold!"
        elif projected_pct < (threshold + 5.0):
            risk_level = "WARNING"
            risk_badge = "badge-ai-moderate"
            risk_label = "Borderline Warning Alert"
            risk_message = f"Projected attendance ({projected_pct}%) is near the borderline of the {threshold}% threshold."
        else:
            risk_level = "SAFE"
            risk_badge = "badge-ai-safe"
            risk_label = "Safe Standing"
            risk_message = f"Projected attendance ({projected_pct}%) remains safely above the {threshold}% requirement."

        # Recovery requirement if projected is below threshold
        if projected_pct < threshold and threshold < 100.0:
            # (projected_attended + X) / (projected_conducted + X) >= threshold / 100
            # => X >= (threshold * projected_conducted - 100 * projected_attended) / (100 - threshold)
            numerator = ((threshold / 100.0) * projected_conducted) - projected_attended
            consecutive_needed = max(0, math.ceil(numerator / (1.0 - (threshold / 100.0))))
        else:
            consecutive_needed = 0

        # Safe miss buffer
        if projected_pct >= threshold and threshold > 0.0:
            # projected_attended / (projected_conducted + Y) >= threshold / 100
            # => Y <= (projected_attended - (threshold/100) * projected_conducted) / (threshold/100)
            buffer_calc = math.floor((projected_attended - ((threshold / 100.0) * projected_conducted)) / (threshold / 100.0))
            buffer_missable = max(0, buffer_calc)
        else:
            buffer_missable = 0

        return {
            'student': student,
            'roll_number': roll_number,
            'start_date': start_date_str,
            'end_date': end_date_str,
            'conducted_classes': conducted,
            'attended_classes': attended,
            'missed_classes': missed,
            'current_attendance_pct': current_pct,
            'affected_classes': affected_count,
            'scheduled_classes': scheduled,
            'projected_conducted': projected_conducted,
            'projected_attended': projected_attended,
            'projected_attendance_pct': projected_pct,
            'percentage_drop': pct_drop,
            'threshold': threshold,
            'risk_level': risk_level,
            'risk_badge': risk_badge,
            'risk_label': risk_label,
            'risk_message': risk_message,
            'consecutive_needed': consecutive_needed,
            'buffer_missable': buffer_missable,
            'is_duty_leave': is_duty_leave
        }

    @classmethod
    def calculate_subject_wise_impact(cls, conn, student_identifier, start_date_str, end_date_str):
        """
        Calculates per-subject attendance impact for each enrolled course.
        """
        student = cls.get_student(conn, student_identifier)
        roll_number = student['roll_number']
        threshold = SystemSettingsManager.get_float(conn, 'attendance_threshold', 75.0)

        # Find courses associated with student's department/section
        courses_query = """
            SELECT c.id as course_id, c.course_code, c.course_name 
            FROM courses c
            WHERE (c.dept_id = ? OR ? IS NULL)
            ORDER BY c.course_code ASC
        """
        courses = conn.execute(courses_query, (student.get('dept_id'), student.get('dept_id'))).fetchall()
        if not courses:
            courses = conn.execute("SELECT id as course_id, course_code, course_name FROM courses ORDER BY course_code ASC").fetchall()

        scheduled = cls.get_scheduled_classes_in_range(conn, student, start_date_str, end_date_str)
        course_miss_map = {}
        for s in scheduled:
            c_id = s.get('course_id')
            if c_id:
                course_miss_map[c_id] = course_miss_map.get(c_id, 0) + 1

        overall_att = cls.get_student_attendance_summary(conn, roll_number)
        base_conducted = max(1, overall_att['conducted'] // max(1, len(courses) if courses else 1))
        base_attended = max(0, overall_att['attended'] // max(1, len(courses) if courses else 1))

        subject_impacts = []
        for c in courses:
            c_id = c['course_id']
            c_code = c['course_code']
            c_name = c['course_name']
            
            c_missed_during_leave = course_miss_map.get(c_id, 1 if not course_miss_map else 0)

            c_conducted = base_conducted
            c_attended = min(c_conducted, base_attended)
            c_current_pct = round((c_attended / c_conducted) * 100.0, 1)

            c_projected_conducted = c_conducted + c_missed_during_leave
            c_projected_attended = c_attended
            c_projected_pct = round((c_projected_attended / c_projected_conducted) * 100.0, 1)

            sub_risk = "SAFE" if c_projected_pct >= (threshold + 5.0) else ("WARNING" if c_projected_pct >= threshold else "HIGH_RISK")

            subject_impacts.append({
                'course_id': c_id,
                'course_code': c_code,
                'course_name': c_name,
                'conducted': c_conducted,
                'attended': c_attended,
                'current_pct': c_current_pct,
                'classes_affected': c_missed_during_leave,
                'projected_pct': c_projected_pct,
                'delta': round(c_current_pct - c_projected_pct, 1),
                'risk_level': sub_risk
            })

        return subject_impacts

    @classmethod
    def simulate_what_if(cls, conn, student_identifier, scenarios=None, custom_miss=None):
        """
        Interactive simulation for what-if future absences.
        """
        student = cls.get_student(conn, student_identifier)
        roll_number = student['roll_number']
        att_summary = cls.get_student_attendance_summary(conn, roll_number)
        conducted = att_summary['conducted']
        attended = att_summary['attended']
        current_pct = att_summary['current_pct']
        threshold = SystemSettingsManager.get_float(conn, 'attendance_threshold', 75.0)

        if not scenarios:
            scenarios = [1, 2, 3, 5, 8, 10]

        if custom_miss is not None and custom_miss not in scenarios:
            scenarios.append(int(custom_miss))
            scenarios.sort()

        results = []
        for miss in scenarios:
            if conducted == 0:
                proj_cond = miss
                proj_att = 0
                proj_pct = 0.0
            else:
                proj_cond = conducted + miss
                proj_att = attended
                proj_pct = round((proj_att / proj_cond) * 100.0, 1)

            risk = "SAFE" if proj_pct >= (threshold + 5.0) else ("WARNING" if proj_pct >= threshold else "HIGH_RISK")
            
            results.append({
                'miss_count': miss,
                'projected_conducted': proj_cond,
                'projected_attended': proj_att,
                'projected_pct': proj_pct,
                'drop': round(current_pct - proj_pct, 1),
                'risk_level': risk,
                'is_below_threshold': proj_pct < threshold
            })

        # Consecutive classes needed to reach threshold
        if current_pct < threshold and threshold < 100.0:
            numerator = ((threshold / 100.0) * conducted) - attended
            consecutive_needed = max(0, math.ceil(numerator / (1.0 - (threshold / 100.0))))
        else:
            consecutive_needed = 0

        # Safe miss buffer
        if current_pct >= threshold and threshold > 0.0:
            buffer_calc = math.floor((attended - ((threshold / 100.0) * conducted)) / (threshold / 100.0))
            buffer_missable = max(0, buffer_calc)
        else:
            buffer_missable = 0

        return {
            'student': student,
            'current_attendance_pct': current_pct,
            'conducted': conducted,
            'attended': attended,
            'threshold': threshold,
            'consecutive_needed': consecutive_needed,
            'buffer_missable': buffer_missable,
            'scenarios': results
        }


class LeaveWorkflowManager:
    """
    Manages leave request submissions, approval state transitions,
    document linkages, and automated stakeholder notifications.
    """

    @staticmethod
    def submit_leave_request(conn, user_id, roll_number, leave_type_id, start_date_str, end_date_str, reason, description=None, applied_via='form', file_data=None, ip_address=None):
        """
        Creates and validates a new student leave request.
        """
        # Validate dates
        try:
            start_d = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_d = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return False, "Invalid date format. Expected YYYY-MM-DD.", None

        if start_d > end_d:
            return False, "End date cannot be prior to start date.", None

        total_days = (end_d - start_d).days + 1

        # Check leave type
        lt_row = conn.execute("SELECT * FROM leave_types WHERE id = ?", (leave_type_id,)).fetchone()
        if not lt_row:
            return False, "Selected leave type does not exist.", None

        if total_days > lt_row['max_days']:
            return False, f"Maximum allowed duration for {lt_row['name']} is {lt_row['max_days']} days (requested {total_days} days).", None

        student = LeaveCalculator.get_student(conn, roll_number)
        student_id = student['id']

        # Check for duplicate overlapping leave requests
        overlap = conn.execute("""
            SELECT id FROM leave_requests 
            WHERE roll_number = ? 
            AND status NOT IN ('REJECTED', 'CANCELLED')
            AND (
                (start_date <= ? AND end_date >= ?) OR
                (start_date <= ? AND end_date >= ?) OR
                (start_date >= ? AND end_date <= ?)
            )
        """, (roll_number, start_date_str, start_date_str, end_date_str, end_date_str, start_date_str, end_date_str)).fetchone()

        if overlap:
            return False, f"An active leave request (#LEAVE-{overlap['id']}) already overlaps with these dates.", None

        # Compute AI Attendance Impact
        impact = LeaveCalculator.calculate_leave_impact(conn, student, start_date_str, end_date_str, leave_type_id=leave_type_id)

        # Determine initial approval workflow state
        hod_threshold_days = SystemSettingsManager.get_int(conn, 'hod_approval_days_threshold', 3)
        if total_days > hod_threshold_days or lt_row['requires_hod_approval'] == 1:
            initial_status = 'PENDING_HOD'
        else:
            initial_status = 'PENDING_FACULTY'

        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO leave_requests (
                student_id, roll_number, leave_type_id, start_date, end_date,
                total_days, reason, description, applied_via,
                current_attendance_pct, projected_attendance_pct,
                conducted_classes, attended_classes, affected_classes,
                risk_level, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            student_id, roll_number, leave_type_id, start_date_str, end_date_str,
            total_days, reason, description, applied_via,
            impact['current_attendance_pct'], impact['projected_attendance_pct'],
            impact['conducted_classes'], impact['attended_classes'], impact['affected_classes'],
            impact['risk_level'], initial_status
        ))
        leave_id = cursor.lastrowid

        # Attach document if uploaded
        doc_id = None
        if file_data:
            cursor.execute("""
                INSERT INTO leave_documents (
                    leave_request_id, filename, original_filename, file_path,
                    file_size, file_type, ocr_extracted_text, ocr_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                leave_id, file_data['filename'], file_data['original_filename'],
                file_data['file_path'], file_data['file_size'], file_data['file_type'],
                file_data.get('ocr_text', ''), file_data.get('ocr_status', 'PROCESSED')
            ))
            doc_id = cursor.lastrowid

        # Record submission in workflow history
        cursor.execute("""
            INSERT INTO leave_approvals (leave_request_id, approver_id, action, role, remarks)
            VALUES (?, ?, ?, ?, ?)
        """, (leave_id, user_id or 1, 'SUBMITTED', 'student', 'Leave application submitted by student'))

        # Log Audit Trail
        AuditLogger.log(conn, user_id, student.get('full_name') or roll_number, 'LEAVE_SUBMITTED', 'leave_requests', leave_id,
                        f"Leave submitted for {total_days} days ({start_date_str} to {end_date_str}). Projected Attendance: {impact['projected_attendance_pct']}%", ip_address)

        # Dispatch Notifications
        # 1. Student confirmation notification
        if user_id:
            NotificationManager.create_notification(
                conn, user_id,
                f"Leave Application #LEAVE-{leave_id} Submitted",
                f"Your {lt_row['name']} for {start_date_str} to {end_date_str} has been submitted for review. Projected Attendance: {impact['projected_attendance_pct']}%.",
                'SUCCESS' if impact['risk_level'] == 'SAFE' else 'WARNING',
                f"/student/leave/history"
            )

        # 2. Alert faculty / HOD
        target_role = 'hod' if initial_status == 'PENDING_HOD' else 'teacher'
        NotificationManager.notify_role(
            conn, target_role,
            f"New Leave Request: {student['full_name']} ({roll_number})",
            f"New {lt_row['name']} ({total_days}d). Projected Attendance: {impact['projected_attendance_pct']}% ({impact['risk_level']}).",
            'WARNING' if impact['risk_level'] == 'HIGH_RISK' else 'INFO',
            f"/faculty/leave-requests" if target_role == 'teacher' else f"/hod/leave-requests",
            dept_id=student.get('dept_id')
        )

        return True, "Leave application successfully submitted.", leave_id

    @staticmethod
    def process_approval_action(conn, leave_id, approver_user, action, remarks=None, ip_address=None):
        """
        Executes workflow actions on a leave request:
        Actions: 'APPROVE', 'REJECT', 'FORWARD_TO_HOD', 'REQUEST_CLARIFICATION'
        """
        leave = conn.execute("SELECT * FROM leave_requests WHERE id = ?", (leave_id,)).fetchone()
        if not leave:
            return False, "Leave request not found."

        approver_id = approver_user['id']
        approver_role = approver_user['role']
        approver_name = approver_user.get('full_name') or approver_user['username']
        current_status = leave['status']

        # Permission verification
        if approver_role not in ['admin', 'teacher', 'hod']:
            return False, "Unauthorized: Insufficient permissions to process leave requests."

        new_status = current_status
        action_clean = action.strip().upper()

        if action_clean == 'APPROVE':
            new_status = 'APPROVED'
            action_desc = f"Approved by {approver_role.upper()} ({approver_name})"
        elif action_clean == 'REJECT':
            new_status = 'REJECTED'
            action_desc = f"Rejected by {approver_role.upper()} ({approver_name})"
        elif action_clean == 'FORWARD_TO_HOD':
            if approver_role not in ['admin', 'teacher']:
                return False, "Only faculty/admin can escalate to HOD."
            new_status = 'PENDING_HOD'
            action_desc = f"Forwarded to HOD for executive review by {approver_name}"
        elif action_clean == 'REQUEST_CLARIFICATION':
            new_status = 'CLARIFICATION_REQUESTED'
            action_desc = f"Clarification / Supporting Documents Requested by {approver_name}"
        else:
            return False, f"Unknown action: {action}"

        # Update leave status
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute("""
            UPDATE leave_requests 
            SET status = ?, updated_at = ?
            WHERE id = ?
        """, (new_status, now_str, leave_id))

        # Record in approval history
        conn.execute("""
            INSERT INTO leave_approvals (leave_request_id, approver_id, action, role, remarks)
            VALUES (?, ?, ?, ?, ?)
        """, (leave_id, approver_id, action_clean, approver_role, remarks or action_desc))

        # Log audit trail
        AuditLogger.log(conn, approver_id, approver_name, f"LEAVE_{action_clean}", 'leave_requests', leave_id,
                        f"Status changed from {current_status} to {new_status}. Remarks: {remarks}", ip_address)

        # Find student user account to notify
        student_user = conn.execute("SELECT id FROM users WHERE username = ? OR email = (SELECT email FROM students WHERE roll_number = ?)",
                                    (leave['roll_number'], leave['roll_number'])).fetchone()
        if student_user:
            notif_type = 'SUCCESS' if new_status == 'APPROVED' else ('DANGER' if new_status == 'REJECTED' else 'WARNING')
            NotificationManager.create_notification(
                conn, student_user['id'],
                f"Leave Request #LEAVE-{leave_id} Update: {new_status}",
                f"Your leave request has been marked as {new_status}. Remarks: {remarks or 'No remarks provided.'}",
                notif_type,
                "/student/leave/history"
            )

        # If forwarded to HOD, alert HODs
        if new_status == 'PENDING_HOD':
            student = LeaveCalculator.get_student(conn, leave['roll_number'])
            NotificationManager.notify_role(
                conn, 'hod',
                f"Escalated Leave Request: {student['full_name']} ({leave['roll_number']})",
                f"Faculty {approver_name} escalated leave #{leave_id} for HOD review. Projected Att: {leave['projected_attendance_pct']}%.",
                'WARNING' if leave['risk_level'] == 'HIGH_RISK' else 'INFO',
                "/hod/leave-requests",
                dept_id=student.get('dept_id')
            )

        return True, f"Leave request successfully marked as {new_status}."

    @staticmethod
    def get_filtered_leave_requests(conn, role='admin', user_id=None, status_filter=None, risk_filter=None, leave_type_filter=None, dept_filter=None, search=None, start_date=None, end_date=None):
        """
        Comprehensive multi-criteria query for faculty, HOD, and admin leave dashboards.
        """
        query = """
            SELECT lr.*, lt.name as leave_type_name, lt.code as leave_type_code,
                   s.full_name as student_name, s.email as student_email,
                   d.name as dept_name, sec.section_name,
                   (SELECT original_filename FROM leave_documents WHERE leave_request_id = lr.id LIMIT 1) as doc_name,
                   (SELECT id FROM leave_documents WHERE leave_request_id = lr.id LIMIT 1) as doc_id
            FROM leave_requests lr
            LEFT JOIN leave_types lt ON lr.leave_type_id = lt.id
            LEFT JOIN students s ON lr.roll_number = s.roll_number
            LEFT JOIN departments d ON s.dept_id = d.id
            LEFT JOIN sections sec ON s.section_id = sec.id
            WHERE 1=1
        """
        params = []

        if status_filter and status_filter.upper() != 'ALL':
            query += " AND lr.status = ?"
            params.append(status_filter.upper())

        if risk_filter and risk_filter.upper() != 'ALL':
            query += " AND lr.risk_level = ?"
            params.append(risk_filter.upper())

        if leave_type_filter and leave_type_filter != 'ALL':
            query += " AND lr.leave_type_id = ?"
            params.append(leave_type_filter)

        if dept_filter and dept_filter != 'ALL':
            query += " AND s.dept_id = ?"
            params.append(dept_filter)

        if search:
            query += " AND (lr.roll_number LIKE ? OR s.full_name LIKE ? OR lr.reason LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        if start_date:
            query += " AND lr.start_date >= ?"
            params.append(start_date)

        if end_date:
            query += " AND lr.end_date <= ?"
            params.append(end_date)

        query += " ORDER BY lr.created_at DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
