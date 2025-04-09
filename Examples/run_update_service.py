from altotrader.database.update_service import TickerUpdateService
from altotrader.ticker.krakenticker import KrakenTicker


def run_update():
    ticker = KrakenTicker(pairs_yaml="Examples/kraken_pairs.yaml")
    service = TickerUpdateService(ticker)

    # Update ticker prices for c, a, b
    success = service.update_pairs_ticker()


if __name__ == '__main__':
    run_update()
