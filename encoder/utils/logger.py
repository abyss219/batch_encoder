import logging
from colorlog import ColoredFormatter
import os
import sys

try:
    import colorama
    colorama.just_fix_windows_console()
    HAS_COLORAMA = True
except (AttributeError, ImportError, OSError):
    HAS_COLORAMA = False

def terminal_supports_color():
    """
    Check if the current system terminal supports color output.
    Returns:
        bool: True if terminal supports color, False otherwise.
    """

    def windows_vt_codes_enabled():
        """
        Check Windows Registry for VT code support.
        """
        try:
            import winreg
        except ImportError:
            return False

        try:
            reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Console")
            value, _ = winreg.QueryValueEx(reg_key, "VirtualTerminalLevel")
            return value == 1
        except FileNotFoundError:
            return False

    is_a_tty = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    return is_a_tty and (
        sys.platform != "win32"
        or (HAS_COLORAMA and getattr(colorama, "fixed_windows_console", False))
        or "ANSICON" in os.environ
        or "WT_SESSION" in os.environ
        or os.environ.get("TERM_PROGRAM") == "vscode"
        or windows_vt_codes_enabled()
    )

# ANSI escape codes
RESET = "\033[0m"
COLOR_CODES = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}
COLOR_SUPPORT = terminal_supports_color()

def setup_logger(log_name: str, log_file: str = "logs/default.log", level=logging.INFO):
    """
    Sets up a logger with file and color-capable console output using colorlog.
    """
    logger = logging.getLogger(log_name)
    logger.setLevel(level)

    if not logger.hasHandlers():
        os.makedirs(os.path.dirname(log_file), exist_ok=True)

        # File handler (no color)
        file_format = logging.Formatter(
            "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
        )
        file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

        # Console handler (with color if supported and colorlog is available)
        console_handler = logging.StreamHandler()
        if COLOR_SUPPORT:
            console_format = ColoredFormatter(
                fmt=(
                    f"{COLOR_CODES['dim']}[%(asctime)s]{RESET} "
                    f"{COLOR_CODES['cyan']}[%(name)s]{RESET} "
                    "%(log_color)s[%(levelname)s] "
                    "%(message)s"
                ),
                log_colors={
                    'DEBUG': 'cyan',
                    'INFO': 'green',
                    'WARNING': 'yellow',
                    'ERROR': 'red',
                    'CRITICAL': 'bold_red',
                },
                secondary_log_colors={},  # Unused unless you define custom color fields
                style='%'
            )
        else:
            console_format = file_format

        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

    return logger

def color_text(text, color="cyan"):
    if COLOR_SUPPORT and color in COLOR_CODES:
        return f"{COLOR_CODES[color]}{text}{RESET}"
    return text

'''
logger.info(f"{color_text('[SUCCESS]', 'green', color_ok)} File processed.")
logger.warning(f"{color_text('Caution:', 'yellow', color_ok)} Low disk space.")
logger.debug(f"Debug info: {color_text('temp_var = 42', 'magenta', color_ok)}")
'''