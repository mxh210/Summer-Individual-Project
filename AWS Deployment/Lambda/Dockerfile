# syntax=docker/dockerfile:1

ARG FUNCTION_DIR=/var/task

# Python 3.11 on Debian Bookworm provides a recent enough glibc for the exact
# NumPy, SciPy, pandas, and scikit-learn wheels used by the frozen model.
FROM python:3.11.16-slim-bookworm AS build-image

ARG FUNCTION_DIR

# The AWS Lambda Runtime Interface Client may be built from source on ARM64.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cmake \
        g++ \
        libcurl4-openssl-dev \
        make \
        unzip \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p "${FUNCTION_DIR}/artifacts"

COPY requirements-lambda.txt /tmp/requirements-lambda.txt

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install \
        --no-cache-dir \
        --target "${FUNCTION_DIR}" \
        -r /tmp/requirements-lambda.txt

COPY src/predictor.py src/lambda_function.py "${FUNCTION_DIR}/"
COPY artifacts/final_model.joblib "${FUNCTION_DIR}/artifacts/"
COPY artifacts/selected_validation_thresholds.csv "${FUNCTION_DIR}/artifacts/"


FROM python:3.11.16-slim-bookworm AS runtime

ARG FUNCTION_DIR

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libcurl4 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV LAMBDA_TASK_ROOT="${FUNCTION_DIR}" \
    MODEL_PATH="${FUNCTION_DIR}/artifacts/final_model.joblib" \
    THRESHOLD_PATH="${FUNCTION_DIR}/artifacts/selected_validation_thresholds.csv" \
    PATIENT_TABLE_NAME="readmission-demo-patients" \
    OMP_NUM_THREADS="1" \
    MKL_NUM_THREADS="1" \
    OPENBLAS_NUM_THREADS="1" \
    NUMEXPR_NUM_THREADS="1" \
    PYTHONDONTWRITEBYTECODE="1" \
    PYTHONUNBUFFERED="1" \
    PYTHONPATH="${FUNCTION_DIR}"

WORKDIR "${FUNCTION_DIR}"

COPY --from=build-image "${FUNCTION_DIR}" "${FUNCTION_DIR}"

ENTRYPOINT ["/usr/local/bin/python", "-m", "awslambdaric"]
CMD ["lambda_function.lambda_handler"]
