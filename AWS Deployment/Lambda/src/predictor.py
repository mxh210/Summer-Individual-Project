"""Reusable inference wrapper for the readmission research prototype."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

# Keep numerical libraries within the small CPU allocation used by AWS Lambda.
# These variables must be set before NumPy and scikit-learn are imported.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

import joblib
import numpy as np
import pandas as pd


EXPECTED_FEATURES = [
    "gender",
    "race_group",
    "age_group",
    "admission_source_group",
    "discharge_group",
    "medical_specialty_group",
    "primary_diagnosis",
    "hba1c_group",
    "max_glu_serum",
    "diabetesMed",
    "time_in_hospital",
    "num_lab_procedures",
    "num_procedures",
    "num_medications",
    "number_outpatient",
    "number_emergency",
    "number_inpatient",
    "number_diagnoses",
]

CATEGORICAL_FEATURES = EXPECTED_FEATURES[:10]
NUMERIC_FEATURES = EXPECTED_FEATURES[10:]

DEFAULT_TARGET_RECALL = 0.80


class PredictionInputError(ValueError):
    """Raised when a patient record cannot be converted to model input."""


class ReadmissionPredictor:
    """Load the frozen pipeline once and use it for repeated predictions."""

    def __init__(
        self,
        model_path: str | Path,
        threshold_path: str | Path,
        target_recall: float = DEFAULT_TARGET_RECALL,
    ) -> None:
        self.model_path = Path(model_path)
        self.threshold_path = Path(threshold_path)
        self.target_recall = float(target_recall)

        if not self.model_path.is_file():
            raise FileNotFoundError(f"Model not found: {self.model_path}")

        if not self.threshold_path.is_file():
            raise FileNotFoundError(
                f"Threshold table not found: {self.threshold_path}"
            )

        self.model = joblib.load(self.model_path)
        self.feature_names = list(self.model.feature_names_in_)

        if self.feature_names != EXPECTED_FEATURES:
            raise RuntimeError(
                "The saved pipeline feature schema does not match the "
                "deployment schema."
            )

        # n_jobs changes only prediction parallelism, not the trained trees.
        self.model.named_steps["model"].set_params(n_jobs=1)
        self.threshold = self._load_threshold()

    def _load_threshold(self) -> float:
        table = pd.read_csv(self.threshold_path)

        required_columns = {"target_recall", "selected_threshold"}
        missing_columns = required_columns.difference(table.columns)

        if missing_columns:
            raise RuntimeError(
                "Threshold table is missing columns: "
                f"{sorted(missing_columns)}"
            )

        matches = table.loc[
            np.isclose(
                table["target_recall"].astype(float),
                self.target_recall,
            )
        ]

        if len(matches) != 1:
            raise RuntimeError(
                "Expected exactly one threshold for target recall "
                f"{self.target_recall}, found {len(matches)}."
            )

        threshold = float(matches["selected_threshold"].iloc[0])

        if not 0.0 <= threshold <= 1.0:
            raise RuntimeError(f"Invalid classification threshold: {threshold}")

        return threshold

    def _prepare_record(self, record: Mapping[str, Any]) -> pd.DataFrame:
        missing_features = [
            feature for feature in self.feature_names if feature not in record
        ]

        if missing_features:
            raise PredictionInputError(
                "Patient record is missing required features: "
                f"{missing_features}"
            )

        row = {feature: record[feature] for feature in self.feature_names}
        frame = pd.DataFrame([row], columns=self.feature_names)

        # DynamoDB NULL values will reach this function as Python None.
        for feature in CATEGORICAL_FEATURES:
            frame[feature] = frame[feature].replace(r"^\s*$", np.nan, regex=True)
            frame[feature] = frame[feature].where(
                frame[feature].notna(),
                np.nan,
            )

        for feature in NUMERIC_FEATURES:
            try:
                frame[feature] = pd.to_numeric(
                    frame[feature],
                    errors="raise",
                )
            except (TypeError, ValueError) as error:
                raise PredictionInputError(
                    f"Feature '{feature}' must be numeric or null."
                ) from error

        return frame

    def predict(
        self,
        demo_patient_id: str,
        record: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Return a frontend-ready research assessment for one demo patient."""

        if not isinstance(demo_patient_id, str) or not demo_patient_id.strip():
            raise PredictionInputError(
                "demo_patient_id must be a non-empty string."
            )

        frame = self._prepare_record(record)
        score = float(self.model.predict_proba(frame)[0, 1])

        if not 0.0 <= score <= 1.0:
            raise RuntimeError(f"Model returned an invalid score: {score}")

        review_flag = bool(score >= self.threshold)

        return {
            "demo_patient_id": demo_patient_id.strip(),
            "assessment": {
                "risk_category": "HIGH" if review_flag else "LOW",
                "clinical_review_flag": review_flag,
                "model_estimated_score": score,
                "selected_threshold": self.threshold,
                "threshold_target_recall": self.target_recall,
            },
            "message": (
                "Flag for clinical review"
                if review_flag
                else "No high-risk flag at the selected threshold"
            ),
            "model_information": {
                "model_type": "Random Forest",
                "prediction_target": "30-day hospital readmission",
                "operating_policy": "Validation-selected 80% recall target",
            },
            "disclaimer": (
                "Research prototype only. The model-estimated score is not "
                "an externally validated absolute probability and must not "
                "be used as an automatic clinical decision."
            ),
        }


def build_default_predictor() -> ReadmissionPredictor:
    """Build a predictor using project paths or Lambda environment variables."""

    project_root = Path(__file__).resolve().parents[1]

    model_path = Path(
        os.environ.get(
            "MODEL_PATH",
            project_root / "artifacts" / "final_model.joblib",
        )
    )
    threshold_path = Path(
        os.environ.get(
            "THRESHOLD_PATH",
            project_root
            / "artifacts"
            / "selected_validation_thresholds.csv",
        )
    )

    return ReadmissionPredictor(
        model_path=model_path,
        threshold_path=threshold_path,
    )
