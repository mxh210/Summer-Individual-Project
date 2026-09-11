"""AWS Lambda adapter for the readmission research prototype."""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import boto3

from predictor import (
    EXPECTED_FEATURES,
    PredictionInputError,
    build_default_predictor,
)


LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)

PATIENT_TABLE_NAME = os.environ.get(
    "PATIENT_TABLE_NAME",
    "readmission-demo-patients",
)
DEMO_ID_PATTERN = re.compile(r"^DEMO-\d{5,}$")

# These objects are created at most once in each warm Lambda environment.
# Tests replace them with local fakes, so no AWS connection is required.
_predictor: Any | None = None
_patient_table: Any | None = None


class RequestValidationError(ValueError):
    """Raised when an invocation does not identify a valid demo record."""


class StoredRecordError(ValueError):
    """Raised when DynamoDB returns an incomplete demo record."""


def _get_predictor() -> Any:
    global _predictor
    if _predictor is None:
        _predictor = build_default_predictor()
    return _predictor


def _get_patient_table() -> Any:
    global _patient_table
    if _patient_table is None:
        _patient_table = boto3.resource("dynamodb").Table(PATIENT_TABLE_NAME)
    return _patient_table


def _json_response(status_code: int, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the response structure expected by API Gateway and Lambda URLs."""

    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(payload, separators=(",", ":")),
    }


def _error_response(
    status_code: int,
    error_code: str,
    message: str,
) -> dict[str, Any]:
    return _json_response(
        status_code,
        {
            "error": {
                "code": error_code,
                "message": message,
            }
        },
    )


def _body_as_mapping(event: Mapping[str, Any]) -> Mapping[str, Any]:
    body = event.get("body")
    if body is None:
        return {}
    if isinstance(body, Mapping):
        return body
    if not isinstance(body, str):
        raise RequestValidationError("Request body must be a JSON object.")

    try:
        decoded_body = json.loads(body)
    except json.JSONDecodeError as error:
        raise RequestValidationError("Request body contains invalid JSON.") from error

    if not isinstance(decoded_body, Mapping):
        raise RequestValidationError("Request body must be a JSON object.")
    return decoded_body


def _extract_demo_patient_id(event: Any) -> str:
    """Read an ID from a direct invocation or an API Gateway request."""

    if not isinstance(event, Mapping):
        raise RequestValidationError("The Lambda event must be a JSON object.")

    candidates: list[Any] = [event.get("demo_patient_id")]

    path_parameters = event.get("pathParameters")
    if isinstance(path_parameters, Mapping):
        candidates.append(path_parameters.get("demo_patient_id"))

    query_parameters = event.get("queryStringParameters")
    if isinstance(query_parameters, Mapping):
        candidates.append(query_parameters.get("demo_patient_id"))

    body = _body_as_mapping(event)
    candidates.append(body.get("demo_patient_id"))

    supplied_ids = [candidate for candidate in candidates if candidate is not None]
    if not supplied_ids:
        raise RequestValidationError("demo_patient_id is required.")

    normalised_ids: list[str] = []
    for candidate in supplied_ids:
        if not isinstance(candidate, str):
            raise RequestValidationError("demo_patient_id must be a string.")
        normalised_ids.append(candidate.strip())

    if len(set(normalised_ids)) > 1:
        raise RequestValidationError(
            "Conflicting demo_patient_id values were supplied."
        )

    demo_patient_id = normalised_ids[0]
    if not DEMO_ID_PATTERN.fullmatch(demo_patient_id):
        raise RequestValidationError(
            "demo_patient_id must match the format DEMO-00001."
        )
    return demo_patient_id


def _model_record_from_item(item: Mapping[str, Any]) -> dict[str, Any]:
    missing_features = [
        feature for feature in EXPECTED_FEATURES if feature not in item
    ]
    if missing_features:
        raise StoredRecordError(
            "Stored demo record is missing model features: "
            f"{missing_features}"
        )
    return {feature: item[feature] for feature in EXPECTED_FEATURES}


def _json_safe_patient_profile(
    model_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert the 18 model inputs to JSON-safe values for the demo UI."""

    profile: dict[str, Any] = {}
    for feature in EXPECTED_FEATURES:
        value = model_record[feature]

        if isinstance(value, Decimal):
            if not value.is_finite():
                raise StoredRecordError(
                    f"Stored feature {feature} is not a finite number."
                )
            value = (
                int(value)
                if value == value.to_integral_value()
                else float(value)
            )
        elif isinstance(value, float) and not math.isfinite(value):
            raise StoredRecordError(
                f"Stored feature {feature} is not a finite number."
            )
        elif value is not None and not isinstance(
            value,
            (str, int, float, bool),
        ):
            raise StoredRecordError(
                f"Stored feature {feature} has an unsupported value type."
            )

        profile[feature] = value

    return profile


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    """Retrieve one demo encounter, run inference, and return JSON."""

    del context  # Reserved for future request tracing.

    try:
        demo_patient_id = _extract_demo_patient_id(event)
    except RequestValidationError as error:
        return _error_response(400, "INVALID_REQUEST", str(error))

    try:
        response = _get_patient_table().get_item(
            Key={"demo_patient_id": demo_patient_id}
        )
    except Exception:
        LOGGER.exception("DynamoDB retrieval failed for %s", demo_patient_id)
        return _error_response(
            500,
            "DATABASE_ERROR",
            "The demo patient record could not be retrieved.",
        )

    item = response.get("Item")
    if not isinstance(item, Mapping):
        return _error_response(
            404,
            "DEMO_PATIENT_NOT_FOUND",
            f"No demo encounter was found for {demo_patient_id}.",
        )

    try:
        model_record = _model_record_from_item(item)
        patient_profile = _json_safe_patient_profile(model_record)
    except StoredRecordError:
        LOGGER.exception("Stored demo record failed schema validation")
        return _error_response(
            500,
            "INVALID_STORED_RECORD",
            "The stored demo record is incomplete.",
        )

    try:
        result = _get_predictor().predict(demo_patient_id, model_record)
    except PredictionInputError:
        LOGGER.exception("Stored demo record failed predictor validation")
        return _error_response(
            500,
            "INVALID_STORED_RECORD",
            "The stored demo record contains invalid model inputs.",
        )
    except Exception:
        LOGGER.exception("Inference failed for %s", demo_patient_id)
        return _error_response(
            500,
            "INFERENCE_ERROR",
            "The readmission assessment could not be generated.",
        )

    response_payload = {
        "demo_patient_id": result["demo_patient_id"],
        "patient_profile": patient_profile,
        **{
            key: value
            for key, value in result.items()
            if key != "demo_patient_id"
        },
    }
    return _json_response(200, response_payload)
