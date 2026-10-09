"""FastEngine: a pure-Python mirror of the on-chain markets, used for Monte Carlo runs."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence

from tfs.core.types import Account, Bundle, Receipt, Side, Trade, Tx, Venue
from tfs.engines.base import Engine, EngineState, VenueState
from tfs.market.lmsr import LmsrMarket

# Floating-point slack when comparing an average price to a limit, or holdings to a sale.
_EPS = 1e-9

BUILDER_ID = "builder"  # account that receives transaction fees and tips


class EngineError(RuntimeError):
    """A programming error (e.g. unknown agent), as opposed to a reverted trade."""


class FastEngine(Engine):
    """Executes trades against one LMSR per venue and keeps agent accounts.

    Collateral is conserved: cash moves only between agent accounts, the
    builder's account (fees) and the venues' collateral, until resolution pays
    winning shares out of collateral. The market maker covers any shortfall, at
    most b·ln 2 per venue.

    Fees: every included trade pays `base_fee` plus its own `priority_fee` to
    the builder, even if the trade then reverts (as gas is paid on-chain). An
    atomic `Bundle` that reverts is not included, so it pays nothing.
    """

    def __init__(
        self, liquidity: Mapping[Venue, float], initial_cash: Mapping[str, float], base_fee: float = 0.0
    ) -> None:
        if BUILDER_ID in initial_cash:
            raise EngineError(f"{BUILDER_ID!r} is reserved for the block builder")
        self._venues = {venue: LmsrMarket(b=b) for venue, b in liquidity.items()}
        self._accounts = {agent: Account(cash=cash) for agent, cash in initial_cash.items()}
        self._accounts[BUILDER_ID] = Account(cash=0.0)
        self.base_fee = base_fee
        self._block = 0
        self._resolved: int | None = None
        self._mm_pnl: dict[Venue, float] = {}

    # ----------------------------------------------------------------- Engine API

    def submit(self, tx: Tx) -> list[Receipt]:
        return self.build_block([tx])

    def build_block(self, ordered_txs: Sequence[Tx]) -> list[Receipt]:
        if self._resolved is not None:
            raise EngineError("market already resolved")
        receipts: list[Receipt] = []
        for tx in ordered_txs:
            if isinstance(tx, Bundle):
                receipts.extend(self._execute_bundle(tx))
            else:
                receipts.append(self._execute_trade(tx))
        self._block += 1
        return receipts

    def state(self) -> EngineState:
        venues = {
            v: VenueState(b=m.b, q_yes=m.q_yes, q_no=m.q_no, collateral=m.collateral, price=m.price())
            for v, m in self._venues.items()
        }
        return EngineState(venues=venues, block=self._block, resolved_outcome=self._resolved)

    def prices(self) -> dict[Venue, float]:
        return {v: m.price() for v, m in self._venues.items()}

    def balances(self) -> dict[str, Account]:
        return {agent: acct.copy() for agent, acct in self._accounts.items()}

    def resolve(self, y: int) -> None:
        if y not in (0, 1):
            raise EngineError("outcome must be 0 or 1")
        if self._resolved is not None:
            raise EngineError("market already resolved")
        winner = Side.YES if y == 1 else Side.NO
        for venue, market in self._venues.items():
            self._mm_pnl[venue] = market.collateral - market.payout(y)
        for acct in self._accounts.values():
            for (venue, side), qty in acct.shares.items():
                if side is winner:
                    acct.cash += qty
                    self._venues[venue].collateral -= qty
            acct.shares.clear()
        self._resolved = y

    # -------------------------------------------------------------- extra queries

    def market_maker_pnl(self) -> dict[Venue, float]:
        """Market maker profit per venue after resolution (negative = subsidy paid to traders)."""
        if self._resolved is None:
            raise EngineError("market not resolved yet")
        return dict(self._mm_pnl)

    def liquidity(self, venue: Venue) -> float:
        return self._venues[venue].b

    def builder_revenue(self) -> float:
        """Total fees and tips collected by the builder so far."""
        return self._accounts[BUILDER_ID].cash

    # ------------------------------------------------------------------ internals

    def _account(self, agent_id: str) -> Account:
        try:
            return self._accounts[agent_id]
        except KeyError:
            raise EngineError(f"unknown agent {agent_id!r}") from None

    def _execute_trade(self, trade: Trade) -> Receipt:
        acct = self._account(trade.agent_id)
        market = self._venues[trade.venue]
        before = market.price()

        def revert(reason: str) -> Receipt:
            return Receipt(trade=trade, ok=False, reason=reason, cost=0.0, price_before=before, price_after=before)

        fee = self.base_fee + trade.priority_fee
        if fee > acct.cash + _EPS:
            return revert("insufficient cash for fee")
        acct.cash -= fee  # paid on inclusion, whether or not the trade then reverts
        self._accounts[BUILDER_ID].cash += fee

        if trade.shares == 0:
            return revert("zero size")
        paid = market.quote(trade.side, trade.shares)
        if trade.shares > 0:  # buy
            if paid / trade.shares > trade.limit_price + _EPS:
                return revert("limit")
            if paid > acct.cash + _EPS:
                return revert("insufficient cash")
        else:  # sell
            held = acct.position(trade.venue, trade.side)
            if -trade.shares > held + _EPS:
                return revert("insufficient shares")
            if (-paid) / (-trade.shares) < trade.limit_price - _EPS:
                return revert("limit")

        market.execute(trade.side, trade.shares)
        acct.cash -= paid
        key = (trade.venue, trade.side)
        # clamp at 0: selling "all" holdings can leave -1e-15 from float rounding
        acct.shares[key] = max(0.0, acct.shares.get(key, 0.0) + trade.shares)
        return Receipt(trade=trade, ok=True, reason="", cost=paid, price_before=before, price_after=market.price())

    def _execute_bundle(self, bundle: Bundle) -> list[Receipt]:
        """Execute all trades or none: on any revert, restore the state from before the bundle."""
        if any(t.agent_id != bundle.agent_id for t in bundle.trades):
            raise EngineError("bundle trades must belong to the bundle's agent")
        saved_venues = copy.deepcopy(self._venues)
        saved_accounts = {aid: self._account(aid).copy() for aid in (bundle.agent_id, BUILDER_ID)}
        receipts = []
        for trade in bundle.trades:
            receipt = self._execute_trade(trade)
            if not receipt.ok:
                self._venues = saved_venues
                self._accounts.update(saved_accounts)  # not included: no fees either
                return [self._reverted(t, f"bundle reverted: {receipt.reason}") for t in bundle.trades]
            receipts.append(receipt)
        return receipts

    def _reverted(self, trade: Trade, reason: str) -> Receipt:
        price = self._venues[trade.venue].price()
        return Receipt(trade=trade, ok=False, reason=reason, cost=0.0, price_before=price, price_after=price)
