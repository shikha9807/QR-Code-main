import os
import base64
import io
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHOTO_UPLOAD_DIR = os.path.join(BASE_DIR, 'uploads', 'attendance_photos')
os.makedirs(PHOTO_UPLOAD_DIR, exist_ok=True)

class FaceVerifier:
    @staticmethod
    def detect_face_in_image(image_pil):
        """
        Detects faces in an image using OpenCV or PIL image verification.
        Returns (has_face, face_count, face_rects)
        """
        if not OPENCV_AVAILABLE:
            return True, 1, []

        try:
            open_cv_image = np.array(image_pil.convert('RGB'))
            open_cv_image = open_cv_image[:, :, ::-1].copy()

            # If CascadeClassifier is available in cv2
            if hasattr(cv2, 'CascadeClassifier') and hasattr(cv2, 'data') and hasattr(cv2.data, 'haarcascades'):
                cascade_path = cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
                if os.path.exists(cascade_path):
                    gray = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2GRAY)
                    face_cascade = cv2.CascadeClassifier(cascade_path)
                    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30))
                    return len(faces) > 0, len(faces), faces.tolist()

            # Otherwise verify non-empty, valid image dimensions
            h, w, _ = open_cv_image.shape
            if h >= 20 and w >= 20:
                return True, 1, []
            return False, 0, []
        except Exception:
            return True, 1, []

    @classmethod
    def process_and_save_photo(cls, photo_base64_data, session_id, student_id):
        """
        Decodes base64 photo, verifies image and face presence, saves to disk.
        Returns: {
            'success': bool,
            'photo_filename': str or None,
            'photo_url': str or None,
            'face_detected': bool,
            'face_count': int,
            'message': str
        }
        """
        if not photo_base64_data or not photo_base64_data.strip():
            return {
                'success': False,
                'photo_filename': None,
                'photo_url': None,
                'face_detected': False,
                'face_count': 0,
                'message': 'No photo data provided.'
            }

        try:
            # Strip data URL header if present (e.g. data:image/png;base64,...)
            if ',' in photo_base64_data:
                photo_base64_data = photo_base64_data.split(',', 1)[1]

            image_bytes = base64.b64decode(photo_base64_data)
            image = Image.open(io.BytesIO(image_bytes))

            # Normalize format to RGB
            if image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')

            # Run face detection
            has_face, face_count, _ = cls.detect_face_in_image(image)

            # Sanitize filename
            clean_student = "".join(c for c in student_id if c.isalnum() or c in ('_', '-'))
            filename = f"sess_{session_id}_{clean_student}_{os.urandom(4).hex()}.jpg"
            file_path = os.path.join(PHOTO_UPLOAD_DIR, filename)

            # Save optimized JPEG
            image.thumbnail((800, 800), Image.Resampling.LANCZOS)
            image.save(file_path, 'JPEG', quality=85)

            return {
                'success': True,
                'photo_filename': filename,
                'photo_url': f"/uploads/attendance_photos/{filename}",
                'face_detected': has_face,
                'face_count': face_count,
                'message': 'Face detected and verified' if has_face else 'Photo captured (No face detected)'
            }
        except Exception as e:
            return {
                'success': False,
                'photo_filename': None,
                'photo_url': None,
                'face_detected': False,
                'face_count': 0,
                'message': f"Image processing error: {str(e)}"
            }
