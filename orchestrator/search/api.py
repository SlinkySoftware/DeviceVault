"""Config search API: ``POST /api/search/`` (ARCHITECTURE.md section 7.2).

A POST, not a GET: a query can hold a secret, which must not end up in a URL (access logs, history).
"""

from rest_framework import response, serializers, status
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView

from accounts.access import HasDeviceGroupPermission
from audit.log import record
from search import indexing, query


class SearchParams(serializers.Serializer):
    q = serializers.CharField(trim_whitespace=False, max_length=query.MAX_QUERY_LENGTH)
    mode = serializers.ChoiceField(choices=query.MODES, default=query.MODE_TEXT)
    device_group = serializers.IntegerField(required=False, allow_null=True)
    driver = serializers.CharField(required=False, allow_blank=True, max_length=128)


class SearchView(APIView):
    """Search the latest backups of the devices whose contents the user may see.

    Devices the user cannot read are filtered out in the query, so they neither appear nor count.
    """

    permission_classes = [HasDeviceGroupPermission('view_contents')]

    def post(self, request):
        if not indexing.enabled():
            raise NotFound('Config search is not enabled.')
        params = SearchParams(data=request.data)
        params.is_valid(raise_exception=True)
        search = query.Search(
            query=params.validated_data['q'],
            mode=params.validated_data['mode'],
            device_group=params.validated_data.get('device_group'),
            driver=params.validated_data.get('driver') or None,
        )
        try:
            result, recorded = query.run(request.user, search)
        except query.SearchError as exc:
            return response.Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record(
            request,
            'search.query',
            details={
                'mode': search.mode,
                'query': recorded,
                'device_group': search.device_group,
                'driver': search.driver,
                'devices': len(result['results']),
                'truncated': result['truncated'],
            },
        )
        return response.Response(result)
