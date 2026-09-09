"""Worker process for asynchronous run execution (proposal Phase 5).

The MVP uses Python's concurrent.futures for in-process async dispatch.
Production deployment should use arq + Redis (see docker-compose.yml).
"""
