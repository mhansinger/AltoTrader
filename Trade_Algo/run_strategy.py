

import numpy as np
import threading
import time
from datetime import datetime

# Broker ist noch eine dummy Klasse. Sollte folgende Funktionen beinhalten:
# buy_order, sell_order

'''
new class to test the run() thread within the the intersection class
'''


class run_strategy(threading.Thread):
    def __init__(self, myinput, broker, history):
        self.time_series = []
        self.short_mean = []
        self.long_mean = []
        self.short_win = myinput.window_short     # sollte noch dynamische werden
        self.long_win = myinput.window_long
        self.Broker = broker
        self.series_name = myinput.series_name
        self.history = history
        self.__last_short = []
        self.__last_long = []

        threading.Thread.__init__(self)
        self.iterations = 0
        self.daemon = True  # OK for main to exit even if instance is still running
        self.paused = True  # start out paused
        self.state = threading.Condition()
        self.timeInteval = timeInterval

    def eval_rollings(self):
        self.short_mean = self.history.getRollingMean(self.short_win)
        self.long_mean = self.history.getRollingMean(self.long_win)
        self.__last_short = np.array(self.short_mean)[-1]
        self.__last_long = np.array(self.long_mean)[-1]

    def intersect(self):
        # call the evaluation
        self.eval_rollings()

        if self.__last_short > self.__last_long:
            ## das ist quasi das Kriterium, um zu checken ob wir Währung haben oder nicht,
            ## entsprechend sollten wir kaufen, oder halt nicht
            if self.Broker.asset_status is False and self.Broker.broker_status is False:
                self.Broker.buy_order()
                print('buy')
                print('long mean: ', self.__last_long)
                print('short mean: ', self.__last_short)
            else:
                self.Broker.idle()
                print('buy idle')
                print('long mean: ', self.__last_long)
                print('short mean: ', self.__last_short)

        elif self.__last_long > self.__last_short:
            if self.Broker.asset_status is True and self.Broker.broker_status is False:
                self.Broker.sell_order()
                print('sell')
                print('long mean: ', self.__last_long)
                print('short mean: ', self.__last_short)
            else:
                self.Broker.idle()
                print('sell idle')
                print('long mean: ', self.__last_long)
                print('short mean: ', self.__last_short)
        else:
            ## idle, soll nix machen
            self.Broker.idle()
            print('idle')
            print('long mean: ', self.__last_long)
            print('short mean: ', self.__last_short)

    # this is the new run funciton. still to test
    def run(self):
        self.resume() # unpause self
        while True:
            with self.state:
                if self.paused:
                    self.state.wait() # block until notified
            self.intersect()
            print('last intersect: ' + str(datetime.now()))
            time.sleep(self.timeInteval)
            self.iterations += 1

    def resume(self):
        with self.state:
            self.paused = False
            self.state.notify()  # unblock self if waiting

    def pause(self):
        with self.state:
            self.paused = True  # make self block and wait
            print('Strategy is currently paused!')