# ADR 0001: Initial technology stack

- **Status:** Accepted for prototype; revisitable.
- **Context:** Chronicle must be feasible for a student team, locally runnable, and extensible for research experiments.
- **Decision:** Next.js/TypeScript frontend; FastAPI/Python backend; PostgreSQL for durable state; NetworkX for initial graph algorithms; Docker Compose for local services.
- **Rationale:** Python supports document/NLP experiments; PostgreSQL provides transactions for relationships and report versions; NetworkX avoids extra graph infrastructure in early milestones.
- **Consequences:** Reassess graph storage with measured requirements before introducing a separate graph database. Avoid a vector database or agent framework until a retrieval/verification baseline is measurable.
