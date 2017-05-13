'''
This is the main file to run the trading bot

@author: mhansinger
'''

from __init__ import *



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