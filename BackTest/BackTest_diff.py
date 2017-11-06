import numpy as np
import pandas as pd
import copy


# NOCH AUSPROBIEREN!!

class BackTest_diff(object):
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

    def __init__(self, time_series, investment=1000.0, transaction_fee=0.0016):

        '''
        :param time_series: the time series
        :param avStrat: either 'SMA' for simple moving average OR: 'EWM' for exponential weighted moving average
        :param investment: initial investment
        :param transaction_fee: presumed transaction fee
        '''
        self.time_series = time_series
        self.zeros = np.zeros(len(self.time_series))
        self.shares = pd.DataFrame(self.zeros,index=self.time_series.index)

        self.trades = np.zeros(len(self.time_series.index))  # set up the trading vector, simply [-1 , 1]
        self.portfolio = []  # set up the portfolio vector
        self.costs = np.zeros(len(self.time_series))
        self.log_returns = np.zeros(len(self.time_series))
        self.grad = np.zeros(len(self.time_series))

        self.investment = investment
        self.transaction_fee = transaction_fee
        self.gain = np.zeros(len(self.time_series))
        self.window = []
        self.winMin = []
        self.winMax = []
        self.interval = []
        self.window_long = []
        self.window_short = []
        self.long_mean = []
        self.short_mean = []
        self.current_fee = []
        self.best_data = []
        self.position = False
        self.signals = pd.DataFrame(self.zeros,index=self.time_series.index, columns=['signal','positions'])
        self.portfolio = pd.DataFrame(self.zeros,index=self.time_series.index, columns=['holdings','cash','total','returns'])

        # check for data type
        try:
            self.time_series = self.time_series.reset_index(drop=True)
            if type(self.time_series) != pd.core.series.Series:
                raise TypeError
        except TypeError as err:
            print('Die Zeitreihe muss im Format: pd.core.series.Series sein.')
            print('z.B: .._series.Price')

    def getRollingMean(self, window):
        rolling_mean = self.time_series.rolling(window).mean()
        return rolling_mean

    def getExpMean(self, window):
        exp_mean = self.time_series.ewm(span=window).mean()
        return exp_mean

    def bollUp(self, series, mean, window):
        # computes upper bollinger band
        delta = series.rolling(window).std()
        return mean + delta

    def bollLow(self, series, mean, window):
        delta = series.rolling(window).std()
        return mean - delta

    def returnRollingStd(self):
        rol_std = self.time_series.rolling(self.window).std()
        return pd.DataFrame(rol_std, columns=['Rolling Std'])

    def getRollingStd(self, window, series):
        std = series.rolling(window).std()
        return std

    def returnRollingMean(self, window):
        print(window)
        rolling_mean = self.getRollingMean(window)
        rolling_df = pd.DataFrame(rolling_mean)
        return rolling_df

    def enterMarket(self, pos):
        # portfolio contains here already the investment sum
        self.shares[pos] = (self.portfolio[pos - 1]) / self.time_series[pos]
        self.portfolio[pos] = (self.shares[pos] * self.time_series[pos]) * (1.0 - self.transaction_fee)
        self.costs[pos] = self.costs[pos - 1] + (self.shares[pos] * self.time_series[
            pos]) * self.transaction_fee
        self.trades[pos] = 1
        self.position = True

    def exitMarket(self, pos):
        # self.current_fee = (self.shares[pos-1] * self.time_series[pos]) * self.transaction_fee
        self.portfolio[pos] = self.shares[pos - 1] * self.time_series[pos] * (1.0 - self.transaction_fee)
        self.shares[pos] = 0
        self.costs[pos] = self.costs[pos - 1] + (self.shares[pos] * self.time_series[
            pos]) * self.transaction_fee
        self.trades[pos] = -1  # indicates a short position in the trading history
        self.position = False  # we are out of the game

    def updatePortfolio(self, pos):
        # if we are hodling
        self.shares[pos] = self.shares[pos - 1]
        self.portfolio[pos] = self.shares[pos] * self.time_series[pos]
        self.position = True  # wir haben coins
        self.costs[pos] = self.costs[pos - 1]

    def downPortfolio(self, pos):
        # if we are short
        self.portfolio[pos] = self.portfolio[pos - 1]
        self.shares[pos] = 0
        self.position = False  # wir haben keine coins
        self.costs[pos] = self.costs[pos - 1]

    def log_return(self, pos):
        self.log_returns[pos] = np.log(self.time_series[pos] / self.time_series[pos - 1])

    def Hodl(self):
        ''' checkt Portfolioentwicklung bei reinem Buy and Hold '''
        initialShares = self.investment / self.time_series[0]
        finalPortfolio = initialShares * self.time_series[-1:]
        return float(finalPortfolio)

    def computeGrad(self, pos):
        # to compute 6th order gradient
        self.grad[pos] = (6 * self.short_mean[pos] - 3 * self.short_mean[pos - 1] - 2 * self.short_mean[pos - 2] -
                          self.short_mean[pos - 3]) / 12
        # self.grad[pos] = (self.short_mean[pos] -  self.short_mean[pos - 1])

    def SMA_crossOver(self):
        # computes the portfolio according to simple moving average, uses only ShortMean()
        self.long_mean = self.getRollingMean(self.window_long)
        self.short_mean = self.getRollingMean(self.window_short)

        # Create signals
        self.signals['signal']=pd.DataFrame(self.zeros)
        self.signals['signal'][self.window_short:] = \
            np.where(self.short_mean[self.window_short:] > self.long_mean[self.window_short:], 1.0, 0.0)
        # Generate trading orders
        self.signals['positions'] = self.signals['signal'].diff()

        # bollinger bands:
        bollUp = self.bollUp(self.time_series, self.long_mean, 3 * self.window_long)

        self.shares = 100 * self.signals['signal']

        self.portfolio = self.shares.multiply(self.time_series, axis=0)
        pos_diff = self.shares.diff()

        # Add `holdings` to portfolio
        self.portfolio['holdings'] = (self.shares.multiply(self.time_series, axis=0)).sum(axis=1)

        # Add `cash` to portfolio
        self.portfolio['cash'] = self.investment - (pos_diff.multiply(self.time_series, axis=0)).sum(axis=1).cumsum()

        # Add `total` to portfolio
        self.portfolio['total'] = self.portfolio['cash'] + self.portfolio['holdings']

        # Add `returns` to portfolio
        self.portfolio['returns'] = self.portfolio['total'].pct_change()


    def optimizeSMA(self, window_long_min, window_long_max, long_interval, window_short_min=1,
                    window_short_max=1, short_interval=1):
        '''should optimize the window for the best SMA'''

        bestWindow_long = 0
        bestWindow_short = 0

        ## Initialize
        tmp_portfolio_old = pd.DataFrame(index=self.time_series).fillna(0.0)
        best_portfolio = pd.DataFrame
        best_trades = []
        best_shares = []
        best_returns = []

        # iterate over the two window lengths
        for i in range(window_long_min, window_long_max, long_interval):
            # assign long window
            self.window_long = i

            for j in range(window_short_min, window_short_max, short_interval):
                # assign short window
                self.window_short = j

                print("window short: ", j)
                print("window long: ", i)

                ## ******************
                self.SMA_crossOver()
                ## ******************
                new_portfolio = copy.deepcopy(self.portfolio)

                print("new portfolio: ", new_portfolio['total'].iloc[-1])

                if tmp_portfolio_old.iloc[-1] < new_portfolio['total'].iloc[-1]:
                    # if tmp_shares_old[-1] < new_shares[-1]:

                    best_portfolio = copy.deepcopy(new_portfolio['total'])
                    bestWindow_long = i
                    bestWindow_short = j

                    tmp_portfolio_old = copy.deepcopy(best_portfolio)

                    best_returns = copy.deepcopy(self.log_returns)
                    filename = ('best_portfolio_' + str(i) + '_' + str(j) + '.csv')

                print("best portfolio:", best_portfolio[-1])
                print(" ")

        output = pd.DataFrame(best_portfolio, columns=['best_portfolio'])
        output['best_returns'] = pd.DataFrame(best_returns)
        output['best_portfolio'] = pd.DataFrame(best_portfolio)

        pd.DataFrame.to_csv(pd.DataFrame(output), filename)
        self.best_data = output

        if self.Hodl() > best_portfolio[-1]:
            print('\nHodln wäre besser gewesen:\n')
            print('Portfolio mit Strategie: ', best_portfolio.iloc[-1], ' basierend auf einem Investment von: ',
                  self.investment)
            print('\n Nur Hodln: ', self.Hodl())

        return self.best_data, bestWindow_long, bestWindow_short


    def plotStrategy(self, shortwin, longwin, trigger=1):
        '''
        :param type: either 'SMA' or 'MACD'
        :param shortwin:
        :param longwin:
        :param trigger:
        :return:
        '''
        import matplotlib.pyplot as plt

        plt.figure(1)
        plt.subplot(211)
        plt.plot(self.time_series, linewidth=2.0)

        plt.plot(self.getRollingMean(shortwin), linewidth=1.5)
        plt.plot(self.getRollingMean(longwin), linewidth=1.5)
        plt.plot(self.bollUp(self.time_series, self.getRollingMean(longwin), 2 * longwin), linewidth=1.5)
        plt.plot(self.bollLow(self.time_series, self.getRollingMean(longwin), 2 * longwin), linewidth=1.5)

        plt.legend(['Time series', 'short window', 'long window', 'Bollinger Up', 'Bollinger Low'])

        plt.subplot(212)
        plt.plot(self.best_data.best_portfolio, linewidth=1.5)
        plt.legend(['Portfolio'])
        plt.title('Time Series')

        plt.show(block=False)



    def qqplot(self):
        import scipy.stats as stats
        import pylab
        stats.probplot(self.best_data.best_returns, dist="norm", plot=pylab)
        pylab.show()

    def boxPlot(self):
        import matplotlib.pyplot as plt
        plt.boxplot(abs(self.best_data.best_returns))
        plt.show()

    def HodlPlot(self):
        initialShares = self.investment / self.time_series[0]
        buyHoldseries = initialShares * self.time_series

        plt.figure(3)
        plt.plot(buyHoldseries)
        plt.title('Buy and Hodln')

        plt.show()
