import logging
from colorlog import ColoredFormatter

# Set up the format with colors and brackets
log_format = ColoredFormatter(
    fmt="%(log_color)s[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    log_colors={
        'DEBUG':    'cyan',
        'INFO':     'green',
        'WARNING':  'yellow',
        'ERROR':    'red',
        'CRITICAL': 'bold_red',
    }
)

# Create logger
logger = logging.getLogger("MyApp")
logger.setLevel(logging.DEBUG)

# Create console handler and set formatter
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)

# Add the handler to the logger
logger.addHandler(console_handler)

# Sample logs
logger.debug("Debug message for troubleshooting.")
logger.info("Informational message.")
logger.warning("This is a warning.")
logger.error("An error occurred!")
logger.critical("Critical issue!")
