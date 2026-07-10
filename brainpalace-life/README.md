# brainpalace-life

The BrainPalace life-memory **product**, as a monorepo subpackage (Packaging
decision in the memory roadmap). Empty scaffold until P1.

## Engine import boundary (enforced)

Product code imports the engine ONLY through the seam modules —
`ingestion.adapter`/`sink`, `indexing.record_validation`/`salience`,
`models.domains`, `services.query_service` (`execute_query`), and the
`models.{record,graph,query}` DTOs. Never engine internals
(`storage.record_store`, `storage.sqlite_graph_store`, other `services.*`).
The `lint:import-boundary` gate (`scripts/check_import_boundary.py`) fails CI on
any violation. Keeps later extraction to a standalone repo a folder-copy.
