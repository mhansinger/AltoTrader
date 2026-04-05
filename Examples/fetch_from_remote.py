"""Fetch ticker data from a remote (e.g. Hetzner) InfluxDB instance and save
it locally as CSV files, ready for the DataLoader / backtesting pipeline.

Usage
-----
Set the connection details either via environment variables or by editing the
constants below, then run:

    python Examples/fetch_from_remote.py

Or pass the Hetzner IP directly:

    INFLUX_URL=http://<hetzner-ip>:8086 python Examples/fetch_from_remote.py

The exported CSV files land in Examples/ticker_export/ and follow the naming
convention expected by DataLoader:

    krakenticker_latest_<N>d_a.csv   (ask)
    krakenticker_latest_<N>d_b.csv   (bid)
    krakenticker_latest_<N>d_c.csv   (current/close)
"""

import os
import sys
import argparse
import logging

# Allow running from project root without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from altotrader.database.export_prices import export_prices
from altotrader.logging_config import setup_logging

# ── Defaults (override via env vars or CLI flags) ────────────────────────────
DEFAULT_OUTPUT_DIR = "Examples/ticker_export"
DEFAULT_DAYS = 20
DEFAULT_FORMAT = "csv"      # "csv" or "parquet"
# ─────────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Export ticker data from a remote InfluxDB to local files."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("INFLUX_URL", "http://localhost:8086"),
        help="InfluxDB URL, e.g. http://<hetzner-ip>:8086  (env: INFLUX_URL)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("INFLUXDB_INIT_ADMIN_TOKEN"),
        help="InfluxDB admin token  (env: INFLUXDB_INIT_ADMIN_TOKEN)",
    )
    parser.add_argument(
        "--org",
        default=os.getenv("INFLUXDB_INIT_ORG"),
        help="InfluxDB organisation  (env: INFLUXDB_INIT_ORG)",
    )
    parser.add_argument(
        "--bucket",
        default=os.getenv("INFLUXDB_INIT_BUCKET"),
        help="InfluxDB bucket  (env: INFLUXDB_INIT_BUCKET)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"How many days of history to fetch (default: {DEFAULT_DAYS})",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "parquet"],
        default=DEFAULT_FORMAT,
        help=f"Output file format (default: {DEFAULT_FORMAT})",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write files into (default: {DEFAULT_OUTPUT_DIR})",
    )
    args = parser.parse_args()

    setup_logging(log_filename="fetch_from_remote.logs", log_dir="logs")
    logger = logging.getLogger(__name__)

    # Validate required parameters
    missing = [name for name, val in [
        ("--token / INFLUXDB_INIT_ADMIN_TOKEN", args.token),
        ("--org   / INFLUXDB_INIT_ORG",         args.org),
        ("--bucket / INFLUXDB_INIT_BUCKET",      args.bucket),
    ] if not val]
    if missing:
        parser.error(
            "Missing required parameters:\n  " + "\n  ".join(missing) +
            "\n\nSet them via environment variables or CLI flags."
        )

    os.makedirs(args.output_dir, exist_ok=True)

    logger.info(
        f"Fetching last {args.days} days from {args.url} "
        f"(bucket={args.bucket}, org={args.org}) → {args.output_dir}/"
    )

    success = export_prices(
        path_to_parquet=args.output_dir,
        days_into_past=args.days,
        file_format=args.format,
        bucket=args.bucket,
        org=args.org,
        url=args.url,
        token=args.token,
    )

    if success:
        logger.info("Export completed successfully.")
        print(f"\nFiles written to: {args.output_dir}/")
    else:
        logger.error("Export failed – check logs for details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
