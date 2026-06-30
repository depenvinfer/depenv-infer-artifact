"""Run the complete MAPPER environment initialization and repair workflow."""

import argparse
import os
import time
import traceback
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger
from typing import List, Optional, Tuple

from constant import *
from EnvInitAgent.agent import EnvInitAgent
from EnvInitAgent.prompt import ENV_INIT_SYSTEM_PROMPT, ENV_INIT_USER_PROMPT
from DockerValidate.validate import run_docker_validation
from EnvRepairAgent.agent import EnvRepairAgent
from EnvRepairAgent.prompt import ENV_REPAIR_SYSTEM_PROMPT, ENV_REPAIR_USER_PROMPT
from memory.memory import *
from tools.tools import *

load_dotenv()

def initialize_environment(
    agent: EnvInitAgent,
    code: str,
    save_dir: str,
) -> dict:
    """Run environment initialization with the original retry and fallback logic.

    Args:
        agent: Environment initialization agent.
        code: Python source code to analyze.
        save_dir: Root result directory for the current sample.

    Returns:
        Initial candidate environment dictionary.
    """
    logger.info("[init] Start environment initialization")
    init_dir = os.path.join(save_dir, "initial")
    os.makedirs(init_dir, exist_ok=True)

    result = None
    env_json = dict(FALLBACK_ENV)

    for retry in range(LLM_MAX_RETRIES):
        try:
            result = agent.initialize(
                code,
                TOOLS,
                ENV_INIT_SYSTEM_PROMPT,
                ENV_INIT_USER_PROMPT
            )
            break
        except Exception as error:
            logger.warning(f"[init] Initialization failed, retry {retry+1}/{LLM_MAX_RETRIES}: {str(error)}")
            if retry < LLM_MAX_RETRIES - 1:
                time.sleep(2**retry)
            else:
                logger.error(f"[init] Initialization failed, using the default environment")
                

    if result is not None:
        env_json = parse_environment(result)
        if "ERROR" in env_json:
            raw_path = os.path.join(init_dir, "initial_invalid_llm_output.txt")
            save_text(raw_path, result)
            env_json = dict(FALLBACK_ENV)

    init_path = os.path.join(init_dir, "initial_result.json")
    save_to_json(env_json, init_path)

    deps = env_json.get("deps", {}) or {}
    nover = sum(1 for v in deps.values() if v == "")
    logger.info(f"[init] deps_total={len(deps)} deps_nover={nover}")

    return env_json

def verificate_environment(
    code_path: str,
    save_dir: str,
    ablation_check_path: str,
    env: dict,
    times: int,
    sample_metrics: Optional[dict] = None,
) -> Tuple[bool, str]:
    """Validate an environment and use the original result directory layout.

    Args:
        code_path: Python code file to validate.
        save_dir: Root result directory for the current sample.
        ablation_check_path: Validation runner file.
        env: Candidate environment dictionary.
        times: Validation round number.
        sample_metrics: Mutable counters for the current sample.

    Returns:
        Validation success flag and command output.
    """
    validate_dir = os.path.join(save_dir, "validate", str(times))
    verify_dir = os.path.join(save_dir, "verify", str(times))
    os.makedirs(validate_dir, exist_ok=True)
    os.makedirs(verify_dir, exist_ok=True)

    logger.info(f"[verify-{times}] python={env.get('python_version', '')}")
    logger.info(f"[verify-{times}] deps={env.get('deps', {})}")

    validation_start = time.perf_counter()
    if sample_metrics is not None:
        sample_metrics["docker_validation_count"] += 1
        sample_metrics["final_validation_round"] = times
    try:
        status, reason = run_docker_validation(
            env.get("python_version", ""),
            env.get("deps", {}),
            code_path,
            validate_dir,
            verify_dir,
            ablation_check_path,
        )
    finally:
        if sample_metrics is not None:
            sample_metrics["docker_total_seconds"] += (
                time.perf_counter() - validation_start
            )

    if status:
        logger.info(f"[verify-{times}] docker-pass")
    else:
        logger.warning(f"[verify-{times}] docker-fail reason={reason}")

    return status, reason

