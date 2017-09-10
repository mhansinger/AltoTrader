import numpy as np
import pandas as pd
import copy


#

class dynamicSMA(object):
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

    def __init__(self, asset1='XETH', asset2='XXBT', path='../' ,length=14400, investment=1000.0, transaction_fee=0.0016):

        '''
        :param time_series: the time series
        :param avStrat: either 'SMA' for simple moving average OR: 'EWM' for exponential weighted moving average
        :param investment: initial investment
        :param transaction_fee: presumed transaction fee 
        '''

        self.__portfolio = []  # set up the portfolio vector
        self.__investment = investment
        self.__transaction_fee = transaction_fee

        self.__window = []
        self.__winMin = []
        self.__winMax = []
        self.__interval = []
        self.__window_long = 1000
        self.__window_short = 470
        self.__long_mean = []
        self.__short_mean = []
        self.__current_fee = []

        self.__position = False
        self.pair = asset1+asset2
        self.__time_series = pd.DataFrame
        self.__shares = []
        self.length = length
        self.path = path
        self.__bollingerFactor = 2

    def updateSeries(self):
        # updated die Zeitreihe
        try:
            raw = pd.read_csv(self.path+self.pair+'_Series.csv')
            self.__time_series = pd.Series(raw['Price'])
        except:
            print('Problem with time series data type ...')

        length_series = len(self.__time_series)
        if length_series > self.length:
            # kürzt die Zeitreihe
            self.__time_series = self.__time_series[-length_series:-1]

        self.__shares = np.zeros(len(self.__time_series))


    def getRollingMean(self, __window):
        __rolling_mean = self.__time_series.rolling(__window).mean()
        return __rolling_mean

    def __getExpMean(self, __window):
        __exp_mean = self.__time_series.ewm(span=__window).mean()
        return __exp_mean

    def __bollUp(self, series, mean, window):
        delta = series.rolling(window).std()
        return mean + delta

    def __bollLow(self, series, mean, window):
        delta = series.rolling(window).std()
        return mean - delta

    def returnRollingStd(self):
        __rol_std = self.__time_series.rolling(self.__window).std()
        return pd.DataFrame(__rol_std, columns=['Rolling Std'])

    def getRollingStd(self, window, series):
        __std = series.rolling(window).std()
        return __std

    def returnRollingMean(self, window):
        print(window)
        __rolling_mean = self.getRollingMean(window)
        __rolling_df = pd.DataFrame(__rolling_mean)
        return __rolling_df

    def __enterMarket(self, pos):
        # portfolio contains here already the investment sum
        self.__shares[pos] = (self.__portfolio[pos - 1]) / self.__time_series[pos]
        self.__portfolio[pos] = (self.__shares[pos] * self.__time_series[pos]) * (1.0 - self.__transaction_fee)
        #self.__costs[pos] = self.__costs[pos - 1] + (self.__shares[pos] * self.__time_series[pos]) * self.__transaction_fee
        self.__position = True

    def __exitMarket(self, pos):
        # self.__current_fee = (self.__shares[pos-1] * self.__time_series[pos]) * self.__transaction_fee
        self.__portfolio[pos] = self.__shares[pos - 1] * self.__time_series[pos] * (1.0 - self.__transaction_fee)
        self.__shares[pos] = 0
        #self.__costs[pos] = self.__costs[pos - 1] + (self.__shares[pos] * self.__time_series[
            #pos]) * self.__transaction_fee
        self.__position = False  # we are out of the game

    def __updatePortfolio(self, pos):
        # if we are hodling
        self.__shares[pos] = self.__shares[pos - 1]
        self.__portfolio[pos] = self.__shares[pos] * self.__time_series[pos]
        self.__position = True  # wir haben coins
        #self.__costs[pos] = self.__costs[pos - 1]

    def __downPortfolio(self, pos):
        # if we are short
        self.__portfolio[pos] = self.__portfolio[pos - 1]
        self.__shares[pos] = 0
        self.__position = False  # wir haben keine coins
        #self.__costs[pos] = self.__costs[pos - 1]

    #def __log_return(self, pos):
    #    self.__log_returns[pos] = np.log(self.__time_series[pos] / self.__time_series[pos - 1])

    def Hodl(self):
        ''' checkt Portfolioentwicklung bei reinem Buy and Hold '''
        __initialShares = self.__investment / self.__time_series[0]
        __finalPortfolio = __initialShares * self.__time_series[-1:]
        return float(__finalPortfolio)

    def SMA_crossOver(self):
        # computes the portfolio according to simple moving average, uses only ShortMean()

        self.__long_mean = self.getRollingMean(self.__window_long)
        self.__short_mean = self.getRollingMean(self.__window_short)

        # bollinger bands:
        bollUp = self.__bollUp(self.__time_series, self.__long_mean, int(self.__bollingerFactor)*self.__window_long)

        self.__position = False
        self.__portfolio = np.ones(len(self.__time_series)) * self.__investment

        # emergency exit flag
        emergencyExit = False
        lastBuy = 0

        for i in range((self.__window_long + 1), len(self.__time_series)):  ## hier muss noch was rein, um von beliebigem index zu starten
            # print(i, self.__trades[i])

            if self.__short_mean[i] > self.__long_mean[i]:
                if self.__position is False and emergencyExit is False and self.__time_series[i] > bollUp[i]:
                    # our position is short and we want to buy
                    self.__enterMarket(i)
                    lastBuy = self.__time_series[i]
                elif lastBuy * 0.975 > self.__time_series[i] and self.__position is True:
                    # print('Emergency Exit')
                    self.__exitMarket(i)
                    emergencyExit = True  # Notfall exit, stop loss
                elif self.__position is False:  # and emergencyExit:   # zusätzlich benötigt für Notfall exit
                    self.__downPortfolio(i)
                elif self.__position is True:
                    # we hold a position and don't want to sell: portfolio is increasing
                    self.__updatePortfolio(i)

            else:  # self.__short_mean[i] <= self.__long_mean[i]:
                emergencyExit = False  # Reset emergency Exit for further trading
                if self.__position is True:
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

        __bestWindow_long = 0
        __bestWindow_short = 0

        # update the time series each time the optimizer is called!
        self.updateSeries()

        ## Initialize
        __tmp_portfolio_old = np.array([0, 0])
        __best_portfolio = np.array([0, 0])

        # iterate over the two window lengths
        for i in range(window_long_min, window_long_max, long_interval):
            # assign long window
            self.__window_long = i

            for j in range(window_short_min, window_short_max, short_interval):
                # assign short window
                self.__window_short = j

                #print("window short: ", j)
                #print("window long: ", i)

                ## ******************
                self.SMA_crossOver()
                ## ******************
                __new_portfolio = copy.deepcopy(self.__portfolio)
                __new_shares = copy.deepcopy(self.__shares)

                #print("new portfolio: ", __new_portfolio[-1])
                #print(" ")

                if __tmp_portfolio_old[-1] < __new_portfolio[-1]:

                    __best_portfolio = copy.deepcopy(__new_portfolio)
                    __bestWindow_long = i
                    __bestWindow_short = j

                    __tmp_portfolio_old = copy.deepcopy(__best_portfolio)

                #print("best portfolio:", __best_portfolio[-1])
                #print(" ")

        print("best long Window: ", __bestWindow_long)
        print("best short Window: ", __bestWindow_short)
        print("best Portfolio: ", __best_portfolio[-1])
        #print("Only Hodl: ", )
        # write the data
        file1 = open(self.pair+"_longWin.txt",'w')
        file1.write(str(__bestWindow_short))
        file1.close()
        file2 = open(self.pair + "_shortWin.txt",'w')
        file2.write(str(__bestWindow_long))
        file2.close()


    def setBollingerFac(self,boll):
        self.__bollingerFactor = boll

    def getBollinger(self):
        return self.__bollingerFactor



