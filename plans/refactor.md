My project trading-bot-farm-simplified is a framework to run multiple trading bots using interactive brokers api (in c:\twsapi\source\pythonclient)
It encapsulates a connection to interactive brokers (IB) in src\ib_connection.py, which can then be used by multiple bots.
All bot types are sub-classes of src\bots\base_bot.py and multiple instances of each bot type can be configured by creating a file in config/default or config/demo, which holds some shared config in .config.yaml and per bot-instance config in dedicated yaml files.

IB's ibapi is asynchronous. The API client in ib_connection.py implements callback functions, whhich are invoked with responses from IB, but then need to dispatch to their own clients.

I have two bots and found they are doing very similar things, so I am trying to simplify the code and make it more reusable:
I want to refactor both bots and create a common utility class that encapsulates IB interactions to find options contracts.
There are multiple important aspects of option contract handling:
1. obtaining the option chain for a given underlying symbol
2. resolving contracts (my code can only provide some information about the exact options contract, such as right, strike, expiry, underlying), but the final contract ID is only known after a request to IB
3. selecting an option contract from a list of candidates based on criteria such as "right is put and delta is closest to 0.5". The delta requirement requires to temporarily subscribe to live market data for the candidate contracts and comparing their deltas after having received a value for each of the contracts.

I am looking for the best tradeoff from a programming model perspective. My new class will be "OptionsFinder" and should expose convenient methods like:
- get_option_chain() - should allow filtering by tradingclass and exchange
- find_option_contract_by_delta()
- find_atm_call() (ATM means at the money, that is, strike is closest to current underlying price)
- find_atm_put()
- find_later_contract() - used for rolling options to a later expiry or for setting up calendar spreads.

My calling bots have no need to store keep data about candidate contracts in their own variables, but I can see that it may be useful to e.g. get the option chain in a step that calls get_option_chain() and then use the result in a subsequent step to find a specific contract. So I am thinking of making the OptionsFinder class a singleton that can be accessed from anywhere in the code. I can also see that it may be useful to have a "context" object that is passed around to all steps in a bot, and that object contains the OptionsFinder instance as well as other data that is relevant for the bot.
It must be possible that multiple bots invoke OptionFinder at the same time and query either the same or independent data. OptionFinder should be efficient and respond from cache for "somewhat static information" (a resolved option chain for an underlying contract does not change within a day), but it should also ensure to fetch fresh data for e.g. prices and option_greeks.