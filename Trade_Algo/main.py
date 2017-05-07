'''
This is the main file to run the trading bot

@author: mhansinger
'''

import numpy as np
import pandas as pd
from Broker_virtual import Broker_virtual
from set_input import set_input
from history_data import history
from criteria import criteria
import threading

# make sure you are in Trade_Algo
pwd

# set the input data with default values
# adjust the windows to our time series!!!
ETH_input = set_input(asset='XETH', long=4800, short=500, fee=0.0016, reinvest=0.0, investment=1000.0)

# check some parameters, e.g.:
ETH_input.fee

ETH_input.investment

# initialize the trading history:  it will read the ETH stream from ftp
ETH_history = history(ETH_input)

ETH_broker = Broker_virtual(ETH_input)

# initialize the broker with the strating values
ETH_broker.initialize()

ETH_trade = criteria(ETH_input,ETH_broker,ETH_history)

