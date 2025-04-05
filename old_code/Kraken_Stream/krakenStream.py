
import pandas as pd
import numpy as np
import krakenex
import time
import os

class krakenStream(object):
    def __init__(self, asset1,asset2):
        '''
        Object streamt über krakenex.API die aktuellen Marktpreise
        :param asset1: 'XETH'
        :param asset2: 'XXBT'
        '''

        self.__asset1 = asset1
        self.__asset2 = asset2
        self.__k = krakenex.API()
        self.__pair = asset1 + asset2
        self.__columns = ['Time','Price']
        self.__history = pd.DataFrame([np.zeros(len(self.__columns))], columns=self.__columns)

        print(self.__asset1)
        print(self.__asset2)

        try:
            # checks if the series.csv is already existing, if so it reads it in
            if (os.path.exists(self.__pair + '_Series.csv')):
                df_old = pd.read_csv(self.__pair + '_Series.csv')
                df_old = df_old.drop('Unnamed: 0', 1)
                self.__history = df_old
            else:
                self.__history = pd.DataFrame([np.zeros(len(self.__columns))], columns=self.__columns)
        except:
            print('sometihngs wrong wiht your time series...')

    def market_price(self):
        market = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['c']
        return float(market[0])

    def updateHist(self):
        __thisPrice = self.market_price()
        __time = time.strftime("%m.%d.%y_%H:%M:%S", time.localtime())
        temp = [[__time, __thisPrice]]
        temp_df = pd.DataFrame(temp, columns=self.__columns)
        self.__history = self.__history.append(temp_df)
        print(temp_df)
        #time.sleep(59)
        #self.iterations += 1

    def writeHist(self):
        pd.DataFrame.to_csv(self.__history, self.__pair + '_Series.csv')







