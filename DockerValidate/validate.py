"""Docker validation logic."""

import os
import shutil
import subprocess
from typing import Optional, Tuple

from constant import CMD_TIMEOUT_SECONDS, PYTHON_VERSIONS
from loguru import logger
from memory.memory import copy_file, json_to_requirements, save_text


def run_command(
    command: str,
    timeout: Optional[int] = None,
) -> Tuple[bool, str]:
    """Execute a shell command.

    Args:
        command: Shell command to execute.
        timeout: Optional timeout in seconds.

    Returns:
        Command success flag and combined standard output and error.
    """
    logger.info(f"[run_command] exec={command}")
    try:
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            timeout=timeout,
        )
        output = process.stdout + process.stderr
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        logger.info(f"[run_command] return_code={process.returncode}")
        return process.returncode == 0, output
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or b""
        stderr = error.stderr or b""
        output = stdout + stderr
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        logger.warning(f"[run_command] timeout={timeout}")
        return False, f"TIMEOUT({timeout}s): {output}"
    except Exception as error:
        logger.error(f"[run_command] exception={error}")
        return False, f"{type(error).__name__}: {error}"


def run_docker_validation(
    python_version: str,
    libraries: dict,
    code_file: str,
    validate_path: str,
    output_path: str,
    ablation_check_path: str,
) -> Tuple[bool, str]:
    """Validate a candidate environment in Docker.

    Args:
        python_version: Python Docker image version.
        libraries: Mapping from package names to optional versions.
        code_file: Python code file to validate.
        validate_path: Directory containing Docker input files.
        output_path: Directory containing Docker output files.
        ablation_check_path: Validation script copied into Docker input.

    Returns:
        Validation success flag and command output.
    """
    if not python_version:
        return False, "Empty python_version from env, skip docker."

    if python_version.count(".") >= 2:
        original_python_version = python_version
        python_version = ".".join(python_version.split(".")[:2])
        logger.info(
            f"[run_docker_validation] Normalize python {original_python_version} -> {python_version}"
        )

    if python_version not in PYTHON_VERSIONS:
        return False, f"Unsupported docker tag python:{python_version}"

    if os.path.exists(validate_path):
        shutil.rmtree(validate_path, ignore_errors=True)
    os.makedirs(validate_path, exist_ok=True)

    snippet_path = os.path.join(validate_path, "snippet.py")
    runner_path = os.path.join(validate_path, "ablation_check.py")
    copy_file(code_file, snippet_path)
    copy_file(ablation_check_path, runner_path)
    json_to_requirements(
        libraries,
        os.path.join(validate_path, "requirements.txt"),
    )

    if os.path.exists(output_path):
        shutil.rmtree(output_path, ignore_errors=True)
    os.makedirs(output_path, exist_ok=True)

    docker_command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{validate_path}:/app/code:ro",
        "-v",
        f"{output_path}:/app/results",
        "-w",
        "/app",
        f"python:{python_version}",
        "python",
        "/app/code/ablation_check.py",
        "--command",
        "python snippet.py",
    ]
    logger.info(f"[run_docker_validation] command={docker_command}")

    result, reason = run_command(
        docker_command,
        timeout=CMD_TIMEOUT_SECONDS,
    )
    logger.info(f"[run_docker_validation] success={result}")

    log_path = os.path.join(output_path, "log.log")
    if not os.path.exists(log_path):
        save_text(log_path, reason)

    return result, reason
