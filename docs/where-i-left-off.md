An order can be sent to TWS but not transmitted to the IB server by setting the Order.Transmit flag in the order class to False. Untransmitted orders will only be available within that TWS session (not for other usernames) and will be cleared on restart. Also, they can be cancelled or transmitted from the API but not viewed while they remain in the “untransmitted” state.

prod geht, demo nicht.
Gateway settings vergleichen

zwischen 11:07 und 11:11 muss die order ausgeführt worden sein - steht was im log?