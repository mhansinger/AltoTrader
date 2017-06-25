'''
This is the main file to run the trading bot

@author: mhansinger
'''

from __init__ import *
from datetime import datetime


# set the input data with default values
# adjust the windows to our time series!!!
XETH_input = set_input(asset1='XETH', asset2='XXBT', long=1000, short=470, fee=0.0016, reinvest=0.0, investment=1000.0);XETH_history = history(XETH_input);XETH_broker = Broker(XETH_input)


# initialize the trading history:  it will read the ETH stream from ftp


# initialize the broker with the strating values
XETH_broker.initialize()

XETH_trade = run_strategy(XETH_input,XETH_broker,XETH_history,600)

def run_new(interval=600):
    try:
        XETH_trade.intersect()
        threading.Timer(interval, run_new).start()
    except ValueError:
        print('ValueError die Funktion wird erneut gestartet')
        run_new()


def run(interval=600):
    XLTC_trade.intersect()
    threading.Timer(interval, run).start()



# oder :

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