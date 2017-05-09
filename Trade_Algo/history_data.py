import pandas as pd

class history(object):
    def __init__(self, input):
        self.input = input
        self.time_series = []
        self.path = self.input.asset1+self.input.asset2+'_data'
        print('Time series from: '+self.path)

    def import_history(self):

        __raw = pd.read_csv(self.path)
        self.time_series = pd.Series(__raw['Price'])

    def getRollingMean(self, __window):

        self.import_history()

        try:
            if type(self.time_series) != pd.core.series.Series:
                raise TypeError
        except TypeError:
            print('Zeitreihe muss im Format pd.Series sein!')

        __rolling_mean = self.time_series.rolling(__window).mean()
        return __rolling_mean
