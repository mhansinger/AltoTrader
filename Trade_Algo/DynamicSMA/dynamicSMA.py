#import numpy as np
#import pandas as pd
#import time

class dynamicSMA(object):
    ''' 
       dynamic backtesting engine to update the moving average windows
        @author: mhansinger
    '''
    def __init__(self, Strategy, asset1=None, asset2=None):

        self.window_long = 0
        self.window_short = 0

        self.Strategy = Strategy

        self.asset1 = asset1
        self.asset2 = asset2
        self.time_series = pd.DataFrame
        self.raw = pd.DataFrame
        self.pair = self.asset1+self.asset2
        self.series_name = self.asset1+self.asset2+'_Series.csv'
        self.path = '../'+self.asset1 + self.asset2 + '_data/' + self.series_name  # self.input.asset1+self.input.asset2+'_Series.csv'

        print('Time series from: ' + self.path)

        self.SMAhistory = pd.DataFrame
        self.SMAhistory.columns=['Time','short','long','Portfolio']

    def runSMA(self):
        self.import_history()

        self.Strategy.setTimeSeries(self.time_series)
        __portfolio, self.window_long, self.window_short = self.Strategy.optimze(700,1200,30,200,600,20)
        __time = self.getTime()
        __update_vec = [[__time,self.window_short,self.window_long,__portfolio]]
        __update_df = pd.DataFrame(__update_vec,columns =self.SMAhistory.columns)
        print(__update_df)
        self.SMAhistory.append(__update_df)

        self.writeCSV(self.SMAhistory)

    ###########################################


    def import_history(self):
        # liest die Zeitreihe ein, z.B. XETH_Series.csv mit einer column: Price
        __path = self.path
        __raw = pd.read_csv(__path,index_col=0)
        #if datapoints > 0:
        #    datapoints = -1*datapoints
        #self.time_series = pd.Series(raw['V2'])
        #self.time_series = self.time_series[datapoints:-1]
        #self.time_series=self.time_series.reset_index()
        return __raw

    def writeCSV(self,__df):
        __filename = self.pair+'_SMA_history.csv'
        pd.DataFrame.to_csv(__df,__filename)

    def getTime(self):
        #return int(time.time())
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
