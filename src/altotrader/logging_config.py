import logging
import logging.handlers
import os


def setup_logging(log_filename: str = "altotrader.logs", log_dir: str = "logs"):
    if logging.getLogger().handlers:
        return  # already configured – avoid duplicate handlers

    os.makedirs(log_dir, exist_ok=True)
    log_filepath = os.path.join(log_dir, log_filename)

    handler_file = logging.handlers.RotatingFileHandler(
        log_filepath,
        maxBytes=10 * 1024 * 1024,  # 10 MB per file
        backupCount=5,
        mode="a",
    )
    handler_console = logging.StreamHandler()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[handler_file, handler_console],
    )
