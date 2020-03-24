
import numpy as np
import threading
import time
from datetime import datetime
import sys


# Überlegung die windows hier zu definieren??

'''
new class to test the run() thread within the the intersection class
'''

class strategy_new(threading.Thread):
    def __init__(self, myinput, broker, history, timeInterval=600):
        threading.Thread.__init__(self)
        self.time_series = []
        self.short_win = myinput.window_short     # sollte noch dynamische werden
        self.long_win = myinput.window_long
        self.signalMACD = myinput.sigMACD
        self.Broker = broker
        self.series_name = myinput.series_name
        self.history = history

        self.iterations = 0
        self.daemon = True  # OK for main to exit even if instance is still running
        self.paused = True  # start out paused
        self.state = threading.Condition()
        #self.timeInteval = timeInterval

        # IMPORTANT: Broker muss initialisiert werden!
        self.Broker.initialize()

        self.__emergencyExit = False
        self.__exitFactor = 0.972
        self.__bollingerFactor = 1

        self.asset1 = self.Broker.getAsset1()
        self.asset2 = self.Broker.getAsset2()

    def eval_rollings(self):
        #computes short and long rolling mean
        short_mean = self.history.getRollingMean(self.short_win)
        long_mean = self.history.getRollingMean(self.long_win)
        last_short = short_mean.iloc[-1]
        last_long = long_mean.iloc[-1]
        return last_short, last_long, long_mean

    def eval_MACD(self):
        # returns MACD and singan/trigger line
        MACD = self.history.getMACD(self.short_win,self.long_win)
        signal = MACD.ewm(span=self.signalMACD).mean()
        # return only the last entry of the columns as float, these will be intersected
        return float(MACD[-1:]), float(signal[-1:])

    def intersectSMA(self):
        # call the evaluation
        try:
            last_short, last_long, long_sma = self.eval_rollings()
        except FileNotFoundError:
            print('Check the name of the data directory: XY_data')
            sys.exit(0)

        # get last buy price
        lastbuy = self.Broker.lastbuy
        # das muss noch geprüft werden, ob marktpreis und welcher faktor!!
        marketAsk = self.Broker.asset_market_ask()
        Bollinger_limit = self.history.getBollUp(self.long_win*int(self.__bollingerFactor))

        # TODO: check Bollinger bands if they make sense

        # it's a good time to buy if we haven't yet
        if last_short > last_long:
            ## das ist das Kriterium, um zu checken ob wir Währung haben oder nicht,
            ## entsprechend sollten wir kaufen, oder halt nicht
            # Broker.broker_status ist das Kriterium, ob der Broker gerade arbeitet, busy ist, dann wird nix gemacht vorerst!
            if not any([self.Broker.get_asset_status(), self.Broker.get_broker_status(), self.__emergencyExit]): # and (marketAsk > Bollinger_limit):
                self.Broker.buy_order()
                print('Buying %s for %s' % (self.asset1,self.asset2))
                print('long mean: ', last_long)
                print('short mean: ', last_short)
                print(' ')

            # # TODO: does this make sense?? --> makes no sense for now!
            # # this is an emergency function to leave the market if price drops; check about 98%
            # elif lastbuy*self.__exitFactor > marketAsk and self.Broker.get_asset_status():
            #     self.__emergencyExit = True
            #     self.Broker.sell_order()
            #     print('Emergency Exit!')
            #     print('Market is dropping!')
            #     print('long mean: ', last_long)
            #     print('short mean: ', last_short)

            # HODL situation
            else:
                self.Broker.idle()
                self.__emergencyExit = False  # in any case reset emergency exit flag
                print('keep calm and HODL '+self.asset1+' -> '+str(self.Broker.get_asset_status()))
                if marketAsk < Bollinger_limit:
                    print('Price below Bollinger')
                print('long mean: ', last_long)
                print('short mean: ', last_short)
                print(' ')

        # it's a good time to sell
        elif last_long > last_short:
            self.__emergencyExit = False        #in any case reset emergency exit flag

            if self.Broker.get_asset_status() is True and self.Broker.get_broker_status() is False:
                self.Broker.sell_order()
                print('Selling %s for %s' % (self.asset1,self.asset2))
                print('long mean: ', last_long)
                print('short mean: ', last_short)
                print(' ')
            else:
                self.Broker.idle()
                print('short, idle')
                print('Do we have '+self.asset1+'? -> '+str(self.Broker.get_asset_status()))
                print('long mean: ', last_long)
                print('short mean: ', last_short)
                print(' ')

        ## idle, do nothing
        else:
            self.Broker.idle()
            print('idle')
            print('long mean: ', last_long)
            print('short mean: ', last_short)
            print(' ')

    # MCAD intersect!
    def intersectMACD(self):
        # call the evaluation for MACD at run time
        try:
            MACD, signal = self.eval_MACD()
        except FileNotFoundError:
            print('Check the name of the data directory: XY_data')
            sys.exit(0)

        if MACD > signal:
            ## das ist quasi das Kriterium, um zu checken ob wir Währung haben oder nicht,
            ## entsprechend sollten wir kaufen, oder halt nicht
            if self.Broker.get_asset_status() is False and self.Broker.get_broker_status() is False:
                self.Broker.buy_order()
                print('go long')
                print('signal: ', signal)
                print('MACD: ', MACD)
                print(' ')
            else:
                self.Broker.idle()
                print('keep calm and HODL')
                print('signal: ', signal)
                print('MACD: ', MACD)
                print(' ')

        elif MACD < signal:
            if self.Broker.get_asset_status() is True and self.Broker.get_broker_status() is False:
                self.Broker.sell_order()
                print('go short')
                print('signal: ', signal)
                print('MACD: ', MACD)
                print(' ')
            else:
                self.Broker.idle()
                print('short, idle')
                print('signal: ', signal)
                print('MACD: ', MACD)
                print(' ')
        else:
            ## idle, soll nix machen
            self.Broker.idle()
            print('idle')
            print('signal: ', signal)
            print('MACD: ', MACD)
            print(' ')


    def setExitFactor(self,fac):
        self.__exitFactor=fac

    def getExitFac(self):
        return self.__exitFactor

    def setBollingerFac(self,boll):
        self.__bollingerFactor = boll

    def getBollinger(self):
        return self.__bollingerFactor

    def checkExit(self):
        return self.__emergencyExit

