import pandas as pd

class history(object):
    def __init__(self, input):
        self.input = input
        self.time_series = []
        self.series_name = self.input.series_name
        self.path = self.input.asset1+self.input.asset2+'_data/'+self.series_name #self.input.asset1+self.input.asset2+'_Series.csv'

        print('Time series from: '+self.path)

    def import_history(self):
        # liest die Zeitreihe ein, z.B. XETH_   Series.csv mit einer column: Price
        raw = pd.read_csv(self.path)
        self.time_series = pd.Series(raw['Price'])

    # computes the SMA
    def getRollingMean(self, __window):
        # berechnet den Rolling mean

        # muss je Zeitschritt immer wieder neu eingelesen werde, da ständig upgedated
        self.import_history()

        try:
            if type(self.time_series) != pd.core.series.Series:
                raise TypeError
        except TypeError:
            print('Zeitreihe muss im Format pd.Series sein!')

        rolling_mean = self.time_series.rolling(__window).mean()
        return rolling_mean

    # upper Bollinger Band
    def getBollUp(self, window):
        # muss je Zeitschritt immer wieder neu eingelesen werde, da ständig upgedated
        self.import_history()
        delta = self.time_series.rolling(window).std()
        sma = self.time_series.rolling(window).mean()
        boll = sma+delta
        return float(boll.values[-1])

    # for MACD
    def getMACD(self,__fast,__slow):

        # muss je Zeitschritt immer wieder neu eingelesen werde, da ständig upgedated
        self.import_history()

        try:
            if type(self.time_series) != pd.core.series.Series:
                raise TypeError
        except TypeError:
            print('Zeitreihe muss im Format pd.Series sein!')

        FAST = self.time_series.ewm(span=__fast).mean()
        SLOW = self.time_series.ewm(span=__slow).mean()

        MACD = FAST - SLOW

        # type should be pandas.Series!
        return MACD

