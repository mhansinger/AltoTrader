import numpy as np
import pandas as pd
from set_input import set_input

# Broker ist noch eine dummy Klasse. Sollte folgende Funktionen beinhalten:
# buy_order, sell_order

'''
NEEDS DEBUGGING!!

'''

import pandas as pd

class criteria(object):
    def __init__(self, Input, broker, history):
        self.time_series = []
        self.short_mean = []
        self.long_mean = []
        self.short_win = Input.window_short     # sollte noch dynamische werden
        self.long_win = Input.window_long
        self.Broker = broker
        self.series_name = Input.series_name
        self.history = history
        self.__last_short = []
        self.__last_long = []

    def eval_rollings(self):
        self.short_mean = self.history.getRollingMean(self.short_win)
        self.long_mean = self.history.getRollingMean(self.long_win)

        self.__last_short = np.array(self.short_mean)[-1]
        self.__last_long = np.array(self.long_mean)[-1]

    def intersect(self):

        # call the evaluation
        self.eval_rollings()

        if self.__last_short > self.__last_long:
            ## das ist quasi das Kriterium, um zu checken ob wir Währung haben oder nicht,
            ## entsprechend sollten wir kaufen, oder halt nicht
            if self.Broker.asset_status is False and self.Broker.broker_status is False:
                self.Broker.buy_order()
                print('buy')
                print('long mean: ', self.__last_long)
                print('short mean: ', self.__last_short)
            else:
                self.Broker.idle()
                print('buy idle')
                print('long mean: ', self.__last_long)
                print('short mean: ', self.__last_short)

        elif self.__last_long > self.__last_short:
            if self.Broker.asset_status is True and self.Broker.broker_status is False:
                self.Broker.sell_order()
                print('sell')
                print('long mean: ', self.__last_long)
                print('short mean: ', self.__last_short)
            else:
                self.Broker.idle()
                print('sell idle')
                print('long mean: ', self.__last_long)
                print('short mean: ', self.__last_short)
        else:
            ## idle, soll nix machen
            self.Broker.idle()
            print('idle')
            print('long mean: ', self.__last_long)
            print('short mean: ', self.__last_short)
