import logging


def setup_logging():
    logging.basicConfig(
        # Set the minimum level to capture (DEBUG is the lowest)
        level=logging.DEBUG,
        # Log format
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            # Log to a file named package_name.log
            logging.FileHandler("package_name.log"),
            logging.StreamHandler()  # Log to the console
        ]
    )
