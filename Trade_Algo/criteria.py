import numpy as np
import pandas as pd
from set_input import set_input

# Broker ist noch eine dummy Klasse. Sollte folgende Funktionen beinhalten:
# buy_order, sell_order

class criteria(object):
    def __init__(self, Input, Broker):
        self.time_series = Input.time_series
        self.short_mean = []
        self.long_mean = []
        self.short_win = Input.short
        self.long_win = Input.long

    def eval_rollings(self):
        self.short_mean = self.getRollingMean(self.short_win)
        self.long_mean = self.getRollingMean(self.long_win)

    def intersect(self):
        if self.short_mean > self.long_mean:
            ## das ist quasi das Kriterium, um zu checken ob wir Währung haben oder nicht,
            ## entsprechend sollten wir kaufen, oder halt nicht
            ## if Broker.asset_status == False:
                ## Broker.buy_order()
            ## elif Broker.idle()
        elif self.long_mean > self.short_mean:
            ## if Broker.asset_status == True:
                ## Broker.sell_order()
            ## elif Broker.idle()
        else
            ## idle, soll nix machen
            # Broker.idle()

    def getRollingMean(self, __window):
        try:
            if type(self.time_series) != pandas.core.series.Series:
                raise TypeError
        except TypeError:
            print('Zeitreihe muss im Format pd.Series sein!')

        __rolling_mean = self.time_series.rolling(__window).mean()
        return __rolling_mean