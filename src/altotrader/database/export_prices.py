import pandas as pd
import time
from influxdb_client import InfluxDBClient
from influxdb_client.client.exceptions import InfluxDBError
from altotrader.logging_config import setup_logging

import os
from os.path import join
import logging
from typing import Optional

setup_logging(log_filename='export_prices.logs')
logger = logging.getLogger(__name__)

_MAX_RETRIES = 4
_RETRY_BASE_DELAY = 2  # seconds (doubles each attempt: 2, 4, 8, 16)


def export_prices(path_to_parquet: str,
                  days_into_past: int = 30,
                  file_format: str = 'parquet',
                  bucket: Optional[str] = None,
                  org: Optional[str] = None,
                  url: Optional[str] = None,
                  token: Optional[str] = None,
                  measurement: Optional[str] = None) -> bool:
    """Export latest prices from InfluxDB to parquet or csv.

    Retries each ticker entry up to _MAX_RETRIES times with exponential backoff
    on transient InfluxDB or network errors.

    Args:
        measurement: InfluxDB measurement name to filter on (e.g. ``"kraken"``
                     or ``"binance"``). Defaults to ``"kraken"`` for backward
                     compatibility.
    """

    influx_config = {
        "bucket":      bucket      or os.getenv("INFLUXDB_INIT_BUCKET"),
        "org":         org         or os.getenv("INFLUXDB_INIT_ORG"),
        "url":         url         or os.getenv("INFLUX_URL"),
        "token":       token       or os.getenv("INFLUXDB_INIT_ADMIN_TOKEN"),
        "measurement": measurement or "kraken",
    }

    missing = [k for k, v in influx_config.items() if not v]
    if missing:
        logger.error(f"Missing InfluxDB configuration: {', '.join(missing)}")
        return False

    ticker_entries = ['a', 'b', 'c', 'v']  # ask, bid, current, volume

    for ticker in ticker_entries:
        df_pivot = _query_with_retry(ticker, days_into_past, influx_config)
        if df_pivot is None:
            return False

        filename = (
            f"{influx_config['bucket']}_latest_{days_into_past}d_{ticker}.{file_format}"
        )
        filepath = join(path_to_parquet, filename)
        try:
            if file_format == 'csv':
                df_pivot.to_csv(filepath)
            elif file_format == 'parquet':
                df_pivot.to_parquet(filepath)
            else:
                logger.error(f"Unknown file format: {file_format!r}")
                return False
            logger.info(f"Exported {ticker!r} → {filepath}")
        except Exception as e:
            logger.error(f"Failed to write {filepath}: {e}")
            return False

    return True


def _query_with_retry(ticker: str, days_into_past: int, influx_config: dict):
    """Query InfluxDB for a single ticker entry with exponential-backoff retry.

    Returns a pivoted DataFrame on success, or None after all retries fail.
    """
    delay = _RETRY_BASE_DELAY
    query = f'''
        from(bucket: "{influx_config['bucket']}")
        |> range(start: -{days_into_past}d)
        |> filter(fn: (r) => r["_measurement"] == "{influx_config['measurement']}")
        |> filter(fn: (r) => r["_field"] == "price")
        |> filter(fn: (r) => r["ticker_entry"] == "{ticker}")
    '''

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            with InfluxDBClient(
                url=influx_config['url'],
                token=influx_config['token'],
                org=influx_config['org'],
                timeout=30_000,
            ) as client:
                result = client.query_api().query(query)

            data = [record.values for table in result for record in table.records]
            if not data:
                logger.warning(f"No data returned for ticker_entry={ticker!r}")
                return pd.DataFrame()

            df = pd.DataFrame(data)
            df['timestamp'] = pd.to_datetime(df['_time']).dt.floor('s')
            return df.pivot_table(
                index=['timestamp', 'ticker_entry'],
                columns='pair',
                values='_value',
            )

        except (InfluxDBError, Exception) as e:
            if attempt < _MAX_RETRIES:
                logger.warning(
                    f"Export query failed for ticker={ticker!r} "
                    f"(attempt {attempt}/{_MAX_RETRIES}): {e}. "
                    f"Retrying in {delay}s..."
                )
                time.sleep(delay)
                delay *= 2
            else:
                logger.error(
                    f"Export query failed for ticker={ticker!r} "
                    f"after {_MAX_RETRIES} attempts: {e}"
                )
                return None


if __name__ == '__main__':
    export_prices(path_to_parquet='Examples/ticker_export',
                  days_into_past=20, file_format='csv')
