'''
This is the Broker class.
The Broker connects with the Kraken account and does the trades

@author: mhansinger 

'''

import numpy as np
import pandas as pd
import krakenex
import time


class Broker_virtual(object):
    def __init__(self, input):
        self.__asset = input.asset

        self.asset_status = False
        self.broker_status = False
        self.__k = krakenex.API()
        self.__k.load_key('kraken.key')
        self.__balance_all = []
        self.__fee = input.fee
        self.__invest = input.investment
        self.__series_name = input.series_name
        self.__balance_df = []

        self.__column_names = []

    def initialize(self):
        self.__column_names = ['Time stamp', self.__asset, 'ZEUR', 'shares', 'costs', 'XETH price']
        self.__balance_df = pd.DataFrame([np.zeros(len(self.__column_names))], columns= self.__column_names)
        self.__balance_df['Time stamp'] = self.getTime()
        self.__balance_df['ZEUR'] = self.__invest
        self.__balance_df['XETH price'] = self.asset_market_bid()

        print(self.__balance_df)

        # return self.__balance_df
        # hier sollte dann auch noch der broker status geklärt werden

    def buy_order(self):
        self.broker_status = True
        # this only for virtual
        __balance_np = np.array(self.__balance_df.tail())
        __current_eur_funds = __balance_np[-1,2] * 0.99999
        __current_costs = __current_eur_funds * self.__fee

        __asset_bid = self.asset_market_bid()

        __new_shares = (__current_eur_funds - __current_costs) / __asset_bid
        __new_XETH = __new_shares * __asset_bid
        __new_eur_fund  = __balance_np[-1,2] - __current_eur_funds      # --> sollte gegen null gehen
        # update time
        __time = self.getTime()

        __balance_update_vec = [[__time, __new_XETH, __new_eur_fund, __new_shares, __current_costs, __asset_bid]]
        __balance_update_df = pd.DataFrame(__balance_update_vec, columns = self.__column_names)
        self.__balance_df = self.__balance_df.append(__balance_update_df)

        # write as csv file
        self.writeCSV(self.__balance_df)
        print(__balance_update_df)
        print(' ')

        self.asset_status = True
        self.broker_status = False

        #return self.__balance_df

    def sell_order(self):
        self.broker_status = True
        __asset_ask = self.asset_market_ask()

        # this only for virtual
        __balance_np = np.array(self.__balance_df.tail())
        __asset_ask = self.asset_market_ask()
        __current_shares = __balance_np[-1,3] * 0.99999
        __current_costs = __current_shares * __asset_ask * self.__fee

        __new_eur_fund = __current_shares * __asset_ask - __current_costs

        __new_shares = __balance_np[-1,3] - __current_shares        # --> sollte gegen null gehen
        __new_XETH = __new_shares * __asset_ask

        # update time
        __time = self.getTime()

        __balance_update_vec = [[__time, __new_XETH, __new_eur_fund, __new_shares, __current_costs, __asset_ask]]
        __balance_update_df = pd.DataFrame(__balance_update_vec, columns = self.__column_names)
        self.__balance_df = self.__balance_df.append(__balance_update_df)

        # write as csv file
        self.writeCSV(self.__balance_df)
        print(__balance_update_df)
        print(' ')

        self.asset_status = False
        self.broker_status = False

    def idle(self):
        self.broker_status = True
        __balance_np = np.array(self.__balance_df.tail())

        if self.asset_status == True:
            __market_price = self.asset_market_ask()
        elif self.asset_status == False:
            __market_price = self.asset_market_bid()

        __new_shares = __balance_np[-1,3]
        __new_XETH = __new_shares*__market_price
        __new_eur_fund = __balance_np[-1,2]
        __current_costs = 0

        # update time
        __time = self.getTime()

        # alter status ist wie neuer balance vektor
        __balance_update_vec = [[__time, __new_XETH, __new_eur_fund, __new_shares, __current_costs, __market_price]]
        __balance_update_df = pd.DataFrame(__balance_update_vec, columns = self.__column_names)
        self.__balance_df = self.__balance_df.append(__balance_update_df)

        # write as csv file
        self.writeCSV(self.__balance_df)

        print(__balance_update_df)
        print(' ')

        self.broker_status = False


    def asset_balance(self):
        self.__balance_all = self.__k.query_private('Balance')
        balance_str = self.__balance_all['result'][self.__asset]
        balance = float(balance_str)
        print(balance)

    def asset_market_bid(self):
        __pair = self.__asset + 'ZEUR'
        __market_bid = self.__k.query_public('Ticker', {'pair': __pair})['result'][__pair]['b']
        return float(__market_bid[0])

    def asset_market_ask(self):
        __pair = self.__asset + 'ZEUR'
        __market_ask = self.__k.query_public('Ticker', {'pair': __pair})['result'][__pair]['a']
        return float(__market_ask[0])

    def get_eur_funds(self):
        __eur_funds = self.__k.query_private('Balance')['result']['ZEUR']
        return float(__eur_funds)

    def get_asset_funds(self):
        __asset_funds = self.__k.query_private('Balance')['result']['XETH']
        return float(__asset_funds)

    def getTime(self):
        return int(time.time())

    def writeCSV(self,__df):
        __filename = self.__asset + '_balance.csv'
        pd.DataFrame.to_csv(__df,__filename)





# Fehlen noch members, die alles tracken und als .csv speichern

# initialer asset check up


