"""Agent tools."""

import json
import random
import threading
import time
from typing import List

import requests
from constant import (
    HTTP_TIMEOUT_SECONDS,
    MAX_SLEEP_TIME,
    PYTHON_VERSIONS,
    URL_MAX_RETRIES,
)
from langchain.tools import tool
from loguru import logger
from stdlib_list import stdlib_list

TOOL_NAMES = (
    "search_stdlib_versions",
    "check_tpl_exists",
    "search_tpl_infos",
    "search_tpl_with_version_infos",
)
_TOOL_CALL_COUNTS = {name: 0 for name in TOOL_NAMES}
_TOOL_CALL_COUNTS_LOCK = threading.Lock()


def reset_tool_call_counts() -> None:
    """Reset tool-call counters before processing one sample."""
    with _TOOL_CALL_COUNTS_LOCK:
        for name in TOOL_NAMES:
            _TOOL_CALL_COUNTS[name] = 0


def get_tool_call_counts() -> dict:
    """Return per-tool counts and their total for the current sample."""
    with _TOOL_CALL_COUNTS_LOCK:
        counts = dict(_TOOL_CALL_COUNTS)
    counts["total"] = sum(counts.values())
    return counts


def _record_tool_call(tool_name: str) -> None:
    """Record entry into an agent tool function."""
    with _TOOL_CALL_COUNTS_LOCK:
        _TOOL_CALL_COUNTS[tool_name] += 1


def key_split(v: str):
    """Split a major-minor version string into integer components.

    Args:
        v: Version string in ``major.minor`` format.

    Returns:
        Tuple containing the integer major and minor versions.
    """
    a, b = v.split(".")
    return int(a), int(b)


def fmt(s: List[str]):
    """Format one version or a continuous version range.

    Args:
        s: Ordered list containing one continuous version segment.

    Returns:
        A single version or an en-dash-separated version range.
    """
    return s[0] if len(s) == 1 else f"{s[0]}–{s[-1]}"


def _compress_ranges(sorted_versions: List[str]):
    """Compress an ordered version list into a range string.

    Args:
        sorted_versions: Python versions ordered from oldest to newest.

    Returns:
        Comma-separated string containing individual versions and ranges.
    """
    if not sorted_versions:
        return ""
    segs, seg = [], [sorted_versions[0]]

    for prev, cur in zip(sorted_versions, sorted_versions[1:]):
        (pa, pb), (ca, cb) = key_split(prev), key_split(cur)
        if pa == ca and (cb - pb == 1):
            seg.append(cur)
        else:
            segs.append(seg)
            seg = [cur]
    segs.append(seg)

    return ", ".join(fmt(s) for s in segs)


# =========================================================
# 1) Check whether a module belongs to the Python standard library.
# =========================================================
@tool
def search_stdlib_versions(func_name: str):
    """Check whether a name is a Python standard library module.

    Args:
        func_name: Module name to query.

    Returns:
        JSON string containing the queried name, standard-library flag, and
        supported Python version range.
    """
    _record_tool_call("search_stdlib_versions")
    logger.info(f"[tool-usage] search_stdlib_versions(name={func_name})")
    logger.info("[search_stdlib_versions] start")

    q = (func_name or "").strip()
    result = {
        "query": q,
        "is_stdlib_module": False,
        "version_range": "",
    }

    stdsets = {}
    for v in PYTHON_VERSIONS:
        try:
            stdsets[v] = set(stdlib_list(v))
        except Exception as e:
            logger.warning(f"[search_stdlib_versions] stdlib_list({v}) failed: {e}")
            stdsets[v] = set()
    covered = [v for v in PYTHON_VERSIONS if q in stdsets.get(v, set())]
    logger.info("[search_stdlib_versions] end")

    if covered:
        vr = _compress_ranges(covered)
        result["is_stdlib_module"] = True
        result["version_range"] = vr
        logger.info(f"[search_stdlib_versions] {q} IS stdlib, versions={vr}")
    else:
        # Keep the version range empty when the name is not a stdlib module.
        result["is_stdlib_module"] = False
        result["version_range"] = ""
        logger.info(f"[search_stdlib_versions] {q} is NOT stdlib")

    return json.dumps(result, ensure_ascii=False)


