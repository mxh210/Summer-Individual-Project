"use strict";

const config = window.READMISSION_CONFIG || {};
const API_BASE_URL = String(config.apiBaseUrl || "").replace(/\/$/, "");
const FIRST_DEMO_ID = Number(config.firstDemoId || 1);
const LAST_DEMO_ID = Number(config.lastDemoId || 2000);
const BASE_TITLE = "Readmission assessment – Research prototype";

const profileGroups = [
  {
    title: "Demographics",
    features: ["gender", "race_group", "age_group"],
  },
  {
    title: "Encounter context",
    features: [
      "admission_source_group",
      "discharge_group",
      "medical_specialty_group",
      "primary_diagnosis",
    ],
  },
  {
    title: "Clinical indicators",
    features: [
      "hba1c_group",
      "max_glu_serum",
      "diabetesMed",
      "time_in_hospital",
      "num_lab_procedures",
      "num_procedures",
      "num_medications",
      "number_diagnoses",
    ],
  },
  {
    title: "Prior utilisation",
    features: [
      "number_outpatient",
      "number_emergency",
      "number_inpatient",
    ],
  },
];

const featureLabels = {
  gender: "Gender",
  race_group: "Race group",
  age_group: "Age group",
  admission_source_group: "Admission source",
  discharge_group: "Discharge destination",
  medical_specialty_group: "Medical specialty",
  primary_diagnosis: "Primary diagnosis",
  hba1c_group: "HbA1c result",
  max_glu_serum: "Maximum glucose serum",
  diabetesMed: "Diabetes medication",
  time_in_hospital: "Time in hospital",
  num_lab_procedures: "Laboratory procedures",
  num_procedures: "Other procedures",
  num_medications: "Medications",
  number_outpatient: "Prior outpatient visits",
  number_emergency: "Prior emergency visits",
  number_inpatient: "Prior inpatient visits",
  number_diagnoses: "Diagnoses",
};

const form = document.querySelector("#assessment-form");
const input = document.querySelector("#patient-id");
const statusBox = document.querySelector("#status");
const results = document.querySelector("#results");
const submitButton = document.querySelector("#submit-button");
const previousButton = document.querySelector("#previous-button");
const nextButton = document.querySelector("#next-button");
const randomButton = document.querySelector("#random-button");

function formatDemoId(number) {
  return `DEMO-${String(number).padStart(5, "0")}`;
}

function parseDemoId(value) {
  const match = /^DEMO-(\d{5})$/.exec(value.trim().toUpperCase());

  if (!match) {
    return null;
  }

  const number = Number(match[1]);

  if (number < FIRST_DEMO_ID || number > LAST_DEMO_ID) {
    return null;
  }

  return number;
}

function setStatus(kind, message) {
  statusBox.className = `status status-${kind}`;
  statusBox.textContent = message;
  document.title =
    kind === "error" ? `Error: ${BASE_TITLE}` : BASE_TITLE;
}

function clearStatus() {
  statusBox.className = "status";
  statusBox.textContent = "";
  document.title = BASE_TITLE;
}

function setLoading(isLoading) {
  submitButton.disabled = isLoading;
  previousButton.disabled = isLoading;
  nextButton.disabled = isLoading;
  randomButton.disabled = isLoading;
  input.disabled = isLoading;

  submitButton.textContent = isLoading
    ? "Loading…"
    : "Load assessment";
}

function displayValue(value, feature) {
  if (value === null || value === undefined || value === "") {
    return "Not recorded";
  }

  if (feature === "time_in_hospital") {
    return `${value} ${Number(value) === 1 ? "day" : "days"}`;
  }

  return String(value);
}

function renderProfile(profile) {
  const container = document.querySelector("#profile-groups");
  container.replaceChildren();

  for (const group of profileGroups) {
    const section = document.createElement("section");
    section.className = "profile-group";

    const heading = document.createElement("h3");
    heading.textContent = group.title;
    section.appendChild(heading);

    const list = document.createElement("dl");

    for (const feature of group.features) {
      const row = document.createElement("div");
      const term = document.createElement("dt");
      const description = document.createElement("dd");

      term.textContent = featureLabels[feature];
      description.textContent = displayValue(
        profile[feature],
        feature,
      );

      row.append(term, description);
      list.appendChild(row);
    }

    section.appendChild(list);
    container.appendChild(section);
  }
}

