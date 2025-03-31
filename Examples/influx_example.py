import influxdb_client
import os
import time
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

TOKEN = os.environ.get("INFLUXDB_TOKEN")
PORT = os.environ.get("INFLUX_PORT")
org = "altotrader"
url = f"http://localhost:{PORT}"

print(TOKEN)

client = influxdb_client.InfluxDBClient(url=url, token=TOKEN, org=org)

bucket = "test_pair"

# write
write_api = client.write_api(write_options=SYNCHRONOUS)

for value in range(5):
    point = (
        Point("measurement1")
        .tag("tagname1", "tagvalue1")
        .field("field1", value)
    )
    write_api.write(bucket=bucket, org="altotrader", record=point)
    time.sleep(1)  # separate points by 1 second

# query
query_api = client.query_api()

query = """from(bucket: "test_pair")
 |> range(start: -10m)
 |> filter(fn: (r) => r._measurement == "measurement1")"""
tables = query_api.query(query, org="altotrader")

for table in tables:
    for record in table.records:
        print(record)
