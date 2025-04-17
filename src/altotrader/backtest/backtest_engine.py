import pandas as pd

from altotrader.backtest.dataloader import DataLoader


class BacktestEngine:
    def __init__(self, dataloader: DataLoader, backtest_config: dict):
        self.dataloader = dataloader
        self.maker_fee = backtest_config.get('maker_fee')
        self.taker_fee = backtest_config.get('taker_fee')
        self.initial_invest = backtest_config.get('initial_invest')
        self.trading_currency = backtest_config.get("trading_currency")
        self.base_currency = backtest_config.get("base_currency")
        self.pair = self.trading_currency+self.base_currency

        self.market_data_view = pd.DataFrame()

        # load crypto ticker data
        self.dataloader.load_csv_export()

        self._set_market_data_df()

    def _set_market_data_df(self):
        self.market_data_view[self.pair] = self.dataloader.ticker_current[self.pair]
        self.market_data_view[self.pair +
                              '_ask'] = self.dataloader.ticker_ask[self.pair]
        self.market_data_view[self.pair +
                              '_bid'] = self.dataloader.ticker_bid[self.pair]

        self.market_data_view[self.base_currency] = self.initial_invest
        self.market_data_view[self.trading_currency] = 0
        self.market_data_view["market_position"] = None
        self.market_data_view["action"] = None

        # TODO add columns for long and short rolling means


if __name__ == '__main__':
    loader_dict = {'export_path': "Examples/ticker_export",
                   "latest_days": 20, "logs_dir": 'logs'}
    testloader = DataLoader(loader_dict)

    backtest_config = {
        "maker_fee": 0.0025,
        "taker_fee": 0.004,
        "initial_invest": 1000,
        "base_currency": "ZEUR",
        "trading_currency": "XXBT"
    }

    backtest = BacktestEngine(testloader, backtest_config)
