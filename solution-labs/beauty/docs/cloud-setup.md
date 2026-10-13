# Cloud reference scaffolds — not executed

Azure Databricks reference replaces SQLite with Delta/PySpark, the metric registry with Unity Catalog metric views, lexical vectors with authorized AI Search using learned embeddings, and local templates with evaluated serving/agent tools. SAP ERP extraction remains an upstream export/sharing contract; the supplied SAP BDC migration route is a reference expansion path.

Placeholders: YOUR_DATABRICKS_HOST, YOUR_SQL_WAREHOUSE_ID, YOUR_CATALOG, YOUR_SCHEMA, YOUR_VECTOR_ENDPOINT, YOUR_MODEL_ENDPOINT, Entra identity and Azure storage. See solution-labs/beauty/cloud/ for asset-bundle placeholders, Gold contracts and metric-view SQL. No workspace/API call occurs locally.

Metric-view scaffolds follow current YAML 1.1 syntax and require a supporting runtime/SQL warehouse. Activate in a dedicated sandbox only after replacing placeholders, loading synthetic data, validating grain/totals and configuring permissions. Cloud ACL/index grants do not replace per-document application authorization. Delta multi-table publication needs a version manifest/pointer design; SQLite transactions do not imply atomic multi-table Delta writes.

References: https://docs.databricks.com/aws/en/uc-semantics/metric-views/create and https://docs.databricks.com/aws/en/vector-search/vector-search
