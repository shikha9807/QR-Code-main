"""
AI Student Retention & Attendance Risk Prediction Engine
Provides predictive analytics, absence trend momentum analysis,
prescriptive recovery calculations, and automated academic intervention notices.
"""

from datetime import datetime
import math

class AIAttendancePredictor:
    """
    Predictive Intelligence engine that calculates student risk scores,
    attendance momentum, projected final semester percentages, and prescriptive recovery plans.
    """

    TARGET_THRESHOLD = 75.0  # Mandatory university minimum attendance percentage
    ASSUMED_SEMESTER_SESSIONS = 40  # Standard university lecture benchmark for projections

    @classmethod
    def calculate_student_metrics(cls, student, session_records, attended_session_ids):
        """
        Calculates detailed AI risk analytics for an individual student.
        
        :param student: dict-like or sqlite3.Row containing student profile
        :param session_records: list of all session dicts sorted by created_at ASC
        :param attended_session_ids: set of session_ids the student attended
        :return: comprehensive metrics dictionary
        """
        total_sessions = len(session_records)
        attended_count = len(attended_session_ids)
        
        # 1. Current Attendance Rate
        if total_sessions == 0:
            current_pct = 100.0
            attended_count = 0
        else:
            current_pct = round((attended_count / total_sessions) * 100, 1)

        # 2. Chronological sequence of presence (1 = present, 0 = absent)
        presence_sequence = []
        days_of_week_missed = {'Monday': 0, 'Tuesday': 0, 'Wednesday': 0, 'Thursday': 0, 'Friday': 0, 'Saturday': 0, 'Sunday': 0}
        
        for sess in session_records:
            sess_id = sess['id']
            is_present = sess_id in attended_session_ids
            presence_sequence.append(is_present)
            
            if not is_present:
                try:
                    sess_date = datetime.strptime(sess['created_at'], '%Y-%m-%d %H:%M:%S')
                    day_name = sess_date.strftime('%A')
                    days_of_week_missed[day_name] = days_of_week_missed.get(day_name, 0) + 1
                except Exception:
                    pass

        # 3. Absence Streak Detection (from most recent sessions backward)
        current_absence_streak = 0
        for is_present in reversed(presence_sequence):
            if not is_present:
                current_absence_streak += 1
            else:
                break

        # 4. Momentum Velocity (Recent 5 sessions vs Prior average)
        recent_window = min(5, total_sessions)
        if recent_window > 0:
            recent_attended = sum(1 for p in presence_sequence[-recent_window:] if p)
            recent_rate = (recent_attended / recent_window) * 100
        else:
            recent_rate = current_pct

        if total_sessions > recent_window:
            prior_attended = sum(1 for p in presence_sequence[:-recent_window] if p)
            prior_rate = (prior_attended / (total_sessions - recent_window)) * 100
            momentum_delta = round(recent_rate - prior_rate, 1)
        else:
            momentum_delta = 0.0

        if momentum_delta > 5:
            trend_label = "Improving"
            trend_icon = "fa-arrow-trend-up"
            trend_color = "var(--success)"
        elif momentum_delta < -5:
            trend_label = "Slipping"
            trend_icon = "fa-arrow-trend-down"
            trend_color = "var(--danger)"
        else:
            trend_label = "Stable"
            trend_icon = "fa-minus"
            trend_color = "var(--secondary)"

        # 5. Projected Final Semester Attendance
        # Uses a weighted momentum forecast: 60% historical base + 40% recent velocity
        remaining_sessions = max(0, cls.ASSUMED_SEMESTER_SESSIONS - total_sessions)
        if total_sessions == 0:
            projected_final_pct = 100.0
        else:
            weighted_rate = (0.6 * (current_pct / 100.0)) + (0.4 * (recent_rate / 100.0))
            expected_future_attended = round(remaining_sessions * weighted_rate)
            projected_final_attended = attended_count + expected_future_attended
            projected_final_pct = round((projected_final_attended / cls.ASSUMED_SEMESTER_SESSIONS) * 100, 1)
            projected_final_pct = max(0.0, min(100.0, projected_final_pct))

        # 6. Prescriptive Recovery Calculations
        # How many consecutive future classes needed to attain >= 75%?
        # Formula: (attended_count + X) / (total_sessions + X) >= 0.75
        # => attended_count + X >= 0.75 * total_sessions + 0.75 * X
        # => 0.25 * X >= 0.75 * total_sessions - attended_count
        # => X >= (3 * total_sessions - 4 * attended_count)
        if current_pct < cls.TARGET_THRESHOLD:
            numerator = (0.75 * total_sessions) - attended_count
            if numerator <= 0:
                consecutive_needed = 0
            else:
                consecutive_needed = math.ceil(numerator / 0.25)
            buffer_missable = 0
            recovery_message = f"Must attend next {consecutive_needed} consecutive class{'es' if consecutive_needed > 1 else ''} to reach 75%"
        else:
            consecutive_needed = 0
            # How many more can they miss before dropping below 75%?
            # Formula: attended_count / (total_sessions + Y) >= 0.75 => 0.75 * Y <= attended_count - 0.75 * total_sessions
            buffer_calc = math.floor((attended_count - (0.75 * total_sessions)) / 0.75) if total_sessions > 0 else 10
            buffer_missable = max(0, buffer_calc)
            if buffer_missable == 0:
                recovery_message = "On borderline: Cannot afford to miss any upcoming class"
            else:
                recovery_message = f"Can safely miss {buffer_missable} class{'es' if buffer_missable > 1 else ''} without falling below 75%"

        # 7. AI Defaulter Risk Score (0 = Perfect, 100 = Imminent Debarment)
        # Risk factors:
        # - Deficit from 75% threshold (0 - 50 pts)
        # - Projected final shortfall (0 - 30 pts)
        # - Current active absence streak (0 - 15 pts)
        # - Negative momentum penalty (0 - 5 pts)
        risk_score = 0
        if current_pct < cls.TARGET_THRESHOLD:
            shortfall = cls.TARGET_THRESHOLD - current_pct
            risk_score += min(50, int(shortfall * 1.5))
        
        if projected_final_pct < cls.TARGET_THRESHOLD:
            proj_shortfall = cls.TARGET_THRESHOLD - projected_final_pct
            risk_score += min(30, int(proj_shortfall * 1.2))
            
        risk_score += min(15, current_absence_streak * 5)
        
        if momentum_delta < -10:
            risk_score += 5

        risk_score = min(100, max(0, risk_score))

        # Risk Tier Classification
        if risk_score >= 60 or projected_final_pct < 65 or (current_pct < 70 and current_absence_streak >= 2):
            risk_level = "CRITICAL"
            risk_badge = "badge-danger"
            risk_label = "Critical Defaulter Risk"
            risk_summary = "High probability of exam debarment. Immediate academic counseling required."
        elif risk_score >= 25 or projected_final_pct < 78 or current_pct < 78 or momentum_delta < -8:
            risk_level = "MODERATE"
            risk_badge = "badge-warning"
            risk_label = "Moderate Warning"
            risk_summary = "Attendance is slipping or near borderline. Proactive warning advised."
        else:
            risk_level = "SAFE"
            risk_badge = "badge-success"
            risk_label = "Good Standing"
            risk_summary = "Consistent attendance record with healthy margin above university threshold."

        # Top day missed
        sorted_days = sorted(days_of_week_missed.items(), key=lambda x: x[1], reverse=True)
        most_missed_day = sorted_days[0][0] if sorted_days and sorted_days[0][1] > 0 else "None"

        return {
            'student_id': student['id'] if 'id' in student.keys() else None,
            'roll_number': student['roll_number'],
            'full_name': student['full_name'],
            'email': student['email'],
            'department': student['dept_name'] if 'dept_name' in student.keys() else (student.get('department') or 'General'),
            'section': student['section_name'] if 'section_name' in student.keys() else (student.get('section') or 'Default'),
            'semester': student['semester'] if 'semester' in student.keys() else 1,
            'total_sessions': total_sessions,
            'attended_count': attended_count,
            'missed_count': total_sessions - attended_count,
            'current_pct': current_pct,
            'projected_final_pct': projected_final_pct,
            'risk_score': risk_score,
            'risk_level': risk_level,
            'risk_badge': risk_badge,
            'risk_label': risk_label,
            'risk_summary': risk_summary,
            'recent_rate': recent_rate,
            'momentum_delta': momentum_delta,
            'trend_label': trend_label,
            'trend_icon': trend_icon,
            'trend_color': trend_color,
            'current_absence_streak': current_absence_streak,
            'consecutive_needed': consecutive_needed,
            'buffer_missable': buffer_missable,
            'recovery_message': recovery_message,
            'most_missed_day': most_missed_day,
            'days_of_week_missed': days_of_week_missed
        }

    @classmethod
    def analyze_all_students(cls, conn, dept_id=None, section_id=None, search=None, risk_filter=None, teacher_id=None):
        """
        Runs batch AI analysis over all students matching the criteria.
        
        :param conn: SQLite connection
        :param dept_id: optional department filter
        :param section_id: optional section filter
        :param search: optional text search on roll number or name
        :param risk_filter: 'CRITICAL', 'MODERATE', 'SAFE', or None
        :param teacher_id: if teacher, restrict session scope to their classes
        :return: (list_of_analyzed_students, summary_metrics)
        """
        # Fetch relevant sessions
        if teacher_id:
            sessions_query = "SELECT id, created_at FROM sessions WHERE teacher_id = ? ORDER BY created_at ASC"
            sessions = conn.execute(sessions_query, (teacher_id,)).fetchall()
        else:
            sessions_query = "SELECT id, created_at FROM sessions ORDER BY created_at ASC"
            sessions = conn.execute(sessions_query).fetchall()

        session_list = [{'id': s['id'], 'created_at': s['created_at']} for s in sessions]
        session_id_set = {s['id'] for s in session_list}

        # Fetch students query
        base_query = """
            SELECT s.*, d.name as dept_name, sec.section_name 
            FROM students s 
            LEFT JOIN departments d ON s.dept_id = d.id 
            LEFT JOIN sections sec ON s.section_id = sec.id
        """
        where_clauses = []
        params = []

        if dept_id:
            where_clauses.append("s.dept_id = ?")
            params.append(dept_id)
        if section_id:
            where_clauses.append("s.section_id = ?")
            params.append(section_id)
        if search:
            where_clauses.append("(s.roll_number LIKE ? OR s.full_name LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if where_clauses:
            base_query += " WHERE " + " AND ".join(where_clauses)

        base_query += " ORDER BY s.roll_number ASC"
        students = conn.execute(base_query, params).fetchall()

        # If no registered students exist, also look up raw student IDs from attendance logs
        raw_students = []
        if not students:
            raw_attendees = conn.execute("SELECT DISTINCT student_id FROM attendance").fetchall()
            for row in raw_attendees:
                roll = row['student_id']
                if search and (search.lower() not in roll.lower()):
                    continue
                raw_students.append({
                    'id': None,
                    'roll_number': roll,
                    'full_name': roll,
                    'email': f"{roll.lower()}@university.edu",
                    'dept_name': 'General Academic',
                    'section_name': 'Section A',
                    'semester': 1
                })
            students = raw_students

        # Pre-fetch all attendance records mapped by student identifier
        attendance_map = {}
        if session_id_set:
            # Query attendance records matching sessions
            placeholders = ','.join('?' * len(session_id_set))
            att_rows = conn.execute(f"SELECT session_id, student_id FROM attendance WHERE session_id IN ({placeholders})", list(session_id_set)).fetchall()
            for r in att_rows:
                st_id = r['student_id'].strip()
                if st_id not in attendance_map:
                    attendance_map[st_id] = set()
                attendance_map[st_id].add(r['session_id'])

        analyzed_students = []
        critical_count = 0
        moderate_count = 0
        safe_count = 0
        total_attendance_pct_sum = 0.0

        for st in students:
            # Match by roll_number or full_name
            roll_key = st['roll_number'].strip()
            name_key = st['full_name'].strip()
            
            attended_sessions = set()
            if roll_key in attendance_map:
                attended_sessions.update(attendance_map[roll_key])
            if name_key in attendance_map:
                attended_sessions.update(attendance_map[name_key])

            analysis = cls.calculate_student_metrics(st, session_list, attended_sessions)
            
            # Risk counters
            if analysis['risk_level'] == 'CRITICAL':
                critical_count += 1
            elif analysis['risk_level'] == 'MODERATE':
                moderate_count += 1
            else:
                safe_count += 1

            total_attendance_pct_sum += analysis['current_pct']

            # Filter by risk level if requested
            if risk_filter and risk_filter.upper() != 'ALL':
                if analysis['risk_level'] != risk_filter.upper():
                    continue

            analyzed_students.append(analysis)

        total_analyzed = len(students)
        avg_attendance = round(total_attendance_pct_sum / total_analyzed, 1) if total_analyzed > 0 else 100.0

        # Sort students: CRITICAL first, then by lowest current percentage
        analyzed_students.sort(key=lambda x: (
            0 if x['risk_level'] == 'CRITICAL' else (1 if x['risk_level'] == 'MODERATE' else 2),
            x['current_pct']
        ))

        summary = {
            'total_analyzed': total_analyzed,
            'critical_count': critical_count,
            'moderate_count': moderate_count,
            'safe_count': safe_count,
            'avg_attendance': avg_attendance,
            'total_sessions_tracked': len(session_list)
        }

        return analyzed_students, summary

    @classmethod
    def get_student_detail(cls, conn, roll_number, teacher_id=None):
        """
        Retrieves in-depth analysis for a specific student.
        """
        student = conn.execute("""
            SELECT s.*, d.name as dept_name, sec.section_name 
            FROM students s 
            LEFT JOIN departments d ON s.dept_id = d.id 
            LEFT JOIN sections sec ON s.section_id = sec.id
            WHERE s.roll_number = ?
        """, (roll_number,)).fetchone()

        if not student:
            # Fallback for dynamic attendee
            student = {
                'id': None,
                'roll_number': roll_number,
                'full_name': roll_number,
                'email': f"{roll_number.lower()}@university.edu",
                'dept_name': 'General Academic',
                'section_name': 'Section A',
                'semester': 1
            }

        if teacher_id:
            sessions = conn.execute("SELECT id, created_at FROM sessions WHERE teacher_id = ? ORDER BY created_at ASC", (teacher_id,)).fetchall()
        else:
            sessions = conn.execute("SELECT id, created_at FROM sessions ORDER BY created_at ASC").fetchall()

        session_list = [{'id': s['id'], 'created_at': s['created_at']} for s in sessions]
        
        att_rows = conn.execute("SELECT session_id FROM attendance WHERE student_id = ?", (roll_number,)).fetchall()
        attended_sessions = {r['session_id'] for r in att_rows}

        return cls.calculate_student_metrics(student, session_list, attended_sessions)

    @classmethod
    def generate_notice_text(cls, analysis, university_name="Metropolitan University"):
        """
        Generates a formal, personalized academic intervention letter ready for email/printing.
        """
        today_str = datetime.now().strftime('%B %d, %Y')
        roll = analysis['roll_number']
        name = analysis['full_name']
        dept = analysis['department']
        sec = analysis['section']
        pct = analysis['current_pct']
        proj = analysis['projected_final_pct']
        streak = analysis['current_absence_streak']
        recovery = analysis['recovery_message']

        if analysis['risk_level'] == 'CRITICAL':
            urgency = "OFFICIAL ATTENDANCE DEFAULTER WARNING — URGENT ACTION REQUIRED"
            tone_msg = (
                f"Your current attendance standing is at a critical deficit of {pct}%, which falls significantly below "
                f"the mandatory university minimum requirement of 75.0%. Our AI retention forecast indicates that if current absence "
                f"patterns continue, your projected final semester attendance will reach {proj}%, resulting in immediate debarment "
                f"from upcoming end-semester examinations and laboratory assessments."
            )
        elif analysis['risk_level'] == 'MODERATE':
            urgency = "ACADEMIC ADVISORY: ATTENDANCE DEFICIT ALERT"
            tone_msg = (
                f"This advisory notice is to inform you that your current attendance is at {pct}%. "
                f"You are approaching the university minimum threshold of 75.0%. To prevent academic penalties or exam eligibility restrictions, "
                f"you are strongly advised to maintain regular lecture attendance immediately."
            )
        else:
            urgency = "ACADEMIC ATTENDANCE STANDING CERTIFICATE"
            tone_msg = (
                f"Congratulations on maintaining consistent attendance of {pct}%. "
                f"Your academic engagement is in good standing."
            )

        streak_text = f"\n• Active Consecutive Absence Streak: {streak} class(es)" if streak > 1 else ""

        notice = f"""================================================================================
{university_name.upper()} — OFFICE OF ACADEMIC AFFAIRS
{urgency}
Date: {today_str}
================================================================================

TO:
Student Name  : {name}
Roll Number   : {roll}
Department    : {dept} (Section {sec})
Email Address : {analysis['email']}

SUBJECT: Formal Academic Notification Regarding Attendance & Eligibility

Dear {name},

{tone_msg}

KEY ATTENDANCE ANALYTICS & AI FORECAST:
--------------------------------------------------------------------------------
• Total Classes Held To Date       : {analysis['total_sessions']}
• Total Classes Attended          : {analysis['attended_count']}
• Current Attendance Percentage   : {pct}%
• AI Projected Semester Outcome   : {proj}%
• Current Risk Assessment Tier    : {analysis['risk_label'].upper()}{streak_text}
• AI Prescriptive Action Plan     : {recovery}
--------------------------------------------------------------------------------

REQUIRED NEXT STEPS:
1. Report to your Department Mentor / Course Instructor within 48 hours to discuss an academic recovery plan.
2. Ensure 100% presence in all forthcoming scheduled lecture sessions and practical laboratories.
3. If absences were due to medical emergencies, submit verified medical documentation via the University portal.

Failure to meet the mandatory 75% attendance criterion by the end of the term will lead to debarment as per University Academic Regulations.

Sincerely,

Office of the Dean & Academic Evaluation Board
{university_name}
Ref ID: ATT-AI-{roll}-{datetime.now().strftime('%Y%m%d')}
================================================================================"""
        return notice
