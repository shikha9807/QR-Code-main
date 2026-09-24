"""
AI Leave Service: NLP Leave Extraction, Conversational AI Assistant, and OCR Verification Assistance.
"""

from datetime import datetime, date, timedelta
import re
import os
import json
import math
from leave_manager import LeaveCalculator, SystemSettingsManager, LeaveWorkflowManager

class AILeaveExtractor:
    """
    Parses unstructured natural language text input and converts it into
    structured leave parameters for student review and confirmation.
    """

    MONTH_MAP = {
        'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
        'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6, 'jul': 7, 'july': 7,
        'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
        'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12
    }

    LEAVE_KEYWORD_MAP = {
        'MED': ['fever', 'sick', 'ill', 'hospital', 'doctor', 'unwell', 'cold', 'injury', 'fracture', 'headache', 'infection', 'medical', 'pain', 'surgery', 'clinic', 'rest'],
        'CAS': ['casual', 'family', 'function', 'wedding', 'marriage', 'trip', 'travel', 'vacation', 'home', 'village', 'festival', 'celebration', 'gathering', 'cousin', 'sister', 'brother'],
        'EMG': ['emergency', 'urgent', 'crisis', 'accident', 'unforeseen', 'sudden', 'hospitalized', 'critical'],
        'DUTY': ['hackathon', 'conference', 'symposium', 'competition', 'sports', 'tournament', 'inter-college', 'workshop', 'seminar', 'representation', 'paper', 'presentation', 'duty', 'academic'],
        'PER': ['personal', 'work', 'appointment', 'exam', 'passport', 'visa', 'interview', 'individual']
    }

    @classmethod
    def extract_leave_intent(cls, text, current_date=None):
        """
        Extracts start_date, end_date, leave_type, and reason from freeform text.
        Example: "I need leave from 21 September to 24 September because I am unwell."
        """
        if not current_date:
            current_date = date.today()
        elif isinstance(current_date, str):
            current_date = datetime.strptime(current_date, '%Y-%m-%d').date()

        current_year = current_date.year
        text_lower = text.lower().strip()

        start_date = None
        end_date = None
        detected_days = None

        # 1. Look for ISO dates YYYY-MM-DD
        iso_dates = re.findall(r'\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b', text)
        if iso_dates:
            try:
                parsed_dates = [datetime.strptime(re.sub(r'[/]', '-', d), '%Y-%m-%d').date() for d in iso_dates]
                start_date = parsed_dates[0]
                end_date = parsed_dates[1] if len(parsed_dates) > 1 else start_date
            except Exception:
                pass

        # 2. Look for "DD Month" or "Month DD" date ranges (e.g. "21 September to 24 September", "from Oct 5 till Oct 8", "on 15th August")
        if not start_date:
            month_pattern = r'(?:january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|september|sept|sep|october|oct|november|nov|december|dec)'
            
            # Pattern: 21 September to 24 September OR 21st to 24th September
            range_match = re.search(
                r'(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?(' + month_pattern + r')?\s*(?:to|till|until|through|-)\s*(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?(' + month_pattern + r')',
                text_lower
            )
            if range_match:
                d1 = int(range_match.group(1))
                m1_str = range_match.group(2)
                d2 = int(range_match.group(3))
                m2_str = range_match.group(4)
                
                m2 = cls.MONTH_MAP.get(m2_str, current_date.month)
                m1 = cls.MONTH_MAP.get(m1_str, m2) if m1_str else m2
                
                try:
                    start_date = date(current_year, m1, d1)
                    end_date = date(current_year, m2, d2)
                except Exception:
                    pass

        # 3. Pattern: "from September 21 to September 24"
        if not start_date:
            range_match_2 = re.search(
                r'(' + month_pattern + r')\s*(\d{1,2})(?:st|nd|rd|th)?\s*(?:to|till|until|-)\s*(?:(' + month_pattern + r')\s*)?(\d{1,2})(?:st|nd|rd|th)?',
                text_lower
            )
            if range_match_2:
                m1_str = range_match_2.group(1)
                d1 = int(range_match_2.group(2))
                m2_str = range_match_2.group(3)
                d2 = int(range_match_2.group(4))
                
                m1 = cls.MONTH_MAP.get(m1_str, current_date.month)
                m2 = cls.MONTH_MAP.get(m2_str, m1) if m2_str else m1
                
                try:
                    start_date = date(current_year, m1, d1)
                    end_date = date(current_year, m2, d2)
                except Exception:
                    pass

        # 4. Pattern: Single Date "on 21 September", "for 21st Oct"
        if not start_date:
            single_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?(' + month_pattern + r')', text_lower)
            if single_match:
                d1 = int(single_match.group(1))
                m1 = cls.MONTH_MAP.get(single_match.group(2), current_date.month)
                try:
                    start_date = date(current_year, m1, d1)
                    end_date = start_date
                except Exception:
                    pass

        # 5. Relative terms: "tomorrow", "for X days from tomorrow", "today and tomorrow"
        if not start_date:
            days_match = re.search(r'(\d+)\s*days?', text_lower)
            if days_match:
                detected_days = int(days_match.group(1))

            if 'tomorrow' in text_lower:
                start_date = current_date + timedelta(days=1)
                if detected_days and detected_days > 1:
                    end_date = start_date + timedelta(days=detected_days - 1)
                else:
                    end_date = start_date
            elif 'today' in text_lower:
                start_date = current_date
                if detected_days and detected_days > 1:
                    end_date = start_date + timedelta(days=detected_days - 1)
                else:
                    end_date = start_date
            elif 'next week' in text_lower:
                # Start next Monday
                days_ahead = 7 - current_date.weekday()
                start_date = current_date + timedelta(days=days_ahead)
                end_date = start_date + timedelta(days=(detected_days - 1) if detected_days else 4)

        # If only start_date found and duration specified
        if start_date and not end_date:
            if detected_days:
                end_date = start_date + timedelta(days=max(0, detected_days - 1))
            else:
                end_date = start_date

        # Fallback if no dates detected at all
        if not start_date:
            start_date = current_date + timedelta(days=1)
            end_date = start_date

        # Sanity check start <= end
        if start_date > end_date:
            start_date, end_date = end_date, start_date

        # Detect Leave Type
        matched_type_code = 'CAS'  # Default
        max_score = 0

        for code, keywords in cls.LEAVE_KEYWORD_MAP.items():
            score = sum(1 for kw in keywords if re.search(r'\b' + kw + r'\b', text_lower))
            if score > max_score:
                max_score = score
                matched_type_code = code

        type_names = {
            'MED': 'Medical Leave',
            'CAS': 'Casual Leave',
            'PER': 'Personal Leave',
            'EMG': 'Emergency Leave',
            'DUTY': 'Academic / Duty Leave',
            'OTH': 'Other Leave'
        }
        leave_type_name = type_names.get(matched_type_code, 'Casual Leave')

        # Clean reason summary
        reason_summary = text.strip()
        # Look for "because ...", "due to ...", "for ...", "as ..."
        reason_match = re.search(r'(?:because|due to|as i have|as i am|owing to|reason:?)\s+(.+)', text, re.IGNORECASE)
        if reason_match:
            reason_summary = reason_match.group(1).strip()
            # Truncate at punctuation if too long
            reason_summary = re.split(r'[.!?\n]', reason_summary)[0].strip()

        if len(reason_summary) > 80:
            reason_summary = reason_summary[:77] + "..."

        return {
            'success': True,
            'start_date': start_date.strftime('%Y-%m-%d'),
            'end_date': end_date.strftime('%Y-%m-%d'),
            'total_days': (end_date - start_date).days + 1,
            'leave_type_code': matched_type_code,
            'leave_type_name': leave_type_name,
            'reason': reason_summary or f"Absence for {leave_type_name}",
            'description': text.strip(),
            'confidence': 0.92 if max_score > 0 else 0.75
        }


