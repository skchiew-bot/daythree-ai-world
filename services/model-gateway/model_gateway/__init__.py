"""Model Gateway (spec §11): the only thing in the system allowed to talk to an LLM
provider. The Mission Engine and Agent Runtime import `ModelGateway` and
`ModelProvider`/`ModelRequest`/`ModelResponse` from here — never a provider SDK.
"""
