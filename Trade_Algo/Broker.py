'''
This is the Broker class.
The Broker connects with the Kraken account and does the trades

@author: mhansinger 

'''

import numpy as np
import pandas as pd
import krakenex
import time

class Broker(object,input):
    def __init__(self, input):
        self.__asset1 = input.asset1
        self.__asset2 = input.asset2
        self.__pair = input.asset1+input.asset2

        self.asset_status = False
        self.broker_status = False
        self.__k = krakenex.API()
        #self.__k.load_key('kraken.key')
        self.__balance_all = []
        self.__fee = input.fee
        self.__invest = input.investment
        self.__series_name = input.series_name
        self.__balance_df = []

        self.__column_names = []

    def initialize(self):
        self.__column_names = ['Time stamp', self.__asset1, self.__asset2, 'shares', 'costs', self.__asset1+' price']
        self.__balance_df = pd.DataFrame([np.zeros(len(self.__column_names))], columns= self.__column_names)
        self.__balance_df['Time stamp'] = self.getTime()
        self.__balance_df[self.__asset2] = self.__invest
        self.__balance_df[self.__asset1+' price'] = self.asset_market_bid()

        print(self.__balance_df)

        # return self.__balance_df
        # hier sollte dann auch noch der broker status geklärt werden

    def buy_order(self):
        self.broker_status = True

        if self.asset_status is False:
            # this only for virtual
            try:
                __balance_np = np.array(self.__balance_df.tail())
            except AttributeError:
                print('Broker muss noch initialisiert werden!')

            __current_eur_funds = __balance_np[-1, 2] * 0.999999
            __current_costs = __current_eur_funds * self.__fee

            __asset_ask = self.asset_market_ask()

            __new_shares = (__current_eur_funds - __current_costs) / __asset_ask
            __new_XETH = __new_shares * __asset_ask
            __new_eur_fund = __balance_np[-1, 2] - __current_eur_funds  # --> sollte gegen null gehen

            # update time
            __time = self.getTime()

            __balance_update_vec = [[__time, __new_XETH, __new_eur_fund, __new_shares, __current_costs, __asset_ask]]
            __balance_update_df = pd.DataFrame(__balance_update_vec, columns=self.__column_names)
            self.__balance_df = self.__balance_df.append(__balance_update_df)

            # write as csv file
            self.writeCSV(self.__balance_df)
            print(' ')
            print(__balance_update_df)
            print(' ')

            self.asset_status = True

        else:
            print('Hast kein Geld zum Kaufen')

        self.broker_status = False


    # Bug to fix
    def sell_order(self):
        self.broker_status = True
        __asset_bid = self.asset_market_bid()

        if self.asset_status is True:
            # this only for virtual
            try:
                __balance_np = np.array(self.__balance_df.tail())
            except AttributeError:
                print('Broker muss noch initialisiert werden!')

            __asset_bid = self.asset_market_bid()
            __current_shares = __balance_np[-1, 3] * 0.999999
            __current_costs = __current_shares * __asset_bid * self.__fee

            __new_eur_fund = __current_shares * __asset_bid - __current_costs

            __new_shares = __balance_np[-1, 3] - __current_shares  # --> sollte gegen null gehen
            __new_XETH = __new_shares * __asset_bid

            # update time
            __time = self.getTime()

            __balance_update_vec = [[__time, __new_XETH, __new_eur_fund, __new_shares, __current_costs, __asset_bid]]
            __balance_update_df = pd.DataFrame(__balance_update_vec, columns=self.__column_names)
            self.__balance_df = self.__balance_df.append(__balance_update_df)

            # write as csv file
            self.writeCSV(self.__balance_df)
            print(__balance_update_df)
            print(' ')

            self.asset_status = False

        else:
            print('Hast nix zu verkaufen')

        self.broker_status = False


    def idle(self):
        self.broker_status = True
        try:
            __balance_np = np.array(self.__balance_df.tail())
        except AttributeError:
            print('Broker muss noch initialisiert werden!')
        #
        if self.asset_status is True:
            __market_price = self.asset_market_ask()
        elif self.asset_status is False:
            __market_price = self.asset_market_bid()
        #
        __new_shares = __balance_np[-1,3]
        __new_assets = __new_shares*__market_price
        __new_eur_fund = __balance_np[-1,2]
        __current_costs = 0
        #
        # update time
        __time = self.getTime()
        #
        # alter status ist wie neuer balance vektor
        __balance_update_vec = [[__time, __new_assets, __new_eur_fund, __new_shares, __current_costs, __market_price]]
        __balance_update_df = pd.DataFrame(__balance_update_vec, columns=self.__column_names)
        self.__balance_df = self.__balance_df.append(__balance_update_df)

        # write as csv file
        self.writeCSV(self.__balance_df)

        print(__balance_update_df)
        print(' ')

        self.broker_status = False


    def virtual_balance(self):
        print(self.__balance_df.tail())


    def asset_balance(self):
        self.__balance_all = self.__k.query_private('Balance')
        balance_str = self.__balance_all['result'][self.__asset1]
        balance = float(balance_str)
        print(balance)

    def asset_market_bid(self):
        __market_bid = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['b']
        return float(__market_bid[0])

    def asset_market_ask(self):
        __market_ask = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['a']
        return float(__market_ask[0])

    def market_price(self):
        __market = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['c']
        return float(__market[0])

    def get_eur_funds(self):
        __eur_funds = self.__k.query_private('Balance')['result'][self.__asset2] # muss noch allgemein angepasst werden!
        return float(__eur_funds)

    def get_asset_funds(self):
        __asset_funds = self.__k.query_private('Balance')['result'][self.__asset1]
        return float(__asset_funds)

    def getTime(self):
        return int(time.time())

    def writeCSV(self,__df):
        __filename = self.__pair+'_balance.csv'
        pd.DataFrame.to_csv(__df,__filename)

    '''def __init__(self,input):
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

        self.__column_names = []

    def initialize(self):
        # check den asset_status von asset1:
        if self.get_asset1_balance() > self.get_asset2_balance():
            self.asset_status = True
        else:
            self.asset_status = False

        self.__column_names = ['Time stamp', self.__asset1 + ' shares', self.__asset2 +' shares', 'costs', 'Market_Price']
        self.__balance_df = pd.DataFrame([np.zeros(len(self.__column_names))], columns=self.__column_names)
        self.__balance_df['Time stamp'] = self.getTime()
        self.__balance_df[self.__asset2] = self.get_asset2_balance()
        self.__balance_df[self.__asset1] = self.get_asset1_balance()
        self.__balance_df['Market_Price'] = self.market_price()

        print(self.__balance_df)

    def buy_order(self):
        self.broker_status = True
        # check den Euro status
        __current_asset2_funds = self.get_asset2_balance()

        # diese if abfrage ist ein double check
        if self.asset_status is False:
            #######################
            # kraken query
            __volume=str(__current_asset2_funds*0.99)
            __api_params = {'pair': self.__asset2+self.__asset1, 'type':'sell',
                            'ordertype':'market','volume':__volume, 'trading_agreement': 'agree'}
            __order = self.__k.query_private('AddOrder',__api_params)

            #__order_id = __order...
            # IMPORTANT: check if order is still open!
            self.__check_order(__order)
            #######################

        # update the balance sheet
        # KOSTEN STIMMEN NOCH NICHT!!
        self.update_balance(0)

        self.asset_status = True
        self.broker_status = False

    def sell_order(self):
        self.broker_status = True
        #__asset1_ask = self.asset1_market_ask()
        __current_asset1_funds = self.get_asset1_balance()

        # diese if abfrage ist ein double check
        if self.asset_status is True:
            #######################
            # kraken query
            __volume=str(__current_asset1_funds*0.99)
            __api_params = {'pair': self.__pair, 'type':'sell',
                            'ordertype':'market','volume': __volume, 'trading_agreement': 'agree'}
            __order = self.__k.query_private('AddOrder', __api_params)

            # IMPORTANT: check if order is still open!
            self.__check_order(__order)
            #######################

        # update the balance sheet
        # KOSTEN STIMMEN NOCH NICHT!!
        self.update_balance(0)

        self.asset_status = False
        self.broker_status = False

    def idle(self):
        self.broker_status = True
        try:
            __balance_np = np.array(self.__balance_df.tail())
        except AttributeError:
            print('Broker muss noch initialisiert werden!')
        #
        # update the balance sheet
        self.update_balance(0)

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

    def update_balance(self,cost):
        # update time
        __time = self.getTime()
        __new_asset1 = self.get_asset1_balance()
        __new_asset2 = self.get_asset2_balance()
        __market_price = self.market_price()
        __costs = cost

        __balance_update_vec = [[__time, __new_asset1, __new_asset2, __costs, __market_price]]
        __balance_update_df = pd.DataFrame(__balance_update_vec, columns=self.__column_names)
        self.__balance_df = self.__balance_df.append(__balance_update_df)

        # write as csv file
        self.writeCSV(self.__balance_df)
        print(' ')
        print(__balance_update_df)
        print(' ')

    def __check_order(self,order):
        __order = order
        __open_orders = self.__k.query_private('OpenOrders')
        __count = 0
        __cancle_flage = False

        while bool(__open_orders['results']['open']):
            __open_orders = self.__k.query_private('OpenOrders')
            __count += 1
            if __count > 20:
                print('Order was not filled!')
                __cancle_flage = True
                break
            time.sleep(20)
        print('Yeah! Order was placed!')

        if __cancle_flage is True:
            # canceln der Order wenn sie nach 400 sec nicht filled ist...
            print('Order should be cancelled')
'''




