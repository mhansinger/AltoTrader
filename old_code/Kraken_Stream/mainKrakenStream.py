import pandas as pd
import numpy as np
import krakenex
import time
import threading
import sys

from krakenStream import krakenStream

XETH_stream = krakenStream('XETH','XXBT')

def run_update(interval=60):
    try:
        XETH_stream.updateHist()
        threading.Timer(interval, run_update).start()
    except:
        print("Fehler: ", sys.exc_info()[0])
        print('Wird erneut gestartet...\n')
        run_update()

def writeUpdate(interval=600):
    try:
        XETH_stream.writeHist()
        threading.Timer(interval, writeUpdate).start()
    except:
        print("Fehler: ", sys.exc_info()[0])
        print('Wird erneut gestartet...\n')
        writeUpdate()

print('execute run_update() and writeUpdate() your own, if sure about asset pairs!')

