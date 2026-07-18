#!/usr/bin/env python3
"""
AnomalyDetect Agent - Coleta métricas e envia para o backend.
Compatível com Windows e Linux.
"""
import os
import sys
import time
import platform
import logging
import signal
import requests
from collector import collect_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log"),
    ],
)
logger = logging.getLogger("anomaly-agent")

API_URL = os.getenv("AGENT_API_URL", "http://localhost:8000")
API_TOKEN = os.getenv("AGENT_API_TOKEN", "")
COLLECTION_INTERVAL = int(os.getenv("COLLECTION_INTERVAL", "10"))
INGEST_ENDPOINT = f"{API_URL}/api/metrics/ingest"

running = True


def handle_signal(signum, frame):
    global running
    logger.info("Shutting down agent...")
    running = False


def send_metrics(metrics: dict) -> bool:
    try:
        response = requests.post(
            INGEST_ENDPOINT,
            json=metrics,
            headers={"X-Agent-Token": API_TOKEN},
            timeout=15,
        )
        if response.status_code == 202:
            data = response.json()
            if data.get("anomaly_detected"):
                logger.warning(f"ANOMALY DETECTED! ID: {data.get('anomaly_id')} - Check dashboard.")
            else:
                logger.debug("Metrics sent successfully.")
            return True
        else:
            logger.error(f"Failed to send metrics: {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to backend at {API_URL}")
        return False
    except requests.exceptions.Timeout:
        logger.error("Request timed out")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return False


def run():
    if not API_TOKEN:
        logger.error("AGENT_API_TOKEN is not set. Exiting.")
        sys.exit(1)

    logger.info(f"AnomalyDetect Agent started on {platform.node()} ({platform.system()})")
    logger.info(f"Backend: {API_URL} | Interval: {COLLECTION_INTERVAL}s")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    consecutive_failures = 0
    max_failures = 5

    while running:
        try:
            logger.info("Collecting metrics...")
            metrics = collect_metrics()
            success = send_metrics(metrics)

            if success:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= max_failures:
                    logger.error(f"Too many consecutive failures ({max_failures}). Waiting 5 minutes.")
                    time.sleep(300)
                    consecutive_failures = 0

        except Exception as e:
            logger.error(f"Error in collection loop: {e}", exc_info=True)

        if running:
            time.sleep(COLLECTION_INTERVAL)

    logger.info("Agent stopped.")


if __name__ == "__main__":
    run()