def repair_environment(
    agent: EnvRepairAgent,
    code: str,
    code_path: str,
    save_dir: str,
    last_env: dict,
    last_error: str,
    loop_numbers: int,
    sample_metrics: Optional[dict] = None,
) -> tuple:
    """Run the original iterative environment repair process.

    Args:
        agent: Environment repair agent.
        code: Python source code being analyzed.
        code_path: Path to the Python source file.
        save_dir: Root result directory for the current sample.
        last_env: Most recently validated environment.
        last_error: Most recent Docker validation error.
        loop_numbers: Maximum number of repair rounds.
        sample_metrics: Mutable counters for the current sample.

    Returns:
        Repair round count, final status, final reason, and final environment.
    """
    logger.info("[remediate] start remediation")
    loop_count = 1
    reason = last_error

    while loop_count <= loop_numbers:
        remediate_dir = os.path.join(save_dir, "remediate", str(loop_count))
        os.makedirs(remediate_dir, exist_ok=True)
        logger.info(f"[remediate-{loop_count}] round-start")
        logger.info(f"[remediate-{loop_count}] last_env={last_env}")
        logger.info(f"[remediate-{loop_count}] last_error={last_error}")

        result = None
        for retry in range(1, LLM_MAX_RETRIES + 1):
            try:
                result = agent.repair(
                    code,
                    last_env,
                    last_error,
                    TOOLS,
                    ENV_REPAIR_SYSTEM_PROMPT,
                    ENV_REPAIR_USER_PROMPT
                )
                break
            except Exception as error:
                logger.warning(
                    f"[remediate-{loop_count}] call failed, retry "
                    f"{retry}/{LLM_MAX_RETRIES}: {error}"
                )
                if retry < LLM_MAX_RETRIES:
                    time.sleep(2**retry)
                else:
                    logger.error(
                        f"[remediate-{loop_count}] call failed, using the "
                        f"last error"
                    )
        
        if result is None:
            logger.warning(
                f"[remediate-{loop_count}] no result, stop"
            )
            invalid_path = os.path.join(
                remediate_dir,
                "invalid_llm_output.txt",
            )
            save_text(invalid_path, result)
            last_error = "INVALID LLM OUTPUT IN JSON FORMAT"
            loop_count += 1
            continue

        if "UNCONTROLLABLE FACTOR" in result:
            logger.warning(
                f"[remediate-{loop_count}] uncontrollable, stop"
            )
            return loop_count, UNCONTROLLABLE_FACTOR, result, last_env

        new_env = parse_environment(result)
        if "ERROR" in new_env:
            invalid_path = os.path.join(
                remediate_dir,
                "invalid_llm_output.txt",
            )
            save_text(invalid_path, result)
            last_error = "INVALID LLM OUTPUT IN JSON FORMAT"
            loop_count += 1
            continue

        remediate_path = os.path.join(
            remediate_dir,
            "remediate_output.json",
        )
        save_to_json(new_env, remediate_path)

        status, reason = verificate_environment(
            code_path,
            save_dir,
            ABLATION_CHECK_PATH,
            new_env,
            loop_count,
            sample_metrics,
        )
        if status:
            logger.info(
                f"[remediate-{loop_count}] remediation-success"
            )
            return loop_count, ENVIRONMENT_FIX_SUCCESS, reason, new_env

        last_env = new_env
        last_error = reason
        loop_count += 1

    logger.warning("[remediate] exceed max rounds")
    return loop_numbers, ENVIRONMENT_FIX_FAIL, reason, last_env


def parse_environment(llm_output: str) -> dict:
    """Parse and validate the environment schema returned by an agent."""
    env = parse_json(llm_output)
    if not isinstance(env, dict) or "ERROR" in env:
        return {"ERROR": "LLM output is NOT a valid environment object"}

    python_version = env.get("python_version")
    deps = env.get("deps")
    if not isinstance(python_version, str) or not isinstance(deps, dict):
        return {
            "ERROR": (
                "Environment must contain string python_version and object deps"
            )
        }
    if python_version not in PYTHON_VERSIONS:
        return {"ERROR": f"Unsupported Python version: {python_version}"}

    if not all(
        isinstance(package, str) and isinstance(version, str)
        for package, version in deps.items()
    ):
        return {"ERROR": "Environment dependency names and versions must be strings"}

    return {
        "python_version": python_version,
        "deps": deps,
    }