function renderAssessment(payload) {
  const assessment = payload.assessment;
  const modelInfo = payload.model_information;
  const flagged = assessment.clinical_review_flag === true;
  const score = Number(assessment.model_estimated_score);
  const threshold = Number(assessment.selected_threshold);
  const displayCeiling = 0.2;

  document.querySelector("#result-id").textContent =
    payload.demo_patient_id;

  document.querySelector("#risk-badge").textContent =
    assessment.risk_category;

  document.querySelector("#risk-badge").className =
    `risk-badge ${flagged ? "risk-high" : "risk-low"}`;

  document.querySelector("#assessment-card").className =
    `assessment-card ${
      flagged ? "assessment-high" : "assessment-low"
    }`;

  document.querySelector("#score-value").textContent =
    score.toFixed(4);

  document.querySelector("#threshold-label").textContent =
    `Threshold ${threshold.toFixed(4)}`;

  document.querySelector("#score-marker").style.left =
    `${Math.min((score / displayCeiling) * 100, 100)}%`;

  document.querySelector("#threshold-marker").style.left =
    `${Math.min((threshold / displayCeiling) * 100, 100)}%`;

  document.querySelector("#score-scale").setAttribute(
    "aria-label",
    `Model score ${score.toFixed(4)} compared with review threshold ${threshold.toFixed(4)}`,
  );

  document.querySelector("#assessment-message").textContent =
    payload.message;

  document.querySelector("#review-value").textContent = flagged
    ? "Clinical review flag"
    : "No review flag";

  document.querySelector("#review-dot").className =
    `review-dot ${flagged ? "dot-high" : "dot-low"}`;

  document.querySelector("#model-type").textContent =
    modelInfo.model_type;

  document.querySelector("#prediction-target").textContent =
    modelInfo.prediction_target;

  document.querySelector("#operating-policy").textContent =
    modelInfo.operating_policy;

  document.querySelector("#interpretation").textContent = flagged
    ? "The model-estimated score is at or above the selected threshold, so this encounter is flagged for human clinical review."
    : "The model-estimated score is below the selected threshold, so this encounter is not flagged under the chosen operating policy.";

  document.querySelector("#disclaimer-text").textContent =
    payload.disclaimer;

  renderProfile(payload.patient_profile);
  results.hidden = false;
}

function validatePayload(payload) {
  if (
    !payload ||
    typeof payload !== "object" ||
    !payload.assessment ||
    !payload.patient_profile ||
    !payload.model_information
  ) {
    throw new Error(
      "The service returned an incomplete assessment.",
    );
  }
}

async function loadAssessment(demoId) {
  if (!API_BASE_URL) {
    setStatus(
      "error",
      "The dashboard API URL has not been configured.",
    );
    return;
  }

  setLoading(true);
  setStatus("loading", `Loading ${demoId} from AWS…`);

  try {
    const response = await fetch(
      `${API_BASE_URL}/assessments/${encodeURIComponent(demoId)}`,
      {
        headers: {
          Accept: "application/json",
        },
        cache: "no-store",
      },
    );

    const payload = await response.json();

    if (!response.ok) {
      const message =
        payload?.error?.message ||
        "The request was not successful.";

      throw new Error(message);
    }

    validatePayload(payload);
    renderAssessment(payload);
    setStatus("success", `${demoId} loaded successfully.`);
  } catch (error) {
    results.hidden = true;

    setStatus(
      "error",
      error instanceof Error
        ? error.message
        : "The assessment could not be loaded.",
    );
  } finally {
    setLoading(false);
  }
}

function selectNumber(number, shouldLoad = true) {
  const bounded = Math.min(
    Math.max(number, FIRST_DEMO_ID),
    LAST_DEMO_ID,
  );

  const demoId = formatDemoId(bounded);
  input.value = demoId;

  if (shouldLoad) {
    loadAssessment(demoId);
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();

  const number = parseDemoId(input.value);

  if (number === null) {
    results.hidden = true;

    setStatus(
      "error",
      `Enter an ID between ${formatDemoId(
        FIRST_DEMO_ID,
      )} and ${formatDemoId(LAST_DEMO_ID)}.`,
    );

    input.focus();
    return;
  }

  input.value = formatDemoId(number);
  loadAssessment(input.value);
});

previousButton.addEventListener("click", () => {
  const current =
    parseDemoId(input.valueBots) || FIRST_DEMO_ID;

  selectNumber(
    current === FIRST_DEMO_ID
      ? LAST_DEMO_ID
      : current - 1,
  );
});

nextButton.addEventListener("click", () => {
  const current =
    parseDemoId(input.value) || FIRST_DEMO_ID;

  selectNumber(
    current === LAST_DEMO_ID
      ? FIRST_DEMO_ID
      : current + 1,
  );
});

randomButton.addEventListener("click", () => {
  const randomNumber =
    Math.floor(
      Math.random() *
        (LAST_DEMO_ID - FIRST_DEMO_ID + 1),
    ) + FIRST_DEMO_ID;

  selectNumber(randomNumber);
});

input.addEventListener("input", clearStatus);

selectNumber(FIRST_DEMO_ID);