# Shopping Copilot

This module is deliberately isolated from commerce write services. Its workflow may retrieve approved catalogue and policy data and propose normal API actions, but it cannot mutate price, inventory, orders, payments, refunds, or delivery promises.

Flow: request -> safety/classification -> approved retrieval -> response with evidence and optional proposed actions.

`POST /api/v1/copilot/chat` is the public local-development surface. Product retrieval currently uses PostgreSQL keyword and structured filters. `product_embeddings` stores provider-neutral embedding payloads and is the boundary for a pgvector-backed retriever when the extension and embedding provider are configured.

