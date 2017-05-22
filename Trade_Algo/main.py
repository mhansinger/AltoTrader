'''
This is the main file to run the trading bot

@author: mhansinger
'''

from __init__ import *
from datetime import datetime


# set the input data with default values
# adjust the windows to our time series!!!
XETH_input = set_input(asset1='XETH', asset2='ZEUR', long=4800, short=500, fee=0.0016, reinvest=0.0, investment=1000.0)


# initialize the trading history:  it will read the ETH stream from ftp
XETH_history = history(XETH_input)

XETH_broker = Broker_virtual(XETH_input)

# initialize the broker with the strating values
XETH_broker.initialize()

XETH_trade = criteria(XETH_input,XETH_broker,XETH_history)

def run(interval=600):
    XETH_trade.intersect()
    threading.Timer(interval, run).start()


class intersect_thread(threading.Thread):
    def __init__(self, asset, timeInterval=600):
        threading.Thread.__init__(self)
        self.iterations = 0
        self.daemon = True  # OK for main to exit even if instance is still running
        self.paused = True  # start out paused
        self.state = threading.Condition()
        self.__asset = asset
        self.timeInteval = timeInterval
        
    def run(self):
        self.resume() # unpause self
        while True:
            with self.state:
                if self.paused:
                    self.state.wait() # block until notified
            self.__asset.intersect()
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