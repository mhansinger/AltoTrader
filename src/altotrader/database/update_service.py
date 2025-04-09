import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from influxdb_client.client.exceptions import InfluxDBError
import logging
from typing import Optional, Union
import pandas as pd

from altotrader.ticker.krakenticker import KrakenTicker
from altotrader.ticker.baseticker import BaseTicker
from altotrader.logging_config import setup_logging


class TickerUpdateService:
    def __init__(self, ticker: BaseTicker, log_dir: str = 'logs'):
        """Initialize with a ticker provider instance.

        Args:
            ticker_provider: An object that implements get_market_price() 
                            (e.g., KrakenTicker instance)
        """
        self.ticker = ticker
        self._ticker_entry = None

        setup_logging(log_filename='ticker_update.logs', log_dir=log_dir)

        self.logger = logging.getLogger(__name__)

    def update_pairs_ticker(self,
                            ticker_entry: Optional[str] = None,
                            bucket: Optional[str] = None,
                            org: Optional[str] = None,
                            url: Optional[str] = None,
                            token: Optional[str] = None) -> bool:
        """Updates the InfluxDB with market prices for different crypto pairs.

        Args:
            bucket: InfluxDB bucket name (falls back to INFLUXDB_INIT_BUCKET env var)
            org: InfluxDB organization (falls back to INFLUXDB_INIT_ORG env var)
            url: InfluxDB URL (falls back to INFLUX_URL env var)
            token: InfluxDB token (falls back to INFLUXDB_INIT_ADMIN_TOKEN env var)

        Returns:
            bool: True if update succeeded, False otherwise.
        """

        try:
            influx_config = {
                "bucket": bucket or os.getenv("INFLUXDB_INIT_BUCKET"),
                "org": org or os.getenv("INFLUXDB_INIT_ORG"),
                "url": url or os.getenv("INFLUX_URL"),
                "token": token or os.getenv("INFLUXDB_INIT_ADMIN_TOKEN")
            }

            # Validate configuration
            if None in influx_config.values():
                missing = [k for k, v in influx_config.items() if v is None]
                raise ValueError(
                    f"Missing configuration: {', '.join(missing)}")

            ticker_entries = [
                ticker_entry] if ticker_entry else ["a", "b", "c"]
            all_points = []

            market_query = self.ticker.get_market_query()

            for entry in ticker_entries:

                self.logger.info(
                    f"Fetching prices for ticker_entry '{entry}'...")

                df = self.ticker.get_last_ticker(
                    ticker_entry=entry, market_query=market_query)
                if df.empty:
                    self.logger.warning(
                        f"No data returned for ticker entry '{entry}'")
                    continue

                points = self._generate_points(df, entry)
                all_points.extend(points)

            if not all_points:
                self.logger.warning(
                    "No valid market data found for any ticker entry")
                return False

            # Write to InfluxDB
            return self._write_points(all_points, influx_config)

        except Exception as e:
            self.logger.error(
                f"Unexpected error in price update: {str(e)}", exc_info=True)
            return False

    def _generate_points(self, df: pd.DataFrame, ticker_entry: str) -> list:
        """Convert DataFrame to InfluxDB points."""
        points = []
        for timestamp, row in df.iterrows():
            for pair, price in row.items():
                points.append(
                    Point("kraken")
                    .tag("pair", pair)
                    .tag("ticker_entry", ticker_entry)
                    .field("price", float(price))
                    .time(timestamp)
                )
        return points

    def _write_points(self, points: list, config: dict) -> bool:
        """Write points to InfluxDB."""
        if not points:
            self.logger.warning("No points to write")
            return False

        try:
            with InfluxDBClient(
                url=config["url"],
                token=config["token"],
                timeout=30_000
            ) as client:
                write_api = client.write_api(write_options=SYNCHRONOUS)
                write_api.write(
                    bucket=config["bucket"],
                    org=config["org"],
                    record=points
                )
                self.logger.info("Write completed successfully")
                return True

        except InfluxDBError as e:
            self.logger.error(f"InfluxDB write failed: {str(e)}")
            if hasattr(e, 'response') and e.response:
                self.logger.error(f"Response details: {e.response.text}")
            return False


if __name__ == "__main__":

    ticker = KrakenTicker(pairs_yaml="Examples/kraken_pairs.yaml")
    service = TickerUpdateService(ticker)

    # Update ticker prices for c, a, b
    success = service.update_pairs_ticker()
