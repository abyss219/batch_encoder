import logging
import os

def setup_logger(log_name: str, log_file: str="logs/default.log", level=logging.INFO):
    """
    Sets up a logger with a file handler and a console handler.

    :param log_name: Name of the logger.
    :param log_file: Path to the log file.
    :param level: Logging level (e.g., logging.INFO, logging.DEBUG).
    :return: Configured logger instance.
    """
    logger = logging.getLogger(log_name)
    logger.setLevel(level)

    # Prevent duplicate handlers if function is called multiple times
    if not logger.hasHandlers():
        # Create log directory if it doesn't exist
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        log_format = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

        # File handler (writes logs to a file)
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setFormatter(log_format)

        # Console handler (outputs logs to the console)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(log_format)

        # Add handlers to logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
