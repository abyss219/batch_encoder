import logging
from colorlog import ColoredFormatter
import os
import sys
from typing import Optional, Union
from pathlib import Path
import re

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
BOLD = "\033[1m"
DIM = "\033[2m"
COLOR_CODES = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "reset": RESET,
}
COLOR_SUPPORT = terminal_supports_color()
COLOR_END_MARKER = "[[COLOR_END]]"
COLOR_BEGIN_MARKER = "[[COLOR_BEGIN]]"
COLOR_RE = re.compile(r"(\033\[\d{1,2}m|\[\[COLOR_BEGIN\]\]|\[\[COLOR_END\]\])")


class ClearColorFormatter(logging.Formatter):

    def format(self, record):
        msg = super().format(record)
        clean_message = COLOR_RE.sub("", msg)
        return clean_message


class SmartColorFormatter(ColoredFormatter):

    def format(self, record):
        msg = super().format(record)
        return self._process_color_stack(msg)

    def _process_color_stack(self, msg: str) -> str:

        color_stack = []
        output = ""

        tokens = COLOR_RE.split(msg)
        n = len(tokens)
        i = 0

        color = RESET
        dim = False
        bold = False

        for i in range(n):
            token = tokens[i]
            if not token:
                continue

            elif token.startswith("\033["):
                if token == DIM:
                    dim = True
                elif token == BOLD:
                    bold = True
                elif token == RESET:
                    color, dim, bold = RESET, False, False
                else:
                    color = token
                output += token
            elif token == COLOR_BEGIN_MARKER:
                color_stack.append((color, dim, bold))
            elif token == COLOR_END_MARKER:
                color, dim, bold = color_stack.pop()
                style = RESET + color + (DIM if dim else "") + (BOLD if bold else "")
                output += style

            else:
                output += token

        return output


def setup_logger(
    log_name: str, log_file: Optional[Union[str, Path]] = "logs/default.log", level=logging.INFO
):
    """
    Sets up a logger with file and color-capable console output using colorlog.
    """
    

    logger = logging.getLogger(log_name)
    logger.setLevel(level)

    if not logger.hasHandlers():

        if log_file:
            log_file = Path(log_file)
            log_file.parent.mkdir(parents=True, exist_ok=True)

            # File handler (no color)
            file_format = ClearColorFormatter(
                "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
            )
            file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            file_handler.setFormatter(file_format)
            file_handler.setLevel(logging.INFO)
            logger.addHandler(file_handler)

        # Console handler (with color if supported and colorlog is available)
        console_handler = logging.StreamHandler()
        if COLOR_SUPPORT:
            console_format = SmartColorFormatter(
                fmt=(
                    f"{DIM}[%(asctime)s]{RESET} "
                    f"{COLOR_CODES['cyan']}[%(name)s]{RESET} "
                    "%(log_color)s[%(levelname)s] "
                    "%(message)s"
                ),
                log_colors={
                    "DEBUG": "cyan",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                },
                secondary_log_colors={},  # Unused unless you define custom color fields
                style="%",
            )
        else:
            console_format = file_format

        console_handler.setFormatter(console_format)
        console_handler.setLevel(logging.DEBUG)
        logger.addHandler(console_handler)

    return logger


def color_text(text: str, color: str = None, bold: bool = False, dim: bool = False):
    """
    Wrap a string with optional color and style using ANSI escape codes.

    Args:
        text (str): The text to style.
        color (str, optional): One of the supported color names. Defaults to None.
        bold (bool, optional): Apply bold style. Defaults to False.
        dim (bool, optional): Apply dim style. Defaults to False.

    Returns:
        str: Styled text with embedded ANSI escape codes if supported, else original text.

    Supported color names:
        - red
        - green
        - yellow
        - blue
        - magenta
        - cyan
        - reset (resets to default terminal color)
    """
    if not isinstance(text, str):
        text = str(text)
    if color is None and not bold and not dim:
        return text

    style = ""
    if COLOR_SUPPORT and color in COLOR_CODES:
        style = RESET + (COLOR_CODES[color] if color != "reset" else "")

    if bold:
        style += BOLD
    if dim:
        style += DIM

    return f"{COLOR_BEGIN_MARKER}{style}{text}{COLOR_END_MARKER}"
