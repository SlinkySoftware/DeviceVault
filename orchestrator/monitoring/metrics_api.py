"""The read-only monitoring endpoints (``/api/monitoring/``): JSON for Zabbix, text for Prometheus.

Each answers for its caller: a session, or a token with the ``monitoring`` or
``api`` scope, filtered to the caller's ``view`` grants (``accounts.access``).
Platform sections need a global administrator's session or the
``monitoring_platform`` scope, and are left out rather than refused, so one
token works for every template. ``device/`` answers from the caller's published
snapshot, as receiver relays do. Reads are not audited (token use is).
"""

import time

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import decorators, renderers, response, status

from accounts import access
from accounts.access import CanReadMonitoring
from accounts.login import is_service_account
from accounts.models import ApiToken
from accounts.tokens import token_scopes
from devicevault_protocol import monitoring as protocol
from monitoring import metrics, prometheus, snapshots, zabbix
from monitoring.catalogue import PLATFORM, RECEIVER, TARGET, WORKER, keys

SCOPES = (ApiToken.MONITORING, ApiToken.API)


class TextRenderer(renderers.BaseRenderer):
    """Lets a Prometheus scrape (``Accept: text/plain``) through content negotiation."""

    media_type = 'text/plain'
    format = 'txt'
    charset = 'utf-8'

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data if isinstance(data, bytes | str) else str(data)


class YamlRenderer(TextRenderer):
    """Lets a download asking for YAML (``Accept: application/yaml``) through content negotiation."""

    media_type = 'application/yaml'
    format = 'yaml'


def _scope_key(request) -> str:
    token = getattr(request, 'auth', None)
    if isinstance(token, ApiToken):
        return '+'.join(token.scopes)
    return 'admin-session' if access.is_global_admin(request.user) else 'session'


def _cached(request, section: str, compute):
    return snapshots.cached(request.user, _scope_key(request), section, compute)


def _devices(request):
    return access.devices_for(request.user, 'view')


def _summary(request) -> dict:
    def compute():
        figures = metrics.summary(_devices(request))
        if access.sees_platform(request):
            figures.update(metrics.platform())
        figures['computed_at'] = int(time.time())
        return figures

    figures = dict(_cached(request, 'summary', compute))
    now = int(time.time())
    figures['computed_age'] = now - figures['computed_at']
    figures['server_time'] = now
    return figures


def _groups(request) -> list[dict]:
    return _cached(
        request,
        'device-groups',
        lambda: metrics.device_groups(_devices(request), access.visible_device_groups(request.user)),
    )


def _platform_list(request, section: str, compute) -> list[dict]:
    if not access.sees_platform(request):
        return []
    return _cached(request, section, compute)


@token_scopes(*SCOPES)
@decorators.api_view(['GET'])
@decorators.permission_classes([CanReadMonitoring])
def summary(request):
    """Estate outcomes, timing, freshness, change, volume, push and self (and platform health when allowed)."""
    return response.Response(_summary(request))


@token_scopes(*SCOPES)
@decorators.api_view(['GET'])
@decorators.permission_classes([CanReadMonitoring])
def device_groups(request):
    """One entry per visible device group, in the shape Zabbix low-level discovery reads."""
    return response.Response({'data': _groups(request)})


@token_scopes(*SCOPES)
@decorators.api_view(['GET'])
@decorators.permission_classes([CanReadMonitoring])
def workers(request):
    return response.Response({'data': _platform_list(request, 'workers', metrics.workers)})


@token_scopes(*SCOPES)
@decorators.api_view(['GET'])
@decorators.permission_classes([CanReadMonitoring])
def storage_targets(request):
    return response.Response({'data': _platform_list(request, 'storage-targets', metrics.storage_targets)})


@token_scopes(*SCOPES)
@decorators.api_view(['GET'])
@decorators.permission_classes([CanReadMonitoring])
def receivers(request):
    return response.Response({'data': _platform_list(request, 'receivers', metrics.receivers)})


@token_scopes(*SCOPES)
@decorators.api_view(['GET'])
@decorators.permission_classes([CanReadMonitoring])
def device(request):
    """One device from the caller's published snapshot: ``?ip=<address>&id=<id>`` (``id`` wins when given).

    Only service accounts have snapshots (404 for anyone else). An unknown device
    and one the caller cannot see both answer ``found: 0``; with no current
    snapshot the answer is 503 ``stale``, so the problem shows in monitoring.
    """
    if not is_service_account(request.user):
        return response.Response(
            {'detail': 'Only service accounts with a monitoring token have device snapshots.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    try:
        snapshot = snapshots.owner_snapshot(request.user)
    except protocol.SnapshotError:
        snapshot = None
    now = timezone.now()
    if snapshot is None or snapshot.stale(now):
        return response.Response({'error': 'stale'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    answer = protocol.device_response(
        snapshot, ip=request.query_params.get('ip', ''), device_id=request.query_params.get('id', ''), now=now
    )
    return response.Response(answer)


@token_scopes(*SCOPES)
@decorators.api_view(['GET'])
@decorators.renderer_classes([renderers.JSONRenderer, YamlRenderer])
@decorators.permission_classes([CanReadMonitoring])
def zabbix_template(request):
    """The generated Zabbix templates (``?version=6.0|7.0``), as the YAML file Zabbix imports.

    The same for every installation and caller, since groups, workers and targets are discovered.
    """
    version = request.query_params.get('version', '')
    if version not in zabbix.VERSIONS:
        return response.Response(
            {'version': [f'Choose one of {", ".join(zabbix.VERSIONS)}.']}, status=status.HTTP_400_BAD_REQUEST
        )
    answer = HttpResponse(zabbix.render(version), content_type='application/yaml; charset=utf-8')
    answer['Content-Disposition'] = f'attachment; filename="devicevault_zabbix_{version}.yaml"'
    return answer


@token_scopes(*SCOPES)
@decorators.api_view(['GET'])
@decorators.renderer_classes([renderers.JSONRenderer, TextRenderer])
@decorators.permission_classes([CanReadMonitoring])
def prometheus_metrics(request):
    """The same figures in Prometheus text format (no per-device series)."""
    summary_figures = _summary(request)
    platform = {key: summary_figures.get(key) for key in keys(PLATFORM)} if access.sees_platform(request) else None
    lists = {
        WORKER: _platform_list(request, 'workers', metrics.workers),
        TARGET: _platform_list(request, 'storage-targets', metrics.storage_targets),
        RECEIVER: _platform_list(request, 'receivers', metrics.receivers),
    }
    body = prometheus.render(summary_figures, _groups(request), platform, lists)
    return HttpResponse(body, content_type=prometheus.CONTENT_TYPE)
