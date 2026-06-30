# -*- coding: utf-8 -*-
import argparse
import logging
import os
import subprocess

LOG_DIR = "/app/results"
if not os.path.isdir(LOG_DIR):
    os.makedirs(LOG_DIR)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
formatter = logging.Formatter(
    "%(asctime)s %(levelname)s [%(filename)s:%(lineno)d] %(message)s"
)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler("/app/results/log.log", mode="a")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)


def run_command(command):
    logger.info("Run command (shell=True): %r", command)
    try:
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
        )
        stdout, stderr = process.communicate()
        return_code = process.returncode
    except Exception as e:
        logger.exception("Command failed to start or run: %r", e)
        stdout = b""
        stderr = repr(e).encode("utf-8", "replace")
        return False, stdout + b"\n" + stderr

    logger.info("Command finished %s", return_code)
    logger.info("stdout: %r", stdout)
    logger.info("stderr: %r", stderr)

    if return_code == 0:
        return True, stdout
    else:
        return False, stdout + b"\n" + stderr


def install_check():
    install_command = "cd /app/code && pip install -r requirements.txt"
    return run_command(install_command)


def run_check(command):
    return run_command("cd /app/code && " + command)


if __name__ == "__main__":
    logger.info("-----Start verify-----")
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", type=str, default="python snippet.py")
    args = parser.parse_args()
    command = args.command

    logger.info("-----Install Reqs-----")
    install_result, install_reason = install_check()
    if install_result:
        logger.info("-----Run Code-----")
        run_result, run_reason = run_check(command)
        if run_result:
            logger.info("-----End Verify-----")
            exit(0)
        else:
            logger.info("-----Verify Fail in Run-----")
            logger.error("FAILED TO RUN. Reason: %r", run_reason)
            exit(1)
    else:
        logger.info("-----Verify Fail in Install-----")
        logger.error("ENVIRONMENT INSTALLATION FAILED. Reason: %r", install_reason)
        exit(1)
