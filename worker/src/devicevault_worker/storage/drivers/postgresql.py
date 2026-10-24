"""PostgreSQL: one ``bytea`` row per backup in a database of the target's own.

The table, in the target's schema::

    CREATE TABLE devicevault_backups (
        ref text PRIMARY KEY,         -- <device_key>/<timestamp>-<job_id><ext>
        content bytea NOT NULL,
        stored_at timestamptz NOT NULL DEFAULT now()
    );

The driver creates it on first use unless the target says not to, in which
case the database user needs only SELECT, INSERT, UPDATE and DELETE on it.
"""

import os
import tempfile
from contextlib import contextmanager
from typing import Literal

import psycopg
from psycopg import sql
from pydantic import Field, SecretStr, model_validator

from .base import StorageDriver, StorageError, StorageParams, StorageUnavailable

TABLE = 'devicevault_backups'

# SQLSTATE classes that retrying will not fix: bad credentials (28) and unknown database (3D).
_PERMANENT_CLASSES = ('28', '3D')
# Connection failures carry no SQLSTATE, only libpq's message.
_PERMANENT_MESSAGES = (
    'password authentication failed',
    'no pg_hba.conf entry',
    'does not exist',  # database or role
    'certificate verify failed',
    'does not match host name',
    'server does not support SSL',
    'no password supplied',
)

_SSLMODES = {
    ('off', 'none'): 'disable',
    ('preferred', 'none'): 'prefer',
    ('forced', 'none'): 'require',
    ('forced', 'ca'): 'verify-ca',
    ('forced', 'full'): 'verify-full',
}


class PostgresParams(StorageParams):
    host: str = Field(min_length=1, description='Database server hostname or address')
    port: int = Field(5432, ge=1, le=65535, description='Database server port')
    database: str = Field(min_length=1, description='Database name')
    username: str = Field(min_length=1, description='Database user')
    password: SecretStr | None = Field(None, description='Password for the database user')
    db_schema: str = Field(
        'public',
        pattern=r'^[A-Za-z_][A-Za-z0-9_$]{0,62}$',
        title='Schema',
        description=f'Schema holding the {TABLE} table',
    )
    create_table: bool = Field(True, description=f'Create the {TABLE} table if it is missing')
    tls: Literal['off', 'preferred', 'forced'] = Field(
        'preferred', title='TLS', description='Off, used when the server offers it, or required'
    )
    certificate_validation: Literal['none', 'ca', 'full'] = Field(
        'none',
        description='Check the server certificate against the CA (ca), and its hostname too (full). Needs TLS forced',
    )
    ca_certificate: str | None = Field(
        None,
        title='CA certificate',
        description="PEM CA certificate(s) to validate against; empty for the worker's system trust store",
        json_schema_extra={'format': 'multiline'},
    )
    connect_timeout: int = Field(10, ge=1, le=300, description='Seconds to wait for a connection')

    @model_validator(mode='after')
    def _tls_settings(self):
        if self.certificate_validation != 'none' and self.tls != 'forced':
            raise ValueError('certificate validation needs TLS forced')
        if self.certificate_validation == 'ca' and not (self.ca_certificate or '').strip():
            raise ValueError('CA-only validation needs a CA certificate (the system trust store needs full validation)')
        return self

    @property
    def sslmode(self) -> str:
        return _SSLMODES[(self.tls, self.certificate_validation)]


def _application_name() -> str:
    from devicevault_worker.app import identity

    return f'devicevault-worker {identity.worker_id}'


def _error(operation: str, exc: psycopg.Error) -> StorageError:
    message = f'PostgreSQL {operation} failed: {str(exc).strip() or exc.__class__.__name__}'
    sqlstate = exc.sqlstate or ''
    permanent = sqlstate.startswith(_PERMANENT_CLASSES) or any(text in message for text in _PERMANENT_MESSAGES)
    if isinstance(exc, psycopg.OperationalError) and not permanent:
        return StorageUnavailable(message)
    return StorageError(message)


