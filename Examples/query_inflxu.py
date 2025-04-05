import pandas as pd
from influxdb_client import InfluxDBClient
from influxdb_client.client.query_api import QueryApi
import os

INFLUXDB_INIT_ADMIN_TOKEN = os.environ.get("INFLUXDB_INIT_ADMIN_TOKEN")
INFLUXDB_INIT_BUCKET = os.environ.get("INFLUXDB_INIT_BUCKET")
INFLUXDB_INIT_ORG = os.environ.get("INFLUXDB_INIT_ORG")
INFLUX_URL = os.environ.get("INFLUX_URL")

# Initialize InfluxDB client
client = InfluxDBClient(
    url=INFLUX_URL, token=INFLUXDB_INIT_ADMIN_TOKEN, org=INFLUXDB_INIT_ORG)

# Create a QueryApi object
query_api = client.query_api()

query = f'''
from(bucket: "{INFLUXDB_INIT_BUCKET}")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_measurement"] == "kraken") 
  |> filter(fn: (r) => r["_field"] == "price") 
'''

# Run the query
result = query_api.query(query)

# Convert the query result to a Pandas DataFrame
data = []
for table in result:
    for record in table.records:
        data.append(record.values)

# Convert the list of records to a DataFrame
df = pd.DataFrame(data)

# Convert the "time" column to pandas datetime
df['timestamp'] = pd.to_datetime(df['_time'])

# Reshape DataFrame to have pairs as columns and prices as values
df_pivot = df.pivot_table(index='timestamp', columns='pair', values='_value')

# Show the DataFrame
print(df_pivot)

# Close the client connection
client.close()
