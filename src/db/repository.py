from sqlalchemy.orm import Session
from sqlalchemy import func
from .models import Execution, ShadowPosition, SyncState, Order, IBContract, Position, PositionLot
from typing import List, Optional, Dict
from datetime import datetime

class Repository:
    def __init__(self, db: Session):
        self.db = db

    def save_contract(self, contract_data: Dict) -> IBContract:
        """Upsert a contract."""
        con_id = contract_data.get('con_id')
        if not con_id:
            return None
            
        existing = self.db.query(IBContract).filter(IBContract.con_id == con_id).first()
        
        if existing:
            for key, value in contract_data.items():
                if hasattr(existing, key):
                     setattr(existing, key, value)
            existing.last_update_time = datetime.now()
            existing.last_seen = datetime.now()
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            if 'last_update_time' not in contract_data:
                contract_data['last_update_time'] = datetime.now()
            if 'last_seen' not in contract_data:
                contract_data['last_seen'] = datetime.now()
            contract = IBContract(**contract_data)
            self.db.add(contract)
            self.db.commit()
            self.db.refresh(contract)
            return contract

    def update_contract_last_seen(self, con_id: int):
        """Updates the last_seen timestamp for a contract."""
        existing = self.db.query(IBContract).filter(IBContract.con_id == con_id).first()
        if existing:
            existing.last_seen = datetime.now()
            self.db.add(existing)
            self.db.commit()

    def get_contract(self, con_id: int) -> Optional[IBContract]:
        return self.db.query(IBContract).filter(IBContract.con_id == con_id).first()

    def save_execution(self, exec_data: Dict) -> Execution:
        """Upsert of an execution."""
        exec_id = exec_data.get('exec_id')
        if not exec_id:
            return None

        existing = self.db.query(Execution).filter(Execution.exec_id == exec_id).first()
        if existing:
            # Update existing if fields changed
            for key, value in exec_data.items():
                if hasattr(existing, key):
                     setattr(existing, key, value)
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        
        execution = Execution(**exec_data)
        self.db.add(execution)
        self.db.commit()
        self.db.refresh(execution)
        return execution

    def save_order(self, order_data: Dict) -> Order:
        """Upsert an order."""
        # Check if order exists by perm_id
        perm_id = order_data.get('perm_id')
        if not perm_id:
             # Should not happen if perm_id is primary key
             return None
             
        existing = self.db.query(Order).filter(Order.perm_id == perm_id).first()
        
        if existing:
            # Update existing
            for key, value in order_data.items():
                if hasattr(existing, key):
                     setattr(existing, key, value)
            existing.last_update_time = datetime.now()
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            # New Order
            if 'last_update_time' not in order_data:
                order_data['last_update_time'] = datetime.now()
                
            order = Order(**order_data)
            self.db.add(order)
            self.db.commit()
            self.db.refresh(order)
            return order

    def get_orders(self, account_id: str = None) -> List[Order]:
        query = self.db.query(Order)
        if account_id:
            query = query.filter(Order.account_id == account_id)
        return query.all()


    def get_executions(self, account_id: Optional[str] = None, limit: int = 100) -> List[Execution]:
        query = self.db.query(Execution)
        if account_id:
            query = query.filter(Execution.account_id == account_id)
        
        query = query.order_by(Execution.time.desc())
        
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_shadow_positions(self, account_id: str) -> List[ShadowPosition]:
        return self.db.query(ShadowPosition).filter(ShadowPosition.account_id == account_id).all()

    def get_shadow_positions_by_bot(self, bot_id: str) -> List[ShadowPosition]:
        return self.db.query(ShadowPosition).filter(ShadowPosition.bot_instance_id == bot_id).all()

    def get_shadow_positions_with_contract_by_bot(self, bot_id: str) -> List[tuple]:
        """Returns list of (ShadowPosition, IBContract) tuples."""
        return self.db.query(ShadowPosition, IBContract).outerjoin(
            IBContract, ShadowPosition.con_id == IBContract.con_id
        ).filter(ShadowPosition.bot_instance_id == bot_id).all()

    def get_all_shadow_positions(self) -> List[ShadowPosition]:
        return self.db.query(ShadowPosition).all()

    def get_sync_state(self, account_id: str) -> Optional[SyncState]:
        return self.db.query(SyncState).filter(SyncState.account_id == account_id).first()

    def update_sync_state(self, account_id: str, last_flex_id: str = None, last_date: datetime = None, last_api_date: datetime = None):
        state = self.get_sync_state(account_id)
        if not state:
            state = SyncState(account_id=account_id)
            self.db.add(state)
        
        if last_flex_id:
            state.last_flex_sync_id = last_flex_id
        if last_date:
            state.last_flex_sync_date = last_date
        if last_api_date:
            state.last_api_sync_date = last_api_date
        
        self.db.commit()
        self.db.refresh(state)

    def apply_execution_overrides(self, overrides: Dict[int, str]):
        """
        Updates the order_ref in the executions table based on perm_id overrides.
        """
        if not overrides:
            return
            
        for perm_id, order_ref in overrides.items():
            # Update all executions with this perm_id
            self.db.query(Execution).filter(Execution.perm_id == perm_id).update({"order_ref": order_ref})
        
        self.db.commit()

    def recalc_shadow_positions(self, account_id: str, ignored_order_refs: List[str] = None):
        """
        Rebuilds the ShadowPosition table for an account by aggregating all executions.
        Groups by (bot_instance_id, symbol).
        """
        # 1. Clear existing positions for this account
        self.db.query(ShadowPosition).filter(ShadowPosition.account_id == account_id).delete()
        
        # 2. Get all executions
        executions = self.db.query(Execution).filter(Execution.account_id == account_id).order_by(Execution.time.asc()).all()
        
        # 3. Aggregate in memory (easier than complex SQL for FIFO/AvgCost if needed, 
        #    but for simple Net Position, SQL SUM is enough. For AvgCost we need iteration)
        
        positions = {} # Key: (bot_id, symbol, con_id) -> {quantity, cost_basis}

        for exc in executions:
            # Skip ignored order refs and empty values
            if (ignored_order_refs and exc.order_ref in ignored_order_refs) or not exc.order_ref or not str(exc.order_ref).strip():
                continue

            # Derive bot_instance_id: everything before the first colon if exists
            bot_instance_id = exc.order_ref.split(':')[0] if ':' in exc.order_ref else exc.order_ref
            
            con_id = exc.con_id
            key = (bot_instance_id, exc.symbol, con_id)
            
            if key not in positions:
                positions[key] = {"quantity": 0.0, "cost_basis": 0.0}
            
            qty = exc.quantity
            if exc.side == "SLD" or exc.side == "SELL": # Normalize side check
                qty = -abs(qty)
            else:
                qty = abs(qty)
            
            # Update
            positions[key]["quantity"] += qty
            # Simple Avg Cost calculation (Total Cost / Total Qty) is tricky with shorts/closing.
            # For now, let's just track Net Quantity. AvgCost requires robust matching logic.
            # We will leave avg_cost as 0.0 or implement simple weighted average later.
            
        # 4. Save new positions
        for (bot_instance_id, symbol, con_id), data in positions.items():
            if abs(data["quantity"]) > 1e-9: # Only store non-zero positions
                 pos = ShadowPosition(
                     account_id=account_id,
                     order_ref=bot_instance_id, # For aggregate, order_ref is the bot ID
                     bot_instance_id=bot_instance_id,
                     symbol=symbol,
                     con_id=con_id,
                     quantity=data["quantity"],
                     avg_cost=0.0 # Placeholder
                 )
                 self.db.add(pos)
        
        self.db.commit()
    def save_position(self, pos_data: Dict) -> Position:
        """Upsert a position."""
        account_id = pos_data.get('account_id')
        con_id = pos_data.get('con_id')
        if not account_id or not con_id:
            return None

        existing = self.db.query(Position).filter(
            Position.account_id == account_id,
            Position.con_id == con_id
        ).first()

        if existing:
            for key, value in pos_data.items():
                if hasattr(existing, key):
                     setattr(existing, key, value)
            existing.last_update_time = datetime.now()
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            if 'last_update_time' not in pos_data:
                pos_data['last_update_time'] = datetime.now()
            position = Position(**pos_data)
            self.db.add(position)
            self.db.commit()
            self.db.refresh(position)
            return position

    def save_position_lot(self, lot_data: Dict) -> PositionLot:
        """Upsert a position lot."""
        lot_id = lot_data.get('lot_id')
        if not lot_id:
            return None

        existing = self.db.query(PositionLot).filter(PositionLot.lot_id == lot_id).first()
        if existing:
            for key, value in lot_data.items():
                if hasattr(existing, key):
                     setattr(existing, key, value)
            self.db.add(existing)
            self.db.commit()
            self.db.refresh(existing)
            return existing
        else:
            lot = PositionLot(**lot_data)
            self.db.add(lot)
            self.db.commit()
            self.db.refresh(lot)
            return lot

    def get_positions(self, account_id: str = None) -> List[Position]:
        query = self.db.query(Position)
        if account_id:
            query = query.filter(Position.account_id == account_id)
        return query.all()

    def get_position_lots(self, account_id: str, con_id: int) -> List[PositionLot]:
        return self.db.query(PositionLot).filter(
            PositionLot.account_id == account_id,
            PositionLot.con_id == con_id
        ).all()
