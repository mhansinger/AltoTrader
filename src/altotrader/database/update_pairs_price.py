import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.exceptions import InfluxDBError
import logging

from altotrader.ticker.krakenticker import KrakenTicker
from altotrader.logging_config import setup_logging

setup_logging()

# Create a logger for this module
logger = logging.getLogger(__name__)


def update_pairs_price(yaml_pairs_path: str = "Examples/kraken_pairs.yaml") -> bool:
    """Updates the InfluxDB with market prices for different crypto pairs.

    Args:
        yaml_pairs_path: Path to YAML file containing pairs configuration.

    Returns:
        bool: True if update succeeded, False otherwise.
    """
    try:
        # Validate environment variables
        required_env_vars = {
            "INFLUXDB_INIT_ADMIN_TOKEN": os.environ.get("INFLUXDB_INIT_ADMIN_TOKEN"),
            "INFLUXDB_INIT_BUCKET": os.environ.get("INFLUXDB_INIT_BUCKET"),
            "INFLUXDB_INIT_ORG": os.environ.get("INFLUXDB_INIT_ORG"),
            "INFLUX_URL": os.environ.get("INFLUX_URL")
        }

        if None in required_env_vars.values():
            missing = [k for k, v in required_env_vars.items() if v is None]
            raise ValueError(
                f"Missing environment variables: {', '.join(missing)}")

        logger.info("Fetching market prices...")
        myTicker = KrakenTicker(pairs_yaml=yaml_pairs_path)
        df = myTicker.get_market_price()

        if df.empty:
            logger.warning("No data returned from KrakenTicker")
            return False

        points = []
        for timestamp, row in df.iterrows():
            for pair, price in row.items():
                points.append(
                    Point("kraken")
                    .tag("exchange", "kraken")  # Additional tag for filtering
                    .tag("pair", pair)
                    .field("price", float(price))
                    .time(timestamp)
                )

        with InfluxDBClient(
            url=required_env_vars["INFLUX_URL"],
            token=required_env_vars["INFLUXDB_INIT_ADMIN_TOKEN"],
            timeout=30_000  # Increased timeout for bulk writes
        ) as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)

            try:
                write_api.write(
                    bucket=required_env_vars["INFLUXDB_INIT_BUCKET"],
                    org=required_env_vars["INFLUXDB_INIT_ORG"],
                    record=points
                )
                logger.info(
                    f"Wrote {len(points)} price points to InfluxDB")
                return True

            except InfluxDBError as e:
                logger.error(f"InfluxDB write failed: {str(e)}")
                if hasattr(e, 'response') and e.response:
                    logger.error(f"Response details: {e.response.text}")
                return False

    except Exception as e:
        logger.error(
            f"Unexpected error in update_pairs_price: {str(e)}", exc_info=True)
        return False


if __name__ == '__main__':
    update_pairs_price()

# def update_pairs_price(yaml_pairs_path: str = "Examples/kraken_pairs.yaml"):
#     """updates the Influx database with the market price for different crypto pairs
#     """

#     INFLUXDB_INIT_ADMIN_TOKEN = os.environ.get("INFLUXDB_INIT_ADMIN_TOKEN")
#     INFLUXDB_INIT_BUCKET = os.environ.get("INFLUXDB_INIT_BUCKET")
#     INFLUXDB_INIT_ORG = os.environ.get("INFLUXDB_INIT_ORG")
#     INFLUX_URL = os.environ.get("INFLUX_URL")

#     myTicker = KrakenTicker(pairs_yaml=yaml_pairs_path)
#     df = myTicker.get_market_price()

#     with InfluxDBClient(url=INFLUX_URL, token=INFLUXDB_INIT_ADMIN_TOKEN) as client:
#         write_api = client.write_api(SYNCHRONOUS)

#         for timestamp, row in df.iterrows():
#             for pair, price in row.items():
#                 point = Point("kraken") \
#                     .tag("pair", pair) \
#                     .field("price", float(price)) \
#                     .time(timestamp)

#                 write_api.write(bucket=INFLUXDB_INIT_BUCKET,
#                                 org=INFLUXDB_INIT_ORG, record=point)

#     print("Successfully wrote Kraken data to InfluxDB!")
