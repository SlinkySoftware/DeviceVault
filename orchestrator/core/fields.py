"""Model fields for secrets at rest."""

from django.db import models

from core.keys import decrypt_value, encrypt_value


class EncryptedJSONField(models.JSONField):
    """A JSON field stored encrypted with the data key ring (core.keys).

    The column holds a JSON string (``"dv1:<kid>:..."``) instead of the value,
    so the value cannot be queried in the database. The ciphertext is bound to
    the model and field, so it cannot be copied into another encrypted column.
    """

    def _context(self) -> str:
        return f'{self.model._meta.label_lower}.{self.attname}'

    def get_db_prep_value(self, value, connection, prepared=False):
        if value is None:
            return None
        return super().get_db_prep_value(encrypt_value(value, context=self._context()), connection, prepared)

    def from_db_value(self, value, expression, connection):
        stored = super().from_db_value(value, expression, connection)
        if stored is None:
            return None
        return decrypt_value(stored, context=self._context())
