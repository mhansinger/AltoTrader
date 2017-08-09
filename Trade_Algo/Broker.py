'''
This is the Broker class.
The Broker connects with the Kraken account and does the trades

@author: mhansinger 
'''

import numpy as np
import pandas as pd
import krakenex
import time
import os
from Twitter_Bot.twitterEngine import twitterEngine

class Broker(object):
    def __init__(self,input):
        self.__asset1 = input.asset1
        self.__asset2 = input.asset2
        self.__pair = input.asset1+input.asset2
        self.asset_status = False
        self.broker_status = False
        self.__k = krakenex.API()
        self.__k.load_key('kraken.key')
        self.__asset1_funds = []
        self.__asset2_funds = []
        self.__balance_all = []
        self.__balance_df = []
        self.__lastbuy = []
        self.__twitter=False
        try:
            self.twitterEngine = twitterEngine()
        except:
            print('No Twitter module enabled\n')

        self.__column_names = []

    def initialize(self):
        # initialisiert den Broker: stellt das dataFrame auf und holt die ersten Werte

        # check den asset_status von asset1 und stellt fest ob wir im Markt sind :
        self.asset_check()

        self.__column_names = ['Time stamp', self.__asset1, self.__asset2, 'fee', 'Market Price', 'Order Id']
        self.__balance_df = pd.DataFrame([np.zeros(len(self.__column_names))], columns=self.__column_names)
        self.__balance_df['Time stamp'] = self.getTime()
        self.__balance_df[self.__asset2] = self.get_asset2_balance()
        self.__balance_df[self.__asset1] = self.get_asset1_balance()
        self.__balance_df['fee'] = self.market_price()
        self.__balance_df['Market Price'] = self.market_price()
        self.__balance_df['Order Id'] = '-'

        print(self.__balance_df.tail())

    def buy_order(self):
        # executes a buy order

        self.broker_status = True
        self.asset_check()
        # check den XBT balance
        __current_asset2_funds = self.get_asset2_balance()

        # diese if abfrage ist ein double check
        if self.asset_status is False:
            #######################
            # kraken query
            # wir können keine Verkaufsorder auf XBT-basis setzen, sondern nur ETH kaufen.
            # Deshalb: Limit order auf Basis des aktuellen Kurses und Berechnung des zu kaufenden ETH volumens.
            __volume2 = __current_asset2_funds*0.99999
            __ask = self.asset_market_ask()
            __volume1 = __volume2 / __ask
            __vol_str = str(__volume1)

            __api_params = {'pair': self.__pair,
                            'type':'buy',
                            'ordertype':'market',
                            #'price': __market_str,
                            'volume':__vol_str,
                            'trading_agreement':'agree'}
            __order = self.__k.query_private('AddOrder',__api_params)

            try:
                __order_id = __order['result']['txid'][0]
            except KeyError:
                print('Probably not enough funding...')

            # IMPORTANT: check if order is still open!
            self.check_order(__order_id)
            #######################

            # store the last buy price, to compare with sell price
            self.__lastbuy = __ask

            # update the balance sheet with transaction costs
            __costs = self.__k.query_private('ClosedOrders')['result']['closed'][__order_id]['cost']
            self.update_balance(__costs,__order_id)

            # change the asset status !
            self.asset_check()

        self.broker_status = False


    def sell_order(self):
        # executes a sell order

        self.broker_status = True
        __bid = self.asset_market_bid()
        __current_asset1_funds = self.get_asset1_balance()
        self.asset_check()
        # diese if abfrage ist ein double check
        if self.asset_status is True:
            #######################
            # kraken query: what's our stock?
            __volume = str(__current_asset1_funds*0.99999)

            __api_params = {'pair': self.__pair,
                            'type':'sell',
                            'ordertype':'market',
                            'volume': __volume,
                            'trading_agreement': 'agree'}
            __order = self.__k.query_private('AddOrder', __api_params)
            try:
                __order_id = __order['result']['txid'][0]
            except KeyError:
                print('Probably not enough funding...')

            # IMPORTANT: check if order is still open!
            self.check_order(__order_id)

            #######################
            # DAS SOLLTE IN EINE METHODE GEBAUT WERDEN
            # checkt ob niedriger verkauft wird als gekauft
            if self.__lastbuy > __bid:
                print('Bad Deal!\n SELL < BUY\n')
            elif self.__lastbuy < __bid:
                print('GREAT Deal!\n SELL > BUY\n')

            if self.__twitter:
                self.setTweet(self.__lastbuy,__bid)
            #######################

            # update the balance sheet with transaction costs
            __costs = self.__k.query_private('ClosedOrders')['result']['closed'][__order_id]['cost']
            self.update_balance(__costs,__order_id)

            # change the asset status !
            self.asset_check()

        self.broker_status = False

    def idle(self):
        self.broker_status = True
        try:
            __balance_np = np.array(self.__balance_df.tail())
        except AttributeError:
            print('Broker muss noch initialisiert werden!\n')
        #
        # update the balance sheet
        self.update_balance(0,'-')

        self.broker_status = False

