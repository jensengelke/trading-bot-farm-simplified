Es wird frühzeitig einmal 
2026-04-20 10:05:53,956 [INFO] fkk-2015-5: All option contracts resolutions requests are done.
rausgeschrieben.

dann kommen noch 2 callbacks für tick....computation

ich vermute, dass die liste der offenen requests falsch maintained wird. Ich brauche ggf. mehr listen und mehr variablen, um die option chain requests von den spread requests zu trennen.


Select an option: Exception in thread Thread-2 (run):
Traceback (most recent call last):
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.3312.0_x64__qbz5n2kfra8p0\Lib\threading.py", line 1044, in _bootstrap_inner
    self.run()
    ~~~~~~~~^^
  File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.3312.0_x64__qbz5n2kfra8p0\Lib\threading.py", line 995, in run
    self._target(*self._args, **self._kwargs)
    ~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\git\trading-bot-farm-simplified\venv\Lib\site-packages\ibapi\client.py", line 442, in run
    self.decoder.interpret(fields, msgId)
    ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^
  File "C:\git\trading-bot-farm-simplified\venv\Lib\site-packages\ibapi\decoder.py", line 1580, in interpret
    handleInfo.processMeth(self, iter(fields))
    ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
  File "C:\git\trading-bot-farm-simplified\venv\Lib\site-packages\ibapi\decoder.py", line 81, in processTickPriceMsg
    self.wrapper.tickPrice(reqId, tickType, price, attrib)
    ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\git\trading-bot-farm-simplified\src\utils.py", line 27, in wrapper
    result = func(*args, **kwargs)
  File "C:\git\trading-bot-farm-simplified\src\ib_connection.py", line 148, in tickPrice
    listener.tick_price(reqId, tick_name, price, attrib)
    ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\git\trading-bot-farm-simplified\src\utils.py", line 27, in wrapper
    result = func(*args, **kwargs)
  File "C:\git\trading-bot-farm-simplified\src\bots\fkk\bot.py", line 407, in tick_price
    self.create_order()
    ~~~~~~~~~~~~~~~~~^^
  File "C:\git\trading-bot-farm-simplified\src\utils.py", line 27, in wrapper
    result = func(*args, **kwargs)
  File "C:\git\trading-bot-farm-simplified\src\bots\fkk\bot.py", line 379, in create_order
    spread_price = self.get_cached_price(self.spread_contract.conId).copy()
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'copy'