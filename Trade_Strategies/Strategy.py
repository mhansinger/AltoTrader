import sys
import os
import numpy as np
import pandas as pd
import csv
import time
import matplotlib.pyplot as plt

class set_input():
    ''' 
        Input data-object
        to be continued ...
        @author: mhansinger
    '''
    def __init__(self,series_name='ETH_series.csv', long=1000, short=100, fee=0.0026):
        self.series_name = series_name
        self.window_long = long
        self.window_short = short
        self.fee = fee

class Strategy_base(object):
    ''' 
        Base class for the different trading stratgies
        should not be used directly.
        @author: mhansinger
    '''

    def __init__(self, Input):
        self.series_name = Input.series_name
        self.window_long = Input.window_long
        self.window_short = Input.window_short
        self.fee = Input.fee

        self.series = []
        self.__long_mean = []
        self.__short_mean = []
        self.__long_std = []
        self.__short_std = []

    def __read_series(self):
        # this reads in the data series, which should be updated by different routine...
        # make sure file names are consistent
        self.series = pd.read_csv(self.series_name)

        # Make 'Time Stamp' to index!
        try:
            self.series = self.series.set_index('Time stamp')
        except: KeyError
        print('Zeitreihe hat bereits ein Label Time Stamp')

    def __getRolling(self):

        # read in the updated series every time
        self.__read_series()

        self.__long_mean = self.series.rolling(self.window_long).mean()
        self.__short_mean = self.series.rolling(self.window_short).mean()

        self.__long_std = self.series.rolling(self.window_long).std()
        self.__short_std = self.series.rolling(self.window_short).std()

    def plotData(self):
        # helper member function to plot
        self.__getRolling()

        plt.plot(self.series)
        plt.plot(self.__long_mean)
        plt.plot(self.__short_mean)
        plt.title('Original series, long and short means')
        plt.show()

    def writeData(self):
        __output_df = 
