"""Provider gateway — Sprint 6.

THE PROVIDER LAYER TOUCHES NO MONEY. Nothing under providers/ may import from
`ledger/` or `economy/`, and no path in it posts a ledger entry. The gateway
supplies FACTS — identities, scores, finality, roster slots, stats — and the
accepted Sprint 1-5 engines remain the only things that move a cent.

That separation is asserted mechanically, not just documented: C-15 replays a
full recorded season through this package and proves the ledger is untouched,
and providers/certify/run.py additionally walks every module here for a
forbidden import.
"""
