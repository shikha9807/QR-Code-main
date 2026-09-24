"""
Model Evaluator & Prediction Testing Module
Performs feature preprocessing, generates model predictions for all 2,000 students,
calculates evaluation metrics (Accuracy, Precision, Recall, F1-Score, Confusion Matrix),
and generates output prediction files.
"""

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, classification_report
from ai_predictor import AIAttendancePredictor
from data_handler import save_csv, save_json

class AttendanceModelEvaluator:
    """
    Evaluates attendance models against cleaned student datasets.
    """

    @staticmethod
    def preprocess_features(df):
        """
        Extracts and prepares feature vectors for model inference.
        """
        feature_cols = [
            "Total_Classes",
            "Classes_Attended",
            "Classes_Missed",
            "Attendance_Percentage",
            "Late_Count",
            "Leave_Count",
            "Medical_Leave",
            "Assignment_Submission",
            "Internal_Marks",
            "Previous_Attendance"
        ]
        
        # Ensure all feature columns are numeric
        X = df[feature_cols].copy().astype(float)
        return X

    @classmethod
    def predict_attendance_outcomes(cls, df):
        """
        Executes model inference on all student records.
        Returns the augmented DataFrame with predictions, risk scores, and prescriptive actions.
        """
        predictions_list = []
        predicted_classes = []
        risk_scores = []
        risk_tiers = []
        projected_finals = []
        prescriptive_plans = []
        confidence_scores = []

        for _, row in df.iterrows():
            total = int(row["Total_Classes"])
            attended = int(row["Classes_Attended"])
            curr_pct = float(row["Attendance_Percentage"])
            prev_att = float(row.get("Previous_Attendance", curr_pct))
            assign_score = float(row.get("Assignment_Submission", 70.0))
            
            # Simulated session history for momentum
            fake_student = {
                'roll_number': row['Student_ID'],
                'full_name': row['Student_Name'],
                'email': f"{row['Student_ID'].lower()}@uni.edu",
                'dept_name': row.get('Course', 'General'),
                'section_name': f"Sem-{row.get('Semester', 1)}",
                'semester': int(row.get('Semester', 1))
            }
            
            # Reconstruct session list & presence for predictor engine
            sessions = [{'id': i, 'created_at': f'2026-09-{((i%28)+1):02d} 10:00:00'} for i in range(total)]
            attended_session_ids = set(range(attended))
            
            metrics = AIAttendancePredictor.calculate_student_metrics(fake_student, sessions, attended_session_ids)
            
            # Model prediction classification
            # If projected semester percentage >= 75% -> "Eligible", else "Low Attendance"
            proj_pct = metrics['projected_final_pct']
            pred_status = "Eligible" if proj_pct >= 75.0 else "Low Attendance"
            
            # Calculate confidence score based on distance from 75% boundary
            dist = abs(proj_pct - 75.0)
            confidence = min(0.99, max(0.60, round(0.55 + (dist / 60.0), 3)))

            predicted_classes.append(pred_status)
            risk_scores.append(metrics['risk_score'])
            risk_tiers.append(metrics['risk_level'])
            projected_finals.append(proj_pct)
            prescriptive_plans.append(metrics['recovery_message'])
            confidence_scores.append(confidence)

        pred_df = df.copy()
        pred_df["Predicted_Status"] = predicted_classes
        pred_df["Predicted_Risk_Tier"] = risk_tiers
        pred_df["Risk_Score"] = risk_scores
        pred_df["Projected_Final_Attendance"] = projected_finals
        pred_df["Confidence_Score"] = confidence_scores
        pred_df["Prescriptive_Action_Plan"] = prescriptive_plans

        return pred_df

    @classmethod
    def evaluate_model(cls, pred_df, actual_col="Attendance_Status", pred_col="Predicted_Status"):
        """
        Calculates complete evaluation metrics comparing ground truth to predictions.
        """
        if actual_col not in pred_df.columns:
            return None, "Ground truth column not found. Evaluated in unsupervised inference mode."

        y_true = pred_df[actual_col].astype(str)
        y_pred = pred_df[pred_col].astype(str)

        # Standardize labels
        labels = ["Eligible", "Low Attendance"]

        acc = accuracy_score(y_true, y_pred)
        prec_macro = precision_score(y_true, y_pred, average="macro", zero_division=0)
        rec_macro = recall_score(y_true, y_pred, average="macro", zero_division=0)
        f1_macro = f1_score(y_true, y_pred, average="macro", zero_division=0)

        # Precision & Recall for Low Attendance (defaulter) specifically
        prec_low = precision_score(y_true, y_pred, pos_label="Low Attendance", zero_division=0)
        rec_low = recall_score(y_true, y_pred, pos_label="Low Attendance", zero_division=0)
        f1_low = f1_score(y_true, y_pred, pos_label="Low Attendance", zero_division=0)

        # Confusion Matrix
        cm = confusion_matrix(y_true, y_pred, labels=labels)
        # [[TP_eligible, FN_eligible], [FP_eligible, TN_eligible]]
        tp_eligible = int(cm[0][0])
        fn_eligible = int(cm[0][1])
        fp_eligible = int(cm[1][0])
        tn_eligible = int(cm[1][1])

        clf_rep = classification_report(y_true, y_pred, labels=labels, zero_division=0)

        metrics = {
            "accuracy": round(float(acc) * 100, 2),
            "precision_macro": round(float(prec_macro) * 100, 2),
            "recall_macro": round(float(rec_macro) * 100, 2),
            "f1_macro": round(float(f1_macro) * 100, 2),
            "precision_low_attendance": round(float(prec_low) * 100, 2),
            "recall_low_attendance": round(float(rec_low) * 100, 2),
            "f1_low_attendance": round(float(f1_low) * 100, 2),
            "confusion_matrix": {
                "labels": labels,
                "matrix": cm.tolist(),
                "true_eligible": tp_eligible,
                "false_low_attendance": fn_eligible,
                "false_eligible": fp_eligible,
                "true_low_attendance": tn_eligible
            },
            "classification_report": clf_rep
        }

        return metrics

    @classmethod
    def generate_evaluation_summary(cls, pred_df, validation_summary, metrics=None):
        """
        Compiles the full executive project report.
        """
        total_students = len(pred_df)
        predicted_eligible = int((pred_df["Predicted_Status"] == "Eligible").sum())
        predicted_low = int((pred_df["Predicted_Status"] == "Low Attendance").sum())
        avg_attendance = round(float(pred_df["Attendance_Percentage"].mean()), 2)
        critical_count = int((pred_df["Predicted_Risk_Tier"] == "CRITICAL").sum())
        moderate_count = int((pred_df["Predicted_Risk_Tier"] == "MODERATE").sum())
        safe_count = int((pred_df["Predicted_Risk_Tier"] == "SAFE").sum())

        summary = {
            "total_students": total_students,
            "predicted_eligible": predicted_eligible,
            "predicted_low_attendance": predicted_low,
            "average_attendance": avg_attendance,
            "risk_distribution": {
                "critical_defaulters": critical_count,
                "moderate_warning": moderate_count,
                "good_standing": safe_count
            },
            "validation_metrics": validation_summary,
            "model_metrics": metrics
        }
        return summary
