# Object container for all input relevant data
import pandas as pd

class set_input():
    ''' 
        Input data-object
        to be continued ...
        @author: mhansinger
    '''
    def __init__(self, asset='XETH', long=48000, short=5000, fee=0.0016, reinvest=1.0, investment=1000.0):

        self.window_long = long
        self.window_short = short
        self.fee = fee
        self.reinvest = reinvest
        self.asset = asset
        self.time_series = []
        self.investment = investment
        self.series_name = []

        if self.asset == 'XETH':
            self.series_name = 'ETH_Series.csv'
            #self.time_series = self.__import_series(series_name)

        elif self.asset == 'XBTC':
            self.series_name = 'BTC_Series.csv'
            # etc.

   # def __import_series(self,__name):
    #    __raw = pd.read_csv(__name)
    #    __series = pd.Series(__raw['Time stamp','Price'])
    #    return __series

