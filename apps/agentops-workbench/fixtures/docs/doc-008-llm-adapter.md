# LLMAdapter interface

Every model call goes through `LLMAdapter.chat(messages, **kw)` which
returns a `ChatResult` with normalized `Usage`. Provider-specific
options live behind the adapter; the graph code never names a provider.

> Source: hand-authored for the workbench fixture; CC-BY-SA.
