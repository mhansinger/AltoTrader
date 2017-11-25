import numpy as np
import pandas as pd
import copy
import matplotlib.pyplot as plt
#

class reinvestBackTest(object):

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

    def __init__(self, time_series, avStrat='SMA',investment=1000.0, transaction_fee=0.0016):

        '''
        :param time_series: the time series
        :param avStrat: either 'SMA' for simple moving average OR: 'EWM' for exponential weighted moving average
        :param investment: initial investment
        :param transaction_fee: presumed transaction fee 
        '''
        self.__time_series = time_series
        self.__shares = np.zeros(len(self.__time_series))

        self.__trades = np.zeros(len(self.__time_series))    # set up the trading vector, simply [-1 , 1]
        self.__portfolio = []                                 # set up the portfolio vector
        self.__costs = np.zeros(len(self.__time_series))
        self.__log_returns = np.zeros(len(self.__time_series))
        self.grad =  np.zeros(len(self.__time_series))

        self.__investment = investment
        self.__transaction_fee = transaction_fee
        self.__gain = np.zeros(len(self.__time_series))
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
        self.__avStrat= avStrat


        # check for data type
        try:
            self.__time_series = self.__time_series.reset_index(drop=True)
            if type(self.__time_series)!= pd.core.series.Series:
                raise TypeError
        except TypeError as err:
            print('Die Zeitreihe muss im Format: pd.core.series.Series sein.')
            print('z.B: .._series.Price')

    def getRollingMean(self,__window):
        __rolling_mean = self.__time_series.rolling(__window).mean()
        return __rolling_mean

    def __getExpMean(self,__window):
        __exp_mean = self.__time_series.ewm(span=__window).mean()
        return __exp_mean

    def __bollUp(self,series,mean,window):
        # computes upper bollinger band
        delta=series.rolling(window).std()
        return mean+delta

    def __bollLow(self,series,mean,window):
        delta=series.rolling(window).std()
        return mean-delta

    def returnRollingStd(self):
        __rol_std = self.__time_series.rolling(self.__window).std()
        return pd.DataFrame(__rol_std, columns=['Rolling Std'])

    def getRollingStd(self,window,series):
        __std = series.rolling(window).std()
        return __std

    def returnRollingMean(self, window):
        print(window)
        __rolling_mean = self.getRollingMean(window)
        __rolling_df = pd.DataFrame(__rolling_mean)
        return __rolling_df

    def __enterMarket(self, pos):
        # portfolio contains here already the investment sum
        self.__shares[pos] = (self.__portfolio[pos-1] ) / self.__time_series[pos]
        self.__portfolio[pos] = (self.__shares[pos] * self.__time_series[pos]) * (1.0 - self.__transaction_fee)
        self.__costs[pos] = self.__costs[pos-1] + (self.__shares[pos] * self.__time_series[pos]) * self.__transaction_fee
        self.__trades[pos] = 1
        self.__position = True

    def __exitMarket(self, pos):
       # self.__current_fee = (self.__shares[pos-1] * self.__time_series[pos]) * self.__transaction_fee
        self.__portfolio[pos] = self.__shares[pos-1] * self.__time_series[pos] * (1.0 - self.__transaction_fee)
        self.__shares[pos] = 0
        self.__costs[pos] = self.__costs[pos-1] + (self.__shares[pos] * self.__time_series[pos]) * self.__transaction_fee
        self.__trades[pos] = -1  # indicates a short position in the trading history
        self.__position = False      # we are out of the game

    def __updatePortfolio(self, pos):
        # if we are hodling
        self.__shares[pos] = self.__shares[pos - 1]
        self.__portfolio[pos] = self.__shares[pos]* self.__time_series[pos]
        self.__position = True   # wir haben coins
        self.__costs[pos] = self.__costs[pos - 1]

    def __downPortfolio(self, pos):
        # if we are short
        self.__portfolio[pos] = self.__portfolio[pos - 1]
        self.__shares[pos] = 0
        self.__position = False  # wir haben keine coins
        self.__costs[pos] = self.__costs[pos - 1]

    def __log_return(self,pos):
        self.__log_returns[pos] = np.log(self.__time_series[pos]/self.__time_series[pos-1])

    def Hodl(self):
        ''' checkt Portfolioentwicklung bei reinem Buy and Hold '''
        __initialShares = self.__investment/self.__time_series[0]
        __finalPortfolio = __initialShares * self.__time_series[-1:]
        return float(__finalPortfolio)

    def computeGrad(self, pos):
        # to compute 6th order gradient
        self.grad[pos] = (6 * self.__short_mean[pos] - 3 *self.__short_mean[pos-1] - 2*self.__short_mean[pos-2] - self.__short_mean[pos-3] ) / 12
        #self.grad[pos] = (self.__short_mean[pos] -  self.__short_mean[pos - 1])

    def SMA_crossOver(self):
        # computes the portfolio according to simple moving average, uses only ShortMean()

        # select between averaging strategy:
        if self.__avStrat=='SMA':
            self.__long_mean = self.getRollingMean(self.__window_long)
            self.__short_mean = self.getRollingMean(self.__window_short)

        elif self.__avStrat=='EWM':
            self.__long_mean = self.__getExpMean(self.__window_long)
            self.__short_mean = self.__getExpMean(self.__window_short)

        # bollinger bands:
        bollUp = self.__bollUp(self.__time_series, self.__long_mean, 3 * self.__window_long)

        self.__position = False

        self.__portfolio = []
        self.__portfolio = np.ones(len(self.__time_series))*self.__investment
        self.__costs = np.zeros(len(self.__time_series))
        self.__shares = np.zeros(len(self.__time_series))

        # emergency exit flag
        emergencyExit = False
        lastBuy = 0

        for i in range((self.__window_long+1), len(self.__time_series)):        ## hier muss noch was rein, um von beliebigem index zu starten
           # print(i, self.__trades[i])

            # compute log returns and gradients
            self.__log_return(i)
            #self.computeGrad(i)

            if self.__short_mean[i] > self.__long_mean[i]:
               if self.__position is False and emergencyExit is False and self.__time_series[i] > bollUp[i] and self.__time_series[i]>self.__short_mean[i]:
                   # our position is short and we want to buy
                   self.__enterMarket(i)
                   lastBuy=self.__time_series[i]
               elif lastBuy*0.975 > self.__time_series[i] and self.__position is True:
                   #print('Emergency Exit')
                   self.__exitMarket(i)
                   emergencyExit=True         # Notfall exit, stop loss
               elif self.__position is False: # and emergencyExit:   # zusätzlich benötigt für Notfall exit
                   self.__downPortfolio(i)
               elif self.__position is True:
                   # we hold a position and don't want to sell: portfolio is increasing
                   self.__updatePortfolio(i)

            else: #self.__short_mean[i] <= self.__long_mean[i]:
                emergencyExit=False         # Reset emergency Exit for further trading
                if self.__position is True:
                   # we should get out of the market and sell:
                   self.__exitMarket(i)
                else:
                   self.__downPortfolio(i)

            if self.__portfolio[i] < 0.0:
                print('Skip loop, negative portfolio')
                break


        print("nach SMA: ", self.__portfolio[-1])

    #########################
    # NEW MACD strategy
    #########################

    def MACD_crossover(self,fast,slow,trigger):
        # computes the MACD and singal line

        MACD = self.__getExpMean(fast) - self.__getExpMean(slow)
        signal = MACD.ewm(span=trigger).mean()

        # Flag if we are long or short
        self.__position = False

        self.__portfolio = []
        self.__portfolio = np.ones(len(self.__time_series))*self.__investment
        self.__costs = np.zeros(len(self.__time_series))
        self.__shares = np.zeros(len(self.__time_series))

        for i in range(1, len(self.__time_series)):

            # compute log returns
            self.__log_return(i)

            # falsch herum implementiert
            if MACD[i] < signal[i]:
                if self.__position == True:
                    # we hold a position and don't want to sell: portfolio is increasing
                    self.__updatePortfolio(i)
                else:
                    # our position is short and we want to buy
                    self.__enterMarket(i)

            elif MACD[i] >= signal[i]:
                if self.__position == True:
                    # we should get out of the market and sell:
                    self.__exitMarket(i)

                else:
                    self.__downPortfolio(i)

            if self.__portfolio[i] < 0.0:
               print('Skip loop, negative portfolio')
               break

        print("portfolio mit MACD: ", self.__portfolio[-1])


    def optimizeSMA(self, window_long_min, window_long_max, long_interval, window_short_min=1,
                    window_short_max=1, short_interval=1):
        '''should optimize the window for the best SMA'''

        __bestWindow_long = 0
        __bestWindow_short = 0

        ## Initialize
        __tmp_portfolio_old = np.array([0, 0])
        __best_portfolio = np.array([0, 0])
        __best_trades = []
        __best_shares = []
        __best_returns = []

        # store all returns in a matrix to visualize
        __axis_long = np.linspace(window_long_min,window_long_max,long_interval)
        __axis_short = np.linspace(window_short_min,window_short_max,short_interval)
        __return_mesh = np.zeros([len(__axis_short),len(__axis_long)])
        __i_count = 0

        # iterate over the two window lengths
        for i in range(window_long_min, window_long_max, long_interval):
            # assign long window
            self.__window_long = i

            __j_count = 0
            for j in range(window_short_min, window_short_max, short_interval):
                # assign short window
                self.__window_short = j

                print("window short: ", j)
                print("window long: ", i)

                ## ******************
                self.SMA_crossOver()
                ## ******************
                __new_portfolio = copy.deepcopy(self.__portfolio)
                __new_shares = copy.deepcopy(self.__shares)

                print("new portfolio: ", __new_portfolio[-1])

                #store best last portfolio value!
                __return_mesh[__i_count,__j_count] = __new_portfolio[-1]
                print('Return Mesh: ', __return_mesh[__i_count,__j_count])
                print('__i:', __i_count)
                print('__j:',__j_count)
                __j_count+=1

                if __tmp_portfolio_old[-1] < __new_portfolio[-1]:
                    # if __tmp_shares_old[-1] < __new_shares[-1]:
                    __best_trades = copy.deepcopy(self.__trades)
                    __best_portfolio = copy.deepcopy(__new_portfolio)
                    __bestWindow_long = i
                    __bestWindow_short = j
                    __best_shares = __new_shares  # copy.deepcopy(self.__shares)
                    __best_cost = copy.deepcopy(self.__costs)
                    __tmp_portfolio_old = copy.deepcopy(__best_portfolio)
                    __tmp_shares_old = copy.deepcopy(__best_shares)
                    __best_returns = copy.deepcopy(self.__log_returns)
                    filename = ('best_portfolio_' + str(i) + '_' + str(j) + '.csv')

                print("best portfolio:", __best_portfolio[-1])
                print(" ")

            __i_count+=1

        __output = pd.DataFrame(__best_portfolio, columns=['best_portfolio'])
        __output['best_shares'] = pd.DataFrame(__best_shares)
        __output['best_trades'] = pd.DataFrame(__best_trades)
        __output['best_costs'] = pd.DataFrame(__best_cost)
        __output['best_returns'] = pd.DataFrame(__best_returns)
        __output['best_portfolio'] = pd.DataFrame(__best_portfolio)

        pd.DataFrame.to_csv(pd.DataFrame(__output), filename)
        self.best_data = __output

        # plot return array
        self.returnMatrix(__axis_long, __axis_short, __return_mesh)

        if self.Hodl() > __best_portfolio[-1]:
            print('\nHodln wäre besser gewesen:\n')
            print('Portfolio mit Strategie: ',__best_portfolio[-1],' basierend auf einem Investment von: ',self.__investment)
            print('\n Nur Hodln: ', self.Hodl())

        return self.best_data, __bestWindow_long, __bestWindow_short

    # Optimize MACD!
    def optimizeMACD(self, fast_win, fast_win2, slow_win, slow_win2, trigger_win, trigger_win2, increment1, increment2):
        '''should optimize the window for the best SMA'''

        ## Initialize
        __tmp_portfolio_old = np.array([0, 0])
        __best_portfolio = np.array([0, 0])
        __best_trades = []
        __best_shares = []
        __best_returns = []

        # loop over the slow
        for i in range(slow_win, slow_win2, increment1):
            # assign long window
            self.__window_long = i
            # loop over the fast
            for j in range(fast_win, fast_win2, increment1):

                # loop over the trigger
                for k in range(trigger_win, trigger_win2, increment2):
                    self.__window_short = j

                    print("slow: ", i)
                    print("fast: ", j)
                    print('signal: ', k)

                    ## ******************
                    self.MACD_crossover(j,i,k)
                    ## ******************
                    __new_portfolio = copy.deepcopy(self.__portfolio)
                    __new_shares = copy.deepcopy(self.__shares)

                    print("new portfolio: ", __new_portfolio[-1])

                    if __tmp_portfolio_old[-1] < __new_portfolio[-1]:
                        # if __tmp_shares_old[-1] < __new_shares[-1]:
                        __best_trades = copy.deepcopy(self.__trades)
                        __best_portfolio = copy.deepcopy(__new_portfolio)
                        __bestfast = j
                        __bestslow = i
                        __best_trigger = k
                        __best_shares = __new_shares  # copy.deepcopy(self.__shares)
                        __best_cost = copy.deepcopy(self.__costs)
                        __tmp_portfolio_old = copy.deepcopy(__best_portfolio)
                        __best_returns = copy.deepcopy(self.__log_returns)
                        filename = ('best_portfolio_' + str(i) + '_' + str(j) + '.csv')

                    print("best portfolio:", __best_portfolio[-1])
                    print(" ")

        __output = pd.DataFrame(__best_portfolio, columns=['best_portfolio'])
        __output['best_shares'] = pd.DataFrame(__best_shares)
        __output['best_trades'] = pd.DataFrame(__best_trades)
        __output['best_costs'] = pd.DataFrame(__best_cost)
        __output['best_returns'] = pd.DataFrame(__best_returns)
        __output['best_portfolio'] = pd.DataFrame(__best_portfolio)

        pd.DataFrame.to_csv(pd.DataFrame(__output), filename)
        self.best_data = __output

        if self.Hodl() > __best_portfolio[-1]:
            print('\nHodln wäre besser gewesen:\n')
            print('Portfolio mit Strategie: ',__best_portfolio[-1],' basierend auf einem Investment von: ',self.__investment)
            print('\n Nur Hodln: ', self.Hodl())

        return self.best_data, __bestfast, __bestslow, __best_trigger

    def plotStrategy(self,strat,shortwin,longwin,trigger=1):
        '''
        :param type: either 'SMA' or 'MACD'
        :param shortwin: 
        :param longwin: 
        :param trigger: 
        :return: 
        '''
        import matplotlib.pyplot as plt

        if strat=='SMA':
            plt.figure(1)
            plt.subplot(211)
            plt.plot(self.__time_series, linewidth=2.0)

            plt.plot(self.getRollingMean(shortwin), linewidth=1.5)
            plt.plot(self.getRollingMean(longwin), linewidth=1.5)
            plt.plot(self.__bollUp(self.__time_series,self.getRollingMean(longwin),2*longwin), linewidth=1.5)
            plt.plot(self.__bollLow(self.__time_series, self.getRollingMean(longwin), 2*longwin), linewidth=1.5)

            plt.legend(['Time series', 'short window', 'long window','Bollinger Up','Bollinger Low'])

            plt.subplot(212)
            plt.plot(self.best_data.best_portfolio, linewidth=1.5)
            plt.legend(['Portfolio'])
            plt.title('Time Series')

            plt.figure(2)
            plt.subplot(211)
            plt.plot(self.best_data.best_shares, linewidth=1.0)
            plt.legend(['Shares'])
            plt.subplot(212)
            plt.plot(self.best_data.best_returns, linewidth=1.0)
            plt.legend(['log returns'])

            plt.show()

        elif strat=='MACD':
            MACD = self.__getExpMean(shortwin) - self.__getExpMean(longwin)
            signal = MACD.ewm(span=trigger).mean()

            plt.figure(1)
            plt.subplot(311)
            plt.plot(self.__time_series, linewidth=2.0)
            plt.legend(['Time series'])

            plt.subplot(312)
            plt.plot(MACD, linewidth=1.5)
            plt.plot(signal, linewidth=1.5)
            plt.legend(['MACD '+str(shortwin)+'/'+str(longwin),'Trigger '+str(trigger)])

            plt.subplot(313)
            plt.plot(self.best_data.best_portfolio, linewidth=1.5)
            plt.legend(['Portfolio'])
            plt.title('Time Series')

            plt.figure(2)
            plt.subplot(211)
            plt.plot(self.best_data.best_shares, linewidth=1.0)
            plt.legend(['Shares'])
            plt.subplot(212)
            plt.plot(self.best_data.best_returns, linewidth=1.0)
            plt.legend(['log returns'])

            plt.show(block = False)


    def qqplot(self):
        import scipy.stats as stats
        import pylab
        stats.probplot(self.best_data.best_returns, dist="norm", plot=pylab)
        pylab.show()

   # def boxPlot(self):
   #     plt.boxplot(abs(self.best_data.best_returns))
   #     plt.show(block = False)

    def HodlPlot(self):
        #import matplotlib.pyplot as plt
        __initialShares = self.__investment/self.__time_series[0]
        __buyHoldseries = __initialShares * self.__time_series

        plt.figure(3)
        plt.plot(__buyHoldseries)
        plt.title('Buy and Hodln')

        plt.show()

    def returnMatrix(self,x,y,z):
        #import matplotlib.pyplot as plt
        plt.figure(5)

        plt.contourf(z,cmap='jet')
        #plt.xticks(str(x))
        #plt.yticks(str(y))
        plt.title('Return Matrix')
        plt.xlabel('Long Window')
        plt.ylabel('Short Window')
        plt.colorbar()
        plt.show(block=False)
