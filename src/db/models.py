from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean
from .database import Base

class Execution(Base):
    __tablename__ = "executions"

    exec_id = Column(String, primary_key=True, index=True) # IB ExecId (unique)
    account_id = Column(String, index=True)
    order_ref = Column(String, index=True) # Critical for Shadow Accounting
    time = Column(DateTime)
    symbol = Column(String, index=True)
    side = Column(String) # 'BOT' (Buy) or 'SLD' (Sell)
    quantity = Column(Float) # shares in API
    price = Column(Float)
    con_id = Column(Integer, index=True, nullable=True)
    perm_id = Column(Integer, index=True, nullable=True) # ibOrderID in Flex
    exchange = Column(String, nullable=True)
    
    # API specific fields
    order_id = Column(Integer, nullable=True)
    client_id = Column(Integer, nullable=True)
    liquidation = Column(Integer, nullable=True)
    cum_qty = Column(Float, nullable=True)
    avg_price = Column(Float, nullable=True)
    ev_rule = Column(String, nullable=True)
    ev_multiplier = Column(Float, nullable=True)
    model_code = Column(String, nullable=True)
    last_liquidity = Column(Integer, nullable=True)
    pending_price_revision = Column(Boolean, nullable=True)
    submitter = Column(String, nullable=True) # traderID in Flex
    
    # Flex specific extras
    commission = Column(Float, nullable=True)
    commission_currency = Column(String, nullable=True)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class ShadowPosition(Base):
    __tablename__ = "shadow_positions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    account_id = Column(String, index=True)
    order_ref = Column(String, index=True) 
    bot_instance_id = Column(String, index=True) # derived from order_ref (e.g. part before colon)
    symbol = Column(String, index=True)
    con_id = Column(Integer, index=True, nullable=True)
    quantity = Column(Float) # Net share count
    avg_cost = Column(Float) 

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class SyncState(Base):
    __tablename__ = "sync_state"

    account_id = Column(String, primary_key=True, index=True)
    last_flex_sync_id = Column(String, nullable=True) # ReferenceCode of last successful flex query
    last_flex_sync_date = Column(DateTime, nullable=True)
    last_api_sync_date = Column(DateTime, nullable=True) # Last time API sync ran
    last_execution_time = Column(DateTime, nullable=True) # For API catch-up

class Order(Base):
    __tablename__ = "orders"

    perm_id = Column(Integer, primary_key=True, index=True) # Unique IB PermId
    client_order_id = Column(Integer, nullable=True)        # Transient, for debugging
    account_id = Column(String, index=True)
    order_ref = Column(String, index=True)                  # Vital for Strategy linking
    
    con_id = Column(Integer, index=True)
    symbol = Column(String)
    sec_type = Column(String)
    exchange = Column(String, nullable=True)
    
    action = Column(String)                                 # 'BUY' / 'SELL'
    order_type = Column(String)                             # 'LMT' / 'MKT'
    total_quantity = Column(Float)
    
    lmt_price = Column(Float, nullable=True)
    aux_price = Column(Float, nullable=True)
    
    status = Column(String)                                 # 'Submitted', 'Filled', 'Cancelled', 'Inactive'
    filled_quantity = Column(Float, default=0.0)
    remaining_quantity = Column(Float, default=0.0)
    avg_fill_price = Column(Float, nullable=True)
    
    order_time = Column(DateTime, nullable=True)
    last_update_time = Column(DateTime)                     # System time of last update

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class IBContract(Base):
    __tablename__ = "contracts"

    con_id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, index=True)
    sec_type = Column(String)
    last_trade_date_or_contract_month = Column(String, nullable=True)
    strike = Column(Float, nullable=True)
    right = Column(String, nullable=True)
    multiplier = Column(String, nullable=True)
    exchange = Column(String, nullable=True)
    currency = Column(String, nullable=True)
    local_symbol = Column(String, index=True, nullable=True)
    trading_class = Column(String, nullable=True)
    long_name = Column(String, nullable=True)
    market_name = Column(String, nullable=True)
    last_update_time = Column(DateTime)
    last_seen = Column(DateTime, nullable=True)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}



class Position(Base):
    __tablename__ = "positions"

    account_id = Column(String, primary_key=True)
    con_id = Column(Integer, primary_key=True)
    symbol = Column(String, index=True)
    underlying = Column(String, index=True, nullable=True)
    sec_type = Column(String)
    currency = Column(String)
    position = Column(Float)
    avg_cost = Column(Float)
    mkt_price = Column(Float, nullable=True)
    mkt_value = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, nullable=True)
    realized_pnl = Column(Float, nullable=True)
    last_update_time = Column(DateTime)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}

class PositionLot(Base):
    __tablename__ = "position_lots"

    lot_id = Column(String, primary_key=True) # originatingTransactionID
    account_id = Column(String, index=True)
    con_id = Column(Integer, index=True)
    quantity = Column(Float)
    avg_price = Column(Float)
    open_date_time = Column(DateTime)

    def to_dict(self):
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}
