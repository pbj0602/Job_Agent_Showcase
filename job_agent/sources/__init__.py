"""Job sources. Each returns plain dicts with at least: company, title, location, url, source.

Fetching (HTTP) and parsing are kept apart so parsers are tested against saved
fixtures and never need the network.
"""