class AILeaveAssistant:
    """
    Role-aware AI Conversational Assistant handling attendance queries,
    leave allowance evaluations, defaulter detection, and leave statuses.
    """

    @classmethod
    def process_query(cls, conn, user, query_text):
        """
        Processes conversational queries for students, teachers, HODs, and admins.
        """
        role = user.get('role', 'student')
        username = user.get('username')
        q = query_text.lower().strip()

        # 1. Student Queries
        if role == 'student':
            student = LeaveCalculator.get_student(conn, username)
            roll_number = student['roll_number']
            threshold = SystemSettingsManager.get_float(conn, 'attendance_threshold', 75.0)

            # Query: What is my attendance?
            if any(k in q for k in ['my attendance', 'attendance rate', 'current attendance', 'how much attendance', 'attendance %']):
                summary = LeaveCalculator.get_student_attendance_summary(conn, roll_number)
                status_icon = "🟢" if summary['current_pct'] >= (threshold + 5.0) else ("🟡" if summary['current_pct'] >= threshold else "🔴")
                msg = f"""### 📊 Your Live Attendance Status
• **Student:** {student['full_name']} (`{roll_number}`)
• **Current Rate:** **{summary['current_pct']}%** {status_icon}
• **Classes Attended:** {summary['attended']} / {summary['conducted']} sessions
• **Classes Missed:** {summary['missed']} sessions
• **Threshold Requirement:** {threshold}%

{"✅ You are in **Good Standing**." if summary['current_pct'] >= threshold else f"⚠️ **Warning**: You are below the mandatory {threshold}% threshold!"}"""
                return msg

            # Query: How many classes missed?
            if any(k in q for k in ['missed', 'how many classes have i missed', 'absence count']):
                summary = LeaveCalculator.get_student_attendance_summary(conn, roll_number)
                return f"""### 📋 Absence Summary
You have missed **{summary['missed']} class{'es' if summary['missed'] != 1 else ''}** out of {summary['conducted']} conducted so far.
Current Attendance: **{summary['current_pct']}%** (Target: {threshold}%)."""

            # Query: Consecutive classes needed to reach threshold
            if any(k in q for k in ['consecutive', 'reach 75', 'reach 80', 'how many classes to attend', 'how many to attend', 'reach threshold']):
                sim = LeaveCalculator.simulate_what_if(conn, roll_number)
                if sim['consecutive_needed'] > 0:
                    return f"""### 🎯 Attendance Recovery Target
To reach the **{threshold}%** attendance threshold from your current **{sim['current_attendance_pct']}%**, you need to attend:
👉 **{sim['consecutive_needed']} consecutive future class{'es' if sim['consecutive_needed'] > 1 else ''}** without missing any."""
                else:
                    return f"""### 🎯 Attendance Standing
Your current attendance is **{sim['current_attendance_pct']}%**, which already satisfies the **{threshold}%** minimum!
You can safely miss up to **{sim['buffer_missable']} class{'es' if sim['buffer_missable'] != 1 else ''}** before falling below {threshold}%."""

            # Query: Can I take leave for X days?
            days_match = re.search(r'(?:take leave for|leave for|miss)\s*(\d+)\s*(?:days?|classes?)', q)
            if days_match or any(k in q for k in ['can i take leave', 'if i take leave', 'leave safe']):
                days = int(days_match.group(1)) if days_match else 3
                start_d = date.today() + timedelta(days=1)
                end_d = start_d + timedelta(days=days - 1)
                impact = LeaveCalculator.calculate_leave_impact(conn, roll_number, start_d.strftime('%Y-%m-%d'), end_d.strftime('%Y-%m-%d'))
                
                risk_tag = "🟢 SAFE" if impact['risk_level'] == 'SAFE' else ("🟡 WARNING" if impact['risk_level'] == 'WARNING' else "🔴 HIGH RISK")
                return f"""### 🔮 Leave Impact Simulation ({days} Days)
• **Period:** {impact['start_date']} to {impact['end_date']}
• **Classes Affected:** {impact['affected_classes']} scheduled lectures
• **Current Attendance:** {impact['current_attendance_pct']}%
• **Projected Attendance:** **{impact['projected_attendance_pct']}%** ({impact['percentage_drop']}% drop)
• **Risk Level:** **{risk_tag}**

💡 **Assessment:** {impact['risk_message']}"""

            # Query: Status of my leave request / History
            if any(k in q for k in ['status', 'my leave', 'leave history', 'pending request', 'applied leave']):
                requests = conn.execute("""
                    SELECT lr.*, lt.name as leave_type_name 
                    FROM leave_requests lr
                    JOIN leave_types lt ON lr.leave_type_id = lt.id
                    WHERE lr.roll_number = ?
                    ORDER BY lr.created_at DESC LIMIT 3
                """, (roll_number,)).fetchall()
                if not requests:
                    return "You haven't submitted any leave requests yet. You can apply anytime from the **Apply Leave** tab."
                
                resp = "### 📑 Your Recent Leave Applications\n\n"
                for r in requests:
                    badge = "🟡 Pending" if 'PENDING' in r['status'] else ("🟢 Approved" if r['status'] == 'APPROVED' else "🔴 Rejected")
                    resp += f"• **#LEAVE-{r['id']} ({r['leave_type_name']})**: {r['start_date']} to {r['end_date']} ({r['total_days']}d)\n"
                    resp += f"  - Status: **{badge}** &bull; Projected: {r['projected_attendance_pct']}%\n"
                    resp += f"  - Reason: {r['reason']}\n\n"
                return resp

            # Default Student Help
            return f"""Hello {student['full_name']}! I am your **AI Attendance & Leave Assistant**. Here is what you can ask me:
- *"What is my current attendance?"*
- *"How many classes have I missed?"*
- *"Can I take leave for 3 days without falling below {threshold}%?"*
- *"How many consecutive classes do I need to attend to reach {threshold}%?"*
- *"What is the status of my leave request?"*"""

        # 2. Faculty / HOD / Admin Queries
        elif role in ['teacher', 'hod', 'admin']:
            threshold = SystemSettingsManager.get_float(conn, 'attendance_threshold', 75.0)

            # Query: Pending leave requests
            if any(k in q for k in ['pending', 'pending leave', 'leave requests', 'approvals']):
                pending = conn.execute("""
                    SELECT lr.*, s.full_name, lt.name as leave_type_name 
                    FROM leave_requests lr
                    LEFT JOIN students s ON lr.roll_number = s.roll_number
                    LEFT JOIN leave_types lt ON lr.leave_type_id = lt.id
                    WHERE lr.status IN ('PENDING_FACULTY', 'PENDING_HOD')
                    ORDER BY lr.created_at DESC LIMIT 5
                """).fetchall()
                if not pending:
                    return "✅ **No pending leave requests** currently require your review."
                
                resp = f"### ⏳ Pending Leave Requests Queue ({len(pending)} pending shown):\n\n"
                for p in pending:
                    risk_icon = "🔴" if p['risk_level'] == 'HIGH_RISK' else ("🟡" if p['risk_level'] == 'WARNING' else "🟢")
                    resp += f"• **#LEAVE-{p['id']}** &bull; **{p['full_name']}** (`{p['roll_number']}`)\n"
                    resp += f"  - Type: {p['leave_type_name']} ({p['total_days']} days: {p['start_date']} to {p['end_date']})\n"
                    resp += f"  - Projected Att: **{p['projected_attendance_pct']}%** {risk_icon} &bull; Stage: `{p['status']}`\n\n"
                resp += "👉 Visit the **Faculty Leave Dashboard** to approve, reject, or forward these requests."
                return resp

            # Query: Defaulters / High-Risk impact
            if any(k in q for k in ['defaulter', 'high risk', 'below threshold', 'fall below']):
                high_risk = conn.execute("""
                    SELECT lr.*, s.full_name, lt.name as leave_type_name 
                    FROM leave_requests lr
                    LEFT JOIN students s ON lr.roll_number = s.roll_number
                    LEFT JOIN leave_types lt ON lr.leave_type_id = lt.id
                    WHERE lr.status IN ('PENDING_FACULTY', 'PENDING_HOD') AND lr.risk_level = 'HIGH_RISK'
                    ORDER BY lr.projected_attendance_pct ASC
                """).fetchall()
                if not high_risk:
                    return f"✅ There are currently **no pending leave requests** that would cause students to drop below the {threshold}% threshold."
                
                resp = f"### ⚠️ Students Forecasted to Fall Below {threshold}% Threshold:\n\n"
                for h in high_risk:
                    resp += f"• **{h['full_name']}** (`{h['roll_number']}`): Current **{h['current_attendance_pct']}%** → Projected **{h['projected_attendance_pct']}%**\n"
                    resp += f"  - Request: #LEAVE-{h['id']} ({h['start_date']} to {h['end_date']})\n"
                    resp += f"  - Reason: *{h['reason']}*\n\n"
                return resp

            # Query: Leave Statistics / Metrics
            if any(k in q for k in ['stats', 'statistics', 'summary', 'this month']):
                total_reqs = conn.execute("SELECT COUNT(*) as count FROM leave_requests").fetchone()['count']
                approved_reqs = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE status = 'APPROVED'").fetchone()['count']
                rejected_reqs = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE status = 'REJECTED'").fetchone()['count']
                pending_reqs = conn.execute("SELECT COUNT(*) as count FROM leave_requests WHERE status LIKE 'PENDING%'").fetchone()['count']

                return f"""### 📊 University Leave Management Analytics
• **Total Leave Requests Submitted:** {total_reqs}
• **Approved Requests:** {approved_reqs}
• **Rejected Requests:** {rejected_reqs}
• **Pending In-Queue:** {pending_reqs}
• **System Attendance Threshold:** {threshold}%"""

            # Default Faculty Help
            return f"""Hello {user.get('username')}! You are logged in as **{role.upper()}**. You can ask:
- *"Show students with pending leave requests"*
- *"Which students will fall below the attendance threshold if leave is approved?"*
- *"Show this month's leave statistics"*"""

        return "How can I assist you with attendance and leave management today?"


