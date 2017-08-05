
import pandas as pd
import numpy as np
import krakenex
import time

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

    def market_price(self):
        __market = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['c']
        return float(__market[0])

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





