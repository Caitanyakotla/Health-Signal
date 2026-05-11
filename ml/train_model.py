"""
HealthSignal — ML model trainer.
Trains on synthetic employee absence data and saves model to disk.
"""
import pandas as pd
import numpy as np
import joblib
import os
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline

def generate_dataset(n=5000, seed=42):
    np.random.seed(seed)

    age = np.random.randint(22, 65, n)
    tenure = np.random.randint(0, 30, n)
    absences_last_year = np.random.poisson(3, n)
    absences_last_3m = np.random.poisson(1, n)
    stress_score = np.random.uniform(1, 10, n)
    previous_long_term = np.random.binomial(1, 0.1, n)
    part_time = np.random.binomial(1, 0.3, n)
    manager_support_score = np.random.uniform(1, 10, n)

    # Realistic label: combination of risk factors
    risk_score = (
        (absences_last_year > 5).astype(int) * 2 +
        (absences_last_3m > 2).astype(int) * 2 +
        (stress_score > 7).astype(int) +
        previous_long_term * 3 +
        (manager_support_score < 4).astype(int) +
        (age > 55).astype(int)
    )
    long_term_risk = (risk_score >= 3).astype(int)

    df = pd.DataFrame({
        'age': age,
        'tenure_years': tenure,
        'absences_last_year': absences_last_year,
        'absences_last_3months': absences_last_3m,
        'department_stress_score': stress_score,
        'previous_long_term': previous_long_term,
        'part_time': part_time,
        'manager_support_score': manager_support_score,
        'long_term_risk': long_term_risk
    })
    return df


def train():
    print("Generating synthetic employee absence dataset...")
    df = generate_dataset(5000)
    print(f"Dataset: {len(df)} rows | Risk positive: {df['long_term_risk'].mean():.1%}")

    X = df.drop('long_term_risk', axis=1)
    y = df['long_term_risk']

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipeline = Pipeline([
        ('scaler', StandardScaler()),
        ('model', GradientBoostingClassifier(
            n_estimators=20,
            max_depth=3,
            learning_rate=0.1,
            random_state=42
        ))
    ])

    print("Training GradientBoosting model...")
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]

    print("\n=== Model Performance ===")
    print(classification_report(y_test, y_pred, target_names=['Low Risk', 'High Risk']))
    print(f"ROC-AUC Score: {roc_auc_score(y_test, y_prob):.3f}")

    os.makedirs('app', exist_ok=True)
    joblib.dump(pipeline, 'app/model.pkl')
    print("\nModel saved to app/model.pkl")

    # Save feature names for the API
    feature_names = list(X.columns)
    joblib.dump(feature_names, 'app/features.pkl')
    print("Feature list saved to app/features.pkl")


if __name__ == '__main__':
    train()
