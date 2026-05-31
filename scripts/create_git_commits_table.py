"""
Create the maya_sawa_git_commits table using the existing Paprika DB config.
"""

from pathlib import Path
import os

import psycopg2


ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def get_paprika_db_url() -> str:
    load_env_file(ROOT / ".env")

    db_type = os.getenv("PAPRIKA_DB_TYPE", "sqlite")
    if db_type != "postgresql":
        raise RuntimeError("PAPRIKA_DB_TYPE must be postgresql")

    host = os.getenv("PAPRIKA_DB_HOST")
    port = os.getenv("PAPRIKA_DB_PORT", "5432")
    database = os.getenv("PAPRIKA_DB_DATABASE")
    username = os.getenv("PAPRIKA_DB_USERNAME")
    password = os.getenv("PAPRIKA_DB_PASSWORD")
    sslmode = os.getenv("PAPRIKA_DB_SSLMODE", "require")

    if not all([host, database, username, password]):
        raise RuntimeError("PAPRIKA database configuration is incomplete")

    return (
        f"postgresql://{username}:{password}@{host}:{port}/{database}"
        f"?sslmode={sslmode}"
    )


def main() -> None:
    sql = (ROOT / "sql" / "create_git_commits_table.sql").read_text(encoding="utf-8")
    column_query = """
        SELECT column_name, data_type, udt_name
        FROM information_schema.columns
        WHERE table_name = 'maya_sawa_git_commits'
        ORDER BY ordinal_position
    """

    with psycopg2.connect(get_paprika_db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute(column_query)
            rows = cur.fetchall()

    print("created_or_exists maya_sawa_git_commits")
    for column_name, data_type, udt_name in rows:
        print(f"{column_name}|{data_type}|{udt_name}")


if __name__ == "__main__":
    main()
