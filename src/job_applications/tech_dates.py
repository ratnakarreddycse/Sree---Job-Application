"""Technology release year database.

Each entry maps a lowercase canonical skill/tool name to the year it became
publicly available / production-ready.  The date is used to prevent injecting
a technology into a resume job entry whose end date pre-dates the tool's
existence — e.g. listing "Delta Lake (2019)" for a role that ended in 2017
would be an obvious factual error.

When a technology is not found in this mapping, the tailor treats it as
"always available" so unknown/niche tools are never silently dropped.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# canonical skill name (lowercase) → first public / GA year
# ---------------------------------------------------------------------------
TECH_RELEASE_YEARS: dict[str, int] = {
    # ── Languages ────────────────────────────────────────────────────────────
    "python": 1991,
    "sql": 1974,
    "java": 1995,
    "scala": 2004,
    "r": 1993,
    "go": 2012,
    "golang": 2012,
    "bash": 1989,
    "shell": 1989,
    "perl": 1987,
    "ruby": 1995,
    "javascript": 1995,
    "typescript": 2012,
    "c": 1972,
    "c++": 1985,
    "rust": 2015,
    # ── Big Data / Batch Processing ───────────────────────────────────────────
    "hadoop": 2006,
    "mapreduce": 2006,
    "hive": 2010,
    "pig": 2008,
    "hbase": 2008,
    "spark": 2014,
    "pyspark": 2014,
    "spark sql": 2014,
    "spark streaming": 2014,
    "structured streaming": 2016,
    "flink": 2014,
    "storm": 2011,
    "samza": 2013,
    "beam": 2016,
    "apache beam": 2016,
    "tez": 2014,
    # ── Orchestration ─────────────────────────────────────────────────────────
    "airflow": 2015,
    "apache airflow": 2015,
    "luigi": 2012,
    "prefect": 2018,
    "dagster": 2018,
    "argo": 2017,
    "argo workflows": 2017,
    "nifi": 2014,
    "apache nifi": 2014,
    "mage": 2022,
    "mage ai": 2022,
    "kestra": 2021,
    "flyte": 2020,
    "metaflow": 2019,
    "zenml": 2021,
    # ── Streaming / Messaging ─────────────────────────────────────────────────
    "kafka": 2011,
    "apache kafka": 2011,
    "kinesis": 2013,
    "aws kinesis": 2013,
    "pubsub": 2015,
    "google pubsub": 2015,
    "pulsar": 2016,
    "apache pulsar": 2016,
    "rabbitmq": 2007,
    "activemq": 2004,
    "nats": 2011,
    "redis streams": 2018,
    # ── Cloud Platforms ───────────────────────────────────────────────────────
    "aws": 2006,
    "gcp": 2008,
    "azure": 2010,
    "google cloud": 2008,
    # ── AWS Services ──────────────────────────────────────────────────────────
    "s3": 2006,
    "ec2": 2006,
    "rds": 2009,
    "dynamodb": 2012,
    "redshift": 2012,
    "emr": 2009,
    "glue": 2017,
    "aws glue": 2017,
    "lambda": 2014,
    "aws lambda": 2014,
    "athena": 2016,
    "aws athena": 2016,
    "sagemaker": 2017,
    "aws sagemaker": 2017,
    "step functions": 2016,
    "aws step functions": 2016,
    "cloudwatch": 2009,
    "sns": 2010,
    "sqs": 2006,
    "eks": 2018,
    "ecs": 2014,
    "fargate": 2017,
    "codepipeline": 2015,
    "lakeformation": 2019,
    "aws lake formation": 2019,
    "quicksight": 2016,
    "aws quicksight": 2016,
    "mwaa": 2020,
    "aws mwaa": 2020,
    "glue databrew": 2020,
    # ── GCP Services ──────────────────────────────────────────────────────────
    "bigquery": 2011,
    "google bigquery": 2011,
    "gcs": 2010,
    "cloud storage": 2010,
    "dataflow": 2015,
    "google dataflow": 2015,
    "dataproc": 2015,
    "google dataproc": 2015,
    "cloud composer": 2018,
    "google cloud composer": 2018,
    "vertex ai": 2021,
    "data studio": 2016,
    "looker studio": 2022,
    "spanner": 2017,
    "bigtable": 2015,
    "firestore": 2017,
    "cloud run": 2019,
    "cloud functions": 2016,
    "bigquery ml": 2018,
    "dataplex": 2021,
    # ── Azure Services ────────────────────────────────────────────────────────
    "azure data factory": 2015,
    "adf": 2015,
    "azure synapse": 2019,
    "synapse analytics": 2019,
    "azure sql data warehouse": 2015,
    "azure data lake": 2015,
    "adls": 2015,
    "azure databricks": 2017,
    "azure functions": 2016,
    "azure event hubs": 2015,
    "event hubs": 2015,
    "azure blob storage": 2010,
    "cosmos db": 2017,
    "azure cosmos db": 2017,
    "hdinsight": 2014,
    "azure hdinsight": 2014,
    "azure stream analytics": 2015,
    "azure purview": 2021,
    "microsoft fabric": 2023,
    "azure machine learning": 2018,
    "power automate": 2016,
    # ── Cloud Data Warehouses / Lakehouses ───────────────────────────────────
    "snowflake": 2014,
    "databricks": 2013,
    "delta lake": 2019,
    "delta": 2019,
    # ── Relational Databases ──────────────────────────────────────────────────
    "postgresql": 1996,
    "postgres": 1996,
    "mysql": 1995,
    "oracle": 1979,
    "sql server": 1989,
    "mssql": 1989,
    "sqlite": 2000,
    "mariadb": 2009,
    "db2": 1983,
    # ── NoSQL / NewSQL ────────────────────────────────────────────────────────
    "mongodb": 2009,
    "cassandra": 2008,
    "apache cassandra": 2008,
    "redis": 2009,
    "elasticsearch": 2010,
    "opensearch": 2021,
    "neo4j": 2007,
    "couchbase": 2010,
    "cockroachdb": 2015,
    "clickhouse": 2016,
    "druid": 2011,
    "apache druid": 2011,
    "influxdb": 2013,
    "scylladb": 2015,
    # ── OLAP Query Engines ────────────────────────────────────────────────────
    "presto": 2013,
    "trino": 2019,
    "dremio": 2015,
    "impala": 2012,
    "apache impala": 2012,
    # ── Data Transformation ───────────────────────────────────────────────────
    "dbt": 2016,
    "dbt core": 2016,
    "dbt cloud": 2020,
    # ── Open Table Formats ────────────────────────────────────────────────────
    "apache iceberg": 2018,
    "iceberg": 2018,
    "apache hudi": 2019,
    "hudi": 2019,
    # ── Data Quality / Observability ──────────────────────────────────────────
    "great expectations": 2017,
    "monte carlo": 2019,
    "soda": 2020,
    "deequ": 2018,
    "elementary": 2021,
    "re_data": 2021,
    # ── ETL / ELT Tools ───────────────────────────────────────────────────────
    "fivetran": 2016,
    "stitch": 2016,
    "airbyte": 2020,
    "informatica": 1993,
    "talend": 2006,
    "matillion": 2011,
    "pentaho": 2004,
    # ── Visualization / BI ────────────────────────────────────────────────────
    "tableau": 2003,
    "power bi": 2015,
    "looker": 2012,
    "grafana": 2014,
    "superset": 2015,
    "apache superset": 2015,
    "metabase": 2015,
    "mode": 2013,
    "sigma": 2016,
    "qlik": 1993,
    "qliksense": 2013,
    "microstrategy": 1989,
    # ── Infrastructure / DevOps ───────────────────────────────────────────────
    "docker": 2013,
    "kubernetes": 2014,
    "k8s": 2014,
    "terraform": 2014,
    "helm": 2015,
    "ansible": 2012,
    "vagrant": 2010,
    "jenkins": 2011,
    "github actions": 2019,
    "gitlab ci": 2012,
    "circleci": 2011,
    "prometheus": 2012,
    "datadog": 2010,
    "splunk": 2004,
    "newrelic": 2008,
    # ── Python Libraries ──────────────────────────────────────────────────────
    "pandas": 2008,
    "numpy": 2005,
    "scipy": 2001,
    "scikit-learn": 2007,
    "sklearn": 2007,
    "matplotlib": 2003,
    "sqlalchemy": 2005,
    "fastapi": 2018,
    "flask": 2010,
    "django": 2005,
    "celery": 2009,
    "pytest": 2004,
    "requests": 2011,
    "pydantic": 2017,
    "polars": 2021,
    "duckdb": 2019,
    "arrow": 2016,
    "apache arrow": 2016,
    "great_expectations": 2017,
    # ── File Formats ─────────────────────────────────────────────────────────
    "parquet": 2013,
    "avro": 2009,
    "orc": 2013,
    "protobuf": 2008,
    # ── ML / AI Platforms ─────────────────────────────────────────────────────
    "mlflow": 2018,
    "kubeflow": 2018,
    "tensorflow": 2015,
    "pytorch": 2016,
    "keras": 2015,
    "xgboost": 2014,
    "lightgbm": 2016,
    "catboost": 2017,
    "feast": 2019,
    "bentoml": 2019,
    "ray": 2017,
    "hugging face": 2016,
    "langchain": 2022,
    "openai": 2015,
    # ── Reverse ETL ───────────────────────────────────────────────────────────
    "census": 2019,
    "hightouch": 2020,
    # ── Version Control / CI ──────────────────────────────────────────────────
    "git": 2005,
    "github": 2008,
    "gitlab": 2011,
    "bitbucket": 2008,
    # ── Misc Modern Stack ─────────────────────────────────────────────────────
    "streamlit": 2019,
    "gradio": 2019,
    "nessie": 2020,
    "open metadata": 2021,
    "apache atlas": 2015,
    "collibra": 2008,
    "alation": 2012,
}

# Maps alternate / verbose names back to the canonical key used in TECH_RELEASE_YEARS.
# Used when rendering the final skill name in output.
TECH_ALIASES: dict[str, str] = {
    "pyspark": "spark",
    "spark sql": "spark",
    "spark streaming": "spark",
    "structured streaming": "spark",
    "apache spark": "spark",
    "apache kafka": "kafka",
    "apache airflow": "airflow",
    "apache beam": "beam",
    "apache cassandra": "cassandra",
    "apache nifi": "nifi",
    "apache hudi": "hudi",
    "apache iceberg": "iceberg",
    "apache arrow": "arrow",
    "apache superset": "superset",
    "apache druid": "druid",
    "apache impala": "impala",
    "aws glue": "glue",
    "aws lambda": "lambda",
    "aws athena": "athena",
    "aws sagemaker": "sagemaker",
    "aws kinesis": "kinesis",
    "aws step functions": "step functions",
    "aws lake formation": "lakeformation",
    "aws mwaa": "mwaa",
    "aws quicksight": "quicksight",
    "google bigquery": "bigquery",
    "google dataflow": "dataflow",
    "google dataproc": "dataproc",
    "google cloud composer": "cloud composer",
    "google pubsub": "pubsub",
    "azure data factory": "adf",
    "azure synapse": "synapse analytics",
    "azure data lake": "adls",
    "azure cosmos db": "cosmos db",
    "azure hdinsight": "hdinsight",
    "azure databricks": "databricks",
    "google cloud": "gcp",
    "postgres": "postgresql",
    "mssql": "sql server",
    "scikit-learn": "sklearn",
    "looker studio": "data studio",
    "delta lake": "delta",
    "k8s": "kubernetes",
    "qliksense": "qlik",
    "golang": "go",
}


def normalize_skill(raw: str) -> str:
    """Return the lowercase, stripped form of a skill name."""
    return raw.strip().lower()


def canonical(skill: str) -> str:
    """Return the canonical skill name (resolving aliases)."""
    key = normalize_skill(skill)
    return TECH_ALIASES.get(key, key)


def release_year(skill: str) -> int | None:
    """Return the release year for a skill, or None if unknown."""
    key = normalize_skill(skill)
    # Try direct lookup, then via alias
    return TECH_RELEASE_YEARS.get(key) or TECH_RELEASE_YEARS.get(canonical(key))


def skill_available_at(skill: str, year: int) -> bool:
    """Return True if the skill was publicly available by *year*.

    Unknown skills (not in the database) are treated as always available so
    niche / new tools introduced by the JD are never silently blocked.
    """
    yr = release_year(skill)
    if yr is None:
        return True  # unknown → don't block
    return yr <= year
