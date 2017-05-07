
# kleines Beispiel zum Streamen

from stream_series import stream_series

URL = 'http://zeiselmair.de/h4ckamuenster/results_eth.txt'

ETH_stream = stream_series(URL,600)

ETH_stream.start()

# zum Pausieren:
#ETH_stream.pause()
