import json
import os
import logging
from grapheneexchange import GrapheneExchange
from stakemachine.storage import Storage
log = logging.getLogger(__name__)


class MissingSettingsException(Exception):
    pass


class BaseStrategy():
    """ This is the base strategy that allows to share commonly used
        methods, such as sell, buy, borrow, cancel, and many more!

        The purpose of this class is to inherit or even overwrite some
        of this calls in your individual bots it required.

        .. note:: Each bot has it's own markets that it serves, hence,
                 we distinguish between `all` orders of a market that
                 are owned by an account and `mine` which are merely the
                 orders that have been created in a market by this bot
                 specifically. For this reasons, every bot stores it's
                 orders in a `json` file on the disk to be able to
                 distinguish its own orders from others!
    """

    def __init__(self, *args, **kwargs):
        self.state = {"orders" : {}}

        for arg in args :
            if isinstance(arg, GrapheneExchange):
                self.dex = arg
        for key in kwargs:
            setattr(self, key, kwargs[key])

        if "name" not in kwargs:
            raise MissingSettingsException("Missing parameter 'name'!")

        self.settings = self.config.bots[self.name]
        self.opened_orders = []
        self.storage = Storage(self.name, self.config)
        self.restore()

        if "markets" not in self.settings:
            raise MissingSettingsException("markets")

        # Finite State machinge for tracking
        self.fsm = "waiting"
        self.fsm_cnt = 0

    def _set(self, market, key, value):
        if market not in self.state:
            self.state[market] = {}
        self.state[market][key] = value

    def _get(self, market, key):
        if market not in self.state:
            self.state[market] = {}
            return None
        return self.state[market].get(key)

    def _cancel_set(self, toCancel):
        numCanceled = 0
        for orderId in toCancel:
            log.info("Canceling %s" % orderId)
            try:
                self.dex.cancel(orderId)
            except Exception as e:
                log.critical("An error occured while trying to sell: %s" % str(e))
            self.orderCanceled(orderId)
            for m in self.state["orders"]:
                if orderId in self.state["orders"][m]:
                    self.state["orders"][m].remove(orderId)
            numCanceled += 1
        return numCanceled

    def cancel_all(self, markets=None, side="both") :
        """ Cancel all the account's orders **of all market** including
            those orders of other bot instances

            :param str side: cancel only "sell", "buy", "both" side(s) (default: "both")
            :return: number of canceld orders
            :rtype: number

        """
        if not markets:
            markets = self.settings["markets"]
        curOrders = self.dex.returnOpenOrders()
        toCancel = set()
        for m in markets:
            if m in curOrders:
                for o in curOrders[m]:
                    if o["type"] is side or side is "both":
                        toCancel.add(o["orderNumber"])
        return self._cancel_set(toCancel)

    def cancel_mine(self, markets=None, side="both") :
        """ Cancel only the orders of this particular bot in all markets
            the bot serves.

            :param str side: cancel only "sell", "buy", "both" side(s) (default: "both")
            :return: number of canceld orders
            :rtype: number
        """
        if not markets:
            markets = self.settings["markets"]
        curOrders = self.dex.returnOpenOrders()
        state = self.getState()
        toCancel = set()
        for m in markets:
            for currentOrderStates in curOrders[m]:
                stateOrderId = currentOrderStates["orderNumber"]
                if m not in state["orders"]:
                    continue
                if stateOrderId in state["orders"][m]:
                    if currentOrderStates["type"] is side or side is "both":
                        toCancel.add(currentOrderStates["orderNumber"])
        return self._cancel_set(toCancel)

    def cancel_this_markets(self, markets=None, side="both") :
        """ Cancel all orders in all markets of that are served by this
            bot.

            :param str side: cancel only "sell", "buy", "both" side(s) (default: "both")
            :return: number of canceld orders
            :rtype: number
        """
        if not markets:
            markets = self.settings["markets"]
        orders = self.dex.returnOpenOrders()
        toCancel = set()
        for m in markets:
            for o in orders[m]:
                if o["type"] is side or side is "both":
                    toCancel.add(o["orderNumber"])
        return self._cancel_set(toCancel)

    def cancel_all_sell_orders(self):
        """ alias for ``self.cancel_all("sell")``
        """
        return self.cancel_all("sell")

    def cancel_all_buy_orders(self):
        """ alias for ``self.cancel_all("buy")``
        """
        return self.cancel_all("buy")

    def cancel_my_sell_orders(self):
        """ alias for ``self.cancel_mine("sell")``
        """
        return self.cancel_mine("sell")

    def cancel_my_buy_orders(self):
        """ alias for ``self.cancel_mine("buy")``
        """
        return self.cancel_mine("buy")

    def cancel_all_bid_orders(self):
        """ alias for ``self.cancel_all("buy")``
        """
        return self.cancel_all("buy")

    def cancel_all_ask_orders(self):
        """ alias for ``self.cancel_all("sell")``
        """
        return self.cancel_all("sell")

    def cancel_my_bid_orders(self):
        """ alias for ``self.cancel_my_buys()``
        """
        return self.cancel_my_buys()

    def cancel_my_ask_orders(self):
        """ alias for ``self.cancel_my_sells()``
        """
        return self.cancel_my_sells()

    def cancel(self, orderid):
        """ Cancel the order with id ``orderid``
        """
        log.info("Canceling %s" % orderid)
        try:
            cancel = self.dex.cancel(orderid)
        except Exception as e:
            log.critical("An error occured while trying to sell: %s" % str(e))
        return cancel

    def getState(self):
        """ Return the stored state of the bot. This includes the
            ``orders`` that have been placed by this bot
        """
        return self.state

    def setState(self, key, value):
        """ Set the full state

            :param str key: Key
            :param Object value: Value
        """
        self.state[key] = value

    def store(self):
        """ Evaluate the changes (orders) made by the bot and store the
            state on disk.
        """
        state = self.getState()
        myorders = state["orders"]
        curOrders = self.dex.returnOpenOrdersIds()
        for market in self.settings["markets"] :
            if market not in myorders:
                myorders[market] = []
            if market in curOrders:
                for orderid in curOrders[market] :
                    if market not in self.opened_orders or \
                            orderid not in self.opened_orders[market] :
                        myorders[market].append(orderid)
                        self.orderPlaced(orderid)

        state["orders"] = myorders
        if not self.config.safe_mode:
            self.storage.store(state)

    def restore(self):
        """ Restore the data stored on the disk
        """
        self.state = self.storage.restore()

    def loadMarket(self, notify=True):
        """ Load the markets and compare the stored orders with the
            still open orders. Calls ``orderFilled(orderid)`` for orders no
            longer open (i.e. fully filled)
        """
        #: Load Open Orders for the markets and store them for later
        self.opened_orders = self.dex.returnOpenOrdersIds()

        #: Have orders been matched?
        old_orders = self.getState()["orders"]
        cur_orders = self.dex.returnOpenOrdersIds()
        for market in self.settings["markets"] :
            if market in old_orders:
                for orderid in old_orders[market] :
                    if orderid not in cur_orders[market] :
                        # Remove it from the state
                        if orderid in self.state["orders"][market]:
                            self.state["orders"][market].remove(orderid)
                        # Execute orderFilled call
                        if notify :
                            self.orderFilled(orderid)

    def changeFSM(self, state):
        log.debug("Changing State to: %s" % state)
        self.fsm = state
        self.resetFSMCounter()

    def getFSM(self):
        return self.fsm

    def incrementFSMCounter(self):
        self.fsm_cnt += 1

    def resetFSMCounter(self):
        self.fsm_cnt = 0

    def getFSMCounter(self):
        return self.fsm_cnt

    def getMyOrders(self):
        """ Return open orders for this bot
        """
        myOrders = {}
        for market in self.settings["markets"] :
            if market in self.state["orders"]:
                myOrders[market] = self.state["orders"][market]
            else:
                myOrders[market] = []
        return myOrders

    def returnBalances(self):
        """ This is a wrapper for self.dex.returnBalances()
            that limits the amounts such that the reserves are always
            available in the account. The reserves are defined in the
            configuration with:

            ```
            reserves:
             - BTS: 1000
             - USD: 10
            ```
        """
        balances = self.dex.returnBalances()
        if not hasattr(self.config, "reserves"):
            return balances

        reserves = getattr(self.config, "reserves")
        for a in balances:
            balances[a] -= reserves.get(a, 0)
            if balances[a] < 0:
                balances[a] = 0.0
        return balances

    def sell(self, market, price, amount, expiration=60 * 60 * 24, **kwargs):
        """ Places a sell order in a given market (sell ``quote``, buy
            ``base`` in market ``quote_base``). Required POST parameters
            are "currencyPair", "rate", and "amount". If successful, the
            method will return the order creating (signed) transaction.

            :param str currencyPair: Return results for a particular market only (default: "all")
            :param float price: price denoted in ``base``/``quote``
            :param number amount: Amount of ``quote`` to sell

            Prices/Rates are denoted in 'base', i.e. the USD_BTS market
            is priced in BTS per USD.

            **Example:** in the USD_BTS market, a price of 300 means
            a USD is worth 300 BTS

            .. note::

                All prices returned are in the **reveresed** orientation as the
                market. I.e. in the BTC/BTS market, prices are BTS per BTS.
                That way you can multiply prices with `1.05` to get a +5%.
        """
        quote, base = market.split(self.config.market_separator)
        log.info(" - Selling %f %s for %f %s @%f %s/%s" % (amount, quote, amount * price, base, price, base, quote))
        try:
            self.dex.sell(market, price, amount, expiration, **kwargs)
        except Exception as e:
            log.critical("An error occured while trying to sell: %s" % str(e))
            return False
        return True

    def buy(self, market, price, amount, expiration=60 * 60 * 24, **kwargs):
        """ Places a buy order in a given market (buy ``quote``, sell
            ``base`` in market ``quote_base``). Required POST parameters
            are "currencyPair", "rate", and "amount". If successful, the
            method will return the order creating (signed) transaction.

            :param str currencyPair: Return results for a particular market only (default: "all")
            :param float price: price denoted in ``base``/``quote``
            :param number amount: Amount of ``quote`` to buy

            Prices/Rates are denoted in 'base', i.e. the USD_BTS market
            is priced in BTS per USD.

            **Example:** in the USD_BTS market, a price of 300 means
            a USD is worth 300 BTS

            .. note::

                All prices returned are in the **reveresed** orientation as the
                market. I.e. in the BTC/BTS market, prices are BTS per BTS.
                That way you can multiply prices with `1.05` to get a +5%.
        """
        quote, base = market.split(self.config.market_separator)
        log.info(" - Buying %f %s with %f %s @%f %s/%s" % (amount, quote, amount * price, base, price, base, quote))
        try:
            self.dex.buy(market, price, amount, expiration, **kwargs)
        except Exception as e:
            log.critical("An error occured while trying to sell: %s" % str(e))
            return False
        return True

    def init(self):
        """ Initialize the bot's individual settings
        """
        log.debug("Init. Please define `%s.init()`" % self.name)

    def place(self):
        """ Place orders
        """
        log.debug("Place order. Please define `%s.place()`" % self.name)

    def tick(self):
        """ Tick every block
        """
        log.debug("New block. Please define `%s.tick()`" % self.name)

    def asset_tick(self):
        """ Tick every block
        """
        log.debug("Asset Updated. Please define `%s.asset_tick()`" % self.name)

    def orderFilled(self, oid):
        """ An order has been fully filled

            :param str oid: The order object id
        """
        log.debug("Order Filled. Please define `%s.orderFilled(%s)`" % (self.name, oid))

#    def orderMatched(self, oid):
#        """ An order has been machted / partially filled
#
#            :param str oid: The order object id
#        """
#        log.debug("An order has been matched: %s" % oid)

    def orderPlaced(self, oid):
        """ An order has been placed

            :param str oid: The order object id
        """
        log.debug("New Order. Please define `%s.orderPlaced(%s)`" % (self.name, oid))

    def orderCanceled(self, oid):
        """ An order has been canceld

            :param str oid: The order object id
        """
        log.debug("Order Canceld. Please define `%s.orderCanceled(%s)`" % (self.name, oid))
