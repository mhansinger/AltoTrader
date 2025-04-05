import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import csv

class plot_series(object):
    def __init__(self,asset1,asset2,short,long):
        '''the csv file you read in is sampled at 10min, thus short and long have to be adjusted for that'''
        self.asset1=asset1
        self.asset2=asset2
        self.short=short
        self.long=long
        self.filename=asset1+asset2+'_balance.csv'
        self.data_df=[]

    def readData(self,path='/../',N=200):
        '''N is the number of data points to plot'''

        # checks the number of rows
        with open(path+self.filename, "r") as f:
            reader = csv.reader(f, delimiter=",")
            data = list(reader)
            row_count = len(data)

        # when reading in the data only the last rows will be read in
        self.data_df = pd.read_csv(path+self.filename, skiprows=row_count - N)

    def plot_rollings(self):

        self.readData()
        market = self.data_df['Market Price']

        timeStamp = self.data_df['Time stamp'][-1:]

        short_mean = market.rolling(self.short).mean()
        long_mean = market.rolling(self.long).mean()

        N=len(market)
        xticks=np.linspace(-N,0,N)
        # set up the figure environment
        plt.figure(1)
        plt.plot(market,lw=1.5,color='black')
        plt.plot(long_mean,lw=1.5,color='blue')
        plt.plot(short_mean,lw=1.5,color='red')
        plt.title('Course data at: '+timeStamp)
        plt.xticks(xticks)
        plt.xlabel('Back in time from now [10 min]')
        plt.ylabel(self.asset1+'-'+self.asset2+' course')

        # save the plot
        plt.savefig(self.asset1+self.asset2+'_plot.png')


