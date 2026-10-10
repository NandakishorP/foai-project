"""EvmEngine: the same `Engine` interface as FastEngine, backed by the Solidity contracts on Anvil.

Every agent gets its own Anvil dev account, so addresses are real and stable. A block
is built by sending the builder's transactions in exactly that order (Anvil runs FIFO
with mining disabled) and then mining once (`evm_mine`). Trades go through the
TradeRouter, so fees, revert protection and atomic bundles follow the FastEngine rules.

Unit conversion at the boundary (FastEngine uses floats, the chain uses integers):
- USDC and share amounts: 6 decimals. Buys round to the nearest unit; sells round
  toward zero, so selling "everything" never asks for one unit more than is held.
- Limit prices: 18 decimals, rounded down.
The differential test (tests/test_differential.py) bounds the resulting differences.

Slow by design (one RPC call per transaction): for the differential test and demos,
never for Monte Carlo runs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from web3 import Web3
from web3.logs import DISCARD

from tfs.core.types import Account, Bundle, Receipt, Side, Trade, Tx, Venue
from tfs.engines.anvil import AnvilProcess, load_artifact
from tfs.engines.base import Engine, EngineState, VenueState

USDC = 10**6
WAD = 10**18
GAS_PER_TX = 3_000_000
ORACLE_BOND = 1 * USDC
ORACLE_WINDOW = 60  # seconds of chain time

SIDE_INDEX = {Side.YES: 0, Side.NO: 1}


def to_units(amount: float) -> int:
    return int(round(amount * USDC))


class EvmEngine(Engine):
    def __init__(self, liquidity: Mapping[Venue, float], initial_cash: Mapping[str, float], base_fee: float = 0.0) -> None:
        self.anvil = AnvilProcess(accounts=len(initial_cash) + 3).start()
        self.w3 = Web3(Web3.HTTPProvider(self.anvil.url, request_kwargs={"timeout": 60}))
        accounts = self.w3.eth.accounts
        self.deployer, self.builder, self.proposer = accounts[0], accounts[1], accounts[2]
        self.address = {agent: accounts[3 + i] for i, agent in enumerate(initial_cash)}
        self._nonce: dict[str, int] = {}
        self._liquidity = dict(liquidity)
        self._block = 0
        self._resolved: int | None = None
        self._mm_pnl: dict[Venue, float] = {}
        try:
            self._deploy(liquidity, base_fee)
            self._fund_agents(initial_cash)
            self._last_price = {v: self._price(v) for v in self.markets}
        except Exception:
            self.close()
            raise

    # ------------------------------------------------------------------ setup

    def _contract(self, name: str, address: str | None = None) -> Any:
        abi, bytecode = load_artifact(name)
        if address is None:
            return self.w3.eth.contract(abi=abi, bytecode=bytecode)
        return self.w3.eth.contract(address=address, abi=abi)

    def _send(self, call: Any, sender: str) -> bytes:
        nonce = self._nonce.get(sender)
        if nonce is None:
            nonce = self.w3.eth.get_transaction_count(sender)
        self._nonce[sender] = nonce + 1
        return call.transact({"from": sender, "gas": GAS_PER_TX, "gasPrice": 0, "nonce": nonce})

    def _mine(self) -> None:
        self.w3.provider.make_request("evm_mine", [])

    def _mined(self, hashes: Sequence[bytes]) -> list[Any]:
        self._mine()
        return [self.w3.eth.get_transaction_receipt(h) for h in hashes]

    def _deploy_one(self, name: str, *args: Any) -> Any:
        [receipt] = self._mined([self._send(self._contract(name).constructor(*args), self.deployer)])
        if receipt.status != 1:
            raise RuntimeError(f"deploying {name} failed")
        return self._contract(name, receipt.contractAddress)

    def _deploy(self, liquidity: Mapping[Venue, float], base_fee: float) -> None:
        self.usdc = self._deploy_one("MockUSDC")
        self.shares = self._deploy_one("OutcomeShares", self.usdc.address)
        self.oracle = self._deploy_one("OptimisticOracle", self.usdc.address, self.shares.address, ORACLE_BOND,
                                       ORACLE_WINDOW, 0, self.deployer)
        self.router = self._deploy_one("TradeRouter", self.usdc.address, self.builder, to_units(base_fee))
        self.markets: dict[Venue, Any] = {}
        self.market_id: dict[Venue, int] = {}
        self.funding: dict[Venue, int] = {}
        for venue in (Venue.MAIN, Venue.REF):
            if venue not in liquidity:
                continue
            market_id = len(self.market_id)
            self._mined([self._send(self.shares.functions.createMarket(self.oracle.address), self.deployer)])
            b = liquidity[venue]
            market = self._deploy_one("LMSRMarket", self.usdc.address, self.shares.address, market_id,
                                      int(round(b * WAD)), self.router.address)
            funding = math.ceil(b * math.log(2) * USDC)  # worst-case market-maker loss, b·ln 2
            self._mined([self._send(self.usdc.functions.mint(market.address, funding), self.deployer)])
            self.markets[venue], self.market_id[venue], self.funding[venue] = market, market_id, funding

    def _fund_agents(self, initial_cash: Mapping[str, float]) -> None:
        hashes = []
        for agent, cash in initial_cash.items():
            addr = self.address[agent]
            hashes.append(self._send(self.usdc.functions.mint(addr, to_units(cash)), self.deployer))
            hashes.append(self._send(self.usdc.functions.approve(self.router.address, 2**256 - 1), addr))
            for market in self.markets.values():
                hashes.append(self._send(self.usdc.functions.approve(market.address, 2**256 - 1), addr))
                hashes.append(self._send(self.shares.functions.setApprovalForAll(market.address, True), addr))
        if any(r.status != 1 for r in self._mined(hashes)):
            raise RuntimeError("funding agents failed")

    def close(self) -> None:
        self.anvil.stop()

    def __enter__(self) -> EvmEngine:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- Engine API

    def submit(self, tx: Tx) -> list[Receipt]:
        return self.build_block([tx])

    def build_block(self, ordered_txs: Sequence[Tx]) -> list[Receipt]:
        hashes = []
        for tx in ordered_txs:
            sender = self.address[tx.agent_id]
            if isinstance(tx, Bundle):
                call = self.router.functions.executeBundle([self._order(t) for t in tx.trades])
            else:
                call = self.router.functions.execute(self._order(tx))
            hashes.append(self._send(call, sender))
        chain_receipts = self._mined(hashes)
        self._block += 1
        receipts: list[Receipt] = []
        for tx, chain in zip(ordered_txs, chain_receipts):
            trades = list(tx.trades) if isinstance(tx, Bundle) else [tx]
            receipts.extend(self._receipts_for(trades, chain, is_bundle=isinstance(tx, Bundle)))
        return receipts

    def state(self) -> EngineState:
        venues = {}
        for v, m in self.markets.items():
            venues[v] = VenueState(
                b=self._liquidity[v],
                q_yes=m.functions.qYes().call() / WAD,
                q_no=m.functions.qNo().call() / WAD,
                collateral=self.usdc.functions.balanceOf(m.address).call() / USDC,
                price=self._price(v),
            )
        return EngineState(venues=venues, block=self._block, resolved_outcome=self._resolved)

    def prices(self) -> dict[Venue, float]:
        return {v: self._price(v) for v in self.markets}

    def balances(self) -> dict[str, Account]:
        out = {}
        for agent, addr in self.address.items():
            acct = Account(cash=self.usdc.functions.balanceOf(addr).call() / USDC)
            for venue in self.markets:
                for side in Side:
                    qty = self.shares.functions.balanceOf(addr, self._token(venue, side)).call()
                    if qty:
                        acct.shares[(venue, side)] = qty / USDC
            out[agent] = acct
        out["builder"] = Account(cash=self.builder_revenue())
        return out

    def resolve(self, y: int) -> None:
        """Optimistic oracle, undisputed path: propose, let the window pass, settle; then everyone redeems."""
        winner = SIDE_INDEX[Side.YES if y == 1 else Side.NO]
        hashes = [self._send(self.usdc.functions.mint(self.proposer, ORACLE_BOND * len(self.markets)), self.deployer),
                  self._send(self.usdc.functions.approve(self.oracle.address, 2**256 - 1), self.proposer)]
        hashes += [self._send(self.oracle.functions.propose(i, winner), self.proposer) for i in self.market_id.values()]
        self._check(self._mined(hashes), "oracle proposal")
        self.w3.provider.make_request("evm_increaseTime", [ORACLE_WINDOW + 1])
        self._check(self._mined([self._send(self.oracle.functions.settle(i), self.deployer)
                                 for i in self.market_id.values()]), "oracle settlement")
        for venue, market in self.markets.items():
            inventory = self.shares.functions.balanceOf(market.address, self._token_index(venue, winner)).call()
            held = self.usdc.functions.balanceOf(market.address).call()
            self._mm_pnl[venue] = (held + inventory - self.funding[venue]) / USDC
        redeems = [self._send(self.shares.functions.redeem(i), addr)
                   for addr in self.address.values() for i in self.market_id.values()]
        self._check(self._mined(redeems), "redemption")
        self._resolved = y

    # ---------------------------------------------------------- extra queries

    def market_maker_pnl(self) -> dict[Venue, float]:
        return dict(self._mm_pnl)

    def builder_revenue(self) -> float:
        return self.usdc.functions.balanceOf(self.builder).call() / USDC

    def liquidity(self, venue: Venue) -> float:
        return self._liquidity[venue]

    # -------------------------------------------------------------- internals

    def _price(self, venue: Venue) -> float:
        return self.markets[venue].functions.priceYes().call() / WAD

    def _token(self, venue: Venue, side: Side) -> int:
        return self._token_index(venue, SIDE_INDEX[side])

    def _token_index(self, venue: Venue, side_index: int) -> int:
        return self.market_id[venue] * 2 + side_index

    def _order(self, t: Trade) -> tuple[Any, ...]:
        if t.shares >= 0:
            amount = to_units(t.shares)
        else:
            amount = -math.floor(-t.shares * USDC)  # toward zero: never sell a unit more than held
        limit = max(0, math.floor(t.limit_price * WAD))
        return (self.markets[t.venue].address, SIDE_INDEX[t.side], amount, limit, to_units(t.priority_fee),
                t.revert_protected)

    def _receipts_for(self, trades: list[Trade], chain: Any, is_bundle: bool) -> list[Receipt]:
        """Turn one mined transaction into our per-trade receipts (from the router's and markets' events)."""
        ok = chain.status == 1
        if ok and not is_bundle:
            [result] = self.router.events.OrderResult().process_receipt(chain, errors=DISCARD)
            ok = bool(result["args"]["ok"])
        fills = []
        if ok:
            # Both markets share the Traded ABI, so decode once and attribute each log by its emitter.
            venue_of = {m.address: v for v, m in self.markets.items()}
            for ev in next(iter(self.markets.values())).events.Traded().process_receipt(chain, errors=DISCARD):
                fills.append((ev["logIndex"], venue_of[ev["address"]], ev["args"]))
            fills.sort(key=lambda f: f[0])
        out = []
        for i, trade in enumerate(trades):
            before = self._last_price[trade.venue]
            if ok:
                _, venue, args = fills[i]
                after = args["priceYesAfter"] / WAD
                self._last_price[venue] = after
                out.append(Receipt(trade, True, "", args["cash"] / USDC, before, after))
            else:
                reason = "reverted" if chain.status != 1 else "limit or funds"
                out.append(Receipt(trade, False, reason, 0.0, before, before))
        return out

    @staticmethod
    def _check(receipts: Sequence[Any], what: str) -> None:
        if any(r.status != 1 for r in receipts):
            raise RuntimeError(f"{what} failed on-chain")
