from django.db import models
from django.db.models import Lookup


class DocumentText(models.TextField):
    """A search document's text. On PostgreSQL it has a trigram index (migration 0001) that these lookups use."""


@DocumentText.register_lookup
class Like(Lookup):
    """Case-insensitive LIKE with a pattern the caller escaped (``search.query``)."""

    lookup_name = 'dv_like'

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} LIKE {rhs} ESCAPE '\\'", [*lhs_params, *rhs_params]

    def as_postgresql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f'{lhs} ILIKE {rhs}', [*lhs_params, *rhs_params]


@DocumentText.register_lookup
class Regex(Lookup):
    """Case-insensitive PostgreSQL regex match (only used to narrow candidates there)."""

    lookup_name = 'dv_iregex'

    def as_sql(self, compiler, connection):
        raise NotImplementedError('dv_iregex is only available on PostgreSQL')

    def as_postgresql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f'{lhs} ~* {rhs}', [*lhs_params, *rhs_params]


class SearchDocument(models.Model):
    """The searchable text of a device's latest backup (``search.indexing``).

    Secret values are replaced by tokens (``search.tokens``). A backup that cannot be
    searched (binary, too large) still has a document, with no text and the reason.
    """

    device = models.OneToOneField(
        'devices.Device', primary_key=True, on_delete=models.CASCADE, related_name='search_document'
    )
    job = models.ForeignKey('backups.BackupJob', on_delete=models.CASCADE, related_name='+')
    driver = models.CharField(max_length=128, blank=True, help_text="The device's backup method when indexed")
    text = DocumentText(blank=True)
    skipped = models.CharField(max_length=255, blank=True, help_text='Why the backup is not searchable')
    token_kid = models.CharField(max_length=64, blank=True, help_text='Data key the secret tokens were made with')
    patterns_hash = models.CharField(max_length=64, blank=True, help_text='Fingerprint of the secret patterns applied')
    indexed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'search document of device {self.device_id}'