def save_final_result(
    save_dir: str,
    sample_id: int,
    dataset: str,
    code_path: str,
    model_name: str,
    temperature: Optional[float],
    loop_num: int,
    status: str,
    repair_rounds_used: int,
    final_env: Optional[dict],
    sample_metrics: dict,
    sample_start_time: float,
) -> None:
    """Save the structured terminal result for one sample."""
    workflow_seconds = time.perf_counter() - sample_start_time
    docker_seconds = sample_metrics["docker_total_seconds"]
    result = {
        "sample_id": sample_id,
        "dataset": dataset,
        "code_file": os.path.abspath(code_path),
        "experiment": {
            "model_name": model_name,
            "temperature": temperature,
            "max_repair_rounds": loop_num,
        },
        "status": status,
        "repair_rounds_used": repair_rounds_used,
        "final_validation_round": sample_metrics["final_validation_round"],
        "final_env": final_env,
        "metrics": {
            "tool_calls": get_tool_call_counts(),
            "docker_validation_count": sample_metrics[
                "docker_validation_count"
            ],
            "timing": {
                "workflow_total_seconds": round(workflow_seconds, 3),
                "docker_total_seconds": round(docker_seconds, 3),
                "inference_seconds": round(
                    max(0.0, workflow_seconds - docker_seconds),
                    3,
                ),
            },
        },
    }
    save_to_json(result, os.path.join(save_dir, "final_result.json"))


def run_samples(
    model_name: str,
    temperature: float,
    loop_num: int,
    dataset_type: str,
    dataset_list: List[str],
    start_idx: int,
    end_idx: int
) -> None:
    """Run the complete MAPPER workflow for a list of code samples.

    Args:
        dataset_list: Ordered list of Python sample file paths.
        test_type: Dataset type. The original workflow uses ``gist`` or ``hg``.
        model_name: Name of the OpenAI-compatible chat model.
        temperature: Sampling temperature used by both agents.
        loop_num: Maximum number of environment repair rounds.
        prefix: Short model identifier used in result paths.
        infix: Experiment identifier derived from loop count and temperature.
        api_secret_key: API key used to access the model service.
        base_url: Base URL of the model service.
        start_idx: One-based index of the first sample to process.
        end_idx: One-based index of the last sample to process.

    Returns:
        None.
    """
    if dataset_type == "gist":
        save_root = os.path.join(
            RESULT_DIR,
            model_name,
            str(loop_num),
            str(temperature).replace(".", "_"),
            "gist_371",
        )
        dataset_label = "[GIST]"
        dataset_name = "gist_371"
    else:
        save_root = os.path.join(
            RESULT_DIR,
            model_name,
            str(loop_num),
            str(temperature).replace(".", "_"),
            "hg_340",
        )
        dataset_label = "[HG]"
        dataset_name = "hg_340"

    # 环境初始化 Agent
    init_agent = EnvInitAgent(
        model_name,
        temperature
    )
    # 环境修复 Agent
    repair_agent = EnvRepairAgent(
        model_name,
        temperature
    )

    slice_start = max(start_idx - 1, 0)
    for code_path in dataset_list[slice_start:end_idx]:
        sample_id = int(os.path.splitext(os.path.basename(code_path))[0])
        sample_save_dir = os.path.join(save_root, str(sample_id))
        sample_start_time = time.perf_counter()
        sample_metrics = {
            "docker_validation_count": 0,
            "docker_total_seconds": 0.0,
            "final_validation_round": None,
        }
        reset_tool_call_counts()
        status = "ERROR"
        repair_rounds_used = 0
        final_env = None
        try:
            logger.info(
                f"{dataset_label} sample={sample_id} file={code_path}"
            )
            with open(code_path, "r", encoding="utf-8") as file:
                code = file.read()

            # 环境初始化
            init_env = initialize_environment(
                init_agent,
                code,
                sample_save_dir,
            )
            final_env = init_env

            status, reason = verificate_environment(
                code_path,
                sample_save_dir,
                ABLATION_CHECK_PATH,
                init_env,
                0,  # 初始环境验证，所以传入的是 0
                sample_metrics,
            )

            if status:
                status = INITIAL_SUCCESS
                logger.info(f"{dataset_label} sample={sample_id} init-verify-pass")
                logger.info(f"{dataset_label} [sample] idx={sample_id} status={status} rounds=0 reason=init-pass file={code_path}")
            else:
                status = "ERROR"
                repair_rounds_used, status, reason, final_env = repair_environment(
                    repair_agent,
                    code,
                    code_path,
                    sample_save_dir,
                    init_env,
                    reason,
                    loop_num,
                    sample_metrics,
                )
                logger.info(
                    f"{dataset_label} [sample] idx={sample_id} status={status} rounds={repair_rounds_used} reason={reason} file={code_path}"
                )
        except Exception as error:
            logger.error(
                f"{dataset_label} sample={sample_id} exception={error}"
            )
            logger.error(traceback.format_exc())
            logger.info(
                f"{dataset_label} [sample] idx={sample_id} status=ERROR reason={error} file={code_path}"
            )
        finally:
            try:
                save_final_result(
                    sample_save_dir,
                    sample_id,
                    dataset_name,
                    code_path,
                    model_name,
                    temperature,
                    loop_num,
                    status,
                    repair_rounds_used,
                    final_env,
                    sample_metrics,
                    sample_start_time,
                )
            except Exception as error:
                logger.error(
                    f"{dataset_label} sample={sample_id} final-result-error={error}"
                )
                logger.error(traceback.format_exc())

        time.sleep(3)


