# AltoTrader

**Automated trading on the kraken exchange**

**Trained to inform you via Twitter on the latest trades**

## Introduction
This is a trading bot to perform automated trading on the kraken exchange via [Kraken's API](https://www.kraken.com/help/api). The bot requires Python 3 and a module called ``krakenex``. You can simply install it by running:

``pip3 install krakenex``

The trading strategy is based on the intersection of rolling means with different window width. Which window width is the best  highly depends on the traded asset pairs and the current market situation. Therefore, no recommendation on the windows can be given. 


## Step by Step

### 0. Kraken key
The magic of automated trading will only work out for you if you have a kraken account with funding. If not, create a [Kraken](https://www.kraken.com/) account, transfer some coins and generate an API key with the necessary rights:

``keykeykeykeykeykeykeykeykeykeykeykeykeykeykeykeykeykeykey
secretsecretsecretsecretsecretsecretsecretsecretsecretsecretsecretsecretsecretsecretsecret``

store the two keys in a file called ``kraken.key`` which you will need later. 


### 1. Asset pair
Decide which asset pair you would like to trade. In this example 'step by step' we assume you'd like to trade between Bitcoin and EUR, so the assets are:
``
asset1='XXBT'
asset2='ZEUR' 
``

### 2. Stream the market data
For the computation of rolling mean averages the trader will need historical market data. Therefore you have to establish a data base with historical market prices. Inside your trading directory, let's assume you called it ``XXBTZEUR``, create another directory called:
``XXBTZEUR_data``

This name is important and must contain the traded asset pair in the begining, as the trading enginge will search for this particular directory. Copy the content of [Stream](https://github.com/mhansinger/AltoTrader/tree/master/Stream) into it. Modify ``Beispiel_stream.py`` according to your asset pairs and run it. It will request the current market price from kraken exchange every minute and update your data base ``XXBTZEUR_Series.csv``every 10 minutes. Of course you can adjust that in the code, too.

### 3. Do some backtesting
Stream the market prices for some days (better: weeks) into your data base. You'll need to do a bit of backtesting now. Backtesting is crucial for the success of your trading strategy, as it provides you the best window widths to maximize your portfolio. However, this is only a good guess as all your knowledge is based on historical(!) data. There is absolutely no guarantee that the market will behave similarly in the future. So, repeat backtesting from time to time to verify your window widths, as in the end you want a care free life and be on the bright side of trader life, or not?

#### How to:

### 4. Set up the trading engine
Open another terminal and copy the Python files from [Trade_Algo](https://github.com/mhansinger/AltoTrader/tree/master/Trade_Algo) into your trading directory (e.g. ``XXBTZEUR``). Copy also the ``kraken.key`` into this directory. 
Have a look into the ``main.py`` file, change for the correct asset pairs and adjust the ``short`` and ``long`` window width in:

``XXBT_input = set_input(asset1='XXBT', asset2='ZEUR', long=100, short=47)``
Be sure to have somehow 'good' values for the windows, otherwise the trader will burn your coins easily. 

That's on your OWN RISK. 

### 4. (Optional) Set up Twitter engine
