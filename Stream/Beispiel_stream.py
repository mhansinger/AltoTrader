
# kleines Beispiel zum Streamen

from stream_series import stream_series

Asset1 = 'XETH'
Asset2 = 'ZEUR'

ETH_stream = stream_series(Asset1, Asset2, 300)

ETH_stream.start()

# zum Pausieren:
#ETH_stream.pause()
