# Resuming interrupted runs

If the process dies mid-run, restart it and it will pick up where it left
off using the last saved checkpoint. No manual replay is required -- the
graph reads the most recent checkpoint for the thread and continues from
there.
