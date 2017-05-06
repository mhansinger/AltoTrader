'''
This is the Broker class.
The Broker connects with the Kraken account and does the trades

@author: mhansinger 

'''

import numpy as np
import pandas as pd
import krakenex
import time

class Broker(object):
    def __init__(self,asset='XETH'):
        self.__asset = asset

        self.asset_status = False
        self.broker_status = False
        self.__k = krakenex.API()
        self.__k.load_key('kraken.key')
        #self.__balance_all

    def buy_order(self):
        self.broker_status = True
        __current_eur_funds = self.get_eur_funds()
        __asset_bid = self.asset_market_bid()

        # place buy order
        # check if order is filled (while loop?)
        # set status to
        self.asset_status = True
        self.broker_status = False

    def sell_order(self):
        self.broker_status = True
        __asset_ask = self.asset_market_ask()

        # place sell order
        # check if order is filled, then:
        # set status to
        self.asset_status = False
        self.broker_status = False

    def asset_balance(self):
        self.__balance_all = self.__k.query_private('Balance')
        balance_str = self.__balance_all['result'][self.__asset]
        balance = float(balance_str)
        print(balance)

    def asset_market_bid(self):
        __pair = self.__asset + 'ZEUR'
        __market_bid = self.__k.query_public('Ticker',{'pair': __pair})['result'][__pair]['b']
        return float(__market_bid[0])

    def asset_market_ask(self):
        __pair = self.__asset + 'ZEUR'
        __market_ask = self.__k.query_public('Ticker',{'pair': __pair})['result'][__pair]['a']
        return float(__market_ask[0])

    def get_eur_funds(self):
        __eur_funds = self.__k.query_private('Balance')['result']['ZEUR']
        return float(__eur_funds)

    def get_asset_funds(self):
        __asset_funds = self.__k.query_private('Balance')['result']['XETH']
        return float(__asset_funds)

    def idle(self):


    def get_asset_status(self):

