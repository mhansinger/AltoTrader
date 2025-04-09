from altotrader.database.update_service import TickerUpdateService
from altotrader.ticker.krakenticker import KrakenTicker


def run_update(pair_yaml: str):
    ticker = KrakenTicker(pairs_yaml=pair_yaml, log_dir='logs')
    service = TickerUpdateService(ticker)

    # Update ticker prices for c, a, b
    success = service.update_pairs_ticker()


if __name__ == '__main__':
    run_update(pair_yaml='kraken_pairs.yaml')
