import numpy as np
import pandas as pd
import copy


#

class strategySMA(object):
    '''
        This is a simple Backtesting strategy based on Rolling Mean
        Funtcions to use:
            getRollingMean(): returns panda DF of the short mean
            optimize_SMA(min_window,max_window,interval): returns best_portfolio, best_trades, best_gain, best_shares, best_window
                        needs as input: maximum window, minimum window, interval

         Whole margin is reinvested. Zero Risk Aversion and Maximum Gain!

         IMPORTANT: time_series has to be pandas.Series !

        @author: mhansinger
    '''

    def __init__(self, investment=1000.0, transaction_fee=0.0016,time_series=None):

        self.__time_series = time_series
        self.__shares = [] #np.zeros(len(self.__time_series))

        self.__trades = [] #np.zeros(len(self.__time_series))  # set up the trading vector, simply [-1 , 1]
        self.__portfolio = []  # set up the portfolio vector

        self.__investment = investment
        self.__transaction_fee = transaction_fee
        self.__gain = [] #np.zeros(len(self.__time_series))
        self.__window = []
        self.__winMin = []
        self.__winMax = []
        self.__interval = []
        self.__window_long = []
        self.__window_short = []
        self.__long_mean = []
        self.__short_mean = []
        self.__current_fee = []
        self.best_data = []
        self.__position = False

    def __getRollingMean(self, __window):
        __rolling_mean = self.__time_series.rolling(__window).mean()
        return __rolling_mean

    def setTimeSeries(self,series):
        self.__time_series = series
        # check for data type
        try:
            self.__time_series = self.__time_series.reset_index(drop=True)
            if type(self.__time_series) != pd.core.series.Series:
                raise TypeError
        except TypeError as err:
            print('Die Zeitreihe muss im Format: pd.core.series.Series sein.')
            print('z.B: .._series.Price')

        self.__shares = np.zeros(len(self.__time_series))
        self.__gain = np.zeros(len(self.__time_series))
        self.__trades = np.zeros(len(self.__time_series))

    def __enterMarket(self, pos):
        # portfolio contains here already the investment sum
        # self.__current_fee = self.__portfolio[pos-1] * self.__transaction_fee
        self.__shares[pos] = (self.__portfolio[pos - 1]) / self.__time_series[pos]
        self.__portfolio[pos] = (self.__shares[pos] * self.__time_series[pos]) * (1.0 - self.__transaction_fee)
        self.__costs[pos] = self.__costs[pos - 1] + (self.__shares[pos] * self.__time_series[
            pos]) * self.__transaction_fee
        self.__trades[pos] = 1
        self.__position = True

    def __exitMarket(self, pos):
        # self.__current_fee = (self.__shares[pos-1] * self.__time_series[pos]) * self.__transaction_fee
        self.__portfolio[pos] = self.__shares[pos - 1] * self.__time_series[pos] * (1.0 - self.__transaction_fee)
        self.__shares[pos] = 0
        self.__costs[pos] = self.__costs[pos - 1] + (self.__shares[pos] * self.__time_series[
            pos]) * self.__transaction_fee
        self.__trades[pos] = -1  # indicates a short position in the trading history
        self.__position = False  # we are out of the game

    def __updatePortfolio(self, pos):
        self.__shares[pos] = self.__shares[pos - 1]
        self.__portfolio[pos] = self.__shares[pos] * self.__time_series[pos]
        self.__position = True  # wir haben coins
        self.__costs[pos] = self.__costs[pos - 1]

    def __downPortfolio(self, pos):
        self.__portfolio[pos] = self.__portfolio[pos - 1]
        self.__shares[pos] = 0
        self.__position = False  # wir haben keine coins
        self.__costs[pos] = self.__costs[pos - 1]


    def SMA_crossOver(self):
        # computes the portfolio according to simple moving average, uses only ShortMean()

        self.__long_mean = self.__getRollingMean(self.__window_long)
        self.__short_mean = self.__getRollingMean(self.__window_short)

        self.__position = False

        self.__portfolio = []
        self.__portfolio = np.ones(len(self.__time_series)) * self.__investment
        self.__costs = np.zeros(len(self.__time_series))
        self.__shares = np.zeros(len(self.__time_series))

        for i in range((self.__window_long + 1),
                       len(self.__time_series)):  ## hier muss noch was rein, um von beliebigem index zu starten
            # print(i, self.__trades[i])

            if self.__short_mean[i] > self.__long_mean[i]:
                if self.__position == False:
                    # our position is short and we want to buy
                    self.__enterMarket(i)
                else:  # self.__position == True:
                    # we hold a position and don't want to sell: portfolio is increasing
                    self.__updatePortfolio(i)

            elif self.__short_mean[i] <= self.__long_mean[i]:
                if self.__position == True:
                    # we should get out of the market and sell:
                    self.__exitMarket(i)
                else:
                    self.__downPortfolio(i)

            if self.__portfolio[i] < 0.0:
                print('Skip loop, negative portfolio')
                break

        #print("nach SMA: ", self.__portfolio[-1])

    def optimizeSMA(self, window_long_min, window_long_max, long_interval, window_short_min=1,
                              window_short_max=1, short_interval=1):
        '''should optimize the window for the best SMA'''

        __window_long_min = window_long_min
        __window_long_max = window_long_max
        __long_interval = long_interval
        __window_short_min = window_short_min
        __window_short_max = window_short_max
        __short_interval = short_interval

        __bestWindow_long = 0
        __bestWindow_short = 0

        ## Initialize
        __tmp_portfolio_old = np.array([0, 0])

        __best_portfolio = np.array([0, 0])

        # iterate over the two window lengths
        for i in range(__window_long_min, __window_long_max, __long_interval):
            # assign long window
            self.__window_long = i

            for j in range(__window_short_min, __window_short_max, __short_interval):
                # assign short window
                self.__window_short = j

                #print("window short: ", j)
                #print("window long: ", i)

                ## ******************
                self.SMA_crossOver()
                ## ******************
                __new_portfolio = copy.deepcopy(self.__portfolio)

                #print("new_portfolio last: ", __new_portfolio[-1])

                if __tmp_portfolio_old[-1] < __new_portfolio[-1]:
                    # if __tmp_shares_old[-1] < __new_shares[-1]:
                    __best_portfolio = copy.deepcopy(__new_portfolio)
                    __bestWindow_long = i
                    __bestWindow_short = j
                    __tmp_portfolio_old = copy.deepcopy(__best_portfolio)

        return __best_portfolio[-1] , __bestWindow_long, __bestWindow_short

