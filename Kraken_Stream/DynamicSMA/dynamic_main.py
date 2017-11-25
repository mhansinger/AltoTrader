import sys
import numpy as np

from dynamicSMA import dynamicSMA
import threading

XXBTZUSD_dynamic = dynamicSMA('XXBT','ZUSD',length=28800,investment=1000.0, transaction_fee=0.002)

# run twice a day: 43200 seconds

def main(interval=43200):
    # introduce a bit of randomness in the parameter choice
    startlong = 750 + 5 * np.random.randint(10)
    stoplong = 1500
    longinterval = 50
    startshort = 250 + 5 * np.random.randint(10)
    stopshort = 650
    shortinterval = 20
    try:
        XXBTZUSD_dynamic.optimizeSMA(startlong,stoplong,longinterval,startshort,stopshort,shortinterval)
        t = threading.Timer(interval, main)
        t.start()
    except:
        print("Fehler: ", sys.exc_info()[0])
        print('Wird erneut gestartet...\n')
        main()


if __name__ == "__main__":
    main()