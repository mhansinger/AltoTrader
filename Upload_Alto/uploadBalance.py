import numpy as np
import pandas as pd
import ftplib
import urllib.request
import time
import threading
from datetime import datetime


class uploadBalance(threading.Thread):
    '''
    Für den Upload der aktuellen Kurse auf die Website
    '''
    def __init__(self, asset1, asset2, initial, url=None, serverpath='/AT/', timeInterval=3600, user=None, password=None):
        threading.Thread.__init__(self)
        self.iterations = 0
        self.daemon = True  # OK for main to exit even if instance is still running
        self.paused = True  # start out paused
        self.state = threading.Condition()

        self.asset1 = asset1
        self.asset2 = asset2
        self.rendite = 0
        self.rendite_old=0
        self.initial = initial
        #self.filepath=filepath
        self.__user = user
        self.__pw = password
        self.serverpath = serverpath
        self.URL = url

        self.timeInteval = timeInterval

        #write rendite

# Fehler in fullserverpath

    def upload_to_ftp(self,asset):
        # Upload a file to ftp server
        # server: ftp server
        # filepath: local path of the file including its name
        # serverpath: path on ftp server WITHOUT preceding '/' and including name
        if self.__user == None or self.__pw == None or self.serverpath == None:
            print("Information missing. Aborting.")
            return
        filepath=asset+'.txt'
        session = ftplib.FTP(self.URL, self.__user, self.__pw)
        myfile = open(filepath, 'rb')
        fullserverpath=self.serverpath+asset+'.txt'
        session.storbinary('STOR' + fullserverpath, myfile)
        myfile.close()
        session.quit()

    def run(self):
        self.resume() # unpause self
        while True:
            with self.state:
                if self.paused:
                    self.state.wait() # block until notified
            #############################
            self.upload_to_ftp(self.asset1)
            self.upload_to_ftp(self.asset2)

            self.calcRendite()
            self.upload_to_ftp('rendite')
            #############################
            print('last upload at: ' + str(datetime.now()))
            time.sleep(self.timeInteval)
            self.iterations += 1

    def calcRendite(self):
        # calculates the rendite and writes a rendite.txt file
        asset1 = np.loadtxt(self.asset1+'.txt')
        if asset1 > 0.00001:
            self.rendite = ((asset1 - self.initial)/self.initial * 100)
            self.rendite = int(self.rendite)
            self.writeTXT(value=self.rendite,name='rendite')
        else:
            self.writeTXT(value=self.rendite_old,name='rendite')
        self.rendite_old = self.rendite

    def resume(self):
        with self.state:
            self.paused = False
            self.state.notify()  # unblock self if waiting

    def pause(self):
        with self.state:
            self.paused = True  # make self block and wait
        print('Stream is currently paused!')

    def writeTXT(self,value,name):
        __filename = name+'.txt'
        with open(__filename, "w") as text_file:
            text_file.write('%s' % value)

