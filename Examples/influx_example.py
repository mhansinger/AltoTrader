import influxdb_client
import os
import time
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from altotrader.ticker.krakenticker import KrakenTicker

INFLUXDB_INIT_ADMIN_TOKEN = os.environ.get("INFLUXDB_INIT_ADMIN_TOKEN")
INFLUXDB_INIT_BUCKET = os.environ.get("INFLUXDB_INIT_BUCKET")
INFLUXDB_INIT_ORG = os.environ.get("INFLUXDB_INIT_ORG")
INFLUX_URL = os.environ.get("INFLUX_URL")

# get sample data
myTicker = KrakenTicker(pairs_yaml="Examples/kraken_pairs.yaml")
df = myTicker.get_market_price()

with InfluxDBClient(url=INFLUX_URL, token=INFLUXDB_INIT_ADMIN_TOKEN) as client:
    write_api = client.write_api(SYNCHRONOUS)

    for timestamp, row in df.iterrows():
        for pair, price in row.items():
            point = Point("kraken") \
                .tag("pair", pair) \
                .field("price", float(price)) \
                .time(timestamp)

            write_api.write(bucket=INFLUXDB_INIT_BUCKET,
                            org=INFLUXDB_INIT_ORG, record=point)

print("Successfully wrote Kraken data to InfluxDB!")
