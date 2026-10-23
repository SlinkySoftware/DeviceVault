"""Flower dashboards administrators can open from the UI."""

from django.core.validators import RegexValidator
from django.db import models

SLUG_PATTERN = r'[a-z0-9-]+'


class FlowerEndpoint(models.Model):
    """A Flower instance.

    A proxied endpoint is served by the web tier at ``/flower/<slug>/``: nginx
    asks the API to authorise every request and forwards it to ``url``, which
    only the web tier has to reach. Flower must then run with
    ``--url_prefix=flower/<slug>``. Otherwise the UI just links to ``url``,
    and that Flower has to secure itself.
    """

    name = models.CharField(max_length=128, unique=True)
    slug = models.CharField(
        max_length=64,
        unique=True,
        validators=[RegexValidator(f'^{SLUG_PATTERN}$', 'Lower-case letters, digits and "-" only')],
        help_text='Proxied at /flower/<slug>/',
    )
    url = models.URLField(max_length=512, help_text='Upstream address when proxied, otherwise the link')
    proxied = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def path(self) -> str:
        """Where the proxied endpoint is served."""
        return f'/flower/{self.slug}/'

    @property
    def link(self) -> str:
        return self.path if self.proxied else self.url
