# Object container for all input relevant data
import pandas as pd

class set_input():
    ''' 
        Input data-object
        to be continued ...
        @author: mhansinger
    '''
    def __init__(self, asset='ETH', long=47000, short=2500, fee=0.0026, reinvest=1.0):

        self.window_long = long
        self.window_short = short
        self.fee = fee
        self.reinvest = reinvest
        self.asset = asset
        self.time_series = []

        if self.asset == 'ETH':
            series_name = 'ETH_series.csv'
            self.time_series = self.__import_series(series_name)

        elif self.asset == 'BTC':
            series_name = 'BTC_series.csv'
            # etc.

    def __import_series(self,__name):
        __raw = pd.read_csv(__name)
        __series = pd.Series(__raw['Price'])
        return __series