# =========================================================
# 2) Check whether a third-party package exists on PyPI.
# =========================================================
@tool
def check_tpl_exists(tpl_name: str):
    """Check whether a third-party package exists on PyPI.

    Args:
        tpl_name: Third-party package name to query.

    Returns:
        JSON string containing the package name, existence flag, HTTP status
        code, and an optional diagnostic message.
    """
    _record_tool_call("check_tpl_exists")
    logger.info(f"[tool-usage] check_tpl_exists(pkg={tpl_name})")
    logger.info("[check_tpl_exists] start")

    name = (tpl_name or "").strip()
    result = {"name": name}

    url = f"https://pypi.python.org/pypi/{name}/json"
    last_exc = None
    max_retries = URL_MAX_RETRIES
    for i in range(max_retries):
        try:
            # Apply the configured timeout to prevent indefinite requests.
            response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
            time.sleep(random.uniform(0, MAX_SLEEP_TIME))
            break
        except Exception as e:
            last_exc = e
            logger.warning(
                f"[check_tpl_exists] request error on attempt {i + 1}/{max_retries}: {e}"
            )
            if i < max_retries - 1:
                time.sleep(1)
    else:
        # Preserve the original error response after all retries fail.
        result["exists"] = False
        result["status_code"] = -1
        result["message"] = (
            f"request error after {max_retries} retries: {type(last_exc).__name__}: {last_exc}"
        )
        logger.error(f"[check_tpl_exists] request error after retries: {last_exc}")
        return json.dumps(result, ensure_ascii=False)

    logger.info("[check_tpl_exists] end")

    status = response.status_code
    result["status_code"] = status
    if status == 200:
        result["exists"] = True
        logger.info(f"[check_tpl_exists] found on PyPI, status={status}")
    elif status == 404:
        result["exists"] = False
        result["message"] = "package not found on PyPI"
        logger.info(f"[check_tpl_exists] NOT found on PyPI, status={status}")
    elif status in (403, 429):
        result["exists"] = False
        result["message"] = "access denied or rate limit"
        logger.info(f"[check_tpl_exists] access denied / rate limit, status={status}")
    elif 500 <= status < 600:
        result["exists"] = False
        result["message"] = "PYPI server error"
        logger.info(f"[check_tpl_exists] PyPI server error, status={status}")
    else:
        result["exists"] = False
        result["message"] = "UNKNOWN_STATUS"
        logger.info(f"[check_tpl_exists] unknown status={status}")

    return json.dumps(result, ensure_ascii=False)


# =========================================================
# 3) Retrieve complete metadata for a third-party package.
# =========================================================
@tool
def search_tpl_infos(tpl_name: str):
    """Retrieve complete metadata for a third-party package from PyPI.

    Args:
        tpl_name: Third-party package name to query.

    Returns:
        JSON string containing package metadata, including version,
        dependencies, Python requirements, extras, and release history.
    """
    _record_tool_call("search_tpl_infos")
    logger.info(f"[tool-usage] search_tpl_infos(pkg={tpl_name})")
    logger.info("[search_tpl_infos] start")

    name = (tpl_name or "").strip()
    result = {"name": name}

    url = f"https://pypi.python.org/pypi/{name}/json"
    last_exc = None
    max_retries = URL_MAX_RETRIES
    for i in range(max_retries):
        try:
            response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
            time.sleep(random.uniform(0, MAX_SLEEP_TIME))
            break
        except Exception as e:
            last_exc = e
            logger.warning(
                f"[search_tpl_infos] request error on attempt {i + 1}/{max_retries}: {e}"
            )
            if i < max_retries - 1:
                time.sleep(1)
    else:
        result["ok"] = False
        result["status_code"] = -1
        result["message"] = (
            f"request error after {max_retries} retries: {type(last_exc).__name__}: {last_exc}"
        )
        logger.error(f"[search_tpl_infos] request error after retries: {last_exc}")
        return json.dumps(result, ensure_ascii=False)

    logger.info("[search_tpl_infos] end")

    status = response.status_code
    result["status_code"] = status

    if status == 200:
        data = response.json()
        info = data.get("info", {})

        latest_version = info.get("version", "unknown")
        classifiers = info.get("classifiers") or []
        requires_dist = info.get("requires_dist") or []
        requires_python = info.get("requires_python", "unspecified")
        extra_info = info.get("provides_extra") or []
        version_history = list(data.get("releases", {}).keys())

        result["ok"] = True
        result["latest_version"] = latest_version
        result["classifiers"] = classifiers
        result["requires_dist"] = requires_dist
        result["requires_python"] = requires_python
        result["extra_info"] = extra_info
        result["version_history"] = version_history

        logger.info(
            f"[search_tpl_infos] success, latest={latest_version}, releases={len(version_history)}, status={status}"
        )
    elif status == 404:
        result["ok"] = False
        result["message"] = "package not found on PyPI"
        logger.info(f"[search_tpl_infos] NOT found on PyPI, status={status}")
    elif status in (403, 429):
        result["ok"] = False
        result["message"] = "access denied or rate limit"
        logger.info(f"[search_tpl_infos] access denied / rate limit, status={status}")
    elif 500 <= status < 600:
        result["ok"] = False
        result["message"] = "PYPI server error"
        logger.info(f"[search_tpl_infos] PyPI server error, status={status}")
    else:
        result["ok"] = False
        result["message"] = "UNKNOWN_STATUS"
        logger.info(f"[search_tpl_infos] unknown status={status}")

    return json.dumps(result, ensure_ascii=False)


