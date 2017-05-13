'''
This is the main file to run the trading bot

@author: mhansinger
'''

from __init__ import *



# set the input data with default values
# adjust the windows to our time series!!!
XLTC_input = set_input(asset1='XLTC', asset2='ZEUR', long=4800, short=500, fee=0.0016, reinvest=0.0, investment=1000.0)


# initialize the trading history:  it will read the ETH stream from ftp
XLTC_history = history(XLTC_input)

XLTC_broker = Broker_virtual(XLTC_input)

# initialize the broker with the strating values
XLTC_broker.initialize()

XLTC_trade = criteria(XLTC_input,XLTC_broker,XLTC_history)

def run(interval=600):
    XLTC_trade.intersect()
    threading.Timer(interval, run).start()