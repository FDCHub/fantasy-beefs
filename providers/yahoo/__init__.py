"""Yahoo provider gateway (§2 responsibilities A-F).

    transport.py    A  transport / auth — the ONLY place credentials are read
    parse.py        B  raw provider parsing — payload bytes to plain dicts
    normalize.py    C  normalization — plain dicts to provider-neutral DTOs
    identity.py     D  identity resolution — provider keys to internal rows
    finality.py     F  economic-finality mapping — the SOLE finalized_at writer
    persist.py      E  persistence / upsert, horizon and conflict recording
    pool_source.py     the accepted PoolStatSource boundary, provider side

Yahoo field names appear in transport.py, parse.py and the stat mapping of
pool_source.py. They appear NOWHERE else, and nothing outside providers/yahoo/
sees one.
"""
