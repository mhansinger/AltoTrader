import pandas as pd

class history(object):
    def __init__(self, input):
        self.input = input
        self.time_series = []
        self.series_name = input.series_name
        self.path = self.input.asset1+self.input.asset2+'_data'
        self.__file = self.path + '/' + self.series_name
        print('Time series from: '+self.__file)

    def import_history(self):

        __raw = pd.read_csv(self.__file)
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
