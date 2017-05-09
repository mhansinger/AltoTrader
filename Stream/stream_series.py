
import numpy as np
import pandas as pd
import urllib.request
from datetime import datetime
import threading
import time

current_time = time.strftime("%m.%d.%y_%H:%M", time.localtime())

class stream_series(threading.Thread):
    def __init__(self, asset1, asset2, timeInterval=600):
        threading.Thread.__init__(self)
        self.iterations = 0
        self.daemon = True  # OK for main to exit even if instance is still running
        self.paused = True  # start out paused
        self.state = threading.Condition()
        __URL_raw = 'http://zeiselmair.de/h4ckamuenster/'

        self.asset1 = asset1
        self.asset2 = asset2
        self.combination = self.asset1 + self.asset2
            # erweitern für Kombinationen

        self.URL = __URL_raw + self.combination +'.txt'
        self.timeInteval = timeInterval

    def __txtload(self):
        ## saves the data as raw time series
        urllib.request.urlretrieve(self.URL, 'raw_series.txt')

        # series array
        series_array = np.loadtxt('raw_series.txt')
        # series_array = series_array.transpose()
        series_df = pd.DataFrame(series_array, columns=['Time stamp', 'Price'])
        series_df = series_df.set_index(['Time stamp'])
        # In this case its hard coded as ETH --> sollte noch geändert werden
        pd.DataFrame.to_csv(series_df, self.combination+'_Series.csv')

    def run(self):
        self.resume() # unpause self
        while True:
            with self.state:
                if self.paused:
                    self.state.wait() # block until notified
            self.__txtload()
            print('last download at: ' + str(datetime.now()))
            time.sleep(self.timeInteval)
            self.iterations += 1

    def resume(self):
        with self.state:
            self.paused = False
            self.state.notify()  # unblock self if waiting

    def pause(self):
        with self.state:
            self.paused = True  # make self block and wait
        print('Stream is currently paused!')
