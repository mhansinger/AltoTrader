import pandas as pd
from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi
from altotrader.logging_config import setup_logging

import os
from os.path import join
import logging
from typing import Optional

setup_logging(log_filename='export_prices.logs')

# Create a logger for this module
logger = logging.getLogger(__name__)


def export_prices(path_to_parquet: str,
                  days_into_past: int = 30,
                  bucket: Optional[str] = None,
                  org: Optional[str] = None,
                  url: Optional[str] = None,
                  token: Optional[str] = None) -> bool:
    """Export latest prices from InfluxDB to parquet.
    """

    influx_config = {
        "bucket": bucket or os.getenv("INFLUXDB_INIT_BUCKET"),
        "org": org or os.getenv("INFLUXDB_INIT_ORG"),
        "url": url or os.getenv("INFLUX_URL"),
        "token": token or os.getenv("INFLUXDB_INIT_ADMIN_TOKEN")
    }

    try:

        # Initialize InfluxDB client
        client = InfluxDBClient(
            url=influx_config.get('url'), token=influx_config.get('token'), org=influx_config.get('org'))

        query_api = client.query_api()

        query = f'''
        from(bucket: "{influx_config.get('bucket')}")
        |> range(start: -{days_into_past}d)
        |> filter(fn: (r) => r["_measurement"] == "kraken") 
        |> filter(fn: (r) => r["_field"] == "price") 
        '''

        result = query_api.query(query)

        client.close()

        data = []
        for table in result:
            for record in table.records:
                data.append(record.values)

        df = pd.DataFrame(data)

        df['timestamp'] = pd.to_datetime(df['_time'])

        # Reshape DataFrame to have pairs as columns and prices as values
        df_pivot = df.pivot_table(
            index='timestamp', columns='pair', values='_value')

        filename = f"{influx_config.get('bucket')}_latest_{days_into_past}d.parquet"
        df_pivot.to_parquet(join(path_to_parquet, filename))

        return True

    except Exception as e:
        logger.error(f"Error in export process: {e}")
        return False


if __name__ == '__main__':
    export_prices(path_to_parquet='Examples', days_into_past=20)
