"""
SickLeave Predictor API
Exposes REST endpoints for sick leave risk prediction,
logs events to ElasticSearch, and exposes Prometheus metrics.
"""
import os
import time
import uuid
import logging
from datetime import datetime
from contextlib import asynccontextmanager

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

try:
    from elasticsearch import Elasticsearch
    ES_HOST = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
    es = Elasticsearch(ES_HOST, request_timeout=3)
    ES_AVAILABLE = es.ping()
except Exception:
    ES_AVAILABLE = False
    es = None

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

PREDICTIONS = Counter('healthsignal_predictions_total', 'Total predictions', ['risk_level'])
LATENCY = Histogram('healthsignal_prediction_latency_seconds', 'Prediction latency')
ES_WRITES = Counter('healthsignal_es_writes_total', 'ES write attempts', ['status'])

MODEL = None
FEATURES = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global MODEL, FEATURES
    log.info("Loading model...")
    MODEL = joblib.load("app/model.pkl")
    FEATURES = joblib.load("app/features.pkl")
    log.info(f"Model loaded. ES available: {ES_AVAILABLE}")
    yield

app = FastAPI(title="HealthSignal API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class EmployeeData(BaseModel):
    employee_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    age: int = Field(..., ge=18, le=80)
    tenure_years: int = Field(..., ge=0, le=45)
    absences_last_year: int = Field(..., ge=0)
    absences_last_3months: int = Field(..., ge=0)
    department_stress_score: float = Field(..., ge=1.0, le=10.0)
    previous_long_term: int = Field(..., ge=0, le=1)
    part_time: int = Field(..., ge=0, le=1)
    manager_support_score: float = Field(..., ge=1.0, le=10.0)

class PredictionResponse(BaseModel):
    model_config = {'protected_namespaces': ()}
    employee_id: str
    risk_level: str
    probability: float
    recommendation: str
    timestamp: str
    model_version: str = "1.0.0"

def get_recommendation(risk_level, prob):
    if risk_level == "HIGH":
        return "URGENT: Schedule immediate occupational health referral." if prob > 0.8 else "Initiate health promotion case within 3 days."
    return "Monitor closely. Consider proactive manager conversation." if prob > 0.35 else "No immediate action required."

@app.get("/")
def root():
    return {"service": "HealthSignal API", "version": "1.0.0", "docs": "/docs"}

@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": MODEL is not None, "elasticsearch": ES_AVAILABLE}

@app.post("/predict", response_model=PredictionResponse)
def predict(data: EmployeeData):
    if MODEL is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    start = time.time()
    features = np.array([[data.age, data.tenure_years, data.absences_last_year,
                          data.absences_last_3months, data.department_stress_score,
                          data.previous_long_term, data.part_time, data.manager_support_score]])
    prob = float(MODEL.predict_proba(features)[0][1])
    risk_level = "HIGH" if prob >= 0.5 else "LOW"
    PREDICTIONS.labels(risk_level=risk_level).inc()
    LATENCY.observe(time.time() - start)
    return {"employee_id": data.employee_id, "risk_level": risk_level,
            "probability": round(prob, 4), "recommendation": get_recommendation(risk_level, prob),
            "timestamp": datetime.utcnow().isoformat(), "model_version": "1.0.0"}

@app.post("/predict/batch")
def predict_batch(employees: list[EmployeeData]):
    if MODEL is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    return [predict(emp) for emp in employees]

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)