# =========================================================
# 4) Retrieve metadata for a specific third-party package version.
# =========================================================
@tool
def search_tpl_with_version_infos(query: str):
    """Retrieve PyPI metadata for a specific package version.

    Args:
        query: Query in ``package_name==version`` format.

    Returns:
        JSON string containing package and version metadata, dependencies,
        Python requirements, extras, and an optional diagnostic message.
    """
    _record_tool_call("search_tpl_with_version_infos")
    logger.info(f"[tool-usage] search_tpl_with_version_infos(pkg==version:{query})")
    logger.info("[search_tpl_with_version_infos] start")

    raw = (query or "").strip()
    result = {"query": raw}

    try:
        # Split the original input once to preserve the package name.
        tpl_name, tpl_version = raw.split("==", 1)
    except ValueError:
        result["ok"] = False
        result["status_code"] = -1
        result["message"] = "input format must be 'package==version'"
        logger.warning(
            "[search_tpl_with_version_infos] bad format, need 'package==version'"
        )
        return json.dumps(result, ensure_ascii=False)

    tpl_name = tpl_name.strip()
    tpl_version = tpl_version.strip()
    url = f"https://pypi.python.org/pypi/{tpl_name}/{tpl_version}/json"
    last_exc = None
    max_retries = URL_MAX_RETRIES
    for i in range(max_retries):
        try:
            response = requests.get(url, timeout=HTTP_TIMEOUT_SECONDS)
            time.sleep(random.uniform(0, MAX_SLEEP_TIME))
            break
        except Exception as e:
            last_exc = e
            logger.warning(
                f"[search_tpl_with_version_infos] request error on attempt {i + 1}/{max_retries}: {e}"
            )
            if i < max_retries - 1:
                time.sleep(1)
    else:
        result["ok"] = False
        result["status_code"] = -1
        result["message"] = (
            f"request error after {max_retries} retries: {type(last_exc).__name__}: {last_exc}"
        )
        logger.error(
            f"[search_tpl_with_version_infos] request error after retries: {last_exc}"
        )
        return json.dumps(result, ensure_ascii=False)

    logger.info("[search_tpl_with_version_infos] end")

    status = response.status_code
    result["status_code"] = status

    if status == 200:
        info = response.json().get("info", {})
        classifiers = info.get("classifiers") or []
        requires_dist = info.get("requires_dist") or []
        requires_python = info.get("requires_python", "unspecified")
        extra_info = info.get("provides_extra") or []

        result["ok"] = True
        result["name"] = tpl_name
        result["version"] = tpl_version
        result["classifiers"] = classifiers
        result["requires_dist"] = requires_dist
        result["requires_python"] = requires_python
        result["extra_info"] = extra_info

        logger.info(
            f"[search_tpl_with_version_infos] success, pkg={tpl_name}, ver={tpl_version}, status={status}"
        )
    elif status == 404:
        result["ok"] = False
        result["message"] = "package version not found on PyPI"
        logger.info(
            f"[search_tpl_with_version_infos] version not found on PyPI, status={status}"
        )
    elif status in (403, 429):
        result["ok"] = False
        result["message"] = "access denied or rate limit"
        logger.info(
            f"[search_tpl_with_version_infos] access denied / rate limit, status={status}"
        )
    elif 500 <= status < 600:
        result["ok"] = False
        result["message"] = "PYPI server error"
        logger.info(
            f"[search_tpl_with_version_infos] PyPI server error, status={status}"
        )
    else:
        result["ok"] = False
        result["message"] = "UNKNOWN_STATUS"
        logger.info(f"[search_tpl_with_version_infos] unknown status={status}")

    return json.dumps(result, ensure_ascii=False)


# Tools available to both environment agents.
TOOLS = [
    search_stdlib_versions,
    check_tpl_exists,
    search_tpl_infos,
    search_tpl_with_version_infos,
]


def parse_json(llm_output: str):
    """Extract the first valid JSON object from an LLM response.

    Args:
        llm_output: Raw text returned by the LLM.

    Returns:
        Parsed dictionary, or an error dictionary if no valid JSON object is
        found.
    """
    logger.info("[parse_json] start parsing LLM output")
    if not isinstance(llm_output, str):
        return {"ERROR": "LLM output is NOT valid JSON"}

    decoder = json.JSONDecoder()
    for index, character in enumerate(llm_output):
        if character != "{":
            continue
        try:
            result, _ = decoder.raw_decode(llm_output[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            logger.info("[parse_json] success")
            return result

    logger.warning("[parse_json] no valid JSON object found")
    return {"ERROR": "LLM output is NOT valid JSON"}
