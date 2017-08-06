
import numpy as np
import threading
import time
from datetime import datetime
import sys


# Überlegung die windows hier zu definieren??

'''
new class to test the run() thread within the the intersection class
'''

class run_strategy(threading.Thread):
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
        self.timeInteval = timeInterval

        # IMPORTANT: Broker muss initialisiert werden!
        self.Broker.initialize()

    def eval_rollings(self):
        #computes short and long rolling mean
        __short_mean = self.history.getRollingMean(self.short_win)
        __long_mean = self.history.getRollingMean(self.long_win)
        __last_short = np.array(__short_mean)[-1]
        __last_long = np.array(__long_mean)[-1]
        return __last_short, __last_long

    def eval_MACD(self):
        # returns MACD and singan/trigger line
        __MACD = self.history.getMACD(self.short_win,self.long_win)
        __signal = __MACD.ewm(span=self.signalMACD).mean()
        # return only the last entry of the columns as float, these will be intersected
        return float(__MACD[-1:]), float(__signal[-1:])

    def intersectSMA(self):
        # call the evaluation
        try:
            __last_short, __last_long = self.eval_rollings()
        except FileNotFoundError:
            print('Check the name of the data directory: XY_data')
            sys.exit(0)

        if __last_short > __last_long:
            ## das ist quasi das Kriterium, um zu checken ob wir Währung haben oder nicht,
            ## entsprechend sollten wir kaufen, oder halt nicht
            # Broker.broker_status ist das Kriterium, ob der Broker gerade arbeitet, busy ist, dann wird nix gemacht vorerst!
            if self.Broker.asset_status is False and self.Broker.broker_status is False:
                self.Broker.buy_order()
                print('go long')
                print('long mean: ', __last_long)
                print('short mean: ', __last_short)
                print(' ')
            else:
                self.Broker.idle()
                print('keep calm and HODL')
                print('long mean: ', __last_long)
                print('short mean: ', __last_short)
                print(' ')

        elif __last_long > __last_short:
            if self.Broker.asset_status is True and self.Broker.broker_status is False:
                self.Broker.sell_order()
                print('go short')
                print('long mean: ', __last_long)
                print('short mean: ', __last_short)
                print(' ')
            else:
                self.Broker.idle()
                print('short, idle')
                print('long mean: ', __last_long)
                print('short mean: ', __last_short)
                print(' ')
        else:
            ## idle, soll nix machen
            self.Broker.idle()
            print('idle')
            print('long mean: ', __last_long)
            print('short mean: ', __last_short)
            print(' ')

    # MCAD intersect!
    def intersectMACD(self):
        # call the evaluation for MACD at run time
        try:
            __MACD, __signal = self.eval_MACD()
        except FileNotFoundError:
            print('Check the name of the data directory: XY_data')
            sys.exit(0)

        if __MACD > __signal:
            ## das ist quasi das Kriterium, um zu checken ob wir Währung haben oder nicht,
            ## entsprechend sollten wir kaufen, oder halt nicht
            if self.Broker.asset_status is False and self.Broker.broker_status is False:
                self.Broker.buy_order()
                print('go long')
                print('signal: ', __signal)
                print('MACD: ', __MACD)
                print(' ')
            else:
                self.Broker.idle()
                print('keep calm and HODL')
                print('signal: ', __signal)
                print('MACD: ', __MACD)
                print(' ')

        elif __MACD < __signal:
            if self.Broker.asset_status is True and self.Broker.broker_status is False:
                self.Broker.sell_order()
                print('go short')
                print('signal: ', __signal)
                print('MACD: ', __MACD)
                print(' ')
            else:
                self.Broker.idle()
                print('short, idle')
                print('signal: ', __signal)
                print('MACD: ', __MACD)
                print(' ')
        else:
            ## idle, soll nix machen
            self.Broker.idle()
            print('idle')
            print('signal: ', __signal)
            print('MACD: ', __MACD)
            print(' ')


    # *************************************************
    # this is the new run funciton. still to test...
    # not to use...

    # oder evtl as eigenen Thread das alles...
    def run(self):
        self.resume()  # unpause self
        while True:
            try:  # das Programm soll nochmal aufgerufen werden, wenn ein Fehler geworfen wird.
                with self.state:
                    if self.paused:
                        self.state.wait()  # block until notified
                ###################
                self.intersectSMA()
                ###################
                print('last intersect: ' + str(datetime.now()))
                time.sleep(self.timeInteval)
                self.iterations += 1
            except EmptyDataError:
                self.run()

    def resume(self):
        with self.state:
            self.paused = False
            self.state.notify()  # unblock self if waiting

    def pause(self):
        with self.state:
            self.paused = True  # make self block and wait
            print('Strategy is currently paused!')

    def updateWindow(self,win,which):
        if which=='short' or which=='fast':
            self.short_win = win
        elif which=='long' or which=='slow':
            self.long_win = win
        elif which=='trigger':
            self.signalMACD = win
        else:
            print('No update! \nValid values are short (fast), long (slow), trigger (only in MACD)')