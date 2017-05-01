# Object container for all input relevant data

class set_input():
    ''' 
        Input data-object
        to be continued ...
        @author: mhansinger
    '''
    def __init__(self,series_name='ETH_series.csv', long=1000, short=100, fee=0.0026, reinvest=0.9):
        self.series_name = series_name
        self.window_long = long
        self.window_short = short
        self.fee = fee
        self.reinvest = reinvest