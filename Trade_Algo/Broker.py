'''
This is the Broker class.
The Broker connects with the Kraken account and does the trades

@author: mhansinger 
'''

# TODO: setter method to update the long and short windwos

import numpy as np
import pandas as pd
import krakenex
import time
import os.path

from Twitter_Bot.twitterEngine import twitterEngine

class Broker(object):
    def __init__(self,input):
        self.__asset1 = input.asset1
        self.__asset2 = input.asset2
        self.__pair = input.asset1+input.asset2
        self.__asset_status = False
        self.broker_status = False
        self.__k = krakenex.API()
        self.__k.load_key('kraken.key')
        self.__asset1_funds = []
        self.__asset2_funds = []
        self.__balance_all = []
        self.__balance_df = []
        self.lastbuy = 0
        self.order_id_sell = self.order_id_buy = []
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

        # checks if there aready exists a balance sheet as .csv
        if (os.path.exists(self.__pair+'_balance.csv')):
            print(self.__pair+'_balance.csv exists \n')
            old_df = pd.read_csv(self.__pair+'_balance.csv')
            old_df = old_df.drop('Unnamed: 0',1)
            self.__column_names = ['Time stamp', self.__asset1, self.__asset2, 'Buy/Sell', 'Market Price', 'Order Id']
            self.__balance_df = old_df
        else:
            #sets up a new, empty data frame for the balance
            self.__column_names = ['Time stamp', self.__asset1, self.__asset2, 'Buy/Sell', 'Market Price', 'Order Id']
            self.__balance_df = pd.DataFrame([np.zeros(len(self.__column_names))], columns=self.__column_names)
            self.__balance_df['Time stamp'] = self.getTime()
            self.__balance_df[self.__asset2] = self.get_asset2_balance()
            self.__balance_df[self.__asset1] = self.get_asset1_balance()
            self.__balance_df['Buy/Sell'] = '-'
            self.__balance_df['Market Price'] = self.market_price()
            self.__balance_df['Order Id'] = '-'

        print(self.__balance_df.tail())

    def buy_order(self):
        # executes a buy order

        self.__set_broker_status(True)
        self.asset_check()
        # check den XBT balance
        current_asset2_funds = self.get_asset2_balance()

        # diese if abfrage ist ein double check
        if self.__asset_status is False:
            #######################
            # kraken query
            # wir können keine Verkaufsorder auf XBT-basis setzen, sondern nur ETH kaufen.
            # Deshalb: Limit order auf Basis des aktuellen Kurses und Berechnung des zu kaufenden ETH volumens.
            volume2 = current_asset2_funds
            ask = self.asset_market_ask()
            volume1 = round(((volume2 / ask) *0.999 ),5)
            vol_str = str(round(volume1,5))     #round -> kraken requirement
            ask_str = str(ask)

            # limit order in test phase
            api_params = {'pair': self.__pair,
                            'type':'buy',
                            'ordertype':'limit',    #'market',
                            'price': ask_str,
                            'volume': vol_str,
                            'trading_agreement':'agree'}
            # order wird rausgeschickt!
            self.order = self.__k.query_private('AddOrder',api_params)

            try:
                self.order_id_buy = self.order['result']['txid'][0]
                #print(self.order_id_buy)
                #######################
                # IMPORTANT: check if order is still open!
                isfilled = self.check_order(self.order_id_buy)
                #print(isfilled)
                #print(self.order_id_buy)
                #######################
            except KeyError:
                isfilled=False
                print('Probably not enough funding...')


            if isfilled is True:
                # store the last buy price, to compare with sell price
                # noch checken
                closed = self.__k.query_private('ClosedOrders')['result']['closed']
                self.lastbuy = float(closed[self.order_id_buy]['price'])

                # update the balance sheet with buy/sell price
                self.update_balance(self.lastbuy,self.order_id_buy)
            else:
                print('No order placed, asset status is: ', self.get_broker_status())
                self.update_balance('-', '-')

            # change the asset status ! redundant
            self.asset_check()

        self.__set_broker_status(False)


    def sell_order(self):
        # executes a sell order -> buy BTC for ETH usually

        self.__set_broker_status(True)
        bid = str(self.asset_market_bid())
        current_asset1_funds = self.get_asset1_balance()
        self.asset_check()
        # diese if abfrage ist ein double check
        if self.__asset_status is True:
            #######################
            # kraken query: what's our stock?
            volume = str(round((current_asset1_funds*0.999),5))

            api_params = {'pair': self.__pair,
                            'type':'sell',
                            'ordertype':'limit', #'market',
                            'price': bid,
                            'volume': volume,
                            'trading_agreement': 'agree'}
            # order wird rausgeschickt!
            self.order = self.__k.query_private('AddOrder', api_params)

            try:
                self.order_id_sell = self.order['result']['txid'][0]
                # check
                # print(self.order_id_sell)
                #######################s
                # IMPORTANT: check if order is still open!
                isfilled = self.check_order(self.order_id_sell)
                # check
                #print(isfilled)
                #print(self.order_id_sell)
                #######################
            except KeyError:
                isfilled = False
                print('Probably not enough funding...')

            if isfilled is True:
                # update the balance sheet with transaction costs
                closed = self.__k.query_private('ClosedOrders')['result']['closed']
                price = float(closed[self.order_id_sell]['price'])
                self.update_balance(price, self.order_id_sell)

                #######################
                # DAS SOLLTE IN EINE METHODE GEBAUT WERDEN
                # checkt ob niedriger verkauft wird als gekauft
                if self.lastbuy > price:
                    print('Bad Deal!\n SELL < BUY\n')
                elif self.lastbuy < price:
                    print('GREAT Deal!\n SELL > BUY\n')

                # twitters, if enabled: setTwitter(True)
                if self.__twitter:
                    self.setTweet(self.lastbuy,price)
                #######################
            else:
                print('No order placed, asset status is: ',self.get_broker_status())
                self.update_balance('-', '-')

            # change the asset status!
            self.asset_check()

        self.__set_broker_status(False)


    def idle(self):
        self.__set_broker_status(True)
        try:
            __balance_np = np.array(self.__balance_df.tail())
        except AttributeError:
            print('Broker muss noch initialisiert werden!\n')
        #
        # update the balance sheet
        self.update_balance('-','-')

        self.__set_broker_status(False)