class PostgresDriver(StorageDriver):
    key = 'postgresql'
    name = 'PostgreSQL database'
    description = 'One row per backup in a PostgreSQL database. Several workers can serve one database.'
    shareable = True
    Params = PostgresParams

    @contextmanager
    def connect(self, params: PostgresParams, operation: str):
        """A connection in a transaction that commits on success, with the table ready."""
        options = {
            'host': params.host,
            'port': params.port,
            'dbname': params.database,
            'user': params.username,
            'password': params.password.get_secret_value() if params.password else None,
            'sslmode': params.sslmode,
            'connect_timeout': params.connect_timeout,
            'application_name': _application_name(),
        }
        ca_file = None
        try:
            if params.certificate_validation != 'none':
                if (params.ca_certificate or '').strip():
                    # libpq reads the CA from a file, during the handshake.
                    with tempfile.NamedTemporaryFile('w', suffix='.pem', delete=False) as handle:
                        handle.write(params.ca_certificate)
                    ca_file = handle.name
                    options['sslrootcert'] = ca_file
                else:
                    options['sslrootcert'] = 'system'
            with psycopg.connect(**{k: v for k, v in options.items() if v is not None}) as connection:
                self._ensure_table(connection, params)
                yield connection
        except psycopg.Error as exc:
            raise _error(operation, exc) from exc
        finally:
            if ca_file:
                os.unlink(ca_file)

    @staticmethod
    def table(params: PostgresParams) -> sql.Identifier:
        return sql.Identifier(params.db_schema, TABLE)

    def _ensure_table(self, connection: psycopg.Connection, params: PostgresParams) -> None:
        exists = connection.execute(
            'SELECT EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = %s AND tablename = %s)',
            [params.db_schema, TABLE],
        ).fetchone()
        if exists and exists[0]:
            return
        if not params.create_table:
            raise StorageError(f'table {params.db_schema}.{TABLE} does not exist (and the target does not create it)')
        try:
            # A savepoint, so losing a creation race with another worker leaves the transaction usable.
            with connection.transaction():
                connection.execute(
                    sql.SQL(
                        'CREATE TABLE IF NOT EXISTS {} ('
                        'ref text PRIMARY KEY, content bytea NOT NULL, stored_at timestamptz NOT NULL DEFAULT now())'
                    ).format(self.table(params))
                )
        except psycopg.errors.UniqueViolation:
            pass

    def store(self, data, name, params):
        ref = self.object_name(name)
        with self.connect(params, 'store') as connection:
            connection.execute(
                sql.SQL(
                    'INSERT INTO {} (ref, content) VALUES (%s, %s) '
                    'ON CONFLICT (ref) DO UPDATE SET content = EXCLUDED.content, stored_at = now()'
                ).format(self.table(params)),
                [ref, data.read()],  # bytea: one value, so the whole backup is in memory here
            )
        return ref

    def read(self, ref, params, sink):
        with self.connect(params, 'read') as connection:
            row = connection.execute(
                sql.SQL('SELECT content FROM {} WHERE ref = %s').format(self.table(params)), [ref]
            ).fetchone()
        if row is None:
            raise StorageError(f'backup not found: {ref}')
        sink.write(row[0])

    def delete(self, ref, params):
        with self.connect(params, 'delete') as connection:
            connection.execute(sql.SQL('DELETE FROM {} WHERE ref = %s').format(self.table(params)), [ref])

    def check(self, params):
        with self.connect(params, 'check') as connection:
            connection.execute(sql.SQL('SELECT 1 FROM {} LIMIT 0').format(self.table(params)))
            tls = 'TLS' if connection.pgconn.ssl_in_use else 'no TLS'
        return f'postgresql://{params.username}@{params.host}:{params.port}/{params.database} {params.db_schema}.{TABLE} ({tls})'
