import pandas as pd
import numpy as np

from dynamicSMA import dynamicSMA
from strategySMA import strategySMA

XETH_strategy = strategySMA()

XETH_dynamic = dynamicSMA(XETH_strategy,'XETH','XXBT')