#!/usr/bin/env python3
"""Create the independent MySQL database for this project."""

from __future__ import annotations

import sys
from pathlib import Path

import pymysql
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.core.constants import PROTECTED_MYSQL_DATABASES  # noqa: E402


class DbBootstrapSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "reach_part_vision4dsv"


def main() -> None:
    settings = DbBootstrapSettings()
    db_name = settings.MYSQL_DATABASE.strip()
    if not db_name:
        raise SystemExit("MYSQL_DATABASE is required")
    if db_name.lower() in {x.lower() for x in PROTECTED_MYSQL_DATABASES}:
        raise SystemExit(f"Refusing to create/use protected database: {db_name}")
    if db_name != "reach_part_vision4dsv":
        print(f"Warning: expected reach_part_vision4dsv, got {db_name}")

    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        charset="utf8mb4",
        autocommit=True,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        print(f"Database ready: {db_name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
