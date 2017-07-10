import pandas as pd
import numpy as np
#import matplotlib.pyplot as plt
import sys

from Backtest_reinvest import SMAreinvest

#Asset1 = raw_input("Enter asset nr 1 (zB: XETH): ")
#Asset2 = raw_input("Enter asset nr 2 (zB: XXBT): ")

XXMR_raw = pd.read_csv('XXMR_Series.csv')
XXMR_series = pd.Series(XXMR_raw.V2)

XXMR_backtest = SMAreinvest(XXMR_series)

data, long, short = XXMR_backtest.optimize_SMAcrossover(900,1100,50,400,450,20)

