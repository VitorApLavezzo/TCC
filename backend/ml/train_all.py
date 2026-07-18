"""
Script para treinar modelos de todas as máquinas registradas.
Execute periodicamente via cron ou manualmente.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models.machine import Machine
from app.services.ml_service import train_model


def train_all():
    db = SessionLocal()
    try:
        machines = db.query(Machine).filter(Machine.is_active == True).all()
        print(f"Found {len(machines)} active machines.")
        for machine in machines:
            print(f"Training model for machine: {machine.name} (id={machine.id})...")
            success = train_model(machine.id, db)
            if success:
                print(f"  ✓ Model trained successfully.")
            else:
                print(f"  ✗ Not enough data (< 100 samples).")
    finally:
        db.close()


if __name__ == "__main__":
    train_all()