###################################
# Weitere member functions:

    def get_broker_status(self):
        return self.broker_status

    def __set_broker_status(self,status):
        self.broker_status=status

    def get_asset_status(self):
        # habe ich ETH oder nicht, bin ich im Markt: True or False
        return self.__asset_status

    def __set_asset_status(self,status):
        self.__asset_status = status

    def getTime(self):
        #return int(time.time())
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

    def asset_balance(self):
        self.__balance_all = self.__k.query_private('Balance')
        balance_str = self.__balance_all['result'][self.__asset1]
        balance = float(balance_str)
        print(balance)

    def asset_market_bid(self):
        market_bid = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['b']
        return round(float(market_bid[0]), 5)

    def asset_market_ask(self):
        market_ask = self.__k.query_public('Ticker',{'pair': self.__pair})['result'][self.__pair]['a']
        return round(float(market_ask[0]), 5)

    def market_price(self):
        market = self.__k.query_public('Ticker', {'pair': self.__pair})['result'][self.__pair]['c']
        return round(float(market[0]), 5)

    def get_asset2_balance(self):
        # unsere XBT
        asset2_funds = self.__k.query_private('Balance')['result'][self.__asset2]
        return round(float(asset2_funds), 5)

    def get_asset1_balance(self):
        # unsere ETH
        asset1_funds = self.__k.query_private('Balance')['result'][self.__asset1]
        return round(float(asset1_funds), 5)

    def update_balance(self, price, id):
        # update time
        time = self.getTime()
        new_asset1 = self.get_asset1_balance()
        new_asset2 = self.get_asset2_balance()
        market_price = self.market_price()

        balance_update_vec = [[time, new_asset1, new_asset2, price, market_price, id]]
        balance_update_df = pd.DataFrame(balance_update_vec, columns=self.__column_names)
        self.__balance_df = self.__balance_df.append(balance_update_df)

        # write as csv file
        self.writeCSV(self.__balance_df)
        print(balance_update_df)

        # schreibt die beiden .txt für den online upload
        self.__writeTXT(new_asset1, new_asset2)


    def check_order(self,order_id):
        #IMPORTANT: checks if your order was filled after some time! If not -> cancel
        print('Checking the Order')
        count = 0
        cancel_flag = False
        open_orders = self.__k.query_private('OpenOrders')['result']['open']

        # check if the order id appears in the OpenOrders list

        # BOOLEAN check
        while bool(order_id in open_orders) is True:
            print('Order is still open ... ')
            open_orders = self.__k.query_private('OpenOrders')['result']['open']
            count += 1
            #cancel the order if not filled after 10 checks
            if count > 10:
                cancel_flag = True
                break
            # repeat check after 30 seconds
            time.sleep(30)

        if cancel_flag is True:
            # cancle the order
            self.__k.query_private('CancelOrder', {'txid': order_id})
            print('Order was not filled and canceled!\n')
            isfilled=False
        else:
            print('Success: Order was filled!\n')
            isfilled=True

        return isfilled


    # schreibt ein CSV raus
    def writeCSV(self,df):
        filename = self.__pair+'_balance.csv'
        pd.DataFrame.to_csv(df,filename)

    def our_balance(self):
        print(self.__balance_df.tail())

    def asset_check(self):
        # checks the assets on our account and sets the asset_status
        asset1 = self.get_asset1_balance()
        asset2 = self.get_asset2_balance()
        marketP = self.market_price()
        # normalize the price
        asset2_norm = asset2/marketP
        # 95% off total volume on asset1 side, which is usually ETH
        if asset1 > (asset2_norm)*0.95:
            self.__asset_status = True
        else:
            self.__asset_status = False

    # speichert die aktuellen asset1 und asset2 Werte der Krake raus, für weiteren Upload
    def __writeTXT(self,asset1,asset2):
        asset_balance_1 = round(asset1,3)
        asset_balance_2 = round(asset2,3)
        filename1 = self.__asset1+'.txt'
        filename2 = self.__asset2+'.txt'
        with open(filename1, "w") as text_file:
            text_file.write('%s' % asset_balance_1)
        with open(filename2, "w") as text_file:
            text_file.write('%s' % asset_balance_2)

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

    def getAsset1(self):
        return str(self.__asset1)

    def getAsset2(self):
        return str(self.__asset2)
