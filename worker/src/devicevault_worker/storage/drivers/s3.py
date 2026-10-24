"""Amazon S3 and S3-compatible object stores (MinIO, Ceph, Wasabi...)."""

from typing import Literal

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from botocore.exceptions import ConnectionError as BotoConnectionError
from pydantic import Field, SecretStr

from .base import StorageDriver, StorageError, StorageParams, StorageUnavailable

# Error codes worth retrying; anything else (access denied, no such bucket) is permanent.
_RETRYABLE = {'InternalError', 'ServiceUnavailable', 'SlowDown', 'RequestTimeout', 'Throttling', '503', '500'}


class S3Params(StorageParams):
    bucket: str = Field(min_length=3, description='Bucket name')
    prefix: str = Field('', description='Key prefix for every backup, e.g. "devicevault/"')
    region: str | None = Field(None, description='Region (default: the SDK default)')
    endpoint_url: str | None = Field(
        None, description='For S3-compatible stores, e.g. https://minio.example.com:9000 (empty for AWS)'
    )
    access_key_id: str | None = Field(None, description="Empty to use the worker's IAM role or environment")
    secret_access_key: SecretStr | None = Field(None, description='Secret for the access key')
    path_style: bool = Field(False, description='Path-style addressing (needed by most S3-compatible stores)')
    server_side_encryption: Literal['', 'AES256', 'aws:kms'] = Field('', description='Server-side encryption')


class S3Driver(StorageDriver):
    key = 's3'
    name = 'S3 bucket'
    description = 'One object per backup in an S3 or S3-compatible bucket. Several workers can serve one bucket.'
    shareable = True
    Params = S3Params

    def client(self, params: S3Params):
        secret = params.secret_access_key.get_secret_value() if params.secret_access_key else None
        return boto3.client(
            's3',
            region_name=params.region or None,
            endpoint_url=params.endpoint_url or None,
            aws_access_key_id=params.access_key_id or None,
            aws_secret_access_key=secret,
            config=Config(
                s3={'addressing_style': 'path' if params.path_style else 'auto'},
                retries={'max_attempts': 3, 'mode': 'standard'},
                connect_timeout=10,
                read_timeout=60,
            ),
        )

    def _call(self, operation: str, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ClientError as exc:
            code = str(exc.response.get('Error', {}).get('Code', ''))
            status = str(exc.response.get('ResponseMetadata', {}).get('HTTPStatusCode', ''))
            error = StorageUnavailable if code in _RETRYABLE or status in _RETRYABLE else StorageError
            raise error(f'S3 {operation} failed: {code or status} {exc}') from exc
        except BotoConnectionError as exc:
            raise StorageUnavailable(f'S3 {operation} failed: {exc}') from exc
        except BotoCoreError as exc:
            raise StorageError(f'S3 {operation} failed: {exc}') from exc

    def store(self, data, name, params):
        key = params.prefix + self.object_name(name)
        extra = {'ServerSideEncryption': params.server_side_encryption} if params.server_side_encryption else {}
        # Multipart for large backups, so they are never read into memory whole.
        client = self.client(params)
        self._call('upload', client.upload_fileobj, data, params.bucket, key, ExtraArgs=extra or None)
        return key

    def read(self, ref, params, sink):
        self._call('download', self.client(params).download_fileobj, params.bucket, ref, sink)

    def delete(self, ref, params):
        self._call('delete', self.client(params).delete_object, Bucket=params.bucket, Key=ref)

    def check(self, params):
        self._call('check', self.client(params).head_bucket, Bucket=params.bucket)
        return f's3://{params.bucket}/{params.prefix}'