def get_sorted_py_files(dir_path: str) -> list:
    """Collect numerically named Python files in numeric order.

    Args:
        dir_path: Directory containing Python sample files.

    Returns:
        Ordered list of Python file paths whose names are numeric.
    """
    numbered_files = []
    filenames = os.listdir(dir_path)

    for filename in filenames:
        file_path = os.path.join(dir_path, filename)
        file_stem, file_extension = os.path.splitext(filename)

        if file_extension != ".py":
            continue
        if not os.path.isfile(file_path):
            continue
        if not file_stem.isdigit():
            continue

        file_number = int(file_stem)
        numbered_files.append((file_number, file_path))

    numbered_files.sort()

    python_files = []
    for file_number, file_path in numbered_files:
        python_files.append(file_path)

    return python_files


def main() -> None:
    """Parse command-line arguments and run the workflow."""
    parser = argparse.ArgumentParser(
        description="Run MAPPER with the specified parameters."
    )
    parser.add_argument("--model_name", type=str, required=True)
    parser.add_argument("--temperature", type=float, required=True)
    parser.add_argument("--loop_num", type=int, required=True)
    parser.add_argument("--dataset_type", type=str, choices=["gist", "hg"], default="hg")
    parser.add_argument("--start_idx", type=int, default=1)
    parser.add_argument("--end_idx", type=int, default=340)
    args = parser.parse_args()

    if args.dataset_type == "gist":
        dataset_path = os.path.join(DATASET_DIR, DATASET_ONE)
        dataset_list = get_sorted_py_files(dataset_path)
    else:
        dataset_path = os.path.join(DATASET_DIR, DATASET_TWO)
        dataset_list = get_sorted_py_files(dataset_path)

    today = datetime.now().strftime("%Y%m%d")
    log_dir = os.path.join(ROOT, "logs", args.model_name, str(args.loop_num), str(args.temperature).replace(".", "_"))
    
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{today}-{str(args.start_idx)}-{str(args.end_idx)}.log")
    logger.add(log_path, encoding="utf-8", enqueue=True, backtrace=False, diagnose=False)
    
    run_samples(
        args.model_name,
        args.temperature,
        args.loop_num,
        args.dataset_type,
        dataset_list,
        start_idx=args.start_idx,
        end_idx=args.end_idx,
    )


if __name__ == "__main__":
    main()