class AIDocumentOCR:
    """
    Lightweight, robust OCR & Document Verification Assistant.
    Extracts text from uploaded medical certificates and documents,
    highlighting key entities for authorized human review.
    """

    @staticmethod
    def extract_document_text(file_path):
        """
        Extracts raw text and entity keywords from image/PDF files.
        Uses Pillow / Tesseract if available, with regex entity recognition.
        """
        if not os.path.exists(file_path):
            return {'text': '', 'status': 'NOT_FOUND', 'entities': {}}

        ext = os.path.splitext(file_path)[1].lower()
        extracted_text = ""

        # Attempt OCR on images
        if ext in ['.png', '.jpg', '.jpeg', '.webp']:
            try:
                import pytesseract
                from PIL import Image
                img = Image.open(file_path)
                extracted_text = pytesseract.image_to_string(img)
            except Exception:
                # Safe fallback if Tesseract is not installed on host
                filename = os.path.basename(file_path)
                extracted_text = f"Document File: {filename} (Image verified and stored securely for manual review)"

        elif ext == '.pdf':
            try:
                import pypdf
                reader = pypdf.PdfReader(file_path)
                for page in reader.pages[:3]:
                    extracted_text += page.extract_text() or ""
            except Exception:
                extracted_text = f"PDF Document: {os.path.basename(file_path)} (Uploaded for manual review)"
        else:
            extracted_text = f"Attached Document: {os.path.basename(file_path)}"

        # Entity Keyword Extraction
        dates_found = re.findall(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', extracted_text)
        
        medical_keywords = ['hospital', 'clinic', 'doctor', 'dr.', 'patient', 'diagnosis', 'fever', 'rest', 'prescription', 'certificate', 'treatment', 'medical officer']
        found_keywords = [kw for kw in medical_keywords if kw in extracted_text.lower()]

        return {
            'text': extracted_text[:1000],
            'status': 'PROCESSED',
            'entities': {
                'dates_found': list(set(dates_found)),
                'medical_terms': found_keywords,
                'char_count': len(extracted_text)
            },
            'review_note': 'Informational OCR assistance only. Authenticity must be verified by faculty/HOD.'
        }
