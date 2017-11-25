'''
This is the main file to run the trading bot

@author: mhansinger
'''

from __init__ import *
from datetime import datetime


# set the input data with default values
# adjust the windows to our time series!!!
XETH_input = set_input(asset1='XETH', asset2='XXBT', long=100, short=47);XETH_history = history(XETH_input);XETH_broker = Broker(XETH_input)


# initialize the trading history:  it will read the ETH stream from ftp


# initialize the broker with the strating values
XETH_broker.initialize()

XETH_trade = run_strategy(XETH_input,XETH_broker,XETH_history,timeInterval=600)

def run_trader(interval=600):
    try:
        XETH_trade.intersect()
        t=threading.Timer(interval, run_trader)
        t.start()
    except:
        print("Fehler: ", sys.exc_info()[0])
        print('Wird erneut gestartet...\n')
        run_trader()
        
# this starts the trading engine!
run_trader()


