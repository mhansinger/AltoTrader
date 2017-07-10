import pandas as pd
import numpy as np
import krakenex
import time
import os
import threading
from datetime import datetime

current_time = time.strftime("%m.%d.%y_%H:%M", time.localtime())

class krakenStream(threading.Thread):
    def __init__(self, asset1,asset2,interval):
        threading.Thread.__init__(self)
        self.iterations = 0
        self.iterations2 = 0
        self.daemon = True  # OK for main to exit even if instance is still running
        self.paused = True  # start out paused
        self.state = threading.Condition()

        self.__asset1 = asset1
        self.__asset2 = asset2
        self.__k = krakenex.API()
        self.__pair = asset1 + asset2
        self.__columns = ['Time','Price']
        self.__history = pd.DataFrame([np.zeros(len(self.__columns))], columns=self.__columns)

        self.__interval = interval  # zB alle 10 min = 600

    def market_price(self):
        __market = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['c']
        return float(__market[0])

    def updateHist(self):
        self.resume()  # unpause self
        while True:
            with self.state:
                if self.paused:
                    self.state.wait() # block until notified
            __thisPrice = self.market_price()
            __time = time.strftime("%m.%d.%y_%H:%M:%S", time.localtime())
            temp = [[__time,__thisPrice]]
            temp_df = pd.DataFrame(temp, columns=self.__columns)
            self.__history = self.__history.append(temp_df)
            print(temp_df)
            time.sleep(59)
            self.iterations += 1

    def writeHist(self):
        self.resume()  # unpause self
        while True:
            if self.paused:
                self.state.wait()  # block until notified
            pd.DataFrame.to_csv(self.__history, self.__pair + '_Series.csv')
            time.sleep(self.__interval)
            self.iterations2 += 1

    def resume(self):
        with self.state:
            self.paused = False
            self.state.notify()  # unblock self if waiting

    def pause(self):
        with self.state:
            self.paused = True  # make self block and wait
        print('Stream is currently paused!')

