'''
管理 Repair Memory SQLite 连接、事务、WAL 和 schema 初始化。

MemoryDatabase.connect(): 创建启用外键和行映射的数据库连接。
MemoryDatabase.initialize(): 原子应用全部 schema migration。
'''

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from idfrepair.memory.migrations import apply_migrations


class MemoryDatabase:
    '''封装一个本地 SQLite 文件，不共享跨进程可变连接。'''

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()

    def connect(self) -> sqlite3.Connection:
        '''创建启用外键、忙等待和字典式行访问的连接。'''
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        '''在立即事务中应用 migration，失败时不留下半成品 schema。'''
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            apply_migrations(connection)
            connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        '''提供提交或回滚边界，供仓储执行一次完整业务操作。'''
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


__all__ = ["MemoryDatabase"]
