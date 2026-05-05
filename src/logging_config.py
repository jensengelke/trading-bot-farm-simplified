import logging
import os
import sys

def setup_logging(logger_name, log_dir, level=logging.DEBUG):
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    # Clear existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()

    # Prevent logs from propagating to the root logger
    logger.propagate = False

    os.makedirs(log_dir, exist_ok=True)

    # Regular log file for INFO and higher
    log_file = os.path.join(log_dir, f"{logger_name}.log")
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Trace log file for DEBUG
    trace_log_file = os.path.join(log_dir, f"{logger_name}-trace.log")
    trace_file_handler = logging.FileHandler(trace_log_file, mode='a')
    trace_file_handler.setLevel(logging.DEBUG)
    trace_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    trace_file_handler.setFormatter(trace_formatter)
    logger.addHandler(trace_file_handler)

    return logger
