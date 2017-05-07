'''
This is the main file to run the trading bot

@author: mhansinger
'''

# make sure you are in Trade_Algo
pwd

# set the input data with default values
ETH_input = set_input()

# check some parameters, e.g.:
ETH_input.fee

ETH_input.investment

# initialize the trading history:  it will read the ETH stream from ftp
ETH_history = history_data(ETH_input)