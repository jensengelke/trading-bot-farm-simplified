Based on the code in src/ib_connection.py, the current framework does not fully support maintaining different lists of global listeners for different types of data.

Here is how the framework currently handles listeners:

Global Broadcast List (self.listeners):
When you register a listener using register_listener(listener), it is appended to a single, global list. Every listener in this list is invoked for all global callback events. For example, when a tickPrice event occurs, the framework loops through all listeners in self.listeners and calls listener.tick_price(...). The same happens for open_order, order_status, etc. This means you cannot register 3 listeners only for tickPrice; they will also receive other callbacks like exec_details or position, and they must implement all those methods to avoid AttributeError exceptions.

Request-Specific Listeners (self.request_listeners):
The framework does have a way to isolate listeners for specific, targeted data requests. When using methods like request_contract_details or request_option_chain, you pass a specific listener instance. The framework maps the generated reqId to that listener in self.request_listeners. When the contractDetails callback fires for that reqId, it triggers only that specific listener. However, this is tied to the request ID, not the general data type, and is only implemented for a few async request methods.

Conclusion
If you want to have a pub/sub style architecture where you can subscribe 3 general listeners specifically to tickPrice events and 1 different listener specifically to contractDetails events, the framework would need to be modified.

To support this, register_listener would need to accept an event type parameter (e.g., register_listener("tickPrice", listener)) and store them in a dictionary mapping event types to lists of listeners (e.g., self.listeners: Dict[str, List[Any]]).

-----
I have two interactions between my bot via basebot to ibconnection that follow the same pattern:
basebot.resolve_contracts() and 
basebot.resolve_option_chain()

in both cases, ibconnection implements the EClient function from ibapi to send a request and keeps track of its caller.
ibconnection also implements the callback methods from ibapi's EWrapper and dispatches responses to the original requestor.

basebot has a "proxy method" and may aggregate data and finally call the bot's callback method.

I want two more of such interactions:
