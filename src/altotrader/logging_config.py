import logging
import os


def setup_logging(log_filename: str = "altotrader.logs", log_dir: str = "logs"):

    os.makedirs(log_dir, exist_ok=True)
    log_filepath = os.path.join(log_dir, log_filename)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_filepath, mode="a"),  # Append logs to file
            logging.StreamHandler(),  # Also log to console
        ],
    )

    # logging.info("Logging initialized.")
