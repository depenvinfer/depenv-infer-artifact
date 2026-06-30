"""File and result storage helpers."""

import json
import os
import shutil
from typing import Union

from loguru import logger


def save_text(filename: str, content: Union[str, bytes]) -> None:
    """Save text or byte content to a UTF-8 file.

    Args:
        filename: Destination file path.
        content: Content to save.

    Returns:
        None.
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    with open(filename, "w", encoding="utf-8") as file:
        file.write(str(content))
    logger.info(f"[memory] saved={filename}")


def save_to_json(data_dict: dict, filename: str) -> None:
    """Save a dictionary to a JSON file.

    Args:
        data_dict: Dictionary to serialize.
        filename: Destination JSON file path.

    Returns:
        None.
    """
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    with open(filename, "w", encoding="utf-8") as file:
        json.dump(data_dict, file, indent=4, ensure_ascii=False)
    logger.info(f"[memory] saved={filename}")


def json_to_requirements(
    json_content: dict,
    requirements_file_path: str,
) -> None:
    """Save a dependency dictionary as a requirements file.

    Args:
        json_content: Mapping from package names to optional versions.
        requirements_file_path: Destination requirements file path.

    Returns:
        None.
    """
    os.makedirs(os.path.dirname(requirements_file_path), exist_ok=True)
    with open(requirements_file_path, "w", encoding="utf-8") as file:
        for package_name, version in json_content.items():
            if version:
                file.write(f"{package_name}=={version}\n")
            else:
                file.write(f"{package_name}\n")
    logger.info(f"[memory] saved={requirements_file_path}")


def copy_file(src: str, dst: str) -> None:
    """Copy a file to a destination path.

    Args:
        src: Source file path.
        dst: Destination file path.

    Returns:
        None.
    """
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    shutil.copyfile(src, dst)
    logger.info(f"[memory] copied={src} -> {dst}")