###################################
# Weitere member functions:

    def getTime(self):
        #return int(time.time())
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

    def asset_balance(self):
        self.__balance_all = self.__k.query_private('Balance')
        balance_str = self.__balance_all['result'][self.__asset1]
        balance = float(balance_str)
        print(balance)

    def asset_market_bid(self):
        __market_bid = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['b']
        return float(__market_bid[0])

    def asset_market_ask(self):
        __market_ask = self.__k.query_public('Ticker',{'pair': self.__pair})['result'][self.__pair]['a']
        return float(__market_ask[0])

    def market_price(self):
        __market = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['c']
        return float(__market[0])

    def get_asset2_balance(self):
        # unsere Euros
        __asset2_funds = self.__k.query_private('Balance')['result'][self.__asset2]
        return float(__asset2_funds)

    def get_asset1_balance(self):
        # unsere Ether
        __asset1_funds = self.__k.query_private('Balance')['result'][self.__asset1]
        return float(__asset1_funds)

    def update_balance(self,cost,id):
        # update time
        __time = self.getTime()
        __new_asset1 = self.get_asset1_balance()
        __new_asset2 = self.get_asset2_balance()
        __market_price = self.market_price()

        __balance_update_vec = [[__time, __new_asset1, __new_asset2, cost, __market_price, id]]
        __balance_update_df = pd.DataFrame(__balance_update_vec, columns=self.__column_names)
        self.__balance_df = self.__balance_df.append(__balance_update_df)

        # write as csv file
        self.writeCSV(self.__balance_df)
        print(__balance_update_df)

        # schreibt die beiden .txt für den online upload
        self.__writeTXT(__new_asset1, __new_asset2)


    def check_order(self,order_id):
        print('Checking the Order')
        __count = 0
        __cancel_flag = False
        __open_orders = self.__k.query_private('OpenOrders')['result']['open']

        # check if the order id appears in the openOrders list

        # BOOL Abfrage ob Order ausgeführt wurde
        while bool(order_id in __open_orders) is True:
            print('Order is still open ... ')
            __open_orders = self.__k.query_private('OpenOrders')['result']['open']
            __count += 1
            #cancel the order if not filled after 10 checks
            if __count > 10:
                __cancel_flag = True
                break
            # repeat check after 30 seconds
            time.sleep(30)

        if __cancel_flag is True:
            # cancle the order
            self.__k.query_private('CancelOrder', {'txid': order_id})
            print('Order was not filled and canceled!\n')
        else:
            print('Success: Order was filled!\n')

    # schreibt ein CSV raus
    def writeCSV(self,__df):
        __filename = self.__pair+'_balance.csv'
        pd.DataFrame.to_csv(__df,__filename)

    def our_balance(self):
        print(self.__balance_df.tail())

    def asset_check(self):
        # checks the assets on our account and sets the asset_status
        __asset1 = self.get_asset1_balance()
        __asset2 = self.get_asset2_balance()
        # normalize the price
        __asset2 = __asset2/self.market_price()
        if __asset1 > __asset2:
            self.asset_status = True
        else:
            self.asset_status = False

    # speichert die aktuellen asset1 und asset2 Werte der Krake raus, für weiteren Upload
    def __writeTXT(self,asset1,asset2):
        __asset_balance_1 = round(asset1,3)
        __asset_balance_2 = round(asset2,3)
        __filename1 = self.__asset1+'.txt'
        __filename2 = self.__asset2+'.txt'
        with open(__filename1, "w") as text_file:
            text_file.write('%s' % __asset_balance_1)
        with open(__filename2, "w") as text_file:
            text_file.write('%s' % __asset_balance_2)

    def setTwitter(self,on=False):
        try:
            if type(on) != bool:
                raise TypeError
        except TypeError:
            print('Either True or False!')
        self.__twitter=on
        print('Twitter is enabled!\n')

    def getTwitter(self):
        return self.__twitter

    def setTweet(self,old,current):
        # checks for old and current prices and sends twitter msgs
        # and sends good or bad tweets
        if old < current:
            self.twitterEngine.good_tweet()
        elif old >= current:
            self.twitterEngine.bad_tweet()
