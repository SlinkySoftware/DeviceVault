"""Config search API: ``POST /api/search/`` and ``/api/saved-searches/`` (ARCHITECTURE.md section 7.2).

A POST, not a GET: a query can hold a secret, which must not end up in a URL (access logs, history).
"""

from rest_framework import response, serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from accounts import access
from accounts.access import HasDeviceGroupPermission
from audit.log import record
from search import indexing
from search import query as engine
from search.models import SavedSearch


class SearchParams(serializers.Serializer):
    q = serializers.CharField(trim_whitespace=False, max_length=engine.MAX_QUERY_LENGTH)
    mode = serializers.ChoiceField(choices=engine.MODES, default=engine.MODE_TEXT)
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
        search = engine.Search(
            query=params.validated_data['q'],
            mode=params.validated_data['mode'],
            device_group=params.validated_data.get('device_group'),
            driver=params.validated_data.get('driver') or None,
        )
        try:
            result, recorded = engine.run(request.user, search)
        except engine.SearchError as exc:
            return response.Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record(
            request,
            'search.query',
            details={
                'mode': search.mode,
                **({'query': recorded} if recorded is not None else {}),
                'device_group': search.device_group,
                'driver': search.driver,
                'devices': len(result['results']),
                # Results show configuration lines, so record whose (as content views are).
                'device_ids': [match['device'] for match in result['results']],
                'truncated': result['truncated'],
            },
        )
        return response.Response(result)


class SavedSearchSerializer(serializers.ModelSerializer):
    mode = serializers.ChoiceField(
        choices=[engine.MODE_TEXT, engine.MODE_REGEX],
        default=engine.MODE_TEXT,
        error_messages={'invalid_choice': 'Only text and regex searches can be saved; secret searches are never kept.'},
    )
    query = serializers.CharField(trim_whitespace=False, max_length=engine.MAX_QUERY_LENGTH)
    device_group_name = serializers.CharField(source='device_group.name', read_only=True, default=None)

    class Meta:
        model = SavedSearch
        fields = [
            'id',
            'name',
            'query',
            'mode',
            'device_group',
            'device_group_name',
            'driver',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']

    def validate_name(self, name):
        name = name.strip()
        others = SavedSearch.objects.filter(owner=self.context['request'].user, name__iexact=name)
        if self.instance is not None:
            others = others.exclude(pk=self.instance.pk)
        if others.exists():
            raise serializers.ValidationError('You already have a saved search with this name.')
        return name

    def validate_device_group(self, group):
        user = self.context['request'].user
        if group is not None and not access.visible_device_groups(user).filter(pk=group.pk).exists():
            raise serializers.ValidationError('Unknown device group.')
        return group

    def validate(self, data):
        current = {'query': self.instance.query, 'mode': self.instance.mode} if self.instance else {}
        merged = {**current, **data}  # a partial update is validated as a whole
        search = engine.Search(query=merged['query'], mode=merged['mode'])
        try:
            engine.validate(search)
            if search.mode == engine.MODE_REGEX:
                engine.compile_regex(search.query)
        except engine.SearchError as exc:
            raise serializers.ValidationError({'query': str(exc)}) from exc
        return data


class SavedSearchViewSet(viewsets.ModelViewSet):
    """The signed-in user's own saved searches; nobody sees anyone else's."""

    serializer_class = SavedSearchSerializer
    permission_classes = [IsAuthenticated]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not indexing.enabled():
            raise NotFound('Config search is not enabled.')

    def get_queryset(self):
        return SavedSearch.objects.filter(owner=self.request.user).select_related('device_group')

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
