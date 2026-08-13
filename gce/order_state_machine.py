"""Order State Machine - Validates state transitions."""

from enum import Enum
from typing import Set, Tuple


class OrderState(Enum):
    """Order lifecycle states."""
    NEW = "NEW"
    LIVE = "LIVE"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILL = "FILL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class OrderStateMachine:
    """Manages valid order state transitions."""
    
    # Define valid transitions: from_state -> set of valid to_states
    VALID_TRANSITIONS = {
        OrderState.NEW: {OrderState.LIVE, OrderState.REJECTED, OrderState.CANCELLED},
        OrderState.LIVE: {OrderState.PARTIAL_FILL, OrderState.FILL, OrderState.CANCELLED},
        OrderState.PARTIAL_FILL: {OrderState.FILL, OrderState.CANCELLED, OrderState.PARTIAL_FILL},
        OrderState.FILL: {OrderState.CLOSED},
        OrderState.CANCELLED: {OrderState.CLOSED},
        OrderState.REJECTED: {OrderState.CLOSED},
        OrderState.CLOSED: set(),  # Terminal state
    }
    
    @staticmethod
    def is_valid_transition(from_state: OrderState, to_state: OrderState) -> bool:
        """Check if state transition is valid."""
        return to_state in OrderStateMachine.VALID_TRANSITIONS.get(from_state, set())
    
    @staticmethod
    def get_valid_next_states(current_state: OrderState) -> Set[OrderState]:
        """Get all valid next states from current state."""
        return OrderStateMachine.VALID_TRANSITIONS.get(current_state, set())
    
    @staticmethod
    def transition(from_state: OrderState, to_state: OrderState) -> Tuple[bool, str]:
        """
        Attempt state transition with validation.
        
        Returns:
            (success: bool, message: str)
        """
        if from_state == to_state:
            return True, f"Already in state {from_state.value}"
        
        if not OrderStateMachine.is_valid_transition(from_state, to_state):
            valid_states = OrderStateMachine.get_valid_next_states(from_state)
            valid_names = ', '.join([s.value for s in valid_states])
            return False, f"Invalid transition: {from_state.value} -> {to_state.value}. Valid states: {valid_names}"
        
        return True, f"Transition valid: {from_state.value} -> {to_state.value}"
