"""Constants."""

import os

# Official Python images supported by Docker.
PYTHON_VERSIONS = [
    "2.7",
    "3.3",
    "3.4",
    "3.5",
    "3.6",
    "3.7",
    "3.8",
    "3.9",
    "3.10",
    "3.11",
    "3.12",
    "3.13",
]

UNCONTROLLABLE_FACTOR = "UNCONTROLLABLE FACTOR"
ENVIRONMENT_FIX_SUCCESS = "ENVIRONMENT FIX SUCCESS"
ENVIRONMENT_FIX_FAIL = "ENVIRONMENT FIX FAIL"
INITIAL_SUCCESS = "INITIAL SUCCESS"

ROOT = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(ROOT, "result")
DATASET_DIR = os.path.join(ROOT, "dataset")
ABLATION_CHECK_PATH = os.path.join(
    ROOT,
    "DockerValidate",
    "ablation_check.py",
)
DATASET_ONE = "371"
DATASET_TWO = "340"

CMD_TIMEOUT_SECONDS = 3600
HTTP_TIMEOUT_SECONDS = 180
URL_MAX_RETRIES = 10
LLM_MAX_RETRIES = 10
MAX_SLEEP_TIME = 3

FALLBACK_ENV = {"python_version": "3.9", "deps": {}}
