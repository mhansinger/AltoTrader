# Object container for all input relevant data
import pandas as pd

class set_input():
    ''' 
        Input data-object
        to be continued ...
        @author: mhansinger
    '''
    def __init__(self, asset1='XETH', asset2='ZEUR',long=4800, short=500, fee=0.0016, reinvest=1.0, investment=1000.0):

        self.window_long = long
        self.window_short = short
        self.fee = fee
        self.reinvest = reinvest
        self.asset1 = asset1
        self.asset2 = asset2
        self.time_series = []
        self.investment = investment
        #self.series_name = []

        #if self.asset1 == 'XETH':
        self.series_name = self.asset1+self.asset2+'_Series.csv'
            #self.time_series = self.__import_series(series_name)

